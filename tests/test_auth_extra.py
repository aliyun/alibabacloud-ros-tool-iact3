import json
from unittest import mock

import pytest
from dataclasses_jsonschema import ValidationError

from iact3.config import Auth, BaseConfig, OssConfig
from iact3.exceptions import Iact3Exception


@pytest.mark.parametrize('mode,expected_type,extra', [
    ('AK', 'access_key', {'access_key_id': 'test-id', 'access_key_secret': 'test-secret'}),
    ('StsToken', 'sts', {'access_key_id': 'test-id', 'access_key_secret': 'test-secret', 'sts_token': 'test-token'}),
    ('RamRoleArn', 'ram_role_arn', {'access_key_id': 'test-id', 'access_key_secret': 'test-secret',
                                   'ram_role_arn': 'role', 'ram_session_name': 'session'}),
    ('EcsRamRole', 'ecs_ram_role', {'ram_role_name': 'role-name'}),
])
def test_auth_converts_profile_modes(tmp_path, mode, expected_type, extra):
    path = tmp_path / (mode + '.json')
    path.write_text(json.dumps({'current': 'selected', 'profiles': [dict(name='selected', mode=mode, **extra)]}))
    with mock.patch('iact3.config.CredentialClient') as client:
        auth = Auth(location=str(path))
    client.assert_called_once()
    assert client.call_args[1]['config'].type == expected_type
    assert auth.credential is client.return_value


def test_auth_rejects_missing_or_invalid_profile(tmp_path):
    path = tmp_path / 'config.json'
    for content in ('{', '{}', '{"current":"missing","profiles":[]}',
                    '{"current":"selected","profiles":[{"name":"selected","mode":"unknown"}]}'):
        Auth._get_credential.cache_clear()
        path.write_text(content)
        assert Auth(location=str(path)).credential is None


def test_auth_explicit_profile_overrides_current_and_missing_files_are_ignored(tmp_path):
    path = tmp_path / 'config.json'
    path.write_text(json.dumps({'current': 'first', 'profiles': [
        {'name': 'first', 'mode': 'AK', 'access_key_id': 'first'},
        {'name': 'selected', 'mode': 'AK', 'access_key_id': 'second'},
    ]}))
    Auth._get_credential.cache_clear()
    with mock.patch('iact3.config.CredentialClient') as client:
        selected = Auth(name='selected', location=str(path))
        assert selected.credential is client.return_value
        assert client.call_args[1]['config'].access_key_id == 'second'
        assert Auth(name='missing', location=str(path)).credential is None
        assert Auth(location=str(tmp_path / 'missing.json')).credential is None


def test_config_file_loading_and_bucket_validation(tmp_path):
    missing = tmp_path / 'missing.yml'
    assert BaseConfig.generate_from_file(missing) == {}
    with pytest.raises(FileNotFoundError):
        BaseConfig.generate_from_file(missing, fail_ok=False)
    invalid = tmp_path / 'invalid.yml'
    invalid.write_text('tests: [')
    assert BaseConfig.generate_from_file(invalid) == {}
    with pytest.raises(Exception):
        BaseConfig.generate_from_file(invalid, fail_ok=False)
    config = OssConfig(bucket_name='bucket', bucket_region='cn-a')
    config.plugin = mock.Mock()
    config.plugin.bucket_exist.return_value = False
    with pytest.raises(Iact3Exception):
        config.validate_bucket()


def test_config_merge_accepts_missing_layers_and_preserves_parameter_precedence():
    assert BaseConfig.merge(None, None) == {}
    assert BaseConfig.merge({'project': {'name': 'old'}}, None) == {'project': {'name': 'old'}}
    assert BaseConfig.merge(None, {'project': {'name': 'new'}}) == {'project': {'name': 'new'}}
    result = BaseConfig.merge({'project': None}, {'project': {'name': 'new'}})
    assert result == {'project': {'name': 'new'}}
    result = BaseConfig.merge({'parameters': {'shared': 'base'}},
                              {'parameters': {'shared': 'new', 'added': 'value'}})
    assert result['parameters'] == {'shared': 'base', 'added': 'value'}


def test_config_loading_can_skip_validation_or_reject_invalid_values(tmp_path):
    path = tmp_path / 'config.yml'
    path.write_text('general: {regions: not-a-list}')
    with mock.patch.object(BaseConfig, 'from_dict', side_effect=ValidationError('bad')):
        assert BaseConfig.generate_from_file(path, validate=False) == {'general': {'regions': 'not-a-list'}}
        assert BaseConfig.generate_from_file(path, fail_ok=True) == {'general': {'regions': 'not-a-list'}}
        with pytest.raises(ValidationError):
            BaseConfig.generate_from_file(path, fail_ok=False)


def test_template_config_builds_terraform_workspace_and_prefers_ros_template(tmp_path):
    from iact3.config import TemplateConfig

    (tmp_path / 'main.tf').write_text('resource "test" "a" {}')
    (tmp_path / 'nested').mkdir()
    (tmp_path / 'nested' / 'vars.tf').write_text('variable "name" {}')
    (tmp_path / 'notes.txt').write_text('ignored')
    config = TemplateConfig(template_location=str(tmp_path), tf_version='Aliyun::Terraform-custom')
    workspace = json.loads(config.generate_template_args()['template_body'])
    assert workspace['Transform'] == 'Aliyun::Terraform-custom'
    assert workspace['Workspace'] == {'main.tf': 'resource "test" "a" {}', 'nested/vars.tf': 'variable "name" {}'}
    ros = tmp_path / 'project.template.yaml'
    ros.write_text('ROSTemplateFormatVersion: "2015-09-01"\nResources: {}')
    config = TemplateConfig(template_location=str(tmp_path))
    assert json.loads(config.generate_template_args()['template_body'])['Resources'] == {}


def test_template_config_url_validation_and_missing_template(tmp_path):
    from iact3.config import TemplateConfig

    for url in ('https://example.invalid/template', 'oss://bucket/template'):
        assert TemplateConfig(template_url=url).generate_template_args()['template_url'] == url
    with pytest.raises(Iact3Exception, match='not legally'):
        TemplateConfig(template_url='ftp://example.invalid/template').generate_template_args()
    with pytest.raises(Iact3Exception, match='Could not find template'):
        TemplateConfig(template_location=str(tmp_path)).generate_template_args()
    with mock.patch('iact3.config.urlopen', side_effect=OSError('missing')):
        with pytest.raises(Iact3Exception, match='missing'):
            TemplateConfig(template_url='file:///missing').generate_template_args()
    template = tmp_path / 'local.yaml'
    template.write_text('Resources: {}')
    args = TemplateConfig(template_url=template.as_uri()).generate_template_args()
    assert args['template_body'] == 'Resources: {}'
    assert 'template_url' not in args
    invalid = tmp_path / 'invalid.template.yaml'
    invalid.write_text('Resources: [')
    with pytest.raises(Iact3Exception, match='can not find a template'):
        TemplateConfig(template_location=str(invalid)).generate_template_args()


@pytest.mark.asyncio
@pytest.mark.parametrize('stdout,stderr,expected_status,expected_output', [
    (b'result', b'', 'Success', 'result'),
    (b'', b'failure', 'Failed', 'failure'),
    (b'', b'', 'Success', ''),
])
async def test_hook_writes_result_and_uploads_available_output(tmp_path, monkeypatch, stdout, stderr,
                                                               expected_status, expected_output):
    import iact3.config as config_module

    class Process:
        async def communicate(self):
            return stdout, stderr

    async def spawn(*args, **kwargs):
        assert args == ('example',)
        return Process()

    monkeypatch.setattr(config_module.asyncio, 'create_subprocess_exec', spawn)
    hook = config_module.HookConfig(execute_time=config_module.HookExecuteTime.PRE_CREATE,
                                    execute_command=['example'])
    hook.hook_name = 'prepare'
    hook.oss_config = OssConfig(bucket_name='bucket', object_prefix='custom')
    hook.oss_config.plugin = mock.Mock()
    result = await hook.execute(tmp_path, 'run', 'uid')
    assert result['ExecuteStatus'] == expected_status
    assert (tmp_path / result['ResultFileName']).read_text() == expected_output
    assert result['OSSLocation'].startswith('oss://bucket/iact3/custom/')
    if expected_output:
        assert hook.oss_config.plugin.put_object_with_string.call_args[1]['strings'] == expected_output
    else:
        hook.oss_config.plugin.put_object_with_string.assert_not_called()


class TestExpandedConfig:
    @pytest.mark.asyncio
    async def test_region_lookup_and_project_credential_are_cached(self, monkeypatch):
        import iact3.config as config_module

        monkeypatch.setattr(config_module.Auth, '_get_credential', lambda self: None)
        base = BaseConfig()
        general_credential = object()
        project_credential = object()
        base.general.auth.credential = general_credential
        base.project.auth.credential = project_credential
        calls = []

        class Plugin:
            def __init__(self, region, credential):
                calls.append((region, credential))

            async def get_regions(self):
                return ['cn-a', 'cn-b']

        monkeypatch.setattr(config_module, 'StackPlugin', Plugin)
        assert await base._get_test_regions() == ['cn-a', 'cn-b']
        assert await base._get_test_regions() == ['cn-a', 'cn-b']
        assert calls == [('cn-hangzhou', general_credential)]
        assert base.get_credential() is project_credential
        base.project.auth.credential = object()
        assert base.get_credential() is project_credential

    @pytest.mark.asyncio
    async def test_named_test_expands_all_regions_and_propagates_parameter_error(self, monkeypatch):
        from types import SimpleNamespace
        import iact3.config as config_module

        monkeypatch.setattr(config_module.Auth, '_get_credential', lambda self: None)
        base = BaseConfig.from_dict({
            'tests': {
                'chosen': {'regions': ['ALL'], 'template_config': {'template_body': '{}'},
                           'parameters': {'Key': 'old'}},
                'ignored': {'regions': ['cn-c'], 'template_config': {'template_body': '{}'}},
            },
        })
        calls = []
        async def regions():
            return ['cn-a', 'cn-b']
        async def resolve(config):
            calls.append((config.test_name, config.region))
            return SimpleNamespace(name=config.test_name, region=config.region,
                                   parameters={'Key': config.region}, error='bad' if config.region == 'cn-b' else None)
        monkeypatch.setattr(base, '_get_test_regions', regions)
        monkeypatch.setattr(config_module.ParamGenerator, 'result', resolve)
        configs = await base.get_all_configs('chosen')
        assert calls == [('chosen', 'cn-a'), ('chosen', 'cn-b')]
        assert [c.parameters['Key'] for c in configs] == ['cn-a', 'cn-b']
        assert configs[1].error == 'bad'
        assert configs[0].oss_config is base.project.oss_config
