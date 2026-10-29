from iact3.plugin.vpc import VpcPlugin
from tests.common import AsyncTestCase


class TestVpcSelection(AsyncTestCase):
    async def test_vpc_selection_skips_vpcs_without_switches(self):
        plugin = VpcPlugin('cn-test', credential=object(), endpoint='vpc.example')
        calls = []
        responses = [
            {'Vpcs': {'Vpc': [{'VpcId': 'empty', 'VSwitchIds': {'VSwitchId': []}},
                              {'VpcId': 'usable', 'VSwitchIds': {'VSwitchId': ['vsw']}}]}},
            {'Vpcs': {'Vpc': []}},
        ]

        async def send(action, **kwargs):
            calls.append((action, kwargs))
            return responses.pop(0)

        plugin.send_request = send
        self.assertEqual((await plugin.get_one_vpc('requested'))['VpcId'], 'usable')
        self.assertIsNone(await plugin.get_one_vpc())
        self.assertEqual(calls[0][1]['VpcId'], 'requested')
        self.assertEqual(plugin.endpoint, 'vpc.example')

    async def test_vswitch_selection_skips_exhausted_switches(self):
        plugin = VpcPlugin('cn-test', credential=object())
        responses = [
            {'VSwitches': {'VSwitch': [{'VSwitchId': 'full', 'AvailableIpAddressCount': 1},
                                       {'VSwitchId': 'usable', 'AvailableIpAddressCount': 2}]}},
            {'VSwitches': {'VSwitch': []}},
        ]
        calls = []

        async def send(action, **kwargs):
            calls.append(kwargs)
            return responses.pop(0)

        plugin.send_request = send
        self.assertEqual((await plugin.get_one_vswitch(vpc_id='vpc', zone_id='zone'))['VSwitchId'], 'usable')
        self.assertIsNone(await plugin.get_one_vswitch())
        self.assertEqual(calls[0]['ZoneId'], 'zone')
        self.assertEqual(calls[0]['VpcId'], 'vpc')
