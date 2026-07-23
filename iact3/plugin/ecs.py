# -*- coding: utf-8 -*-
from alibabacloud_ecs20140526.client import Client

from iact3.plugin.base_plugin import TeaSDKPlugin


class EcsBasePlugin(TeaSDKPlugin):
    product = 'ECS'

    def __init__(self, region_id: str, credential=None, config_kwargs: dict = None, endpoint: str = None):
        if not endpoint:
            endpoint = f'ecs.{region_id}.aliyuncs.com'
        super().__init__(region_id, credential=credential, config_kwargs=config_kwargs, endpoint=endpoint)

    def api_client(self):
        return Client

    def models_path(self, action_name):
        return 'alibabacloud_ecs20140526.models.{}'.format(action_name)

    def runtime_kwargs(self):
        return {'autoretry': True, 'max_attempts': 3, 'read_timeout': 60000, 'connect_timeout': 60000}


class EcsPlugin(EcsBasePlugin):
    async def get_security_group(self, vpc_id: str = None, security_group_id: str = None):
        kwargs = dict(VpcId=vpc_id, SecurityGroupIds=security_group_id)
        sgs = await self.fetch_all('DescribeSecurityGroups', kwargs, 'SecurityGroups', 'SecurityGroup')
        for sg in sgs:
            if not sg['ServiceManaged']:
                return sg

    async def describe_zones(self) -> list:
        """Return list of available zone IDs in the current region.

        Only returns zones with Status='Available' to avoid creating
        resources in disabled zones.
        """
        resp = await self.send_request('DescribeZones')
        zones = resp.get('Zones', {}).get('Zone', [])
        # Filter to only available zones; fall back to all if none have Status field
        available = [z['ZoneId'] for z in zones if z.get('ZoneId') and z.get('Status') == 'Available']
        if available:
            return available
        # Fallback: some API versions don't include Status, return all zones
        return [z['ZoneId'] for z in zones if z.get('ZoneId')]

    async def describe_available_instance_types(self, zone_id: str = None,
                                               instance_charge_type: str = None,
                                               system_disk_category: str = None) -> list:
        """Return list of instance type IDs the account is authorized to use.

        Uses DescribeAvailableResource (not DescribeZones) so that only
        authorized instance types are returned, avoiding
        InvalidInstanceType.ValueUnauthorized errors during cost estimation.
        When system_disk_category is provided, only instance types that
        support that disk category are returned.
        """
        # Primary: DescribeAvailableResource respects account authorization
        try:
            kwargs = {
                'DestinationResource': 'InstanceType',
                'IoOptimized': 'optimized',
                'Network': 'vpc',
            }
            if zone_id:
                kwargs['ZoneId'] = zone_id
            if instance_charge_type:
                kwargs['InstanceChargeType'] = instance_charge_type
            if system_disk_category:
                kwargs['SystemDiskCategory'] = system_disk_category
            resp = await self.send_request('DescribeAvailableResource', **kwargs)
            zones = resp.get('AvailableZones', {}).get('AvailableZone', [])
            instance_types = []
            for zone in zones:
                # Defensive: only collect from the requested zone to avoid
                # types from other zones leaking in.
                resp_zone_id = zone.get('ZoneId', '')
                if zone_id and resp_zone_id and resp_zone_id != zone_id:
                    continue
                resources = zone.get('AvailableResources', {}).get('AvailableResource', [])
                for res in resources:
                    items = res.get('SupportedResources', {}).get('SupportedResource', [])
                    for item in items:
                        if item.get('Status') == 'Available' and item.get('Value'):
                            instance_types.append(item['Value'])
            if instance_types:
                return list(set(instance_types))
            # Primary query returned empty — if system_disk_category was
            # specified, return empty so caller can try next disk category.
            # Do NOT fall back to DescribeZones (which ignores the filter).
            if system_disk_category:
                return []
        except Exception as e:
            # If system_disk_category was specified, do not fall back to
            # DescribeZones (which would return unfiltered types).
            if system_disk_category:
                import logging
                logging.getLogger(__name__).debug(
                    f'DescribeAvailableResource failed with system_disk_category='
                    f'{system_disk_category} in {zone_id}: {e}')
                return []
            # Otherwise, fall through to DescribeZones fallback
            pass

        # Fallback: DescribeZones (may include unauthorized types)
        kwargs = {}
        if zone_id:
            kwargs['ZoneId'] = zone_id
        resp = await self.send_request('DescribeZones', **kwargs)
        zones = resp.get('Zones', {}).get('Zone', [])
        instance_types = []
        for zone in zones:
            # Defensive: only collect from the requested zone
            resp_zone_id = zone.get('ZoneId', '')
            if zone_id and resp_zone_id and resp_zone_id != zone_id:
                continue
            available = zone.get('AvailableInstanceTypes', {})
            types = available.get('InstanceTypes', [])
            if types:
                instance_types.extend(types)
                break
        return list(set(instance_types))
