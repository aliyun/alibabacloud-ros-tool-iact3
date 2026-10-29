from unittest import mock

from Tea.exceptions import TeaException
from Tea.model import TeaModel

from iact3.plugin.ecs import EcsPlugin
from tests.common import AsyncTestCase


class TestPluginRequests(AsyncTestCase):
    def setUp(self):
        self.plugin = EcsPlugin('cn-test', credential=object())

    def test_request_names_and_tag_conversion(self):
        self.assertEqual(self.plugin._get_api_name('DescribeZonesRequest'), 'DescribeZones')
        self.assertEqual(self.plugin._get_api_name('DescribeZones'), 'DescribeZones')
        self.assertEqual(self.plugin._get_action_name('DescribeZones'), 'describe_zones_with_options_async')
        request = self.plugin._build_request('DescribeZones')
        self.assertEqual(request.region_id, 'cn-test')
        args = {}
        self.plugin._convert_tags({'one': '1', 'empty': None}, args)
        self.assertEqual(args['Tags'], [{'Key': 'one', 'Value': '1'}])
        self.plugin._convert_tags({}, args)
        with self.assertRaises(AssertionError):
            self.plugin._convert_tags(['invalid'], args)

    async def test_send_request_success_invalid_response_and_ignored_error(self):
        response = TeaModel()
        error = TeaException({'code': 'BadRequest', 'message': 'invalid'})
        outcomes = [response, {}, error, error]
        async def send(request, options):
            result = outcomes.pop(0)
            if isinstance(result, Exception):
                raise result
            return result
        client = mock.Mock()
        client.describe_zones_with_options_async = send
        self.plugin._client = client
        with mock.patch('iact3.plugin.base_plugin.TeaCore.to_map', return_value={'body': {'value': 42}}):
            self.assertEqual(await self.plugin.send_request('DescribeZones'), {'value': 42})
        with self.assertRaises(TeaException):
            await self.plugin.send_request('DescribeZones')
        self.assertEqual(await self.plugin.send_request('DescribeZones', ignore_exception=True), error.data)
        with self.assertRaises(TeaException):
            await self.plugin.send_request('DescribeZones')

    async def test_fetch_all_paginates_and_preserves_caller_parameters(self):
        calls = []
        async def send(action, **kwargs):
            calls.append(kwargs.copy())
            return {'TotalCount': 5, 'Items': {'Item': [kwargs['PageNumber']]}}
        self.plugin.send_request = send
        params = {'PageSize': 2, 'Filter': 'x'}
        values = await self.plugin.fetch_all('Describe', params, 'Items', 'Item')
        self.assertEqual(sorted(values), [1, 2, 3])
        self.assertEqual(params, {'PageSize': 2, 'Filter': 'x'})
        self.assertEqual({call['PageNumber'] for call in calls}, {1, 2, 3})

    async def test_fetch_all_handles_total_pages_and_fetch_errors(self):
        async def send(action, **kwargs):
            if kwargs['PageNumber'] == 2:
                raise ValueError('page failed')
            return {'Data': {'TotalPages': 2, 'Items': []}}
        self.plugin.PAGE_OUTER_KEY = 'Data'
        self.plugin.send_request = send
        with self.assertRaisesRegex(ValueError, 'page failed'):
            await self.plugin.fetch_all('Describe', {}, 'Items')
        self.assertEqual(self.plugin._get_from_resp({}, 'missing', 'items'), [])


def test_ssl_proxy_only_adjusts_tea_client_context():
    import ssl
    from iact3.plugin import base_plugin
    marker = object()
    with mock.patch.object(base_plugin, '_original_cdc', return_value=marker) as create:
        assert base_plugin._TeaSSLProxy.create_default_context(ssl.Purpose.CLIENT_AUTH) is marker
        create.assert_called_once_with(ssl.Purpose.SERVER_AUTH)
    proxy = base_plugin._TeaSSLProxy('ssl')
    assert proxy.Purpose is ssl.Purpose
    with mock.patch.object(base_plugin, '_original_cdc', return_value=marker) as create:
        assert base_plugin._TeaSSLProxy.create_default_context(cafile='example.pem') is marker
        create.assert_called_once_with(ssl.Purpose.SERVER_AUTH, cafile='example.pem')


def test_credential_file_selection_prefers_explicit_path(tmp_path, monkeypatch):
    from iact3.plugin import base_plugin
    provider = object.__new__(base_plugin.CredentialsProvider)
    first = tmp_path / 'first.ini'
    second = tmp_path / 'second.ini'
    second.write_text('')
    monkeypatch.setattr(base_plugin, 'DEFAULT_INI_CREDENTIAL_FILE_PATHS', [str(first), str(second)])
    monkeypatch.setattr(base_plugin.auth_util, 'environment_credentials_file', None)
    assert provider._get_credential_file_path() == str(second)
    monkeypatch.setattr(base_plugin.auth_util, 'environment_credentials_file', 'configured.ini')
    assert provider._get_credential_file_path() == 'configured.ini'
    monkeypatch.setattr(base_plugin.auth_util, 'environment_credentials_file', None)
    second.unlink()
    assert provider._get_credential_file_path() is None


def test_credential_provider_uses_optional_ecs_role_and_fallback_chain():
    from iact3.plugin import base_plugin

    with mock.patch.object(base_plugin.providers.DefaultCredentialsProvider, '__init__', return_value=None), \
         mock.patch.object(base_plugin.providers, 'EnvironmentVariableCredentialsProvider', return_value='env'), \
         mock.patch.object(base_plugin.providers, 'ProfileCredentialsProvider', return_value='profile'), \
         mock.patch.object(base_plugin.providers, 'EcsRamRoleCredentialProvider', return_value='role') as role, \
         mock.patch.object(base_plugin.providers, 'CredentialsUriProvider', return_value='uri'), \
         mock.patch.object(base_plugin.CredentialsProvider, '_get_credential_file_path', return_value='config.ini'):
        with mock.patch.object(base_plugin.auth_util, 'environment_ECSMeta_data', None):
            provider = base_plugin.CredentialsProvider()
        assert provider.user_configuration_providers == ['env', 'profile', 'uri']
        role.assert_not_called()
        with mock.patch.object(base_plugin.auth_util, 'environment_ECSMeta_data', 'role-name'):
            provider = base_plugin.CredentialsProvider()
        assert provider.user_configuration_providers == ['env', 'profile', 'role', 'uri']
        role.assert_called_once_with('role-name')


def test_credential_client_uses_default_provider_when_no_configuration():
    from iact3.plugin import base_plugin

    provider = mock.Mock()
    provider.get_credentials.return_value = object()
    with mock.patch.object(base_plugin, 'CredentialsProvider', return_value=provider):
        client = base_plugin.CredentialClient()
    assert client.cloud_credential is provider.get_credentials.return_value


def test_credential_client_passes_explicit_configuration_to_sdk():
    from iact3.plugin import base_plugin

    config = object()
    with mock.patch.object(base_plugin.Client, '__init__', return_value=None) as initialize:
        client = base_plugin.CredentialClient(config)
    initialize.assert_called_once_with(config)
    assert client is not None


class TestPluginPaginationAndClient(AsyncTestCase):
    async def test_fetch_all_handles_total_alias_and_empty_single_page(self):
        plugin = EcsPlugin('cn-test', credential=object())
        calls = []
        async def send(action, **kwargs):
            calls.append(kwargs.copy())
            return {'Total': 0, 'Items': {'Item': []}}
        plugin.send_request = send
        self.assertEqual(await plugin.fetch_all('Describe', {}, 'Items', 'Item'), [])
        self.assertEqual(calls, [{'PageNumber': 1, 'PageSize': 50}])

    async def test_fetch_all_unwraps_each_page_with_total_page_count(self):
        plugin = EcsPlugin('cn-test', credential=object())
        plugin.PAGE_OUTER_KEY = 'Data'
        calls = []

        async def send(action, **kwargs):
            calls.append(kwargs['PageNumber'])
            return {'Data': {'TotalPages': 3, 'Items': {'Item': [kwargs['PageNumber']]}}}

        plugin.send_request = send
        assert sorted(await plugin.fetch_all('Describe', {}, 'Items', 'Item')) == [1, 2, 3]
        assert sorted(calls) == [1, 2, 3]

    def test_client_applies_explicit_endpoint_or_reads_sdk_endpoint(self):
        plugin = EcsPlugin('cn-test', credential=object(), endpoint='custom.example')
        client = mock.Mock()
        client._endpoint = 'original.example'
        with mock.patch.object(plugin, 'api_client', return_value=lambda config: client):
            self.assertIs(plugin.client, client)
            self.assertEqual(client._endpoint, 'custom.example')
            self.assertIs(plugin.client, client)
        plugin = EcsPlugin('cn-test', credential=object())
        plugin.endpoint = None
        client = mock.Mock()
        client._endpoint = 'sdk.example'
        with mock.patch.object(plugin, 'api_client', return_value=lambda config: client):
            self.assertIs(plugin.client, client)
            self.assertEqual(plugin.endpoint, 'sdk.example')

    def test_request_builder_preserves_explicit_region(self):
        plugin = EcsPlugin('cn-test', credential=object())
        request = plugin._build_request('DescribeZonesRequest', RegionId='cn-other')
        self.assertEqual(request.region_id, 'cn-other')

    def test_explicit_options_and_client_without_endpoint_attribute(self):
        credential = object()
        options = {'protocol': 'HTTP'}
        plugin = EcsPlugin('cn-test', credential=credential, config_kwargs=options, endpoint='custom.example')
        client = object()
        with mock.patch.object(plugin, 'api_client', return_value=lambda config: client):
            self.assertIs(plugin.client, client)
        self.assertEqual(plugin.endpoint, 'custom.example')
        self.assertEqual(plugin.config.protocol, 'HTTP')
        self.assertIs(plugin.credential, credential)
