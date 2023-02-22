from alibabacloud_vpc20160428.client import Client

from iact3.plugin.base_plugin import TeaSDKPlugin


class VpcBasePlugin(TeaSDKPlugin):

    product = 'VPC'

    def api_client(self):
        return Client

    def models_path(self, action_name):
        return 'alibabacloud_vpc20160428.models.{}'.format(action_name)


class VpcPlugin(VpcBasePlugin):

    async def get_one_vpc(self, vpc_id: str = None):
        kwargs = dict(VpcId=vpc_id, PageSize=50)
        response = await self.send_request('DescribeVpcsRequest', **kwargs)
        vpcs = response['Vpcs']['Vpc']
        for vpc in vpcs:
            if vpc['VSwitchIds']['VSwitchId']:
                return vpc

    async def get_one_vswitch(self, vpc_id: str = None, vsw_id: str = None, zone_id: str = None):
        kwargs = dict(VpcId=vpc_id, VSwitchId=vsw_id, ZoneId=zone_id)
        response = await self.send_request('DescribeVSwitchesRequest', **kwargs)
        vsws = response['VSwitches']['VSwitch']
        for vsw in vsws:
            if vsw['AvailableIpAddressCount'] > 1:
                return vsw
