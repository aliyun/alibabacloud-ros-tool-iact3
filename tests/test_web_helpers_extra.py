import json
from pathlib import Path
from unittest import mock

import pytest
import yaml

from iact3.web import routes
from tests.common import AsyncTestCase


@pytest.mark.parametrize('name', ['', '../foo', '/tmp/a', 'dir/', 'bad\x00name', 42])
def test_template_names_reject_unsafe_paths(name):
    with pytest.raises(ValueError):
        routes._validate_template_files({name: 'contents'})


def test_template_files_validate_contents():
    routes._validate_template_files(None)
    routes._validate_template_files({'nested/main.tf': 'contents'})
    with pytest.raises(ValueError):
        routes._validate_template_files([])
    with pytest.raises(ValueError):
        routes._validate_template_files({'main.tf': 7})


def test_boolean_parameters_are_strict():
    assert routes._json_bool({}, 'flag', True) is True
    assert routes._json_bool({'flag': False}, 'flag') is False
    with pytest.raises(ValueError):
        routes._json_bool({'flag': 'false'}, 'flag')


@pytest.mark.parametrize('config', [[], {'project': 1}, {'auth': []}, {'parameters': []},
                                    {'tests': []}, {'tests': {'default': None}}, {'tests': {1: {}}}])
def test_config_structure_rejects_invalid_shapes(config):
    with pytest.raises(ValueError):
        routes._validate_config_structure(config)


def test_config_structure_accepts_empty_sections_and_preserves_valid_data():
    assert routes._validate_config_structure(None) == {}
    config = {'project': None, 'auth': None, 'parameters': None, 'tests': {'default': {}}}
    assert routes._validate_config_structure(config) is config
    assert yaml.safe_load(routes._sync_project_name_in_config('parameters: {}', 'renamed')) == {
        'project': {'name': 'renamed'}, 'parameters': {}}
    original = 'project: {name: renamed}\n'
    assert routes._sync_project_name_in_config(original, 'renamed') == original


def test_path_containment_uses_boundaries_and_resolves_symlinks(tmp_path):
    root = tmp_path / 'project'
    root.mkdir()
    outside = tmp_path / 'project-other'
    outside.mkdir()
    (root / 'link').symlink_to(outside, target_is_directory=True)
    assert routes._is_path_within(root / 'file', [root])
    assert not routes._is_path_within(outside / 'file', [root])
    assert not routes._is_path_within(root / 'link' / 'file', [root])


def test_generate_tests_section_only_when_needed():
    assert routes._ensure_tests_section('', None) == ''
    result = routes._ensure_tests_section('', 'cn-a, cn-b', 'my-project')
    assert yaml.safe_load(result) == {'project': {'name': 'my-project'},
                                      'tests': {'default': {'regions': ['cn-a', 'cn-b']}}}
    existing = 'tests: {default: {regions: [cn-old]}}\n'
    assert routes._ensure_tests_section(existing, 'cn-new') == existing
    assert routes._ensure_tests_section('project: {}', ' , ') == 'project: {}'
    result = routes._ensure_tests_section('project: {}', 'cn-new')
    assert yaml.safe_load(result)['tests']['default']['regions'] == ['cn-new']
    with pytest.raises(ValueError, match='Invalid config YAML'):
        routes._ensure_tests_section('tests: [', 'cn-a')


def test_generated_params_target_correct_section_and_reject_invalid_yaml():
    assert yaml.safe_load(routes._merge_generated_parameters('', {'A': 1})) == {'parameters': {'A': 1}}
    result = routes._merge_generated_parameters('tests: {smoke: {hooks: {}}}', {'B': 2})
    assert yaml.safe_load(result)['tests']['smoke'] == {'hooks': {}, 'parameters': {'B': 2}}
    for config in ('[', '[]', 'tests: []', 'tests: {smoke: 1}', 'tests: {a: {}, b: {}}'):
        with pytest.raises(ValueError):
            routes._merge_generated_parameters(config, {})
    assert routes._get_target_parameters({'parameters': {'A': 1}}) == {'A': 1}
    assert routes._get_target_parameters({'tests': {'smoke': {'parameters': {'B': 2}}}}) == {'B': 2}
    assert routes._get_target_parameters({'tests': {'smoke': {'parameters': []}}}) == {}


def test_generated_parameters_initialize_empty_or_null_default_test():
    for config in ('tests: {}', 'tests: {default: null}', 'tests: {default: {hooks: {}}}'):
        result = yaml.safe_load(routes._merge_generated_parameters(config, {'VpcId': 'vpc'}))
        assert result['tests']['default']['parameters'] == {'VpcId': 'vpc'}
    with pytest.raises(ValueError, match='multiple tests'):
        routes._get_target_parameters({'tests': {'first': {}, 'second': {}}})
    assert routes._get_target_parameters({'parameters': []}) == {}


def test_config_matching_ignores_project_names():
    assert routes._config_matches_project('project: {name: old}\nparameters: {A: 1}',
                                          ['project: {name: new}\nparameters: {A: 1}'])
    assert not routes._config_matches_project('', [''])
    assert not routes._config_matches_project('parameters: {A: 1}', ['parameters: {A: 2}'])
    assert routes._strip_project_name_from_config('invalid: [') == 'invalid: ['


def test_config_helpers_preserve_non_project_fields_and_empty_inputs():
    assert routes._sync_project_name_in_config('', 'name') == ''
    assert routes._sync_project_name_in_config('parameters: {}', '') == 'parameters: {}'
    assert routes._strip_project_name_from_config('') == ''
    assert routes._strip_project_name_from_config('- one\n- two') == '- one\n- two'
    stripped = routes._strip_project_name_from_config('project: {name: old, description: keep}\nparameters: {A: 1}')
    assert json.loads(stripped) == {'project': {'description': 'keep'}, 'parameters': {'A': 1}}
    assert yaml.safe_load(routes._merge_generated_parameters('null', {'A': 1})) == {'parameters': {'A': 1}}
    assert routes._get_target_parameters(None) == {}


def test_tests_section_and_defaults_support_missing_optional_values():
    config = routes._ensure_tests_section('', 'cn-a, , cn-b')
    assert yaml.safe_load(config) == {'tests': {'default': {'regions': ['cn-a', 'cn-b']}}}
    assert routes._ensure_tests_section('parameters: {}', None) == 'parameters: {}'
    assert routes._get_param_default('ImageId', {}, is_terraform=True) == routes._COMMON_DEFAULTS['ImageId']
    template = 'Parameters: {Count: {Type: Number, Default: 3}}'
    generated = yaml.safe_load(routes._inject_auto_params(template, None, 'parameters: []'))
    assert generated['parameters'] == {'Count': '3'}


def test_parameter_defaults_and_auto_detection():
    assert routes._get_param_default('Example', {'Default': 4}) == '4'
    assert routes._get_param_default('Example', {'default': False}, True) == 'False'
    assert routes._get_param_default('ImageId', {'Default': None}) == routes._COMMON_DEFAULTS['ImageId']
    assert routes._get_param_default('Other', {}) == ''
    assert routes._is_auto_resolvable('VpcId')
    assert routes._is_auto_resolvable('Password')
    assert not routes._is_auto_resolvable('Arbitrary')


def test_terraform_parser_handles_comments_defaults_and_incomplete_blocks():
    text = '''
variable "first" {
  type = string
  description = "A description"
  default = "value {escaped}"
}
variable "number" {
  default = -3.5
}
variable "boolean" {
  default = false
}
variable "none" {
  default = null
}
variable "list" {
  default = [1, 2]
}
variable "unfinished" {
  default = true
'''
    result = routes._parse_terraform_variables({'main.tf': text, 'ignore.txt': text})
    assert result['first']['type'] == 'string'
    assert result['first']['description'] == 'A description'
    assert result['first']['default'] == 'value {escaped}'
    assert result['number']['default'] == '-3.5'
    assert result['boolean']['default'] == 'false'
    assert result['none']['has_default'] and result['none']['default'] is None
    assert result['list']['default'] == '[1, 2]'
    assert 'unfinished' not in result
    assert routes._parse_terraform_variables({}) == {}


def test_terraform_parser_ignores_braces_in_comments_strings_and_heredoc():
    source = '''variable "description" {
  # } ignored until newline
  // another } comment
  description = "quoted \\" } still quoted"
  default = true
  validation {
    error_message = <<EOT
} is part of the message
EOT
  }
}
variable "next" {
  default = "ok"
}
'''
    result = routes._parse_terraform_variables({'main.tf': source})
    assert result['description']['default'] == 'true'
    assert result['next']['default'] == 'ok'


def test_multi_region_parameters_keep_user_values_and_generate_common_values():
    result = routes._resolve_non_region_params({'VpcId': 'vpc-old', 'Password': '$[iact3-auto]',
                                                'Name': '$[iact3-auto]', 'Other': 'kept', 'Count': 2})
    assert result['VpcId'] == '$[iact3-auto]'
    assert len(result['Password']) == 16
    assert result['Name'].startswith('iact3-')
    assert result['Other'] == 'kept' and result['Count'] == 2


def test_multi_region_leaves_unrecognized_auto_values_for_later_resolution():
    from uuid import UUID

    auto = '$[iact3-auto]'
    result = routes._resolve_non_region_params({'UUID': auto, 'Other': auto, 'Name': 'existing'})
    assert str(UUID(result['UUID'])) == result['UUID']
    assert result['Other'] == auto
    assert result['Name'] == 'existing'


def test_history_is_serialized_and_limited(tmp_path, monkeypatch):
    monkeypatch.setattr(routes, '_HISTORY_DIR', tmp_path / 'history')
    first = routes._save_history('example', 'validate', {'nested': [Path('file')]})
    entry = json.loads((routes._HISTORY_DIR / (first + '.json')).read_text())
    assert entry['project_name'] == 'example'
    assert entry['result'] == {'nested': ['file']}
    routes._save_history(None, 'cost', 'result', max_entries=1)
    assert len(list(routes._HISTORY_DIR.glob('*.json'))) == 1


class TestTerraformParameterResolution(AsyncTestCase):
    async def test_resolves_resource_dependencies_and_compatible_disk(self):
        auto = '$[iact3-auto]'
        original = {key: auto for key in ('VpcId', 'VSwitchId', 'ZoneId', 'SecurityGroupId',
                                         'InstanceType', 'SystemDiskCategory', 'Name', 'Password', 'UUID', 'Unknown')}
        class Vpc:
            def __init__(self, *args, **kwargs):
                pass
            async def get_one_vswitch(self):
                return {'VpcId': 'vpc-a', 'VSwitchId': 'vsw-a'}
        class Ecs:
            def __init__(self, *args, **kwargs):
                pass
            async def describe_zones(self):
                return ['zone-a']
            async def get_security_group(self, vpc_id):
                self_vpc.append(vpc_id)
                return {'SecurityGroupId': 'sg-a'}
            async def describe_available_instance_types(self, **kwargs):
                return ['ecs.t6.small'] if kwargs.get('system_disk_category') == 'cloud_ssd' else []
        self_vpc = []
        with mock.patch('iact3.plugin.vpc.VpcPlugin', Vpc), mock.patch('iact3.plugin.ecs.EcsPlugin', Ecs):
            result = await routes._resolve_terraform_params(original, 'cn-test', object())
        self.assertEqual(result['VpcId'], 'vpc-a')
        self.assertEqual(result['VSwitchId'], 'vsw-a')
        self.assertEqual(result['ZoneId'], 'zone-a')
        self.assertEqual(result['SecurityGroupId'], 'sg-a')
        self.assertEqual(self_vpc, ['vpc-a'])
        self.assertEqual(result['InstanceType'], 'ecs.t6.small')
        self.assertEqual(result['SystemDiskCategory'], 'cloud_ssd')
        self.assertEqual(result['Unknown'], '')
        self.assertEqual(len(result['Password']), 16)
        self.assertTrue(result['Name'].startswith('iact3-'))
        self.assertEqual(original['VpcId'], auto)

    async def test_multi_region_preserves_region_dependent_placeholders(self):
        auto = '$[iact3-auto]'
        params = {key: auto for key in ('VpcId', 'ZoneId', 'SecurityGroupId', 'InstanceType', 'Name')}
        result = await routes._resolve_terraform_params(params, 'cn-test', None, multi_region=True)
        self.assertEqual([result[key] for key in ('VpcId', 'ZoneId', 'SecurityGroupId', 'InstanceType')], [auto] * 4)
        self.assertTrue(result['Name'].startswith('iact3-'))

    async def test_ecs_initialization_failure_falls_back_for_disk(self):
        auto = '$[iact3-auto]'
        with mock.patch('iact3.plugin.ecs.EcsPlugin', side_effect=ValueError('unavailable')):
            result = await routes._resolve_terraform_params({'InstanceType': auto, 'SystemDiskCategory': auto},
                                                            'cn-test', None)
        self.assertEqual(result, {'InstanceType': '', 'SystemDiskCategory': 'cloud_essd'})


def test_inject_auto_params_preserves_each_test_and_removes_stale():
    template = '''Parameters:
  VpcId: {Type: String}
  Name: {Type: String}
  Count: {Default: 2}
'''
    config = '''tests:
  first: {parameters: {VpcId: old, Name: user, Stale: discarded}}
  second: {parameters: {Name: other}}
'''
    result = yaml.safe_load(routes._inject_auto_params(template, None, config))
    assert result['tests']['first']['parameters'] == {'VpcId': '$[iact3-auto]', 'Name': 'user', 'Count': '2'}
    assert result['tests']['second']['parameters'] == {'VpcId': '$[iact3-auto]', 'Name': 'other', 'Count': '2'}
    assert routes._inject_auto_params('not: [', None, config) == config


def test_config_regions_and_terraform_wrapper():
    assert routes._config_has_regions('tests: {default: {regions: [cn-hangzhou]}}')
    assert not routes._config_has_regions('tests: {default: {regions: [all]}}')
    assert not routes._config_has_regions('tests: [')
    assert not routes._config_has_regions('[]')
    assert routes._is_terraform_template_body('{"Transform": "Aliyun::Terraform-v1.2"}')
    assert not routes._is_terraform_template_body('{')
    assert not routes._is_terraform_template_body('')


def test_temp_files_are_isolated_and_cleanup_is_scoped(tmp_path, monkeypatch):
    monkeypatch.setattr(routes, '_UPLOAD_DIR', tmp_path / 'uploads')
    monkeypatch.setattr(routes, 'DEFAULT_PROJECT_ROOT', tmp_path)
    template, config, request_id = routes._write_current_files(
        None, 'tests: {}', template_files={'sub/main.tf': 'variable "a" {}'}, subdir='request')
    assert request_id == 'request'
    assert (tmp_path / template / 'sub/main.tf').read_text() == 'variable "a" {}'
    assert (tmp_path / config).read_text() == 'tests: {}'
    assert (tmp_path / template).exists()
    routes._cleanup_current_files(request_id)
    assert not (tmp_path / template).exists()
    with pytest.raises(ValueError):
        routes._write_current_files(None, None, template_files={'../bad.tf': 'text'})


def test_credential_resolution_uses_config_then_fallback(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from iact3.config import Auth
    credential = object()
    monkeypatch.setattr(routes, '_write_current_files', lambda *args, **kwargs: (None, 'config.yml', 'request'))
    cleanup = mock.Mock()
    monkeypatch.setattr(routes, '_cleanup_current_files', cleanup)
    base = SimpleNamespace(tests={'default': SimpleNamespace(auth=SimpleNamespace(credential=credential))})
    create = mock.Mock(return_value=base)
    monkeypatch.setattr(routes.BaseConfig, 'create', create)
    assert routes._resolve_credential('tests: {}', template_body='body', regions=['cn-a', 'cn-b']) is credential
    assert create.call_args[1]['args']['project']['regions'] == ['cn-a', 'cn-b']
    cleanup.assert_called_once_with(subdir='request')
    fallback = object()
    monkeypatch.setattr(Auth, '_get_credential', lambda self: fallback)
    assert routes._resolve_credential('') is fallback
    create.side_effect = ValueError('invalid config')
    assert routes._resolve_credential('invalid config') is fallback


def test_credential_resolution_uses_project_auth_for_empty_test_set(monkeypatch):
    from types import SimpleNamespace
    credential = object()
    cleanup = mock.Mock()
    create = mock.Mock(return_value=SimpleNamespace(tests={}, project=SimpleNamespace(
        auth=SimpleNamespace(credential=credential))))
    monkeypatch.setattr(routes, '_write_current_files', lambda *args, **kwargs: (None, 'config.yml', 'request'))
    monkeypatch.setattr(routes, '_cleanup_current_files', cleanup)
    monkeypatch.setattr(routes.BaseConfig, 'create', create)
    assert routes._resolve_credential('project: {}', template_location='/tmp/template', regions='cn-a,cn-b') is credential
    assert create.call_args[1]['args']['project']['regions'] == ['cn-a', 'cn-b']
    assert create.call_args[1]['args']['project'][routes.TEMPLATE_CONFIG][routes.TEMPLATE_LOCATION] == '/tmp/template'
    cleanup.assert_called_once_with(subdir='request')


def test_config_regions_ignores_absent_tests_and_invalid_test_entries():
    assert not routes._config_has_regions('project: {}')
    assert not routes._config_has_regions('tests: {broken: invalid, valid: {regions: [all]}}')
    assert routes._config_has_regions('tests: {broken: invalid, valid: {regions: [cn-a]}}')


def test_deletion_groups_share_credentials_and_skip_incomplete_stacks(monkeypatch):
    from iact3.cli_modules.list import List
    credential = object()
    get_credential = mock.Mock(return_value=credential)
    monkeypatch.setattr(List, 'get_credential', get_credential)
    monkeypatch.setattr(routes, 'get_credential_key_id', lambda value: 'key')
    stacks = [{'stack_id': 'a', 'region': 'cn-a'}, {'stack_id': 'b', 'region': 'cn-a'},
              {'stack_id': '', 'region': 'cn-a'}, {'stack_id': 'c', 'region': ''}]
    groups = routes._build_deletion_groups(stacks)
    assert len(groups) == 1
    assert groups[0]['credential'] is credential
    assert groups[0]['stacks'] == stacks[:2]
    get_credential.assert_called_once()


def test_saved_project_inputs_are_used_only_when_editor_fields_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(routes, '_PROJECTS_DIR', tmp_path)
    (tmp_path / 'demo.json').write_text(json.dumps({
        'template': 'saved template', 'config': 'project: {name: old}\ntests: {default: {regions: [cn-a]}}',
    }))
    params = {'project_name': 'demo', 'regions': ['cn-a', ' cn-b ']}
    template, files, config = routes._resolve_project_inputs(params)
    assert template == 'saved template'
    assert files is None
    assert yaml.safe_load(config)['project']['name'] == 'demo'
    assert params['regions'] == 'cn-a,cn-b'
    template, _, config = routes._resolve_project_inputs({
        'project_name': 'demo', 'template_content': '', 'config_content': '',
    })
    assert template == '' and config == ''


@pytest.mark.parametrize('params', [
    {'project_name': 1}, {'project_name': '../bad'}, {'template_content': []},
    {'config_content': []}, {'regions': [1]}, {'regions': 1}, {'name': []},
    {'test_names': 2}, {'log_format': []}, {'no_delete': 'true'},
    {'template_files': {'../bad.tf': 'text'}}, {'config_content': 'tests: ['},
])
def test_invalid_request_fields_are_rejected(params):
    with pytest.raises(ValueError):
        routes._resolve_project_inputs(params)


def test_project_rename_updates_loaded_and_disk_runs(tmp_path, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(routes, '_RUNS_DIR', tmp_path)
    matching = SimpleNamespace(params={'project_name': 'old'})
    other = SimpleNamespace(params={'project_name': 'other'})
    runner = SimpleNamespace(_runs={'one': matching, 'two': other}, _save_run_to_disk=mock.Mock())
    disk = tmp_path / 'run.json'
    disk.write_text(json.dumps({'params': {'project_name': 'old'}}))
    (tmp_path / 'broken.json').write_text('{')
    routes._sync_project_name_in_runs('old', 'new', runner)
    assert matching.params['project_name'] == 'new'
    assert other.params['project_name'] == 'other'
    runner._save_run_to_disk.assert_called_once_with(matching)
    assert json.loads(disk.read_text())['params']['project_name'] == 'new'
    routes._sync_project_name_in_runs('new', 'new', runner)
    runner._save_run_to_disk.assert_called_once()


def test_project_rename_updates_disk_even_when_in_memory_persistence_fails(tmp_path, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(routes, '_RUNS_DIR', tmp_path)
    run = SimpleNamespace(params={'project_name': 'old'})
    runner = SimpleNamespace(_runs={'run': run}, _save_run_to_disk=mock.Mock(side_effect=OSError('disk unavailable')))
    persisted = tmp_path / 'persisted.json'
    persisted.write_text(json.dumps({'params': {'project_name': 'old'}, 'name': 'task'}))
    routes._sync_project_name_in_runs('old', 'new', runner)
    assert run.params['project_name'] == 'new'
    assert json.loads(persisted.read_text()) == {'params': {'project_name': 'new'}, 'name': 'task'}


def test_temp_single_template_and_legacy_cleanup(tmp_path, monkeypatch):
    monkeypatch.setattr(routes, '_UPLOAD_DIR', tmp_path / 'uploads')
    monkeypatch.setattr(routes, 'DEFAULT_PROJECT_ROOT', tmp_path)
    template, config, request_id = routes._write_current_files('template content', None)
    assert (tmp_path / template).read_text() == 'template content'
    assert config is None
    routes._cleanup_current_files(request_id)
    assert not (tmp_path / template).exists()
    current = tmp_path / 'uploads' / '_current'
    (current / 'template.yaml').write_text('legacy')
    (current / 'config.yml').write_text('legacy')
    routes._cleanup_current_files()
    assert not (current / 'template.yaml').exists()
    assert not (current / 'config.yml').exists()


class TestPendingCreationRecovery(AsyncTestCase):
    async def test_recovery_records_lookup_failure_and_keeps_stack_retryable(self):
        from types import SimpleNamespace

        stack = {'stack_name': 'demo', 'region': 'cn-a', 'status': 'CREATE_REQUESTING'}
        run = SimpleNamespace(id='run', credential_key_id=None)
        with mock.patch.object(routes, '_resolve_stack_credential', side_effect=ValueError('profile missing')):
            recovered = await routes._recover_pending_creation(None, run, stack, {})
        self.assertFalse(recovered)
        self.assertEqual(stack['status'], 'CREATE_UNCONFIRMED')
        self.assertFalse(stack['launch_succeeded'])
        self.assertEqual(stack['status_reason'], 'profile missing')
        self.assertEqual(routes._pending_creation_stacks(SimpleNamespace(stacks=[stack])), [stack])

    async def test_recovery_filters_unmatched_stacks_and_retries(self):
        from types import SimpleNamespace

        stack = {'stack_name': 'demo', 'region': 'cn-a', 'status': 'CREATE_REQUESTING'}
        run = SimpleNamespace(id='run', credential_key_id=None)
        calls = []
        class Plugin:
            def __init__(self, **kwargs):
                pass
            async def list_stacks(self, stack_name):
                calls.append(stack_name)
                if len(calls) == 1:
                    return [{'StackName': 'other', 'StackId': 'wrong'}, {'StackName': 'demo'}]
                return [{'StackName': 'demo', 'StackId': 'stack-id', 'Status': 'CREATE_COMPLETE'}]
        async def sleep(delay):
            self.assertEqual(delay, 1)
        with mock.patch.object(routes, '_resolve_stack_credential', return_value=(('', ''), object())), \
             mock.patch.object(routes, 'StackPlugin', Plugin), mock.patch.object(routes.asyncio, 'sleep', sleep):
            recovered = await routes._recover_pending_creation(None, run, stack, {}, attempts=3)
        self.assertTrue(recovered)
        self.assertEqual(stack['stack_id'], 'stack-id')
        self.assertEqual(stack['status'], 'CREATE_COMPLETE')
        self.assertEqual(calls, ['demo', 'demo'])

    async def test_retry_stops_when_recovery_succeeds_and_saves_each_attempt(self):
        from types import SimpleNamespace

        stack = {'stack_name': 'demo', 'region': 'cn-a', 'status': 'CREATE_UNCONFIRMED'}
        run = SimpleNamespace(id='run', stacks=[stack])
        runner = SimpleNamespace(get_run_raw=mock.Mock(return_value=run), _save_run_to_disk=mock.Mock())
        sleeps = []

        async def recover(runner, run, item, credentials, attempts=1):
            self.assertEqual(attempts, 1)
            self.assertIs(item, stack)
            sleeps_seen = len(sleeps)
            if sleeps_seen:
                item['stack_id'] = 'recovered'
            return bool(sleeps_seen)

        async def sleep(delay):
            sleeps.append(delay)

        with mock.patch.object(routes, '_recover_pending_creation', recover), mock.patch.object(routes.asyncio, 'sleep', sleep):
            await routes._retry_pending_creations(runner, 'run', poll_interval=7, max_polls=3)
        self.assertEqual(stack['stack_id'], 'recovered')
        self.assertEqual(sleeps, [7])
        self.assertEqual(runner._save_run_to_disk.call_count, 2)
        runner.get_run_raw.return_value = None
        await routes._retry_pending_creations(runner, 'gone', max_polls=1)
        self.assertEqual(runner._save_run_to_disk.call_count, 2)
        runner.get_run_raw.return_value = run
        await routes._retry_pending_creations(runner, 'run', max_polls=1)
        self.assertEqual(runner._save_run_to_disk.call_count, 2)

    async def test_startup_schedules_retry_for_unconfirmed_creation(self):
        import asyncio
        from types import SimpleNamespace

        stack = {'stack_name': 'demo', 'region': 'cn-a', 'status': 'CREATE_UNCONFIRMED'}
        run = SimpleNamespace(id='run', stacks=[stack], credential_key_id=None)
        runner = SimpleNamespace(_runs={'run': run}, _save_run_to_disk=mock.Mock())
        retried = []

        async def recover(*args, **kwargs):
            return False

        async def retry(runner, run_id):
            retried.append(run_id)

        app = {'runner': runner, 'creation_recovery_tasks': set()}
        with mock.patch.object(routes, '_recover_pending_creation', recover), \
             mock.patch.object(routes, '_retry_pending_creations', retry):
            await routes._resume_pending_creations(app)
            self.assertEqual(len(app['creation_recovery_tasks']), 1)
            await asyncio.gather(*app['creation_recovery_tasks'])
            await asyncio.sleep(0)
        self.assertEqual(retried, ['run'])
        self.assertEqual(app['creation_recovery_tasks'], set())
        runner._save_run_to_disk.assert_called_once_with(run)

    async def test_startup_resumes_only_pending_deletions(self):
        from types import SimpleNamespace

        stack = {'stack_id': 'id', 'region': 'cn-a', 'status': 'DELETE_IN_PROGRESS'}
        run = SimpleNamespace(id='run', stacks=[stack], credential_key_id=None)
        completed = SimpleNamespace(id='complete', stacks=[{'status': 'DELETE_COMPLETE'}], credential_key_id=None)
        scheduled = []

        def start(run_id, coroutine):
            scheduled.append((run_id, coroutine))

        runner = SimpleNamespace(_runs={'run': run, 'complete': completed}, start_background_task=start)
        groups = [{'region': 'cn-a', 'credential': object(), 'stacks': [stack]}]
        with mock.patch.object(routes, '_build_deletion_groups', return_value=groups) as build:
            await routes._resume_pending_deletions({'runner': runner})
        build.assert_called_once_with([stack], None)
        self.assertEqual([run_id for run_id, _ in scheduled], ['run'])
        scheduled[0][1].close()

    async def test_startup_skips_deletion_when_no_valid_group_can_be_formed(self):
        from types import SimpleNamespace

        stack = {'stack_id': 'id', 'status': 'DELETE_IN_PROGRESS', 'region': ''}
        run = SimpleNamespace(id='run', stacks=[stack], credential_key_id=None)
        runner = SimpleNamespace(_runs={'run': run}, start_background_task=mock.Mock())
        await routes._resume_pending_deletions({'runner': runner})
        runner.start_background_task.assert_not_called()
        self.assertEqual(stack['status'], 'DELETE_IN_PROGRESS')

    async def test_deletion_poll_keeps_completed_stacks_when_another_times_out(self):
        from types import SimpleNamespace

        done = {'stack_id': 'done', 'status': 'DELETE_IN_PROGRESS'}
        pending = {'stack_id': 'pending', 'status': 'DELETE_REQUESTING'}
        run = SimpleNamespace(stacks=[done, pending])
        runner = SimpleNamespace(get_run_raw=mock.Mock(return_value=run), _save_run_to_disk=mock.Mock())

        class Plugin:
            def __init__(self, **kwargs):
                pass
            async def get_stack(self, stack_id):
                return None if stack_id == 'done' else {'Status': 'DELETE_REQUESTING'}

        groups = [{'region': 'cn-a', 'credential': object(), 'stacks': [done, pending]}]
        with mock.patch.object(routes, 'StackPlugin', Plugin):
            await routes._poll_stack_deletion(runner, 'run', groups, max_polls=1)
        self.assertEqual(done['status'], 'DELETE_COMPLETE')
        self.assertEqual(pending['status'], 'DELETE_TIMEOUT')
        self.assertIn('Timed out', pending['delete_error'])
        self.assertEqual(runner._save_run_to_disk.call_count, 2)


class TestTerraformFallbackPaths(AsyncTestCase):
    async def test_missing_security_group_remains_unresolved_and_other_values_survive(self):
        auto = '$[iact3-auto]'
        class Vpc:
            def __init__(self, *args, **kwargs):
                pass
            async def get_one_vswitch(self):
                return {'VpcId': 'vpc-a', 'VSwitchId': 'vsw-a'}
        class Ecs:
            def __init__(self, *args, **kwargs):
                pass
            async def get_security_group(self, vpc_id):
                self_vpc.append(vpc_id)
                return None
        self_vpc = []
        with mock.patch('iact3.plugin.vpc.VpcPlugin', Vpc), mock.patch('iact3.plugin.ecs.EcsPlugin', Ecs):
            result = await routes._resolve_terraform_params({'VpcId': auto, 'SecurityGroupId': auto}, 'cn-a', object())
        self.assertEqual(result, {'VpcId': 'vpc-a', 'SecurityGroupId': ''})
        self.assertEqual(self_vpc, ['vpc-a'])

    async def test_empty_cloud_results_leave_unresolved_values_empty(self):
        auto = '$[iact3-auto]'
        class Vpc:
            def __init__(self, *args, **kwargs):
                pass
            async def get_one_vswitch(self):
                return None
        class Ecs:
            def __init__(self, *args, **kwargs):
                pass
            async def describe_zones(self):
                return []
            async def describe_available_instance_types(self, **kwargs):
                return []
        params = {'VpcId': auto, 'ZoneId': auto, 'InstanceType': auto, 'AlreadySet': 7}
        with mock.patch('iact3.plugin.vpc.VpcPlugin', Vpc), mock.patch('iact3.plugin.ecs.EcsPlugin', Ecs):
            result = await routes._resolve_terraform_params(params, 'cn-a', object())
        self.assertEqual(result, {'VpcId': '', 'ZoneId': '', 'InstanceType': '', 'AlreadySet': 7})

    async def test_instance_type_uses_unfiltered_query_after_disk_filters_fail(self):
        auto = '$[iact3-auto]'
        calls = []
        class Ecs:
            def __init__(self, *args, **kwargs):
                pass
            async def describe_available_instance_types(self, **kwargs):
                calls.append(kwargs)
                return [] if 'system_disk_category' in kwargs else ['ecs.t6.small']
        with mock.patch('iact3.plugin.ecs.EcsPlugin', Ecs):
            result = await routes._resolve_terraform_params(
                {'InstanceType': auto, 'SystemDiskCategory': auto}, 'cn-a', object())
        self.assertEqual(result, {'InstanceType': 'ecs.t6.small', 'SystemDiskCategory': 'cloud_essd'})
        self.assertEqual(len(calls), 5)
        self.assertNotIn('system_disk_category', calls[-1])

    async def test_network_query_errors_leave_unresolved_values_empty(self):
        auto = '$[iact3-auto]'
        class Vpc:
            def __init__(self, *args, **kwargs):
                pass
            async def get_one_vswitch(self):
                raise ValueError('network unavailable')
        class Ecs:
            def __init__(self, *args, **kwargs):
                pass
            async def describe_zones(self):
                raise ValueError('zones unavailable')
        params = {'VpcId': auto, 'VSwitchId': auto, 'ZoneId': auto, 'SecurityGroupId': auto}
        with mock.patch('iact3.plugin.vpc.VpcPlugin', Vpc), mock.patch('iact3.plugin.ecs.EcsPlugin', Ecs):
            result = await routes._resolve_terraform_params(params, 'cn-a', object())
        self.assertEqual(result, {key: '' for key in params})
        self.assertEqual(params['VpcId'], auto)

    async def test_single_instance_type_resolves_without_disk_filter(self):
        auto = '$[iact3-auto]'
        class Ecs:
            def __init__(self, *args, **kwargs):
                pass
            async def describe_available_instance_types(self, **kwargs):
                self_kwargs.append(kwargs)
                return ['ecs.t6.small']
        self_kwargs = []
        with mock.patch('iact3.plugin.ecs.EcsPlugin', Ecs):
            result = await routes._resolve_terraform_params({'InstanceType': auto}, 'cn-a', object())
        self.assertEqual(result['InstanceType'], 'ecs.t6.small')
        self.assertNotIn('system_disk_category', self_kwargs[0])


def test_explicit_ros_template_takes_precedence_over_saved_terraform_files(tmp_path, monkeypatch):
    monkeypatch.setattr(routes, '_PROJECTS_DIR', tmp_path)
    (tmp_path / 'demo.json').write_text(json.dumps({
        'template_files': {'main.tf': 'saved terraform'}, 'config': 'parameters: {Name: saved}',
    }))
    template, files, config = routes._resolve_project_inputs({
        'project_name': 'demo', 'template_content': 'Resources: {}',
    })
    assert template == 'Resources: {}'
    assert files is None
    assert yaml.safe_load(config)['parameters']['Name'] == 'saved'
    template, files, _ = routes._resolve_project_inputs({'project_name': 'demo', 'template_content': ''})
    assert template == ''
    assert files is None
    template, files, _ = routes._resolve_project_inputs({'project_name': 'demo'})
    assert template is None
    assert files == {'main.tf': 'saved terraform'}


def test_project_inputs_validate_saved_config_and_fall_back_after_corrupt_project(tmp_path, monkeypatch):
    monkeypatch.setattr(routes, '_PROJECTS_DIR', tmp_path)
    project = tmp_path / 'demo.json'
    project.write_text('{')
    assert routes._resolve_project_inputs({'project_name': 'demo'}) == (None, None, None)
    project.write_text(json.dumps({'template': 'saved', 'config': 'tests: ['}))
    with pytest.raises(ValueError, match='Invalid config YAML'):
        routes._resolve_project_inputs({'project_name': 'demo'})
    assert routes._resolve_project_inputs({
        'project_name': 'demo', 'template_content': 'editor', 'config_content': '',
    }) == ('editor', None, '')


def test_parameter_injection_uses_defaults_without_overwriting_user_values():
    template = '''Parameters:
  Name: {Type: String}
  VpcId: {Type: String}
  ImageId: {Type: String}
  Count: {Type: Number, Default: 3}
  Unknown: {Type: String}
'''
    config = 'parameters: {Name: chosen, VpcId: old, Count: 7, Stale: discard}'
    result = yaml.safe_load(routes._inject_auto_params(template, None, config))['parameters']
    assert result == {'Name': 'chosen', 'VpcId': '$[iact3-auto]', 'Count': 7,
                      'ImageId': routes._COMMON_DEFAULTS['ImageId'], 'Unknown': ''}
    result = yaml.safe_load(routes._inject_auto_params(template, None, 'parameters: {Name: ""}'))['parameters']
    assert result['Name'] == '$[iact3-auto]'
    assert result['Count'] == '3'


def test_terraform_parameter_injection_keeps_complex_defaults_and_explicit_values():
    files = {'main.tf': '''
variable "Name" {}
variable "VpcId" {}
variable "plain" {
  default = "example"
}
variable "complex" {
  default = [
    "a", "b"
  ]
}
'''}
    result = yaml.safe_load(routes._inject_auto_params(None, files, 'tests: {default: {parameters: {Name: user}}}'))
    params = result['tests']['default']['parameters']
    assert params['Name'] == 'user'
    assert params['VpcId'] == '$[iact3-auto]'
    assert params['plain'] == 'example'
    assert 'complex' not in params


def test_parameter_injection_retains_config_when_template_is_not_parseable():
    config = 'tests: {default: {parameters: {Name: original}}}'
    for template in ('broken: [', 'Parameters: []', None):
        assert routes._inject_auto_params(template, None, config) == config
    result = yaml.safe_load(routes._inject_auto_params('Parameters: {Name: {Type: String}}', None, None))
    assert result['tests']['default']['parameters']['Name'] == '$[iact3-auto]'
