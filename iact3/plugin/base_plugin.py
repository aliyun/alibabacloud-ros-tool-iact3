import abc
import asyncio
import importlib
import logging
import os
import ssl as _ssl
import types

from Tea.core import TeaCore
from Tea.exceptions import TeaException
from Tea.model import TeaModel
from alibabacloud_credentials import providers
from alibabacloud_credentials.client import Client
from alibabacloud_credentials.utils import auth_util
from alibabacloud_credentials.utils.auth_constant import HOME
from alibabacloud_tea_openapi.models import Config
from alibabacloud_tea_util.models import RuntimeOptions

from iact3.plugin import error_code
from iact3.util import pascal_to_snake

LOG = logging.getLogger(__name__)

# --- Targeted SSL fix for Tea SDK (Python 3.12+) ---
# The Tea SDK (alibabacloud-tea) incorrectly uses ssl.Purpose.CLIENT_AUTH
# (a server-side context) for client HTTPS connections. Python 3.12 with
# OpenSSL 3.x enforces this strictly and raises:
#   "Cannot create a client socket with a PROTOCOL_TLS_SERVER context"
#
# Instead of patching the global ssl module, we install a proxy only in the
# Tea.core module namespace so other code in the process is unaffected.
import Tea.core as _tea_core

_original_cdc = _ssl.create_default_context


class _TeaSSLProxy(types.ModuleType):
    """Proxy for ssl module that fixes Purpose.CLIENT_AUTH → SERVER_AUTH.

    Only installed in Tea.core's namespace; does not affect the global
    ssl module used by other libraries.
    """

    def __getattr__(self, name):
        return getattr(_ssl, name)

    @staticmethod
    def create_default_context(purpose=_ssl.Purpose.SERVER_AUTH, **kwargs):
        if purpose == _ssl.Purpose.CLIENT_AUTH:
            purpose = _ssl.Purpose.SERVER_AUTH
        return _original_cdc(purpose, **kwargs)


_tea_core.ssl = _TeaSSLProxy('ssl')

DEFAULT_INI_CREDENTIAL_FILE_PATHS = [
    os.path.join(HOME, '.alibabacloud/credentials.ini'),
    os.path.join(HOME, '.aliyun/credentials.ini'),
]


ASYNC_FLAG = '_async'
RUNTIME_OPTIONS_FLAG = '_with_options'
REQUEST_SUFFIX = 'Request'


class CredentialsProvider(providers.DefaultCredentialsProvider):
    def __init__(self):
        super().__init__()
        self.user_configuration_providers = [
            providers.EnvironmentVariableCredentialsProvider(),
            providers.ProfileCredentialsProvider(path=self._get_credential_file_path()),
        ]
        role_name = auth_util.environment_ECSMeta_data
        if role_name is not None:
            self.user_configuration_providers.append(providers.EcsRamRoleCredentialProvider(role_name))
        self.user_configuration_providers.append(providers.CredentialsUriProvider())

    def _get_credential_file_path(self):
        if auth_util.environment_credentials_file:
            return auth_util.environment_credentials_file
        for path in DEFAULT_INI_CREDENTIAL_FILE_PATHS:
            if os.path.exists(path):
                return path


class CredentialClient(Client):
    def __init__(self, config=None):
        if config is None:
            provider = CredentialsProvider()
            self.cloud_credential = provider.get_credentials()
            return
        super(CredentialClient, self).__init__(config)


class TeaSDKPlugin(metaclass=abc.ABCMeta):
    product = None

    def __init__(
        self, region_id: str, credential: CredentialClient = None, config_kwargs: dict = None, endpoint: str = None
    ):
        self.region_id = region_id
        if not credential:
            credential = CredentialClient()
        self.credential = credential

        if not config_kwargs:
            config_kwargs = {}
        config_kwargs.update(region_id=region_id, credential=credential)
        if endpoint:
            config_kwargs.update(endpoint=endpoint)

        self.config = Config(**config_kwargs)
        self.endpoint = self.config.endpoint
        self._client = None
        self.runtime_option = RuntimeOptions(**self.runtime_kwargs())

    @abc.abstractmethod
    def api_client(self):
        raise NotImplementedError

    @abc.abstractmethod
    def models_path(self, action_name):
        raise NotImplementedError

    def runtime_kwargs(self):
        return {'autoretry': True, 'max_attempts': 3}

    @property
    def client(self):
        if not self._client:
            self._client = self.api_client()(self.config)
            if not self.endpoint:
                self.endpoint = getattr(self._client, '_endpoint', '')
            elif hasattr(self._client, '_endpoint'):
                # Force override SDK's internal endpoint resolver
                self._client._endpoint = self.endpoint
        return self._client

    async def send_request(self, request_name: str, ignore_exception: bool = False, **kwargs) -> dict:
        request = self._build_request(request_name, **kwargs)
        api_name = self._get_api_name(request_name)
        action_name = self._get_action_name(api_name)
        func = getattr(self.client, action_name)
        try:
            resp = await func(request, self.runtime_option)
        except TeaException as ex:
            LOG.debug(f'plugin exception: {self.product} {self.endpoint} {api_name} {request.to_map()} {ex.data}')
            if ignore_exception:
                return ex.data
            raise ex
        if not isinstance(resp, TeaModel):
            LOG.error(f'plugin response: {self.product} {self.endpoint} {api_name} {request.to_map()} {resp}')
            raise TeaException(
                dict(code=error_code.UNKNOWN_ERROR, message='The response of TeaSDK is not TeaModel.', data=resp)
            )
        resp = TeaCore.to_map(resp)
        LOG.debug(f'plugin response: {self.product} {self.endpoint} {api_name} {request.to_map()} {resp}')
        return resp.get('body', {})

    def _get_api_name(self, request_name):
        if request_name.endswith(REQUEST_SUFFIX):
            suffix_len = len(REQUEST_SUFFIX)
            api_name = request_name[:-suffix_len]
        else:
            api_name = request_name
        return api_name

    def _get_action_name(self, api_name):
        action_name = pascal_to_snake(api_name)
        if not action_name.endswith(RUNTIME_OPTIONS_FLAG):
            action_name = f'{action_name}{RUNTIME_OPTIONS_FLAG}'
        if not action_name.endswith(ASYNC_FLAG):
            action_name = f'{action_name}{ASYNC_FLAG}'
        return action_name

    def _build_request(self, request_name, **kwargs):
        if 'RegionId' not in kwargs:
            kwargs['RegionId'] = self.region_id
        if not request_name.endswith('Request'):
            request_name = f'{request_name}Request'
        class_path = self.models_path(request_name)
        module_path, class_name = class_path.rsplit('.', 1)
        request_class = getattr(importlib.import_module(module_path), class_name)
        request = request_class()
        request = request.from_map(kwargs)
        return request

    @staticmethod
    def _convert_tags(tags: dict, kwargs, tag_key='Tags'):
        if not tags:
            return
        assert isinstance(tags, dict)
        kwargs[tag_key] = [dict(Key=k, Value=v) for k, v in tags.items() if v is not None]

    PAGE_NUMBER, PAGE_SIZE, TOTAL_COUNT, TOTAL_PAGES, TOTAL = (
        'PageNumber',
        'PageSize',
        'TotalCount',
        'TotalPages',
        'Total',
    )
    PAGE_OUTER_KEY = None

    async def fetch_all(self, request, kwargs, *keys):
        kwargs = kwargs.copy()
        if self.PAGE_SIZE not in kwargs:
            kwargs[self.PAGE_SIZE] = 50

        ex = []
        result = []

        # first fetch
        kwargs[self.PAGE_NUMBER] = 1
        resp = await self.send_request(request, **kwargs)
        if self.PAGE_OUTER_KEY:
            resp = resp.get(self.PAGE_OUTER_KEY)
        values = self._get_from_resp(resp, *keys)
        result.extend(values)

        # calculate total pages
        if self.TOTAL_COUNT in resp:
            total_pages = (resp[self.TOTAL_COUNT] - 1) // kwargs[self.PAGE_SIZE] + 1
        elif self.TOTAL in resp:
            total_pages = (resp[self.TOTAL] - 1) // kwargs[self.PAGE_SIZE] + 1
        else:
            total_pages = resp[self.TOTAL_PAGES]

        if total_pages <= 1:
            return result

        # concurrent fetch
        async def fetch_one_page(page, params):
            try:
                params = params.copy()
                params[self.PAGE_NUMBER] = page
                resp = await self.send_request(request, **params)
                if self.PAGE_OUTER_KEY:
                    resp = resp.get(self.PAGE_OUTER_KEY)
                values = self._get_from_resp(resp, *keys)
                result.extend(values)
            except Exception as e:
                LOG.error(e)
                ex.append(e)

        tasks = []
        for i in range(2, total_pages + 1):
            task = asyncio.create_task(fetch_one_page(i, kwargs))
            tasks.append(task)
        await asyncio.gather(*tasks)

        if ex:
            raise ex[0]

        return result

    @staticmethod
    def _get_from_resp(resp, *keys):
        values = []
        last_index = len(keys) - 1
        for i, key in enumerate(keys):
            if i == last_index:
                resp = resp.get(key, [])
                values.extend(resp)
            else:
                resp = resp.get(key, {})
        return values
