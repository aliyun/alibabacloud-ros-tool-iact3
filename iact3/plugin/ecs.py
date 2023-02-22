# -*- coding: utf-8 -*-
from alibabacloud_ecs20140526.client import Client

from iact3.plugin.base_plugin import TeaSDKPlugin


class EcsBasePlugin(TeaSDKPlugin):
    product = 'ECS'

    def api_client(self):
        return Client

    def models_path(self, action_name):
        return 'alibabacloud_ecs20140526.models.{}'.format(action_name)

    def runtime_kwargs(self):
        return {
            'autoretry': True,
            'max_attempts': 3,
            'read_timeout': 60000,
            'connect_timeout': 60000
        }


class EcsPlugin(EcsBasePlugin):

    async def get_security_group(self, vpc_id: str = None, security_group_id: str = None):
        kwargs = dict(
            VpcId=vpc_id,
            SecurityGroupIds=security_group_id
        )
        sgs = await self.fetch_all('DescribeSecurityGroups', kwargs, 'SecurityGroups', 'SecurityGroup')
        for sg in sgs:
            if not sg['ServiceManaged']:
                return sg
