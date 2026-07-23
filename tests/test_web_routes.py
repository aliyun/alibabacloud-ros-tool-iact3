# -*- coding: utf-8 -*-
import json
import tempfile
import uuid
from pathlib import Path
from unittest import mock

import yaml
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from iact3.web import routes
from iact3.web.runner import TestRun as WebTestRun
from iact3.web.runner import TestRunner as WebTestRunner
from tests.common import AsyncTestCase


class TestProjectConfigHelpers(AsyncTestCase):
    def test_project_name_update_handles_flow_style_yaml(self):
        updated = routes._sync_project_name_in_config(
            'project: {name: old}\ntests: {default: {regions: [cn-hangzhou]}}\n',
            'new-name',
        )
        parsed = yaml.safe_load(updated)
        self.assertEqual('new-name', parsed['project']['name'])
        self.assertEqual(['cn-hangzhou'], parsed['tests']['default']['regions'])

    def test_project_name_is_ignored_semantically(self):
        first = 'project: {name: first}\ntests:\n  default:\n    parameters: {A: 1}\n'
        second = 'tests: {default: {parameters: {A: 1}}}\nproject:\n  name: second\n'
        self.assertEqual(
            routes._strip_project_name_from_config(first),
            routes._strip_project_name_from_config(second),
        )

    def test_invalid_project_section_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'project section'):
            routes._sync_project_name_in_config('project: invalid\n', 'example')

    def test_invalid_tests_section_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'tests section'):
            routes._validate_config_structure({'tests': ['default']})

    def test_multiline_terraform_default_is_left_to_terraform(self):
        files = {
            'variables.tf': '''
variable "cidrs" {
  type = list(string)
  default = [
    "10.0.0.0/24",
    "10.0.1.0/24",
  ]
}
''',
        }
        variables = routes._parse_terraform_variables(files)
        self.assertTrue(variables['cidrs']['has_default'])
        self.assertIsNone(variables['cidrs']['default'])

        updated = routes._inject_auto_params(
            None,
            files,
            'tests:\n  default:\n    parameters: {}\n',
        )
        parameters = yaml.safe_load(updated)['tests']['default']['parameters']
        self.assertNotIn('cidrs', parameters)

    def test_terraform_expression_and_heredoc_defaults_are_not_truncated(self):
        files = {
            'variables.tf': '''
variable "labels" {
  default = tomap({
    owner = "platform"
  })
}

variable "script" {
  default = <<-EOT
    echo ready
    echo "}"
  EOT
}

variable "after_script" {
  type = string
  default = "still parsed"
}
''',
        }

        variables = routes._parse_terraform_variables(files)

        self.assertTrue(variables['labels']['has_default'])
        self.assertIsNone(variables['labels']['default'])
        self.assertTrue(variables['script']['has_default'])
        self.assertIsNone(variables['script']['default'])
        self.assertEqual('still parsed', variables['after_script']['default'])

    def test_terraform_block_comment_brace_does_not_close_variable(self):
        files = {
            'variables.tf': '''
variable "cidrs" {
  /* this brace is only a comment: } */
  type = list(string)
  default = ["10.0.0.0/24"]
}
''',
        }

        variables = routes._parse_terraform_variables(files)

        self.assertEqual('list(string)', variables['cidrs']['type'])
        self.assertEqual('["10.0.0.0/24"]', variables['cidrs']['default'])

    def test_generated_parameters_preserve_the_full_config(self):
        original = '''
project:
  name: example
  template_config:
    template_url: oss://bucket/template.yaml
auth:
  name: profile-a
tests:
  default:
    regions: [cn-hangzhou]
    parameters:
      Old: value
    hooks:
      after:
        execute_time: post_create
  secondary:
    parameters:
      Keep: this
'''

        merged = routes._merge_generated_parameters(
            original,
            {'New': 'generated'},
        )
        parsed = yaml.safe_load(merged)

        self.assertEqual('profile-a', parsed['auth']['name'])
        self.assertEqual(
            'oss://bucket/template.yaml',
            parsed['project']['template_config']['template_url'],
        )
        self.assertEqual(
            {'New': 'generated'},
            parsed['tests']['default']['parameters'],
        )
        self.assertIn('hooks', parsed['tests']['default'])
        self.assertEqual(
            {'Keep': 'this'},
            parsed['tests']['secondary']['parameters'],
        )

    def test_parameter_generation_reads_only_the_target_test(self):
        config = {
            'tests': {
                'default': {'parameters': {'Shared': 'default-value'}},
                'secondary': {'parameters': {'Shared': 'secondary-value'}},
            },
        }

        self.assertEqual(
            {'Shared': 'default-value'},
            routes._get_target_parameters(config),
        )

    def test_parameter_generation_requires_default_when_multiple_tests_exist(self):
        with self.assertRaisesRegex(ValueError, 'default'):
            routes._get_target_parameters({
                'tests': {
                    'smoke': {'parameters': {'A': 1}},
                    'production': {'parameters': {'A': 2}},
                },
            })


class TestTerraformProjectVersions(AsyncTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.patches = [
            mock.patch.object(routes, '_UPLOAD_DIR', root),
            mock.patch.object(routes, '_PROJECTS_DIR', root / 'projects'),
            mock.patch.object(routes, '_HISTORY_DIR', root / 'history'),
            mock.patch.object(routes, '_SETTINGS_FILE', root / 'settings.json'),
        ]
        for patcher in self.patches:
            patcher.start()

        self.app = web.Application()
        self.app['runner'] = WebTestRunner()
        routes.setup_routes(self.app)
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        for patcher in reversed(self.patches):
            patcher.stop()
        self.temp_dir.cleanup()

    async def test_terraform_only_project_versions_are_preserved(self):
        initial = {
            'name': 'terraform-project',
            'template': '',
            'template_files': {'main.tf': 'resource "null_resource" "a" {}\n'},
            'config': '',
        }
        response = await self.client.post('/api/projects', json=initial)
        self.assertEqual(200, response.status)

        updated = dict(initial)
        updated['template_files'] = {'main.tf': 'resource "null_resource" "b" {}\n'}
        updated['allow_overwrite'] = True
        response = await self.client.post('/api/projects', json=updated)
        self.assertEqual(200, response.status)

        project_file = Path(self.temp_dir.name) / 'projects' / 'terraform-project.json'
        data = json.loads(project_file.read_text(encoding='utf-8'))
        self.assertEqual(2, data['current_version'])
        self.assertEqual([1, 2], [item['version'] for item in data['versions']])
        self.assertEqual(updated['template_files'], data['versions'][-1]['template_files'])

    async def test_batch_delete_rejects_non_string_run_ids(self):
        response = await self.client.post('/api/runs/batch-delete', json={'ids': [123]})
        self.assertEqual(400, response.status)
        self.assertEqual('INVALID_RUN_IDS', (await response.json())['code'])

    async def test_batch_delete_project_handles_non_string_names(self):
        response = await self.client.post('/api/projects/batch-delete', json={'names': [123]})
        self.assertEqual(200, response.status)
        data = await response.json()
        self.assertEqual([{'name': 123, 'reason': 'invalid name'}], data['failed'])

    async def test_mutating_endpoints_reject_wrong_json_types(self):
        response = await self.client.post('/api/reports/cleanup', json=[])
        self.assertEqual(400, response.status)

        response = await self.client.post(
            '/api/config/template-path',
            json={'template_path': 123},
        )
        self.assertEqual(400, response.status)

        response = await self.client.post(
            '/api/file',
            json={'path': 'example.txt', 'content': 123},
        )
        self.assertEqual(400, response.status)

    async def test_save_project_rejects_string_booleans_without_overwriting(self):
        initial = {
            'name': 'strict-booleans',
            'template': '{"ROSTemplateFormatVersion": "2015-09-01"}',
            'config': 'tests: {default: {regions: [cn-hangzhou]}}\n',
        }
        response = await self.client.post('/api/projects', json=initial)
        self.assertEqual(200, response.status)
        project_file = Path(self.temp_dir.name) / 'projects' / 'strict-booleans.json'
        before = project_file.read_text(encoding='utf-8')

        changed = dict(initial)
        changed['template'] = '{"changed": true}'
        changed['allow_overwrite'] = 'false'
        response = await self.client.post('/api/projects', json=changed)

        self.assertEqual(400, response.status)
        self.assertEqual(before, project_file.read_text(encoding='utf-8'))

    async def test_start_run_rejects_invalid_config_before_starting_runner(self):
        with mock.patch.object(
            self.app['runner'],
            'start_test_run',
            wraps=self.app['runner'].start_test_run,
        ) as start:
            response = await self.client.post('/api/runs', json={
                'template_content': '{"ROSTemplateFormatVersion": "2015-09-01"}',
                'config_content': 'tests: [not valid for iact3',
                'regions': 'cn-hangzhou',
            })

        self.assertEqual(400, response.status)
        start.assert_not_called()

    async def test_start_run_rejects_non_string_regions(self):
        response = await self.client.post('/api/runs', json={
            'template_content': '{"ROSTemplateFormatVersion": "2015-09-01"}',
            'config_content': 'tests: {default: {regions: [cn-hangzhou]}}\n',
            'regions': 123,
        })

        self.assertEqual(400, response.status)

    async def test_start_run_rejects_invalid_tests_shape_before_starting_runner(self):
        response = await self.client.post('/api/runs', json={
            'template_content': '{"ROSTemplateFormatVersion": "2015-09-01"}',
            'config_content': 'tests: [default]\n',
            'regions': 'cn-hangzhou',
        })

        self.assertEqual(400, response.status)

    async def test_start_run_reuses_a_completed_request_id(self):
        request_id = str(uuid.uuid4())
        run_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f'iact3-web-run:{request_id}',
        ).hex[:12]
        run = WebTestRun(
            run_id,
            'already-started',
            {'request_id': request_id},
        )
        run.status = 'running'
        self.app['runner']._runs[run_id] = run

        with mock.patch.object(
            self.app['runner'],
            'start_test_run',
            wraps=self.app['runner'].start_test_run,
        ) as start:
            response = await self.client.post(
                '/api/runs',
                json={'request_id': request_id},
            )

        self.assertEqual(200, response.status)
        self.assertEqual(run_id, (await response.json())['id'])
        start.assert_not_called()

    async def test_start_run_rejects_an_invalid_request_id(self):
        response = await self.client.post(
            '/api/runs',
            json={'request_id': 'retry-this'},
        )

        self.assertEqual(400, response.status)
        self.assertEqual('INVALID_REQUEST_ID', (await response.json())['code'])
