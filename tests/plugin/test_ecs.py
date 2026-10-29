# -*- coding: utf-8 -*-
from iact3.plugin.ecs import EcsPlugin
from tests.common import BaseTest


class TestEcsPlugin(BaseTest):
    def setUp(self) -> None:
        super(TestEcsPlugin, self).setUp()
        self.plugin = EcsPlugin(region_id=self.REGION_ID)

    async def test_get_sg(self):
        result = await self.plugin.get_security_group(vpc_id='vpc-2zeh14fqe8g53hoyvxdpv')
        self._pprint_json(result)


class TestEcsAvailableResources(BaseTest):
    def setUp(self):
        super().setUp()
        self.plugin = EcsPlugin(region_id=self.REGION_ID)
        self.calls = []

    def set_responses(self, responses):
        async def send(action, **kwargs):
            self.calls.append((action, kwargs))
            response = responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response
        self.plugin.send_request = send

    async def test_zones_filter_available_and_fallback(self):
        self.set_responses([
            {'Zones': {'Zone': [{'ZoneId': 'a', 'Status': 'Available'},
                                {'ZoneId': 'b', 'Status': 'Disabled'}, {'Status': 'Available'}]}},
            {'Zones': {'Zone': [{'ZoneId': 'b'}, {}, {'ZoneId': 'c'}]}},
            {},
        ])
        self.assertEqual(await self.plugin.describe_zones(), ['a'])
        self.assertEqual(await self.plugin.describe_zones(), ['b', 'c'])
        self.assertEqual(await self.plugin.describe_zones(), [])

    async def test_available_types_are_filtered_by_zone_and_status(self):
        self.set_responses([{'AvailableZones': {'AvailableZone': [
            {'ZoneId': 'other', 'AvailableResources': {'AvailableResource': [
                {'SupportedResources': {'SupportedResource': [{'Status': 'Available', 'Value': 'wrong'}]}}]}},
            {'ZoneId': 'zone-a', 'AvailableResources': {'AvailableResource': [
                {'SupportedResources': {'SupportedResource': [
                    {'Status': 'Available', 'Value': 'type-a'}, {'Status': 'Available', 'Value': 'type-a'},
                    {'Status': 'SoldOut', 'Value': 'type-b'}, {'Status': 'Available'}]}}]}},
        ]}}])
        result = await self.plugin.describe_available_instance_types('zone-a', 'PostPaid', 'cloud_essd')
        self.assertEqual(result, ['type-a'])
        self.assertEqual(self.calls, [('DescribeAvailableResource', {
            'DestinationResource': 'InstanceType', 'IoOptimized': 'optimized', 'Network': 'vpc',
            'ZoneId': 'zone-a', 'InstanceChargeType': 'PostPaid', 'SystemDiskCategory': 'cloud_essd'})])

    async def test_disk_filtered_query_never_falls_back(self):
        for response in ({}, RuntimeError('unavailable')):
            self.set_responses([response])
            self.calls = []
            self.assertEqual(await self.plugin.describe_available_instance_types('zone-a', system_disk_category='disk'), [])
            self.assertEqual(len(self.calls), 1)

    async def test_unfiltered_query_falls_back_on_empty_or_error(self):
        for response in ({}, RuntimeError('unavailable')):
            self.set_responses([response, {'Zones': {'Zone': [
                {'ZoneId': 'other', 'AvailableInstanceTypes': {'InstanceTypes': ['wrong']}},
                {'ZoneId': 'zone-a', 'AvailableInstanceTypes': {'InstanceTypes': ['a', 'a', 'b']}},
            ]}}])
            self.calls = []
            self.assertEqual(set(await self.plugin.describe_available_instance_types('zone-a')), {'a', 'b'})
            self.assertEqual([call[0] for call in self.calls], ['DescribeAvailableResource', 'DescribeZones'])

    async def test_get_security_group_skips_service_managed(self):
        async def fetch(*args):
            return [{'ServiceManaged': True}, {'ServiceManaged': False, 'SecurityGroupId': 'sg'}]
        self.plugin.fetch_all = fetch
        self.assertEqual((await self.plugin.get_security_group())['SecurityGroupId'], 'sg')

        async def empty(*args):
            return []
        self.plugin.fetch_all = empty
        self.assertIsNone(await self.plugin.get_security_group())
