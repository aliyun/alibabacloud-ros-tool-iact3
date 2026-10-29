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

    async def test_version_history_reconciles_phantom_current_after_deletion(self):
        routes._PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
        project_path = routes._PROJECTS_DIR / 'example.json'
        project_path.write_text(json.dumps({
            'name': 'example', 'template': 'unversioned', 'current_version': 99,
            'versions': [{'version': 1, 'template': 'one'}, {'version': 2, 'template': 'two'}],
        }))
        response = await self.client.get('/api/projects/example/versions')
        self.assertEqual((await response.json())['current_version'], 2)
        response = await self.client.delete('/api/projects/example/versions/1')
        result = await response.json()
        self.assertEqual(result['current_version'], 2)
        self.assertTrue(result['auto_switched'])
        saved = json.loads(project_path.read_text())
        self.assertEqual(saved['template'], 'unversioned')
        self.assertEqual(saved['current_version'], 2)
        self.assertEqual((await self.client.delete('/api/projects/example/versions/2')).status, 400)

    async def test_version_activation_and_deletion_preserve_empty_configuration(self):
        routes._PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
        path = routes._PROJECTS_DIR / 'example.json'
        path.write_text(json.dumps({'name': 'example', 'current_version': 2, 'template': 'second',
                                    'versions': [{'version': 1, 'template': 'first', 'config': ''},
                                                 {'version': 2, 'template': 'second', 'config': ''}]}))
        response = await self.client.get('/api/projects/example/versions')
        self.assertEqual((await response.json())['current_version'], 2)
        response = await self.client.post('/api/projects/example/versions/1/activate')
        self.assertEqual(response.status, 200)
        activated = json.loads(path.read_text())
        self.assertEqual(activated['template'], 'first')
        self.assertEqual(activated['config'], '')
        self.assertEqual(len(activated['versions']), 2)
        response = await self.client.delete('/api/projects/example/versions/1')
        self.assertEqual(response.status, 200)
        saved = json.loads(path.read_text())
        self.assertEqual(saved['current_version'], 2)
        self.assertEqual(saved['template'], 'second')
        self.assertEqual(saved['config'], '')

    async def test_project_version_routes_reject_invalid_names(self):
        for method, url in [('GET', '/api/projects/bad%20name/versions'),
                            ('GET', '/api/projects/bad%20name/versions/1'),
                            ('POST', '/api/projects/bad%20name/versions/1/activate'),
                            ('DELETE', '/api/projects/bad%20name/versions/1')]:
            response = await self.client.request(method, url)
            self.assertEqual(response.status, 400)
            self.assertEqual((await response.json())['error'], 'Invalid project name')

    async def test_run_listing_and_project_history_work_without_filters_or_saved_project(self):
        from iact3.web.runner import TestRun

        run = TestRun('run-id', 'example', {})
        run.status = 'completed'
        self.app['runner']._runs[run.id] = run
        response = await self.client.get('/api/runs')
        data = await response.json()
        self.assertEqual(data['total'], 1)
        self.assertEqual(data['runs'][0]['id'], 'run-id')
        response = await self.client.get('/api/projects/example/runs')
        self.assertEqual((await response.json())['runs'][0]['id'], 'run-id')
        self.assertEqual((await self.client.get('/api/projects/bad%20name/runs')).status, 400)

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

    async def test_start_run_rejects_invalid_bodies_and_request_id_collision(self):
        response = await self.client.post('/api/runs', data='{', headers={'Content-Type': 'application/json'})
        self.assertEqual(response.status, 400)
        self.assertEqual((await response.json())['error'], 'Invalid JSON')
        for payload in ([], {}, {'request_id': 123}):
            response = await self.client.post('/api/runs', json=payload)
            self.assertEqual(response.status, 400)
        request_id = str(uuid.uuid4())
        run_id = uuid.uuid5(uuid.NAMESPACE_URL, 'iact3-web-run:' + request_id).hex[:12]
        self.app['runner']._runs[run_id] = WebTestRun(run_id, 'other', {'request_id': str(uuid.uuid4())})
        response = await self.client.post('/api/runs', json={'request_id': request_id})
        self.assertEqual(response.status, 409)
        self.assertEqual((await response.json())['code'], 'REQUEST_ID_COLLISION')

    async def test_start_run_cleans_temporary_files_if_runner_fails(self):
        async def fail(params, run_id):
            raise RuntimeError('cannot start')
        with mock.patch.object(routes, 'DEFAULT_OUTPUT_DIRECTORY', str(Path(self.temp_dir.name) / 'output')), \
             mock.patch.object(routes, '_write_current_files', return_value=('template', 'config', 'temp')), \
             mock.patch.object(routes, '_cleanup_current_files') as cleanup, \
             mock.patch.object(self.app['runner'], 'start_test_run', fail):
            response = await self.client.post('/api/runs', json={'template_content': 'Resources: {}'})
            self.assertEqual(response.status, 500)
            self.assertEqual((await response.json())['error'], 'cannot start')
            cleanup.assert_called_once()

    async def test_history_listing_filter_and_cleanup(self):
        first = routes._save_history('one', 'validate', {'ok': True})
        second = routes._save_history('two', 'cost', {'amount': 3})
        (routes._HISTORY_DIR / 'broken.json').write_text('{')
        response = await self.client.get('/api/history?project_name=one')
        data = await response.json()
        self.assertEqual([entry['id'] for entry in data['history']], [first])
        response = await self.client.get('/api/history/' + second)
        self.assertEqual((await response.json())['result'], {'amount': 3})
        self.assertEqual((await self.client.delete('/api/history/' + first)).status, 200)
        self.assertEqual((await self.client.get('/api/history/' + first)).status, 404)
        self.assertEqual((await self.client.delete('/api/history/' + first)).status, 404)
        response = await self.client.post('/api/history/cleanup')
        self.assertEqual((await response.json())['deleted'], 2)

    async def test_project_version_activate_and_delete(self):
        routes._PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
        project = {
            'current_version': 99,
            'template': 'current',
            'config': 'project: {name: old}',
            'versions': [
                {'version': 1, 'template': 'first', 'configs': [{'config': 'project: {name: old}'}]},
                {'version': 2, 'template': 'second', 'config': 'project: {name: old}'},
            ],
        }
        project_path = routes._PROJECTS_DIR / 'example.json'
        project_path.write_text(json.dumps(project))
        response = await self.client.get('/api/projects/example/versions')
        self.assertEqual((await response.json())['current_version'], 2)
        response = await self.client.get('/api/projects/example/versions/1')
        self.assertEqual((await response.json())['config'], 'project: {name: old}')
        self.assertEqual((await self.client.get('/api/projects/example/versions/8')).status, 404)
        response = await self.client.post('/api/projects/example/versions/1/activate')
        self.assertEqual((await response.json())['current_version'], 1)
        data = json.loads(project_path.read_text())
        self.assertEqual(data['template'], 'first')
        self.assertEqual(yaml.safe_load(data['config'])['project']['name'], 'example')
        self.assertEqual(len(data['versions']), 3)
        response = await self.client.post('/api/projects/example/versions/1/activate')
        self.assertEqual((await response.json())['message'], 'Already current version')
        response = await self.client.delete('/api/projects/example/versions/1')
        result = await response.json()
        self.assertTrue(result['auto_switched'])
        self.assertEqual(result['current_version'], 3)
        self.assertEqual((await self.client.delete('/api/projects/example/versions/8')).status, 404)
        self.assertEqual((await self.client.get('/api/projects/missing/versions')).status, 404)

    async def test_samples_include_retrievable_entries(self):
        response = await self.client.get('/api/samples?lang=en')
        samples = (await response.json())['samples']
        self.assertTrue(samples)
        for sample in samples:
            response = await self.client.get('/api/samples/' + sample['id'])
            self.assertEqual(response.status, 200)
            data = await response.json()
            self.assertTrue('template' in data or 'template_files' in data)
        self.assertEqual((await self.client.get('/api/samples/not-a-sample')).status, 404)
        self.assertEqual((await self.client.get('/api/projects/examples')).status, 200)

    async def test_report_file_lifecycle_and_cleanup(self):
        import os
        previous_dir = os.getcwd()
        try:
            os.chdir(self.temp_dir.name)
            response = await self.client.get('/api/reports')
            self.assertEqual((await response.json())['reports'], [])
            output = Path('iact3_outputs')
            output.mkdir()
            (output / 'run-result.json').write_text('{"success":true}')
            (output / 'run.txt').write_text('log content')
            (output / 'run.html').write_text('<p>report</p>')
            (output / 'hook.bin').write_bytes(b'\xff')
            (output / 'other.dat').write_text('other')
            (output / 'subdirectory').mkdir()
            response = await self.client.get('/api/reports')
            reports = (await response.json())['reports']
            self.assertEqual({item['category'] for item in reports}, {'result', 'log', 'report', 'hook', 'other'})
            response = await self.client.get('/api/reports/run-result.json')
            self.assertTrue((await response.json())['success'])
            response = await self.client.get('/api/reports/run.txt')
            self.assertEqual(await response.text(), 'log content')
            response = await self.client.get('/api/reports/run.html')
            self.assertEqual(await response.text(encoding='utf-8'), '<p>report</p>')
            response = await self.client.get('/api/reports/other.dat')
            self.assertEqual(await response.text(encoding='utf-8'), 'other')
            response = await self.client.get('/api/reports/run-result.json/raw')
            self.assertIn('\n', (await response.json())['content'])
            response = await self.client.get('/api/reports/run.txt/raw')
            self.assertEqual((await response.json())['content'], 'log content')
            self.assertEqual((await self.client.get('/api/reports/hook.bin/raw')).status, 400)
            self.assertEqual((await self.client.get('/api/reports/missing.txt')).status, 404)
            self.assertEqual((await self.client.get('/api/reports/missing.txt/raw')).status, 404)
            self.assertEqual((await self.client.delete('/api/reports/other.dat')).status, 200)
            self.assertEqual((await self.client.delete('/api/reports/other.dat')).status, 404)
            self.assertEqual((await self.client.post('/api/reports/cleanup', json={'mode': 'invalid'})).status, 400)
            self.assertEqual((await self.client.post('/api/reports/cleanup', json={'mode': 'keep_last', 'keep': -1})).status, 400)
            self.assertEqual((await self.client.post('/api/reports/cleanup', json={'mode': 'older_than', 'days': True})).status, 400)
            response = await self.client.post('/api/reports/cleanup', json={'mode': 'keep_last', 'keep': 1})
            self.assertEqual((await response.json())['deleted'], 3)
            response = await self.client.post('/api/reports/cleanup', json={'mode': 'all'})
            self.assertEqual((await response.json())['deleted'], 1)
        finally:
            os.chdir(previous_dir)

    async def test_report_cleanup_skips_files_it_cannot_delete(self):
        import os

        previous_dir = os.getcwd()
        try:
            os.chdir(self.temp_dir.name)
            response = await self.client.post('/api/reports/cleanup', json={})
            self.assertEqual(await response.json(), {'deleted': 0, 'freed': 0})
            output = Path('iact3_outputs')
            output.mkdir()
            (output / 'keep.txt').write_text('keep')
            (output / 'delete.txt').write_text('delete')
            original_unlink = Path.unlink

            def unlink(path, *args, **kwargs):
                if path.name == 'keep.txt':
                    raise PermissionError('denied')
                return original_unlink(path, *args, **kwargs)

            with mock.patch.object(Path, 'unlink', unlink):
                response = await self.client.post('/api/reports/cleanup', json={'mode': 'all'})
            self.assertEqual(await response.json(), {'deleted': 1, 'freed': 6})
            self.assertTrue((output / 'keep.txt').exists())
            self.assertFalse((output / 'delete.txt').exists())
        finally:
            os.chdir(previous_dir)

    async def test_file_and_config_endpoints_use_project_boundary(self):
        root = Path(self.temp_dir.name)
        with mock.patch.object(routes, 'DEFAULT_PROJECT_ROOT', root):
            response = await self.client.post('/api/file', json={'path': 'nested/a.yml', 'content': 'hello'})
            self.assertEqual(response.status, 200)
            response = await self.client.get('/api/file', params={'path': 'nested/a.yml'})
            self.assertEqual((await response.json())['content'], 'hello')
            self.assertEqual((await self.client.get('/api/file', params={'path': '../outside'})).status, 403)
            self.assertEqual((await self.client.post('/api/file', json={'path': '../outside', 'content': 'x'})).status, 403)
            self.assertEqual((await self.client.get('/api/file', params={'path': 'missing'})).status, 404)
            self.assertEqual((await self.client.get('/api/file', params={'path': '.'})).status, 400)
            (root / 'binary').write_bytes(b'\xff')
            self.assertEqual((await self.client.get('/api/file', params={'path': 'binary'})).status, 400)
            self.assertEqual((await self.client.post('/api/config/template-path', json={'template_path': ''})).status, 400)
            self.assertEqual((await self.client.post('/api/config/template-path', json={
                'template_path': 'template.yml', 'config_file': '../outside'})).status, 403)
            response = await self.client.post('/api/config/template-path', json={
                'template_path': ' template.yml ', 'config_file': 'config.yml'})
            self.assertEqual(response.status, 200)
            config = yaml.safe_load((root / 'config.yml').read_text())
            self.assertEqual(config['project']['template_config']['template_location'], 'template.yml')
            response = await self.client.post('/api/config/template-path', json={
                'template_path': 'updated.yml', 'config_file': 'config.yml'})
            self.assertEqual(response.status, 200)
            config = yaml.safe_load((root / 'config.yml').read_text())
            self.assertEqual(config['project']['template_config']['template_location'], 'updated.yml')

    async def test_file_and_config_endpoints_handle_malformed_and_unwritable_inputs(self):
        root = Path(self.temp_dir.name)
        (root / 'broken.yml').write_text('project: [')
        with mock.patch.object(routes, 'DEFAULT_PROJECT_ROOT', root):
            self.assertEqual((await self.client.get('/api/file')).status, 400)
            for endpoint in ('/api/file', '/api/config/template-path'):
                response = await self.client.post(endpoint, data='{', headers={'Content-Type': 'application/json'})
                self.assertEqual(response.status, 400)
                response = await self.client.post(endpoint, json=[])
                self.assertEqual(response.status, 400)
            self.assertEqual((await self.client.post('/api/file', json={})).status, 400)
            response = await self.client.post('/api/file', json={'path': '.', 'content': 'cannot overwrite directory'})
            self.assertEqual(response.status, 500)
            response = await self.client.post('/api/config/template-path', json={
                'template_path': 'template.yml', 'config_file': 'broken.yml'})
            self.assertEqual(response.status, 500)
            self.assertEqual((root / 'broken.yml').read_text(), 'project: [')

    async def test_upload_list_and_delete_template(self):
        from aiohttp import FormData

        form = FormData()
        form.add_field('file', b'content', filename='test.yaml', content_type='application/octet-stream')
        response = await self.client.post('/api/upload?type=config', data=form)
        self.assertEqual(response.status, 200)
        data = await response.json()
        self.assertEqual(data['size'], 7)
        response = await self.client.get('/api/templates?type=config')
        entries = (await response.json())['templates']
        self.assertEqual(len(entries), 1)
        response = await self.client.delete('/api/templates/' + entries[0]['name'] + '?type=config')
        self.assertEqual((await response.json())['size'], 7)
        self.assertEqual((await self.client.delete('/api/templates/missing.yaml')).status, 404)
        form = FormData()
        form.add_field('file', b'content', filename='test.exe', content_type='application/octet-stream')
        self.assertEqual((await self.client.post('/api/upload', data=form)).status, 400)

    async def test_upload_rejects_oversized_file_and_removes_partial_output(self):
        from aiohttp import FormData

        form = FormData()
        form.add_field('file', b'x' * (5 * 1024 * 1024 + 1), filename='large.yaml',
                       content_type='application/octet-stream')
        response = await self.client.post('/api/upload', data=form)
        self.assertEqual(response.status, 400)
        self.assertIn('too large', (await response.json())['error'])
        self.assertEqual(list((Path(self.temp_dir.name) / 'templates').iterdir()), [])

    async def test_upload_requires_a_file_form_field(self):
        from aiohttp import FormData

        form = FormData()
        form.add_field('other', b'content', filename='other.yaml', content_type='application/octet-stream')
        response = await self.client.post('/api/upload', data=form)
        self.assertEqual(response.status, 400)
        self.assertEqual((await response.json())['error'], 'No file field found')
        self.assertFalse((Path(self.temp_dir.name) / 'templates').exists())

    async def test_regions_filter_private_regions_and_fallback(self):
        async def regions(*args, **kwargs):
            return [{'id': 'cn-hangzhou', 'name': 'Hangzhou'}, {'id': 'private-region', 'name': 'Private'}]
        plugin = mock.Mock()
        plugin.get_regions_with_names = regions
        with mock.patch.object(routes, 'StackPlugin', return_value=plugin):
            response = await self.client.get('/api/regions?lang=en')
            self.assertEqual((await response.json())['regions'], [{'id': 'cn-hangzhou', 'name': 'Hangzhou'}])

        async def unavailable(*args, **kwargs):
            raise RuntimeError('credentials unavailable')
        plugin.get_regions_with_names = unavailable
        with mock.patch.object(routes, 'StackPlugin', return_value=plugin):
            for lang in ('en', 'zh'):
                response = await self.client.get('/api/regions?lang=' + lang)
                data = await response.json()
                self.assertTrue(data['fallback'])
                self.assertIn('cn-hangzhou', [region['id'] for region in data['regions']])

    async def test_validation_and_policy_save_success_and_failure_history(self):
        class Plugin:
            async def validate_template(self, **kwargs):
                return {'description': 'valid'}
            async def generate_template_policy(self, **kwargs):
                return {'Statement': []}
        payload = {'template_content': 'ROSTemplateFormatVersion: "2015-09-01"', 'project_name': 'demo'}
        log_root = Path(self.temp_dir.name) / 'logs'
        with mock.patch.object(routes, 'DEFAULT_OUTPUT_DIRECTORY', str(log_root)), \
             mock.patch.object(routes, '_resolve_credential', return_value=object()), \
             mock.patch.object(routes, 'StackPlugin', return_value=Plugin()), \
             mock.patch.object(routes, '_cleanup_current_files'):
            response = await self.client.post('/api/validate', json=payload)
            self.assertEqual(response.status, 200)
            self.assertEqual((await response.json())['details'], {'description': 'valid'})
            response = await self.client.post('/api/policy', json=payload)
            self.assertEqual(response.status, 200)
            self.assertEqual((await response.json())['policy'], {'Statement': []})
            entries = [json.loads(path.read_text()) for path in routes._HISTORY_DIR.glob('*.json')]
            self.assertEqual({entry['type'] for entry in entries}, {'validate', 'policy'})
            self.assertEqual(list(log_root.glob('*.log')), [])

            async def fail(*args, **kwargs):
                raise RuntimeError('service unavailable')
            with mock.patch.object(Plugin, 'validate_template', fail):
                response = await self.client.post('/api/validate', json=payload)
                self.assertEqual(response.status, 400)
                self.assertIn('service unavailable', (await response.json())['error'])
            with mock.patch.object(Plugin, 'generate_template_policy', fail):
                response = await self.client.post('/api/policy', json=payload)
                self.assertEqual(response.status, 500)
                self.assertIn('service unavailable', (await response.json())['logs'])

    async def test_cost_and_preview_return_stack_results_and_save_history(self):
        from types import SimpleNamespace
        stack = SimpleNamespace(test_name='test', region='cn-hangzhou', template_price={'amount': 1},
                                preview_result={'resources': ['one']}, status='OK')
        test = SimpleNamespace(stacker=SimpleNamespace(stacks=[stack]))
        calls = []
        async def from_file(**kwargs):
            calls.append(kwargs)
            return test
        async def calculate(result):
            self.assertIs(result, test)
        payload = {'template_content': 'ROSTemplateFormatVersion: "2015-09-01"',
                   'regions': 'cn-hangzhou', 'project_name': 'demo'}
        log_root = Path(self.temp_dir.name) / 'logs'
        with mock.patch.object(routes, 'DEFAULT_OUTPUT_DIRECTORY', str(log_root)), \
             mock.patch.object(routes, '_write_current_files', return_value=(None, 'config.yml', 'tmp')), \
             mock.patch.object(routes, '_cleanup_current_files') as cleanup, \
             mock.patch.object(routes.StackTest, 'from_file', from_file), \
             mock.patch.object(routes.StackTest, 'get_stacks_price', calculate), \
             mock.patch.object(routes.StackTest, 'preview_stacks_result', calculate):
            response = await self.client.post('/api/cost', json=payload)
            self.assertEqual(response.status, 200)
            self.assertEqual((await response.json())['prices'][0]['price'], {'amount': 1})
            response = await self.client.post('/api/preview', json=payload)
            self.assertEqual(response.status, 200)
            self.assertEqual((await response.json())['previews'][0]['resources'], {'resources': ['one']})
            self.assertEqual(len(calls), 2)
            self.assertEqual(cleanup.call_count, 4)
            entries = [json.loads(path.read_text()) for path in routes._HISTORY_DIR.glob('*.json')]
            self.assertEqual({entry['type'] for entry in entries}, {'cost', 'preview'})

    async def test_analysis_endpoints_reject_missing_inputs_and_report_errors(self):
        for endpoint in ('validate', 'cost', 'preview', 'policy'):
            self.assertEqual((await self.client.post('/api/' + endpoint, json={})).status, 400)
        for endpoint in ('cost', 'preview'):
            response = await self.client.post('/api/' + endpoint, json={'template_content': 'template'})
            self.assertEqual(response.status, 400)
            self.assertIn('地域', (await response.json())['error'])
        async def fail(**kwargs):
            raise RuntimeError('construction failed')
        with mock.patch.object(routes, 'DEFAULT_OUTPUT_DIRECTORY', str(Path(self.temp_dir.name) / 'logs')), \
             mock.patch.object(routes, '_write_current_files', return_value=(None, 'config.yml', 'tmp')), \
             mock.patch.object(routes, '_cleanup_current_files'), \
             mock.patch.object(routes.StackTest, 'from_file', fail):
            for endpoint in ('cost', 'preview'):
                response = await self.client.post('/api/' + endpoint, json={
                    'template_content': 'template', 'regions': 'cn-hangzhou'})
                self.assertEqual(response.status, 500)
                self.assertIn('construction failed', (await response.json())['error'])

    async def test_generate_ros_parameters_filters_stale_and_preserves_user_values(self):
        from types import SimpleNamespace
        from iact3.generate_params import ParamGenerator
        captured = []
        async def result(config):
            captured.append(dict(config.parameters))
            return SimpleNamespace(parameters=dict(config.parameters, VpcId='vpc-resolved'), error=ValueError('partial'))
        payload = {
            'template_content': json.dumps({'Parameters': {
                'VpcId': {'Type': 'String'}, 'Name': {'Type': 'String'},
                'ImageId': {'Default': 'image-default'}, 'Count': {'Default': 2}}}),
            'config_content': 'tests: {default: {parameters: {VpcId: old, Name: custom, Stale: stale}}}',
            'regions': 'cn-hangzhou',
        }
        with mock.patch.object(routes, '_resolve_credential', return_value=object()), \
             mock.patch('iact3.config.Auth._get_credential', return_value=None), \
             mock.patch.object(ParamGenerator, 'result', result):
            response = await self.client.post('/api/generate-params', json=payload)
        self.assertEqual(response.status, 200)
        data = await response.json()
        self.assertEqual(captured[0], {'VpcId': '$[iact3-auto]', 'Name': 'custom',
                                       'ImageId': 'image-default', 'Count': '2'})
        self.assertEqual(yaml.safe_load(data['config'])['tests']['default']['parameters']['VpcId'], 'vpc-resolved')
        self.assertEqual(data['warning'], 'partial')

    async def test_generate_ros_parameters_resolves_empty_name_and_captures_logs(self):
        import logging
        from types import SimpleNamespace
        from iact3.generate_params import ParamGenerator
        captured = []

        async def result(config):
            captured.append(dict(config.parameters))
            logging.getLogger('iact3.generate_params').info('parameter lookup completed')
            return SimpleNamespace(parameters=dict(config.parameters, Name='generated'), error=None)

        payload = {'template_content': 'Parameters: {Name: {Type: String}, Count: {Default: 2}}',
                   'config_content': 'parameters: {Name: "", Count: 9}', 'regions': 'cn-a'}
        with mock.patch.object(routes, '_resolve_credential', return_value=object()), \
             mock.patch('iact3.config.Auth._get_credential', return_value=None), \
             mock.patch.object(ParamGenerator, 'result', result):
            response = await self.client.post('/api/generate-params', json=payload)
        self.assertEqual(response.status, 200)
        data = await response.json()
        self.assertEqual(captured[0], {'Name': '$[iact3-auto]', 'Count': 9})
        self.assertEqual(yaml.safe_load(data['config'])['parameters'], {'Name': 'generated', 'Count': 9})
        self.assertIn('parameter lookup completed', data['logs'])
        self.assertNotIn('warning', data)

    async def test_generate_multi_region_params_retains_regional_placeholders(self):
        payload = {
            'template_content': 'Parameters: {VpcId: {Type: String}, Name: {Type: String}}',
            'config_content': 'tests: {default: {parameters: {VpcId: old, Name: custom}}}',
            'regions': ['cn-hangzhou', 'cn-shanghai'],
        }
        with mock.patch.object(routes, '_resolve_credential', return_value=object()), \
             mock.patch('iact3.config.Auth._get_credential', return_value=None):
            response = await self.client.post('/api/generate-params', json=payload)
        self.assertEqual(response.status, 200)
        data = await response.json()
        parameters = yaml.safe_load(data['config'])['tests']['default']['parameters']
        self.assertEqual(parameters, {'VpcId': '$[iact3-auto]', 'Name': 'custom'})
        self.assertIn('Multi-region', data['logs'])

    async def test_generate_terraform_params_single_and_multi_region(self):
        template = '''variable "VpcId" {\n}\nvariable "region_name" {\n default = "cn-test"\n}\n'''
        payload = {'template_files': {'main.tf': template},
                   'config_content': 'tests: {default: {parameters: {VpcId: old, Stale: stale}}}',
                   'regions': 'cn-hangzhou'}
        async def resolve(params, region, credential):
            self.assertEqual(region, 'cn-hangzhou')
            self.assertNotIn('Stale', params)
            return dict(params, VpcId='vpc-generated')
        with mock.patch.object(routes, 'DEFAULT_PROJECT_ROOT', Path(self.temp_dir.name)), \
             mock.patch.object(routes, '_resolve_credential', return_value=object()), \
             mock.patch.object(routes, '_resolve_terraform_params', resolve):
            response = await self.client.post('/api/generate-params', json=payload)
            self.assertEqual(response.status, 200)
            data = await response.json()
            params = yaml.safe_load(data['config'])['tests']['default']['parameters']
            self.assertEqual(params, {'VpcId': 'vpc-generated', 'region_name': 'cn-test'})
            self.assertIn('2 Terraform variable', data['logs'])
            payload['regions'] = 'cn-hangzhou,cn-shanghai'
            response = await self.client.post('/api/generate-params', json=payload)
            self.assertEqual(response.status, 200)
            params = yaml.safe_load((await response.json())['config'])['tests']['default']['parameters']
            self.assertEqual(params['VpcId'], '$[iact3-auto]')

    async def test_generate_params_rejects_missing_credentials(self):
        with mock.patch.object(routes, 'DEFAULT_PROJECT_ROOT', Path(self.temp_dir.name)), \
             mock.patch.object(routes, '_resolve_credential', return_value=None), \
             mock.patch('iact3.config.Auth._get_credential', return_value=None):
            for payload in ({'template_content': 'Parameters: {}'}, {'template_files': {'main.tf': ''}}):
                response = await self.client.post('/api/generate-params', json=payload)
                self.assertEqual(response.status, 400)
                self.assertIn('凭证', (await response.json())['error'])

    async def test_project_create_search_conflict_rename_and_delete(self):
        template = 'Description: Example\nParameters: {A: {Type: String}}\nResources: {R: {Type: Test}}'
        config = 'tests: {default: {regions: [cn-hangzhou]}}'
        payload = {'name': 'demo', 'template': template, 'config': config, 'no_delete': True}
        self.assertEqual((await self.client.post('/api/projects', json=payload)).status, 200)
        self.assertEqual((await self.client.post('/api/projects', json=payload)).status, 409)
        response = await self.client.get('/api/projects?search=DEMO&page=bad&per_page=bad')
        result = await response.json()
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['projects'][0]['param_count'], 1)
        self.assertEqual(result['projects'][0]['resource_count'], 1)
        self.assertEqual(result['projects'][0]['test_count'], 1)
        response = await self.client.get('/api/projects/demo')
        created = await response.json()
        self.assertEqual(yaml.safe_load(created['config'])['project']['name'], 'demo')
        payload.update({'name': 'renamed', 'old_name': 'demo'})
        response = await self.client.post('/api/projects', json=payload)
        self.assertEqual(response.status, 200)
        self.assertEqual((await self.client.get('/api/projects/demo')).status, 404)
        renamed = await (await self.client.get('/api/projects/renamed')).json()
        self.assertEqual(renamed['created_at'], created['created_at'])
        self.assertTrue(renamed['no_delete'])
        self.assertEqual(yaml.safe_load(renamed['config'])['project']['name'], 'renamed')
        self.assertEqual((await self.client.delete('/api/projects/renamed')).status, 200)
        self.assertEqual((await self.client.delete('/api/projects/renamed')).status, 404)

    async def test_project_runs_match_name_and_equivalent_config(self):
        payload = {'name': 'demo', 'template': 'template',
                   'config': 'project: {name: demo}\ntests: {default: {parameters: {A: 1}}}'}
        self.assertEqual((await self.client.post('/api/projects', json=payload)).status, 200)
        runs = [
            {'id': '1', 'name': 'other', 'params': {'project_name': 'demo'}},
            {'id': '2', 'name': 'demo', 'params': {}},
            {'id': '3', 'name': 'other', 'params': {'raw_template_content': 'template',
                     'raw_config_content': 'project: {name: old}\ntests: {default: {parameters: {A: 1}}}'}},
            {'id': '4', 'name': 'other', 'params': {'raw_template_content': 'different'}},
        ]
        with mock.patch.object(self.app['runner'], 'get_all_runs', return_value=runs):
            response = await self.client.get('/api/projects/demo/runs?per_page=2&page=2')
        data = await response.json()
        self.assertEqual(data['total'], 3)
        self.assertEqual([run['id'] for run in data['runs']], ['3'])

    async def test_project_listing_tolerates_corrupt_files_and_extracts_terraform_metadata(self):
        project_dir = Path(self.temp_dir.name) / 'projects'
        project_dir.mkdir()
        (project_dir / 'corrupt.json').write_text('{')
        (project_dir / 'invalid.json').write_text(json.dumps({
            'name': 'invalid', 'template': 'Resources: [', 'config': 'tests: ['}))
        (project_dir / 'terraform.json').write_text(json.dumps({
            'name': 'terraform', 'template_files': {'main.tf': 'resource {}', 'empty.tf': '',
                                                     'notes.txt': 'not terraform'},
            'config': 'project: {name: tf}\ntests: {one: {}, two: {}}'}))
        response = await self.client.get('/api/projects?page=invalid&per_page=invalid')
        data = await response.json()
        self.assertEqual(data['total'], 2)
        self.assertEqual((data['page'], data['per_page']), (1, 12))
        projects = {item['name']: item for item in data['projects']}
        self.assertEqual(projects['invalid']['resource_count'], 0)
        self.assertEqual(projects['invalid']['test_count'], 0)
        self.assertTrue(projects['terraform']['is_terraform'])
        self.assertEqual(projects['terraform']['resource_count'], 1)
        self.assertEqual(projects['terraform']['test_count'], 2)
        self.assertEqual(projects['terraform']['project_name_in_config'], 'tf')

    async def test_project_runs_match_terraform_files_and_equivalent_config(self):
        payload = {'name': 'tf', 'template_files': {'main.tf': 'resource {}'},
                   'config': 'project: {name: tf}\ntests: {default: {regions: [cn-a]}}'}
        self.assertEqual((await self.client.post('/api/projects', json=payload)).status, 200)
        runs = [{'id': 'match', 'params': {'raw_template_files': payload['template_files'],
                                          'raw_config_content': payload['config']}},
                {'id': 'other', 'params': {'raw_template_files': payload['template_files'],
                                          'raw_config_content': 'tests: {different: {}}'}}]
        with mock.patch.object(self.app['runner'], 'get_all_runs', return_value=runs):
            response = await self.client.get('/api/projects/tf/runs?page=bad&per_page=bad')
        data = await response.json()
        self.assertEqual([run['id'] for run in data['runs']], ['match'])
        self.assertEqual((data['page'], data['per_page']), (1, 20))

    async def test_project_validation_and_batch_delete(self):
        for payload in ({'name': 'bad/name'}, {'name': 4}, {'name': 'ok', 'configs': {}},
                        {'name': 'ok', 'configs': [4]}, {'name': 'ok', 'config': '['},
                        {'name': 'ok', 'template_files': {'../unsafe.tf': 'content'}}):
            self.assertEqual((await self.client.post('/api/projects', json=payload)).status, 400)
        for name in ('first', 'second'):
            self.assertEqual((await self.client.post('/api/projects', json={'name': name})).status, 200)
        response = await self.client.post('/api/projects/batch-delete', json={'names': ['first', 'missing', 'bad/name']})
        data = await response.json()
        self.assertEqual(data['deleted'], ['first'])
        self.assertEqual({entry['reason'] for entry in data['failed']}, {'not found', 'invalid name'})
        self.assertEqual((await self.client.get('/api/projects/second')).status, 200)

    async def test_project_mutations_reject_invalid_names_and_body_types(self):
        cases = [
            ({}, 'Project name is required'),
            ({'name': 'valid', 'old_name': 42}, 'old_name must be a string'),
            ({'name': 'valid', 'old_name': 'bad/name'}, 'Invalid old_name'),
            ({'name': 'valid', 'template': []}, 'template must be a string'),
            ({'name': 'valid', 'config': []}, 'config must be a string'),
        ]
        for payload, error in cases:
            response = await self.client.post('/api/projects', json=payload)
            self.assertEqual(response.status, 400)
            self.assertIn(error, (await response.json())['error'])
        for path, payload in [('/api/projects', []), ('/api/projects/batch-delete', []),
                              ('/api/projects/batch-delete', {'names': []})]:
            response = await self.client.post(path, json=payload)
            self.assertEqual(response.status, 400)
        self.assertEqual((await self.client.get('/api/projects/bad%20name')).status, 400)
        self.assertEqual((await self.client.delete('/api/projects/bad%20name')).status, 400)

    async def test_project_update_keeps_legacy_terraform_files_and_snapshots_original(self):
        routes._PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
        path = routes._PROJECTS_DIR / 'legacy.json'
        path.write_text(json.dumps({'name': 'legacy', 'template': '',
                                    'template_files': {'main.tf': 'resource {}'},
                                    'config': 'parameters: {Name: old}', 'created_at': 'original'}))
        response = await self.client.post('/api/projects', json={
            'name': 'legacy', 'old_name': 'legacy', 'config': 'parameters: {Name: new}'})
        self.assertEqual(response.status, 200)
        saved = json.loads(path.read_text())
        self.assertEqual(saved['template_files'], {'main.tf': 'resource {}'})
        self.assertEqual(saved['created_at'], 'original')
        self.assertEqual([item['version'] for item in saved['versions']], [1, 2])
        self.assertEqual(saved['versions'][0]['template_files'], {'main.tf': 'resource {}'})
        self.assertEqual(saved['current_version'], 2)

    async def test_project_save_with_missing_rename_source_creates_new_project(self):
        response = await self.client.post('/api/projects', json={
            'name': 'newname', 'old_name': 'missing', 'template': 'Resources: {}'})
        self.assertEqual(response.status, 200)
        response = await self.client.get('/api/projects/newname')
        project = await response.json()
        self.assertEqual(project['template'], 'Resources: {}')
        self.assertEqual(project['current_version'], 1)
        self.assertEqual(len(project['versions']), 1)

    async def test_start_run_injects_parameters_and_preserves_original_config(self):
        import asyncio
        from types import SimpleNamespace
        captured = {}
        future = asyncio.get_running_loop().create_future()
        async def start(params, run_id):
            captured['params'] = dict(params)
            captured['run_id'] = run_id
            return SimpleNamespace(_task=future, to_dict=lambda: {'id': run_id})
        def write(template, config, **kwargs):
            captured['written_config'] = config
            return 'template-path', 'config-path', kwargs['subdir']
        payload = {'template_content': 'Parameters: {VpcId: {Type: String}}',
                   'config_content': 'tests: {default: {parameters: {VpcId: old}}}',
                   'regions': 'cn-hangzhou'}
        with mock.patch.object(routes, 'DEFAULT_OUTPUT_DIRECTORY', str(Path(self.temp_dir.name) / 'output')), \
             mock.patch.object(routes, '_write_current_files', write), \
             mock.patch.object(routes, '_cleanup_current_files') as cleanup, \
             mock.patch.object(self.app['runner'], 'start_test_run', start):
            response = await self.client.post('/api/runs', json=payload)
            self.assertEqual(response.status, 201)
            params = captured['params']
            self.assertEqual(yaml.safe_load(params['raw_config_content'])['tests']['default']['parameters']['VpcId'], 'old')
            self.assertEqual(yaml.safe_load(captured['written_config'])['tests']['default']['parameters']['VpcId'], '$[iact3-auto]')
            self.assertEqual(params['template'], 'template-path')
            self.assertEqual(params['config_file'], 'config-path')
            self.assertIn(captured['run_id'], params['output_directory'])
            future.set_result(None)
            await asyncio.sleep(0)
            cleanup.assert_called_once()

    async def test_start_terraform_run_uses_written_directory_and_preserves_editor_files(self):
        import asyncio
        from types import SimpleNamespace

        captured = {}
        future = asyncio.get_running_loop().create_future()

        async def start(params, run_id):
            captured['params'] = dict(params)
            return SimpleNamespace(_task=future, to_dict=lambda: {'id': run_id})

        def write(template, config, **kwargs):
            captured['template'] = template
            captured['files'] = kwargs['template_files']
            return 'terraform-dir', None, kwargs['subdir']

        payload = {'template_files': {'main.tf': 'variable "Name" {}'}, 'regions': 'cn-a'}
        with mock.patch.object(routes, 'DEFAULT_OUTPUT_DIRECTORY', str(Path(self.temp_dir.name) / 'output')), \
             mock.patch.object(routes, '_write_current_files', write), \
             mock.patch.object(routes, '_cleanup_current_files') as cleanup, \
             mock.patch.object(self.app['runner'], 'start_test_run', start):
            response = await self.client.post('/api/runs', json=payload)
            self.assertEqual(response.status, 201)
            self.assertEqual(captured['files'], payload['template_files'])
            self.assertEqual(captured['params']['raw_template_files'], payload['template_files'])
            self.assertEqual(captured['params']['template'], 'terraform-dir')
            self.assertNotIn('template_content', captured['params'])
            future.set_result(None)
            await asyncio.sleep(0)
            cleanup.assert_called_once()

    async def test_run_endpoints_filter_cancel_and_batch_delete(self):
        runs = [{'id': 'a', 'name': 'Alpha', 'status': 'completed'},
                {'id': 'b', 'name': 'Beta', 'status': 'failed'},
                {'id': 'c', 'name': 'Alphabet', 'status': 'failed'}]
        async def cancel(run_id):
            return run_id == 'a'
        with mock.patch.object(self.app['runner'], 'get_all_runs', return_value=runs), \
             mock.patch.object(self.app['runner'], 'get_run', side_effect=lambda run_id: runs[0] if run_id == 'a' else None), \
             mock.patch.object(self.app['runner'], 'get_run_logs', return_value='log'), \
             mock.patch.object(self.app['runner'], 'cancel_run', cancel), \
             mock.patch.object(self.app['runner'], 'delete_run', side_effect=lambda run_id: run_id == 'a'):
            response = await self.client.get('/api/runs?search=alpha&status=failed&page=bad&per_page=bad')
            self.assertEqual([run['id'] for run in (await response.json())['runs']], ['c'])
            self.assertEqual((await self.client.get('/api/runs/a')).status, 200)
            self.assertEqual((await self.client.get('/api/runs/missing')).status, 404)
            self.assertEqual(await (await self.client.get('/api/runs/a/logs')).text(), 'log')
            self.assertEqual((await self.client.post('/api/runs/a/cancel')).status, 200)
            self.assertEqual((await self.client.post('/api/runs/b/cancel')).status, 400)
            self.assertEqual((await self.client.delete('/api/runs/b')).status, 400)
            response = await self.client.post('/api/runs/batch-delete', json={'ids': ['a', 'b']})
            self.assertEqual(await response.json(), {'deleted': ['a'], 'failed': [{'id': 'b', 'reason': 'cannot delete'}]})

    async def test_batch_delete_reports_invalid_requests_and_individual_failures(self):
        response = await self.client.post('/api/runs/batch-delete', data='{',
                                          headers={'Content-Type': 'application/json'})
        self.assertEqual(response.status, 400)
        for payload in ([], {}, {'ids': 'bad'}, {'ids': ['']}, {'ids': [None]}):
            self.assertEqual((await self.client.post('/api/runs/batch-delete', json=payload)).status, 400)

        def delete(run_id):
            if run_id == 'broken':
                raise RuntimeError('store unavailable')
            return run_id == 'ok'

        with mock.patch.object(self.app['runner'], 'delete_run', side_effect=delete):
            response = await self.client.post('/api/runs/batch-delete', json={'ids': ['ok', 'missing', 'broken']})
        self.assertEqual(await response.json(), {'deleted': ['ok'], 'failed': [
            {'id': 'missing', 'reason': 'cannot delete'}, {'id': 'broken', 'reason': 'store unavailable'}]})

    async def test_validation_reports_empty_template_and_uninformative_backend_error(self):
        response = await self.client.post('/api/validate', json={})
        self.assertEqual(response.status, 400)
        self.assertIn('模板内容为空', (await response.json())['error'])

        class Plugin:
            async def validate_template(self, **kwargs):
                raise RuntimeError()

        with mock.patch.object(routes, 'DEFAULT_OUTPUT_DIRECTORY', str(Path(self.temp_dir.name) / 'logs')), \
             mock.patch.object(routes, '_resolve_credential', return_value=object()), \
             mock.patch.object(routes, 'StackPlugin', return_value=Plugin()), \
             mock.patch.object(routes, '_cleanup_current_files') as cleanup:
            response = await self.client.post('/api/validate', json={'template_content': 'Resources: {}'})
            data = await response.json()
            self.assertEqual(response.status, 400)
            self.assertEqual(data['result'], 'invalid')
            self.assertEqual(data['error'], 'RuntimeError: (no message)')
            cleanup.assert_called_once()

    async def test_delete_stacks_reconciles_uncertain_requests(self):
        from types import SimpleNamespace

        statuses = {
            'accepted': 'CREATE_COMPLETE', 'unconfirmed': 'CREATE_COMPLETE',
            'failed': 'CREATE_COMPLETE', 'missing': 'CREATE_COMPLETE',
            'in_progress': 'CREATE_COMPLETE', 'unchanged': 'CREATE_COMPLETE',
            'unknown': 'CREATE_COMPLETE', 'already_polling': 'DELETE_IN_PROGRESS',
        }
        stacks = [{'stack_id': key, 'region': 'cn-test', 'status': value}
                  for key, value in statuses.items()]
        run = SimpleNamespace(stacks=stacks, _task=None, credential_key_id=None, log_path=None)

        class Plugin:
            def __init__(self, **kwargs):
                pass

            async def delete_stack(self, stack_id):
                if stack_id == 'accepted':
                    return True
                if stack_id == 'unconfirmed':
                    return False
                raise RuntimeError('request failed')

            async def get_stack(self, stack_id):
                if stack_id == 'unknown':
                    raise RuntimeError('query failed')
                if stack_id == 'missing':
                    return None
                return {'Status': {'failed': 'DELETE_FAILED', 'in_progress': 'DELETE_IN_PROGRESS',
                                   'unchanged': 'CREATE_COMPLETE'}[stack_id]}

        def groups(items, legacy_key_id):
            return [{'region': 'cn-test', 'credential': object(), 'stacks': items}]

        def capture_background(run_id, coroutine):
            coroutine.close()

        runner = self.app['runner']
        with mock.patch.object(runner, 'get_run_raw', return_value=run), \
             mock.patch.object(runner, '_save_run_to_disk') as save, \
             mock.patch.object(runner, 'start_background_task', side_effect=capture_background) as background, \
             mock.patch.object(routes, '_build_deletion_groups', side_effect=groups), \
             mock.patch.object(routes, 'StackPlugin', Plugin):
            response = await self.client.post('/api/runs/example/delete-stacks')
            data = await response.json()
        self.assertEqual(response.status, 200)
        self.assertEqual((data['deleted'], data['errors']), (3, 5))
        self.assertEqual({s['stack_id']: s['status'] for s in stacks}, {
            'accepted': 'DELETE_IN_PROGRESS', 'unconfirmed': 'DELETE_UNCONFIRMED',
            'failed': 'DELETE_FAILED', 'missing': 'DELETE_UNCONFIRMED',
            'in_progress': 'DELETE_IN_PROGRESS', 'unchanged': 'CREATE_COMPLETE',
            'unknown': 'DELETE_REQUESTING', 'already_polling': 'DELETE_IN_PROGRESS',
        })
        self.assertTrue(save.called)
        background.assert_called_once()

    async def test_delete_stacks_rejects_invalid_run_states(self):
        from types import SimpleNamespace

        runner = self.app['runner']
        with mock.patch.object(runner, 'get_run_raw', return_value=None), \
             mock.patch.object(runner, '_load_single_run_from_disk', return_value=None):
            response = await self.client.post('/api/runs/missing/delete-stacks')
            self.assertEqual((response.status, (await response.json())['code']), (404, 'RUN_NOT_FOUND'))
        run = SimpleNamespace(stacks=[], _task=None, credential_key_id=None, log_path=None)
        with mock.patch.object(runner, 'get_run_raw', return_value=run):
            response = await self.client.post('/api/runs/example/delete-stacks')
            self.assertEqual((response.status, (await response.json())['code']), (400, 'NO_STACKS'))
            run.stacks = [{'stack_id': 'a', 'status': 'DELETE_COMPLETE'}]
            response = await self.client.post('/api/runs/example/delete-stacks')
            self.assertEqual((response.status, (await response.json())['code']), (400, 'NO_DELETABLE_STACKS'))
            run._task = mock.Mock()
            run._task.done.return_value = False
            response = await self.client.post('/api/runs/example/delete-stacks')
            self.assertEqual((response.status, (await response.json())['code']), (409, 'RUN_IN_PROGRESS'))
            run._task = None
            with mock.patch.object(runner, 'claim_background_operation', return_value=False):
                response = await self.client.post('/api/runs/example/delete-stacks')
                self.assertEqual((response.status, (await response.json())['code']), (409, 'DELETION_IN_PROGRESS'))

    async def test_delete_stacks_releases_claim_when_grouping_fails(self):
        from types import SimpleNamespace

        runner = self.app['runner']
        run = SimpleNamespace(stacks=[{'stack_id': 'a', 'status': 'CREATE_COMPLETE'}], _task=None,
                              credential_key_id=None, log_path=None)
        with mock.patch.object(runner, 'get_run_raw', return_value=run), \
             mock.patch.object(runner, 'release_background_claim', wraps=runner.release_background_claim) as release:
            for error, status in ((ValueError('credential mismatch'), 403), (RuntimeError('service error'), 500)):
                with mock.patch.object(routes, '_build_deletion_groups', side_effect=error):
                    response = await self.client.post('/api/runs/example/delete-stacks')
                self.assertEqual(response.status, status)
                self.assertEqual((await response.json())['error'], str(error))
            self.assertEqual(release.call_count, 2)
            self.assertFalse(runner.has_background_task('example'))

    async def test_save_project_preserves_legacy_phantom_version(self):
        project_dir = Path(self.temp_dir.name) / 'projects'
        project_dir.mkdir(parents=True)
        project_file = project_dir / 'legacy.json'
        original = {
            'name': 'legacy', 'template': 'current template', 'config': 'parameters: {Value: old}',
            'current_version': 9, 'versions': [{'version': 1, 'template': 'first template',
                                                 'template_files': {}, 'config': ''}],
        }
        project_file.write_text(json.dumps(original))
        response = await self.client.post('/api/projects', json={
            'name': 'legacy', 'old_name': 'legacy', 'template': 'new template',
            'configs': [{'config': 'parameters: {Value: new}'}],
        })
        self.assertEqual(response.status, 200)
        saved = json.loads(project_file.read_text())
        self.assertEqual([v['version'] for v in saved['versions']], [1, 2, 3])
        self.assertEqual(saved['versions'][1]['template'], 'current template')
        self.assertEqual(saved['versions'][2]['template'], 'new template')
        self.assertEqual(saved['current_version'], 3)
        self.assertEqual(yaml.safe_load(saved['config'])['parameters']['Value'], 'new')

    async def test_project_versions_limit_and_invalid_legacy_configs(self):
        project_dir = Path(self.temp_dir.name) / 'projects'
        project_dir.mkdir(parents=True)
        project_file = project_dir / 'legacy.json'
        versions = [{'version': n, 'template': str(n), 'template_files': {}, 'config': ''}
                    for n in range(1, 21)]
        project_file.write_text(json.dumps({'name': 'legacy', 'template': '20', 'config': '',
                                            'current_version': 20, 'versions': versions}))
        for configs in ([42], [{'config': 42}]):
            response = await self.client.post('/api/projects', json={
                'name': 'legacy', 'old_name': 'legacy', 'template': '21', 'configs': configs,
            })
            self.assertEqual((response.status, (await response.json())['code']), (400, 'INVALID_REQUEST'))
            self.assertEqual(json.loads(project_file.read_text())['current_version'], 20)
        response = await self.client.post('/api/projects', json={
            'name': 'legacy', 'old_name': 'legacy', 'template': '21',
        })
        self.assertEqual(response.status, 200)
        saved = json.loads(project_file.read_text())
        self.assertEqual(len(saved['versions']), 20)
        self.assertEqual(saved['versions'][0]['version'], 2)
        self.assertEqual(saved['current_version'], 21)
        self.assertEqual(saved['versions'][-1]['template'], '21')

    async def test_credential_detection_masks_key_and_respects_environment(self):
        import os

        auth_file = Path(self.temp_dir.name) / 'credentials.json'
        auth_file.write_text(json.dumps({'current': 'chosen', 'profiles': [
            {'name': 'other', 'mode': 'AK', 'access_key_id': 'OTHERKEY', 'access_key_secret': 'other-secret'},
            {'name': 'chosen', 'mode': 'AK', 'access_key_id': 'EXAMPLE1234', 'access_key_secret': 'private-secret'},
        ]}))
        with mock.patch.object(routes, 'DEFAULT_AUTH_FILE', auth_file), mock.patch.dict(os.environ, {}, clear=True):
            settings = await (await self.client.get('/api/settings')).json()
            credentials = await (await self.client.get('/api/credentials')).json()
            self.assertEqual(settings['settings']['source'], 'aliyun-cli')
            self.assertEqual(credentials['source'], 'aliyun-cli')
            self.assertEqual(credentials['current_profile_key_id_tail'], '****1234')
            self.assertNotIn('private-secret', json.dumps(credentials))
            self.assertNotIn('EXAMPLE1234', json.dumps(settings))
            with mock.patch.dict(os.environ, {'ALIBABA_CLOUD_ACCESS_KEY_ID': 'ENV',
                                              'ALIBABA_CLOUD_ACCESS_KEY_SECRET': 'ENVSECRET'}):
                credentials = await (await self.client.get('/api/credentials')).json()
                self.assertEqual(credentials['source'], 'env')
                self.assertTrue(credentials['env_set'])
            auth_file.write_text('{')
            credentials = await (await self.client.get('/api/credentials')).json()
            self.assertEqual(credentials['source'], 'none')
            self.assertEqual(credentials['profiles'], [])

    async def test_version_deletion_restores_legacy_config_and_rejects_last_version(self):
        project_dir = Path(self.temp_dir.name) / 'projects'
        project_dir.mkdir(parents=True)
        project_file = project_dir / 'demo.json'
        project_file.write_text(json.dumps({
            'name': 'demo', 'current_version': 2, 'template': 'current', 'config': '',
            'versions': [
                {'version': 1, 'template': 'legacy', 'configs': [{'config': 'project: {name: old}'}]},
                {'version': 2, 'template': 'current', 'config': ''},
            ],
        }))
        response = await self.client.delete('/api/projects/demo/versions/2')
        result = await response.json()
        self.assertTrue(result['auto_switched'])
        self.assertEqual(result['current_version'], 1)
        saved = json.loads(project_file.read_text())
        self.assertEqual(saved['template'], 'legacy')
        self.assertEqual(yaml.safe_load(saved['config'])['project']['name'], 'demo')
        response = await self.client.delete('/api/projects/demo/versions/1')
        self.assertEqual(response.status, 400)
        self.assertIn('last version', (await response.json())['error'])

    async def test_version_deletion_repairs_phantom_current_and_missing_project_returns_404(self):
        project_dir = Path(self.temp_dir.name) / 'projects'
        project_dir.mkdir(parents=True)
        project_file = project_dir / 'demo.json'
        project_file.write_text(json.dumps({
            'name': 'demo', 'current_version': 99, 'template': 'newest',
            'versions': [{'version': 1, 'template': 'old'}, {'version': 2, 'template': 'newest'}],
        }))
        response = await self.client.delete('/api/projects/demo/versions/1')
        result = await response.json()
        self.assertTrue(result['auto_switched'])
        self.assertEqual(result['current_version'], 2)
        for method, path in [
            ('get', '/api/projects/missing/versions/1'),
            ('post', '/api/projects/missing/versions/1/activate'),
            ('delete', '/api/projects/missing/versions/1'),
        ]:
            response = await getattr(self.client, method)(path)
            self.assertEqual(response.status, 404)
        response = await self.client.post('/api/projects/demo/versions/999/activate')
        self.assertEqual(response.status, 404)

    async def test_terraform_analysis_uses_location_and_cleans_up_on_success_and_failure(self):
        calls = []
        class Config:
            def __init__(self, template_location):
                calls.append(('config', template_location))
            def generate_template_args(self):
                return {'template_body': 'terraform-wrapper'}
        class Plugin:
            async def validate_template(self, **kwargs):
                calls.append(('validate', kwargs))
                return {'valid': True}
            async def generate_template_policy(self, **kwargs):
                raise RuntimeError('policy failed')
        payload = {'template_files': {'main.tf': 'resource {}'}, 'regions': 'cn-a'}
        log_root = Path(self.temp_dir.name) / 'logs'
        with mock.patch.object(routes, 'DEFAULT_OUTPUT_DIRECTORY', str(log_root)), \
             mock.patch.object(routes, '_prepare_template_location', return_value=('/tmp/template', 'temp-id')), \
             mock.patch.object(routes, '_cleanup_current_files') as cleanup, \
             mock.patch.object(routes, '_resolve_credential', return_value=object()) as credential, \
             mock.patch.object(routes, 'TemplateConfig', Config), \
             mock.patch.object(routes, 'StackPlugin', return_value=Plugin()):
            response = await self.client.post('/api/validate', json=payload)
            self.assertEqual(response.status, 200)
            self.assertEqual((await response.json())['details'], {'valid': True})
            response = await self.client.post('/api/policy', json=payload)
            self.assertEqual(response.status, 500)
            self.assertEqual((await response.json())['error'], 'policy failed')
            self.assertEqual(credential.call_count, 2)
            self.assertEqual(credential.call_args[1]['template_location'], '/tmp/template')
            self.assertEqual(cleanup.call_args_list, [mock.call(subdir='temp-id'), mock.call(subdir='temp-id')])
            self.assertEqual(list(log_root.glob('*.log')), [])
        self.assertIn(('validate', {'template_body': 'terraform-wrapper'}), calls)

    async def test_report_endpoints_reject_symlink_escape_and_handle_invalid_json_preview(self):
        import os
        previous_dir = os.getcwd()
        try:
            os.chdir(self.temp_dir.name)
            output = Path('iact3_outputs')
            output.mkdir()
            outside = Path(self.temp_dir.name) / 'outside.txt'
            outside.write_text('private')
            (output / 'escape.txt').symlink_to(outside)
            (output / 'invalid.json').write_text('{invalid')
            for method, path in [
                ('get', '/api/reports/escape.txt'),
                ('get', '/api/reports/escape.txt/raw'),
                ('delete', '/api/reports/escape.txt'),
            ]:
                response = await getattr(self.client, method)(path)
                self.assertEqual(response.status, 403)
            self.assertEqual(outside.read_text(), 'private')
            response = await self.client.get('/api/reports/invalid.json/raw')
            self.assertEqual((await response.json())['content'], '{invalid')
        finally:
            os.chdir(previous_dir)

    async def test_report_cleanup_removes_only_files_older_than_threshold(self):
        import os
        import time
        previous_dir = os.getcwd()
        try:
            os.chdir(self.temp_dir.name)
            output = Path('iact3_outputs')
            output.mkdir()
            old = output / 'old.txt'
            new = output / 'new.txt'
            old.write_text('old')
            new.write_text('new')
            timestamp = time.time() - 10 * 86400
            os.utime(str(old), (timestamp, timestamp))
            response = await self.client.post('/api/reports/cleanup', json={'mode': 'older_than', 'days': 7})
            self.assertEqual(await response.json(), {'deleted': 1, 'freed': 3})
            self.assertFalse(old.exists())
            self.assertTrue(new.exists())
        finally:
            os.chdir(previous_dir)

    async def test_analysis_formats_known_cloud_errors_and_cleans_up(self):
        from Tea.exceptions import TeaException
        log_root = Path(self.temp_dir.name) / 'logs'
        cases = [
            ('UnknownUserParameter', 'The Parameter (VpcId) was not defined in template', 'VpcId'),
            ('TemplateNotFound', 'missing', 'Template not found'),
            ('InvalidTemplate', 'bad template', 'Invalid template'),
            ('Other', 'failure', '[Other] failure'),
        ]
        payload = {'template_content': 'Resources: {}', 'regions': 'cn-a'}
        with mock.patch.object(routes, 'DEFAULT_OUTPUT_DIRECTORY', str(log_root)), \
             mock.patch.object(routes, '_write_current_files', return_value=(None, 'config.yml', 'cfg')), \
             mock.patch.object(routes, '_cleanup_current_files') as cleanup:
            for code, message, expected in cases:
                async def fail(**kwargs):
                    raise TeaException({'code': code, 'message': message})
                with mock.patch.object(routes.StackTest, 'from_file', fail):
                    for endpoint in ('cost', 'preview'):
                        response = await self.client.post('/api/' + endpoint, json=payload)
                        self.assertEqual(response.status, 400)
                        self.assertIn(expected, (await response.json())['error'])
            self.assertEqual(cleanup.call_count, len(cases) * 4)
            self.assertEqual(list(log_root.glob('*.log')), [])

    async def test_analysis_rejects_bad_bodies_and_missing_template_or_region(self):
        for endpoint in ('validate', 'cost', 'preview', 'policy', 'generate-params'):
            path = '/api/' + endpoint
            response = await self.client.post(path, data='{', headers={'Content-Type': 'application/json'})
            self.assertEqual(response.status, 400, endpoint)
            self.assertEqual((await response.json())['error'], 'Invalid JSON')
            response = await self.client.post(path, json=[])
            self.assertEqual(response.status, 400, endpoint)
            self.assertEqual((await response.json())['error'], 'Request body must be an object')
            response = await self.client.post(path, json={'regions': 123})
            self.assertEqual(response.status, 400, endpoint)
            self.assertEqual((await response.json())['code'], 'INVALID_REQUEST')

        for endpoint in ('cost', 'preview', 'policy', 'generate-params'):
            response = await self.client.post('/api/' + endpoint, json={})
            self.assertEqual(response.status, 400, endpoint)
            self.assertIn('模板内容为空', (await response.json())['error'])
        for endpoint in ('cost', 'preview'):
            response = await self.client.post('/api/' + endpoint, json={'template_content': 'Resources: {}'})
            self.assertEqual(response.status, 400, endpoint)
            self.assertIn('地域', (await response.json())['error'])

    async def test_analysis_reports_unexpected_errors_and_cleans_up(self):
        async def fail(**kwargs):
            raise RuntimeError('backend unavailable')

        payload = {'template_content': 'Resources: {}', 'regions': 'cn-a'}
        with mock.patch.object(routes, 'DEFAULT_OUTPUT_DIRECTORY', str(Path(self.temp_dir.name) / 'logs')), \
             mock.patch.object(routes, '_write_current_files', return_value=(None, 'config.yml', 'cfg')), \
             mock.patch.object(routes, '_cleanup_current_files') as cleanup, \
             mock.patch.object(routes.StackTest, 'from_file', fail):
            for endpoint in ('cost', 'preview'):
                response = await self.client.post('/api/' + endpoint, json=payload)
                self.assertEqual(response.status, 500)
                self.assertEqual((await response.json())['error'], 'backend unavailable')
            self.assertEqual(cleanup.call_count, 4)

    async def test_generate_parameters_requires_credentials_for_ros_and_terraform(self):
        template_dir = Path(self.temp_dir.name) / 'template'
        template_dir.mkdir()
        (template_dir / 'main.tf').write_text('variable "Name" {}')
        with mock.patch.object(routes, '_resolve_credential', return_value=None), \
             mock.patch.object(routes, '_prepare_template_location', return_value=(str(template_dir), 'tf-temp')), \
             mock.patch.object(routes, '_cleanup_current_files') as cleanup:
            for payload in ({'template_content': 'Resources: {}'},
                            {'template_files': {'main.tf': 'variable "Name" {}'}}):
                response = await self.client.post('/api/generate-params', json=payload)
                self.assertEqual(response.status, 400)
                self.assertIn('凭证', (await response.json())['error'])
            self.assertEqual(cleanup.call_count, 2)

    async def test_analysis_stack_errors_identify_undefined_parameters(self):
        from types import SimpleNamespace
        stack = SimpleNamespace(test_name='case', region='cn-a', template_price=None, preview_result=None,
                                status='UnknownUserParameter',
                                status_reason='The Parameter (VpcId) was not defined in template')
        async def from_file(**kwargs):
            return SimpleNamespace(stacker=SimpleNamespace(stacks=[stack]))
        async def analyse(test):
            return None
        with mock.patch.object(routes, 'DEFAULT_OUTPUT_DIRECTORY', str(Path(self.temp_dir.name) / 'logs')), \
             mock.patch.object(routes, '_write_current_files', return_value=(None, 'config.yml', 'cfg')), \
             mock.patch.object(routes, '_cleanup_current_files'), \
             mock.patch.object(routes.StackTest, 'from_file', from_file), \
             mock.patch.object(routes.StackTest, 'get_stacks_price', analyse), \
             mock.patch.object(routes.StackTest, 'preview_stacks_result', analyse):
            for endpoint, key in [('cost', 'prices'), ('preview', 'previews')]:
                response = await self.client.post('/api/' + endpoint, json={
                    'template_content': 'Resources: {}', 'regions': 'cn-a'})
                self.assertEqual(response.status, 200)
                self.assertIn('VpcId', (await response.json())[key][0]['error'])

    async def test_terraform_analysis_uses_directory_and_handles_empty_stacker(self):
        from types import SimpleNamespace
        calls = []

        async def from_file(**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(stacker=None)

        async def analyse(test):
            self.assertIsNone(test.stacker)

        with mock.patch.object(routes, 'DEFAULT_OUTPUT_DIRECTORY', str(Path(self.temp_dir.name) / 'logs')), \
             mock.patch.object(routes, '_prepare_template_location', return_value=('/tmp/tf-project', 'tf')), \
             mock.patch.object(routes, '_write_current_files', return_value=(None, 'config.yml', 'cfg')), \
             mock.patch.object(routes, '_cleanup_current_files') as cleanup, \
             mock.patch.object(routes.StackTest, 'from_file', from_file), \
             mock.patch.object(routes.StackTest, 'get_stacks_price', analyse), \
             mock.patch.object(routes.StackTest, 'preview_stacks_result', analyse):
            for endpoint, key in [('cost', 'prices'), ('preview', 'previews')]:
                response = await self.client.post('/api/' + endpoint, json={
                    'template_files': {'main.tf': 'resource {}'}, 'regions': 'cn-a'})
                self.assertEqual(response.status, 200)
                self.assertEqual((await response.json())[key], [])
        self.assertEqual([call['template'] for call in calls], ['/tmp/tf-project'] * 2)
        self.assertTrue(all('template_content' not in call for call in calls))
        self.assertEqual(cleanup.call_args_list, [mock.call(subdir='tf'), mock.call(subdir='cfg')] * 2)

    async def test_generate_terraform_params_without_variables_and_with_complex_defaults(self):
        async def resolve(params, region, credential):
            return params
        base_payload = {'template_files': {'main.tf': 'resource "x" "y" {}'},
                        'config_content': 'parameters: {Custom: value}', 'regions': 'cn-a'}
        with mock.patch.object(routes, 'DEFAULT_PROJECT_ROOT', Path(self.temp_dir.name)), \
             mock.patch.object(routes, '_resolve_credential', return_value=object()), \
             mock.patch.object(routes, '_resolve_terraform_params', resolve):
            response = await self.client.post('/api/generate-params', json=base_payload)
            data = await response.json()
            self.assertEqual(response.status, 200)
            self.assertIn('No Terraform variables', data['logs'])
            self.assertEqual(yaml.safe_load(data['config'])['parameters']['Custom'], 'value')
            multi_payload = dict(base_payload, regions='cn-a,cn-b')
            response = await self.client.post('/api/generate-params', json=multi_payload)
            multi_data = await response.json()
            self.assertEqual(response.status, 200)
            self.assertIn('No Terraform variables', multi_data['logs'])
            self.assertIn('Multi-region', multi_data['logs'])
            self.assertEqual(yaml.safe_load(multi_data['config'])['parameters']['Custom'], 'value')
            payload = {'template_files': {'main.tf': '''
variable "VpcId" { type = string }
variable "Name" {
  type = string
  default = "example"
}
variable "complex" {
  default = [
    "value"
  ]
}
'''}, 'regions': 'cn-a,cn-b'}
            response = await self.client.post('/api/generate-params', json=payload)
            data = await response.json()
            self.assertEqual(response.status, 200)
            params = yaml.safe_load(data['config'])['parameters']
            self.assertEqual(params['VpcId'], '$[iact3-auto]')
            self.assertEqual(params['Name'], 'example')
            self.assertNotIn('complex', params)
            self.assertIn('type=string', data['logs'])
            self.assertIn('Multi-region', data['logs'])
