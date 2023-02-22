# -*- coding: utf-8 -*-
import os

from Tea.core import TeaCore
from alibabacloud_credentials.client import Client
from alibabacloud_tea_openapi.models import Config
from alibabacloud_ros20190910.client import Client as ROSClient
from alibabacloud_ros20190910 import models as ros_models
from alibabacloud_tea_util.models import RuntimeOptions

from iact3.plugin.base_plugin import CredentialClient
from tests.common import BaseTest


class TestBasePlugin(BaseTest):

    def test_credentials_env(self):
        '''
        set environment
        '''
        # os.environ['ALIBABA_CLOUD_ACCESS_KEY_ID'] = 'test_ak'
        # os.environ['ALIBABA_CLOUD_ACCESS_KEY_SECRET'] = 'test_sk'
        cred = CredentialClient()
        self.assertEqual(cred.cloud_credential.credential_type, 'access_key')

    def get_ros_client(self):
        cred = Client()
        config = Config(credential=cred)
        client = ROSClient(config)
        return client

    async def test_list_stacks(self):
        client = self.get_ros_client()
        request = ros_models.ListStacksRequest(region_id='cn-hangzhou')
        runtime_option = RuntimeOptions()
        response = await client.list_stacks_with_options_async(request, runtime_option)
        response = TeaCore.to_map(response)
        print(response)

