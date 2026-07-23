import json
import logging
import random
import re
import string
import uuid
from urllib.parse import urlparse, parse_qs
from urllib.request import urlopen

import requests

from iact3.util import yaml, CustomSafeLoader, pick_cheapest_instance_type, sort_cheapest_db_instance_classes
from iact3.exceptions import Iact3Exception
from iact3.plugin.ecs import EcsPlugin
from iact3.plugin.oss import OssPlugin
from iact3.plugin.ros import StackPlugin
from iact3.plugin.vpc import VpcPlugin

LOG = logging.getLogger(__name__)

IAC_NAME = 'iact3'
IAC_PACKAGE_NAME = 'alibabacloud-ros-iact3'


class Selector:
    def __init__(self, key: str, original_value: any, allowed_values: list = None, parameters: dict = None):
        self.key = key
        self.original_value = original_value
        self.allowed_values = allowed_values or []
        self.parameters = parameters
        self.current_value = allowed_values[0] if allowed_values else None
        self.next = None
        self.prev = None

    def refresh_parameters(self):
        self.parameters[self.key] = self.current_value


class LinkedList:
    def __init__(self):
        self._head = None
        self._last = None

    def is_empty(self):
        return self._head is None

    def append(self, key, original_value, allowed_values=None, parameters=None):
        node = Selector(key, original_value, allowed_values, parameters)
        if self.is_empty():
            self._head = node
        else:
            cur = self._last
            cur.next = node
            node.prev = cur
        self._last = node

    def first(self):
        return self._head

    def remove(self, key):
        if self.is_empty():
            return
        cur = self.first()
        if cur.key == key:
            cur = cur.next
            if cur is None:
                self._head = None
                return
            cur.prev = None
            self._head = cur
            return
        while cur is not None:
            if cur.key == key:
                if cur.prev is not None:
                    cur.prev.next = cur.next
                if cur.next is not None:
                    cur.next.prev = cur.prev
                break
            cur = cur.next

    def __iter__(self):
        cur = self._head
        while cur is not None:
            value = cur.key
            cur = cur.next
            yield value


def _error_message(key, value, msg):
    return f'Parsing pseudo parameter (Key: {key}, Value: {value}) error, {msg}'


class ResolvedParameters:
    def __init__(self, name: str, region: str, parameters: dict, error=None):
        self.name = name
        self.region = region
        self.parameters = parameters
        self.error = error


class ParamGenerator:
    RE_V_AUTO = re.compile(rf'\$\[{IAC_NAME}-auto]', re.I)
    RE_V_CURRENT_REGION = re.compile(rf'\$\[{IAC_NAME}-current[-_]region]', re.I)

    RE_K_ZONE_ID = re.compile(r'(\w*)zone(_|)id(_|)(\d*)', re.I)
    RE_K_VPC_ID = re.compile(r'(\w*)vpc(_|)id(_|)(\d*)', re.I)
    RE_K_VSW_ID = re.compile(r'(\w*)v(_|)switch(_|)id(_|)(\d*)', re.I)
    RE_K_SECURITY_GROUP = re.compile(r'(\w*)security(_|)group(_id|id)(_|)(\d*)', re.I)
    RE_K_COMMON_NAME = re.compile(r'(\w*)name(_|)(\d*)', re.I)
    RE_K_PASSWORD = re.compile(r'(\w*)password(_|)(\d*)', re.I)
    RE_K_UUID = re.compile(r'(\w*)uuid(_|)(\d*)', re.I)
    RE_K_DB_INSTANCE_CLASS = re.compile(r'(\w*)DBInstanceClass(\w*)', re.I)
    RE_K_INSTANCE_TYPE = re.compile(r'(\w*)instance(_|)type(\w*)', re.I)
    RE_K_SYSTEM_DISK = re.compile(r'(\w*)system(_|)disk(_|)(category|type)(\w*)', re.I)

    # Disk categories known to be broadly supported by ROS ECS creation.
    # Only these are accepted during InstanceType cross-validation to avoid
    # false positives from the DescribeAvailableResource API.
    SAFE_DISK_CATEGORIES = ('cloud_essd', 'cloud_ssd', 'cloud_efficiency', 'cloud_auto')

    def __init__(self, config):
        self.config = config
        self.region = config.region
        self.parameters = config.parameters
        self.template_config = config.template_config
        self.parameters_order = config.parameters_order
        self.credential = config.auth.credential
        self.plugin = StackPlugin(region_id=self.region, credential=self.credential)
        self._vpc_id = None
        self._vsw_id = None
        self._not_support_keys = None
        self._linked_list: LinkedList = LinkedList()
        self._unresolved_parameters = {}
        self._template_defaults_cache = None
        self._association_property_cache = None
        self._zone_list_cache = None
        self._zone_assignments = {}
        self._resolved_disk_category = None  # Set by _resolve_instance_type when disk-aware query succeeds

    @classmethod
    async def result(cls, config) -> ResolvedParameters:
        pg = cls(config)
        LOG.debug(f'start to generate parameters for {config.test_name}')
        error = None
        try:
            await pg.resolve_auto_value()
            LOG.debug(f'resolve auto value result: {pg.parameters}')
            try:
                await pg.resolve_auto_key()
                LOG.debug(f'resolve auto key result: {pg.parameters}')
                LOG.debug(f'_vpc_id={pg._vpc_id}, _vsw_id={pg._vsw_id}')
                # Post-resolution sync: if _gen_sg switched VPC during resolve_auto_key,
                # ensure VpcId/VSwitchId parameters reflect the current _vpc_id/_vsw_id.
                if pg._vpc_id:
                    for pname in list(pg.parameters.keys()):
                        if pg.RE_K_VPC_ID.fullmatch(pname) and pg.parameters[pname] != pg._vpc_id:
                            LOG.debug(f'post-sync: updating {pname} from {pg.parameters[pname]} to {pg._vpc_id}')
                            pg.parameters[pname] = pg._vpc_id
                if pg._vsw_id:
                    for pname in list(pg.parameters.keys()):
                        if pg.RE_K_VSW_ID.fullmatch(pname) and pg.parameters[pname] != pg._vsw_id:
                            LOG.debug(f'post-sync: updating {pname} from {pg.parameters[pname]} to {pg._vsw_id}')
                            pg.parameters[pname] = pg._vsw_id
            except Exception as ex:
                # resolve_auto_key failed (e.g. no vswitch in zone), but still try
                # to resolve remaining parameters via defaults/fallbacks.
                error = ex
                LOG.debug(f'resolve_auto_key partial failure: {ex}')
            # Always run fallback resolution, even if resolve_auto_key raised.
            await pg.resolve_unresolved_with_defaults()
            resolved_parameters = ResolvedParameters(
                config.test_name, config.region, pg.parameters, error=error
            )
            if error:
                LOG.debug(
                    f'partial generate parameters for {config.test_name}, parameters {resolved_parameters.parameters}'
                )
            else:
                LOG.debug(
                    f'success generate parameters for {config.test_name}, parameters {resolved_parameters.parameters}'
                )
        except Exception as ex:
            resolved_parameters = ResolvedParameters(config.test_name, config.region, pg.parameters, error=ex)
            LOG.debug(f'failed generate parameters for {config.test_name}, {ex}', exc_info=True)
        return resolved_parameters

    async def resolve_unresolved_with_defaults(self):
        """Fallback: replace remaining $[iact3-auto] values with template Default values
        or API-based resolution (e.g. ZoneId via ECS DescribeZones)."""
        remaining = {
            k: v for k, v in self.parameters.items()
            if isinstance(v, str) and self.RE_V_AUTO.fullmatch(v)
        }
        if not remaining:
            return

        defaults = await self._get_template_defaults()
        for key in remaining:
            if key in defaults:
                self.parameters[key] = defaults[key]
                LOG.debug(f'used template default value for unresolved parameter {key}: {defaults[key]}')

        # Second pass: resolve ZoneId parameters that have no template Default
        # using ECS DescribeZones API as a fallback.
        still_remaining = {
            k: v for k, v in self.parameters.items()
            if isinstance(v, str) and self.RE_V_AUTO.fullmatch(v)
        }
        for key in still_remaining:
            if self.RE_K_ZONE_ID.fullmatch(key):
                resolved_zone = await self._resolve_zone_id(key)
                if resolved_zone:
                    self.parameters[key] = resolved_zone
                    LOG.debug(f'resolved zone parameter {key} via fallback: {resolved_zone}')

        # Final safety net: ensure no ZoneId parameter remains as $[iact3-auto].
        # If all API-based resolution failed, try once more with a broader VSwitch query.
        final_remaining = {
            k: v for k, v in self.parameters.items()
            if isinstance(v, str) and self.RE_V_AUTO.fullmatch(v) and self.RE_K_ZONE_ID.fullmatch(k)
        }
        for key in final_remaining:
            try:
                plugin = VpcPlugin(self.region, credential=self.credential)
                vsw = await plugin.get_one_vswitch()
                if vsw and vsw.get('ZoneId'):
                    self.parameters[key] = vsw['ZoneId']
                    LOG.warning(f'resolved zone parameter {key} via final VSwitch fallback: {vsw["ZoneId"]}')
            except Exception as ex:
                LOG.warning(f'all zone resolution methods failed for {key}: {ex}')

        # Name-based fallback for well-known ECS properties without AssociationProperty.
        # These are common ROS template parameters whose valid values are fixed and known.
        _KNOWN_PARAM_DEFAULTS = {
            'AllocatePublicIP': 'false',
            'InstanceChargeType': 'PostPaid',
            'NetworkType': 'vpc',
            'InternetChargeType': 'PayByTraffic',
            'InternetMaxBandwidthOut': '0',
            'DeletionProtection': 'false',
            'AutoRenew': 'false',
        }
        name_remaining = {
            k: v for k, v in self.parameters.items()
            if isinstance(v, str) and self.RE_V_AUTO.fullmatch(v)
        }
        for key in name_remaining:
            key_lower = key.lower()
            for known_name, default_val in _KNOWN_PARAM_DEFAULTS.items():
                if key_lower == known_name.lower():
                    self.parameters[key] = default_val
                    LOG.debug(f'resolved parameter {key} via name-based fallback: {default_val}')
                    break

    async def _get_template_defaults(self) -> dict:
        """Parse template and return a dict of {param_name: Default} for parameters that have Default values."""
        if self._template_defaults_cache is not None:
            return self._template_defaults_cache

        defaults = {}
        try:
            template = await self._get_template_body()
            if not template:
                self._template_defaults_cache = defaults
                return defaults
            parsed_tpl = yaml.load(template, Loader=CustomSafeLoader)
            tpl_params = parsed_tpl.get('Parameters', {})
            if isinstance(tpl_params, dict):
                for param_name, param_def in tpl_params.items():
                    if isinstance(param_def, dict) and 'Default' in param_def:
                        default_val = param_def['Default']
                        if default_val is not None:
                            defaults[param_name] = str(default_val) if not isinstance(default_val, str) else default_val
        except Exception as ex:
            LOG.debug(f'failed to get template defaults: {ex}', exc_info=True)

        self._template_defaults_cache = defaults
        return defaults

    async def _get_association_properties(self) -> dict:
        """Parse template and return a dict of {param_name: AssociationProperty} for parameters that have one."""
        if self._association_property_cache is not None:
            return self._association_property_cache

        props = {}
        try:
            template = await self._get_template_body()
            if not template:
                self._association_property_cache = props
                return props
            parsed_tpl = yaml.load(template, Loader=CustomSafeLoader)
            tpl_params = parsed_tpl.get('Parameters', {})
            if isinstance(tpl_params, dict):
                for param_name, param_def in tpl_params.items():
                    if isinstance(param_def, dict) and 'AssociationProperty' in param_def:
                        props[param_name] = param_def['AssociationProperty']
        except Exception as ex:
            LOG.debug(f'failed to get association properties: {ex}', exc_info=True)

        self._association_property_cache = props
        return props

    async def resolve_auto_key(self):
        # Pass 1: Resolve ZoneId, VPC, VSwitch, SecurityGroup first —
        # InstanceType and SystemDiskCategory depend on a resolved zone.
        for key, unresolved_value in self._unresolved_parameters.items():
            if not isinstance(unresolved_value, str) or not self.RE_V_AUTO.fullmatch(unresolved_value):
                continue
            # Skip parameters that depend on zone (handled in pass 2)
            ap_map = await self._get_association_properties()
            ap = ap_map.get(key, '')
            if ap in ('ALIYUN::ECS::Instance::ECSInstanceType', 'ALIYUN::ECS::Instance::InstanceType',
                      'ALIYUN::ECS::Disk::SystemDiskCategory'):
                continue
            # Also skip by parameter name (templates without AssociationProperty)
            if self.RE_K_INSTANCE_TYPE.fullmatch(key) or self.RE_K_SYSTEM_DISK.fullmatch(key):
                continue

            if self.RE_K_VSW_ID.fullmatch(key):
                if self._vsw_id is None:
                    await self._gen_vpc_vsw_id(key, unresolved_value)
                self.parameters[key] = re.sub(self.RE_V_AUTO, self._vsw_id, unresolved_value)
            elif self.RE_K_VPC_ID.fullmatch(key):
                if self._vpc_id is None:
                    await self._gen_vpc_vsw_id(key, unresolved_value)
                self.parameters[key] = re.sub(self.RE_V_AUTO, self._vpc_id, unresolved_value)
            elif self.RE_K_ZONE_ID.fullmatch(key):
                resolved_zone = await self._resolve_zone_id(key)
                if resolved_zone:
                    self.parameters[key] = resolved_zone
            elif self.RE_K_COMMON_NAME.fullmatch(key):
                value = self._gen_common_name()
                self.parameters[key] = re.sub(self.RE_V_AUTO, value, unresolved_value)
            elif self.RE_K_PASSWORD.fullmatch(key):
                value = self._gen_password()
                self.parameters[key] = re.sub(self.RE_V_AUTO, value, unresolved_value)
            elif self.RE_K_UUID.fullmatch(key):
                value = self._gen_uuid()
                self.parameters[key] = re.sub(self.RE_V_AUTO, value, unresolved_value)
            elif self.RE_K_SECURITY_GROUP.fullmatch(key):
                if self._vpc_id is None:
                    self._vpc_id, self._vsw_id = await self._gen_vpc_vsw_id(key, unresolved_value)
                value = await self._gen_sg(key, unresolved_value)
                self.parameters[key] = re.sub(self.RE_V_AUTO, value, unresolved_value)

        # Pass 2: Resolve InstanceType and SystemDiskCategory — now ZoneId is available.
        for key, unresolved_value in self._unresolved_parameters.items():
            if not isinstance(unresolved_value, str) or not self.RE_V_AUTO.fullmatch(unresolved_value):
                continue
            # Only process if still unresolved (pass 1 may have resolved some)
            current = self.parameters.get(key)
            if isinstance(current, str) and not self.RE_V_AUTO.fullmatch(current):
                continue

            ap_map = await self._get_association_properties()
            ap = ap_map.get(key, '')
            if ap in ('ALIYUN::ECS::Instance::ECSInstanceType', 'ALIYUN::ECS::Instance::InstanceType') \
                    or self.RE_K_INSTANCE_TYPE.fullmatch(key):
                value = await self._resolve_instance_type(key)
                if value:
                    self.parameters[key] = value
            elif ap == 'ALIYUN::ECS::Disk::SystemDiskCategory' or self.RE_K_SYSTEM_DISK.fullmatch(key):
                value = await self._resolve_system_disk_category(key)
                if value:
                    self.parameters[key] = value

        return self.parameters

    async def resolve_auto_value(self):
        linked_list = LinkedList()
        resolved_parameters = {}
        parameters_order = self.parameters_order
        if not parameters_order:
            parameters_order = await self._get_parameters_order() or self.parameters.keys()
        for key in parameters_order:
            if key not in self.parameters:
                continue
            original_value = self.parameters[key]
            if not isinstance(original_value, str):
                resolved_parameters[key] = original_value
                continue

            if self.RE_V_AUTO.fullmatch(original_value):
                # Skip InstanceType and SystemDiskCategory — they need disk-aware
                # resolution in resolve_auto_key Pass 2.  If resolved here via ROS
                # constraints API, the result won't consider SystemDiskCategory
                # compatibility, leading to ECS creation failures.
                if self.RE_K_INSTANCE_TYPE.fullmatch(key) or self.RE_K_SYSTEM_DISK.fullmatch(key):
                    # Set to None (not $[iact3-auto]) so _convert_parameters
                    # filters it out when sending to ROS constraints API.
                    # Pass 2 will resolve it via disk-aware logic.
                    resolved_parameters[key] = None
                    self._unresolved_parameters[key] = original_value  # For Pass 2
                    continue
                resolved_parameters[key] = None
                linked_list.append(key, original_value, parameters=resolved_parameters)
            elif self.RE_V_CURRENT_REGION.fullmatch(original_value):
                resolved_parameters[key] = self.region
            else:
                resolved_parameters[key] = original_value

        self._linked_list = linked_list
        first_selector = linked_list.first()
        if not first_selector:
            return resolved_parameters
        resolved_parameters = await self._select_value(first_selector)
        self.parameters.update(resolved_parameters)
        self.parameters.update(self._unresolved_parameters)
        return self.parameters

    async def _get_constraints(self, **kwargs):
        for _ in range(3):
            constraints = await self.plugin.get_parameter_constraints(**kwargs)
            behavior = constraints[0].get('Behavior')
            values = constraints[0].get('AllowedValues')
            reason = constraints[0].get('BehaviorReason')
            if behavior == 'QueryError' and reason and 'timeout' in reason:
                LOG.debug(f'get constraints timeout, {constraints}')
                continue
            if behavior == 'NotSupport':
                return
            return values
        else:
            return 'timeout'

    async def _select_value(self, selector: Selector, error_message=None) -> dict:
        key = selector.key
        parameters = selector.parameters
        allowed_values = selector.allowed_values
        current_value = selector.current_value
        error_msg = (
            f'can not find any available value for {key} in {self.region} region '
            f'in {allowed_values} for {self.config.test_name}'
        )

        if allowed_values:
            next_selector = selector.next
            if not next_selector:
                return selector.parameters
            index = allowed_values.index(current_value)
            if index + 1 >= len(allowed_values):
                prev_selector = selector.prev
                if not prev_selector:
                    raise Iact3Exception(error_message or error_msg)
                return await self._select_value(prev_selector, error_message=error_message)
            selector.current_value = allowed_values[index + 1]
            next_selector.parameters[key] = selector.current_value
            next_selector.allowed_values = []
            return await self._select_value(next_selector, error_message=error_message)

        values = await self._get_constraints(
            parameters=parameters,
            **self.template_config.to_dict(),
            parameters_key_filter=[key],
            parameters_order=self.parameters_order,
        )
        if values is None:
            # NotSupport from constraints API — try direct resolution for ZoneId
            if self.RE_K_ZONE_ID.fullmatch(key):
                resolved_zone = await self._resolve_zone_id(key)
                if resolved_zone:
                    selector.parameters[key] = resolved_zone
                    LOG.debug(f'resolved zone parameter {key} via ECS DescribeZones: {resolved_zone}')
                    next_selector = selector.next
                    if not next_selector:
                        return selector.parameters
                    next_selector.parameters[key] = resolved_zone
                    return await self._select_value(next_selector, error_message=error_message)
            next_selector = selector.next
            self._unresolved_parameters[key] = selector.original_value
            self._linked_list.remove(key)
            if not next_selector:
                return selector.parameters
            return await self._select_value(next_selector, error_message=error_message)
        elif values == 'timeout':
            msg = f'get constraints timeout for {key} in {self.region} region for {self.config.test_name}'
            raise Iact3Exception(msg)
        elif not values:
            # Try template Default value as fallback before raising
            defaults = await self._get_template_defaults()
            if key in defaults:
                selector.parameters[key] = defaults[key]
                LOG.debug(f'used template default for {key} during constraint resolution: {defaults[key]}')
                next_selector = selector.next
                if not next_selector:
                    return selector.parameters
                next_selector.parameters[key] = defaults[key]
                return await self._select_value(next_selector, error_message=error_message)

            # For ZoneId parameters, try direct ECS DescribeZones resolution
            if self.RE_K_ZONE_ID.fullmatch(key):
                resolved_zone = await self._resolve_zone_id(key)
                if resolved_zone:
                    selector.parameters[key] = resolved_zone
                    LOG.debug(f'resolved zone parameter {key} via ECS DescribeZones (empty constraints): {resolved_zone}')
                    next_selector = selector.next
                    if not next_selector:
                        return selector.parameters
                    next_selector.parameters[key] = resolved_zone
                    return await self._select_value(next_selector, error_message=error_message)

            prev_selector = selector.prev
            if prev_selector:
                error_msg = f'no available value found for {key} in {self.region} region for {self.config.test_name}'
                return await self._select_value(prev_selector, error_message=error_msg)

            # No previous selector to backtrack to and no template Default.
            # Treat as unresolved (same as NotSupport) so later stages can handle it
            # via resolve_auto_key / resolve_unresolved_with_defaults.
            LOG.warning(
                f'constraints API returned empty values for {key} and no template Default available, '
                f'marking as unresolved'
            )
            next_selector = selector.next
            self._unresolved_parameters[key] = selector.original_value
            self._linked_list.remove(key)
            if not next_selector:
                return selector.parameters
            return await self._select_value(next_selector, error_message=error_message)

        # For RDS DBInstanceClass, sort values from cheapest to most expensive
        if self.RE_K_DB_INSTANCE_CLASS.fullmatch(key):
            values = sort_cheapest_db_instance_classes(values)

        selector.allowed_values = values
        selector.current_value = values[0]
        selector.parameters[key] = selector.current_value
        next_selector = selector.next
        if not next_selector:
            return selector.parameters
        next_selector.parameters[key] = selector.current_value
        return await self._select_value(next_selector, error_message=error_message)

    async def _get_parameters_order(self):
        template = await self._get_template_body()
        if not template:
            raise Iact3Exception(f'failed to retrieve template by template config {self.template_config}')
        parsed_tpl = yaml.load(template, Loader=CustomSafeLoader)
        param_groups = parsed_tpl.get('Metadata', {}).get('ALIYUN::ROS::Interface', {}).get('ParameterGroups', [])
        if not param_groups:
            return
        params_in_metadata = []
        for param_group in param_groups:
            params = param_group.get('Parameters', []) if param_group else None
            if not params:
                continue
            standard_params = [p for p in params if isinstance(p, str)]
            params_in_metadata += standard_params

        for key in self.parameters:
            if key not in params_in_metadata:
                params_in_metadata.append(key)

        self.parameters_order = params_in_metadata
        return params_in_metadata

    template_max_size = 524288

    async def _get_template_body(self):
        template_body = self.template_config.template_body
        if template_body:
            return template_body

        template_id = self.template_config.template_id
        if template_id:
            try:
                template_info = await self.plugin.get_template(
                    template_id=template_id, template_version=self.template_config.template_version
                )
                return template_info['TemplateBody']
            except Exception as ex:
                raise Iact3Exception(f'Failed to retrieve {template_id}: {ex}')

        template_url = self.template_config.template_url
        if template_url:
            components = urlparse(template_url)
            if components.scheme == 'oss':
                return self._get_template_from_oss(template_url, components)
            elif components.scheme == 'file':
                try:
                    return urlopen(template_url).read()
                except Exception as ex:
                    raise Iact3Exception(f'Failed to retrieve {template_url}: {ex}')
            else:
                try:
                    resp = requests.get(template_url, timeout=10, stream=True)
                    resp.raise_for_status()

                    reader = resp.iter_content(chunk_size=1000)
                    result = b''
                    max_size = self.template_max_size
                    for chunk in reader:
                        result += chunk
                        if len(result) > max_size:
                            raise Iact3Exception(
                                f'template from {template_url}exceeds maximum allowed size ({max_size} bytes)'
                            )
                    return result
                except Exception as ex:
                    raise Iact3Exception(f'Failed to retrieve {template_url}: {ex}')

    def _get_template_from_oss(self, template_url, components):
        bucket_name = components.netloc
        object_path = components.path.strip('/')
        if not bucket_name or not object_path:
            raise Iact3Exception(f'Invalid oss url {template_url}')
        region_id = self.region
        if components.query:
            t = parse_qs(components.query)
            region_ids = t.get('RegionId')
            region_id = region_ids[0] if region_ids else self.region

        oss_plugin = OssPlugin(region_id=region_id, bucket_name=bucket_name, credential=self.credential)
        try:
            object_meta = oss_plugin.get_object_meta(object_path)
        except Exception as ex:
            raise Iact3Exception(f'Oss failed: {ex}')
        if object_meta is None:
            raise Iact3Exception(f'Invalid oss url {template_url}')
        if object_meta.content_length > self.template_max_size:
            raise Iact3Exception(f'template from {template_url} exceeds maximum allowed size (524288 bytes)')

        try:
            r = oss_plugin.get_object_content(object_path)
        except Exception as ex:
            raise Iact3Exception(f'Oss failed: {ex}')
        if r is None:
            raise Iact3Exception(f'Invalid oss url {template_url}')
        return r.read()

    async def _gen_vpc_id(self, key, value):
        plugin = VpcPlugin(self.region, credential=self.credential)
        vpc = await plugin.get_one_vpc()
        if not vpc:
            msg = f'can not find any vpc in region {self.region}'
            raise Iact3Exception(_error_message(key, value, msg))
        return vpc['VpcId']

    async def _gen_vpc_vsw_id(self, key, value):
        zone_id = None
        zone_key = None
        for name, val in self.parameters.items():
            if self.RE_K_ZONE_ID.fullmatch(name):
                zone_key = name
                zone_id = val
                break

        # If the zone parameter is still unresolved ($[iact3-auto]), try to resolve it
        # so that VSwitch lookup gets a real zone value.
        zone_unresolved = zone_id is not None and isinstance(zone_id, str) and self.RE_V_AUTO.fullmatch(zone_id)
        if zone_unresolved:
            resolved_zone = await self._resolve_zone_id(zone_key)
            if resolved_zone:
                zone_id = resolved_zone
                self.parameters[zone_key] = zone_id
                zone_unresolved = False

        plugin = VpcPlugin(self.region, credential=self.credential)
        vsw = await plugin.get_one_vswitch(zone_id=zone_id if not zone_unresolved else None)

        # If no VSwitch found in the selected zone, try other available zones
        # before giving up.  This handles cases where the auto-selected zone
        # (e.g. an internal zone like cn-shenzhen-x2) has no VSwitches.
        if not vsw and zone_id and not zone_unresolved:
            LOG.debug(f'no vswitch in zone {zone_id}, trying other zones')
            if self._zone_list_cache is None:
                self._zone_list_cache = await self._fetch_available_zones()
            for alt_zone in self._zone_list_cache:
                if alt_zone == zone_id:
                    continue
                try:
                    vsw = await plugin.get_one_vswitch(zone_id=alt_zone)
                    if vsw:
                        LOG.debug(f'found vswitch in alternative zone {alt_zone}')
                        # Update the zone parameter to the zone that actually has a VSwitch
                        if zone_key:
                            self.parameters[zone_key] = alt_zone
                            self._zone_assignments[zone_key] = alt_zone
                        zone_id = alt_zone
                        break
                except Exception:
                    continue

        if not vsw:
            msg = f'can not find any vswitch in zone {zone_id}' if not zone_unresolved else f'can not find any vswitch in region {self.region}'
            raise Iact3Exception(_error_message(key, value, msg))

        # Backfill the zone parameter with the actual zone from the found VSwitch
        if zone_unresolved and zone_key:
            self.parameters[zone_key] = vsw.get('ZoneId', zone_id)

        self._vpc_id = vsw['VpcId']
        self._vsw_id = vsw['VSwitchId']

        # Proactively check for SecurityGroup: if the template has an
        # unresolved SecurityGroupId parameter, verify that the chosen VPC
        # also has a security group.  If not, try other VPCs that have BOTH
        # VSwitch and SecurityGroup — this avoids picking a VPC that would
        # later fail in _gen_sg and require a reactive VPC switch.
        has_sg_param = any(
            self.RE_K_SECURITY_GROUP.fullmatch(k)
            for k, v in self.parameters.items()
            if isinstance(v, str) and self.RE_V_AUTO.fullmatch(v)
        )
        if has_sg_param:
            ecs_plugin = EcsPlugin(self.region, credential=self.credential)
            sg = await ecs_plugin.get_security_group(vpc_id=self._vpc_id)
            if not sg:
                LOG.debug(f'vpc {self._vpc_id} has vswitch but no security group, trying other vpcs')
                vpc_plugin = VpcPlugin(self.region, credential=self.credential)
                response = await vpc_plugin.send_request('DescribeVpcsRequest', PageSize=50)
                vpcs = response.get('Vpcs', {}).get('Vpc', [])
                for vpc in vpcs:
                    candidate_vpc_id = vpc['VpcId']
                    if candidate_vpc_id == self._vpc_id:
                        continue
                    sg = await ecs_plugin.get_security_group(vpc_id=candidate_vpc_id)
                    if sg:
                        candidate_vsw = await vpc_plugin.get_one_vswitch(vpc_id=candidate_vpc_id)
                        if candidate_vsw:
                            old_vpc_id = self._vpc_id
                            old_vsw_id = self._vsw_id
                            self._vpc_id = candidate_vpc_id
                            self._vsw_id = candidate_vsw['VSwitchId']
                            # Update zone if the new VSwitch is in a different zone
                            new_zone = candidate_vsw.get('ZoneId', '')
                            if new_zone and new_zone != zone_id:
                                zone_id = new_zone
                                if zone_key:
                                    self.parameters[zone_key] = zone_id
                                    self._zone_assignments[zone_key] = zone_id
                            # Sync VpcId/VSwitchId parameters
                            for pname in list(self.parameters.keys()):
                                if self.RE_K_VPC_ID.fullmatch(pname) and self.parameters[pname] == old_vpc_id:
                                    self.parameters[pname] = self._vpc_id
                                elif self.RE_K_VSW_ID.fullmatch(pname) and self.parameters[pname] == old_vsw_id:
                                    self.parameters[pname] = self._vsw_id
                            LOG.debug(f'switched to vpc {self._vpc_id} (vswitch={self._vsw_id}, sg={sg["SecurityGroupId"]})')
                            break

        return self._vpc_id, self._vsw_id

    async def _resolve_zone_id(self, zone_key) -> str:
        """Resolve a ZoneId parameter. Uses ECS DescribeZones API for reliable zone listing.

        When multiple ZoneId parameters exist (e.g. ZoneId1, ZoneId2), each is assigned
        a different zone to support ExclusiveTo constraints in templates.
        """
        # Return existing assignment for this key (idempotent)
        if zone_key in self._zone_assignments:
            return self._zone_assignments[zone_key]

        # Fetch zone list once and cache it
        if self._zone_list_cache is None:
            self._zone_list_cache = await self._fetch_available_zones()

        zones = self._zone_list_cache
        if not zones:
            return None

        # Pick a zone not yet assigned to any other ZoneId parameter
        used_zones = set(self._zone_assignments.values())
        for zone in zones:
            if zone not in used_zones:
                self._zone_assignments[zone_key] = zone
                LOG.debug(f'assigned zone {zone} to {zone_key} (exclusive)')
                return zone

        # All zones are already assigned — reuse the first one
        self._zone_assignments[zone_key] = zones[0]
        LOG.debug(f'assigned zone {zones[0]} to {zone_key} (reused, all zones in use)')
        return zones[0]

    async def _fetch_available_zones(self) -> list:
        """Fetch list of available zones via ECS DescribeZones, with VSwitch fallback.

        Zones are sorted in reverse alphabetical order so that newer zones
        (e.g. cn-hangzhou-k) are preferred over older ones (e.g. cn-hangzhou-b).
        Internal zones (e.g. cn-shenzhen-x2) are deprioritised to the end
        of the list because they often lack VSwitches and standard resources.
        """
        # Primary: use ECS DescribeZones API to get available zones in the region
        ecs_plugin = None
        try:
            ecs_plugin = EcsPlugin(self.region, credential=self.credential)
            LOG.debug(f'resolving zones via ECS DescribeZones, region={self.region}, endpoint={ecs_plugin.endpoint}')
            zones = await ecs_plugin.describe_zones()
            if zones:
                # Separate standard zones from internal zones (e.g. cn-shenzhen-x2)
                # Internal zones have an '-x<digit>' component in the zone ID suffix.
                internal_pattern = re.compile(r'-x\d', re.IGNORECASE)
                standard = [z for z in zones if not internal_pattern.search(z)]
                internal = [z for z in zones if internal_pattern.search(z)]
                # Prefer newer standard zones first, then internal zones as last resort
                return sorted(standard, reverse=True) + sorted(internal, reverse=True)
        except Exception as ex:
            ep_info = ''
            if ecs_plugin:
                ep_info = f' (endpoint={ecs_plugin.endpoint})'
            LOG.warning(f'failed to describe zones{ep_info}: {ex}')

        # Fallback: find any VSwitch in the region and use its ZoneId
        vpc_plugin = None
        try:
            vpc_plugin = VpcPlugin(self.region, credential=self.credential)
            LOG.debug(f'resolving zone via VPC VSwitch fallback, region={self.region}, endpoint={vpc_plugin.endpoint}')
            vsw = await vpc_plugin.get_one_vswitch()
            if vsw and vsw.get('ZoneId'):
                return [vsw['ZoneId']]
        except Exception as ex:
            ep_info = ''
            if vpc_plugin:
                ep_info = f' (endpoint={vpc_plugin.endpoint})'
            LOG.warning(f'failed to find vswitch for zone fallback{ep_info}: {ex}')

        return []

    def _safe_endpoint(self, product) -> str:
        """Get expected endpoint string for logging without creating a plugin instance."""
        return f'{product}.{self.region}.aliyuncs.com'

    async def _query_disk_available(self, zone_id, instance_type, disk_type='SystemDisk'):
        """Query available disk categories for a given zone + instance type.

        Passes InstanceChargeType=PostPaid, IoOptimized=optimized and
        Network=vpc to match the actual ROS ECS creation parameters,
        so the API only returns disk categories that are compatible with
        the full property combination.

        Returns a list of available disk category strings, or [] on failure.
        """
        try:
            kwargs = {
                'DestinationResource': disk_type,
                'InstanceChargeType': 'PostPaid',
                'IoOptimized': 'optimized',
                'Network': 'vpc',
            }
            if zone_id:
                kwargs['ZoneId'] = zone_id
            if instance_type:
                kwargs['InstanceType'] = instance_type
            ecs_plugin = EcsPlugin(self.region, credential=self.credential)
            resp = await ecs_plugin.send_request('DescribeAvailableResource', **kwargs)
            zones = resp.get('AvailableZones', {}).get('AvailableZone', [])
            candidates = []
            for zone in zones:
                resp_zone_id = zone.get('ZoneId', '')
                if zone_id and resp_zone_id and resp_zone_id != zone_id:
                    continue
                resources = zone.get('AvailableResources', {}).get('AvailableResource', [])
                for res in resources:
                    items = res.get('SupportedResources', {}).get('SupportedResource', [])
                    for item in items:
                        val = item.get('Value', '')
                        if item.get('Status') == 'Available' and val:
                            candidates.append(val)
            return list(set(candidates))
        except Exception as ex:
            LOG.debug(f'failed to query {disk_type} for {instance_type} in {zone_id}: {ex}')
            return []

    async def _resolve_instance_type(self, key) -> str:
        """Resolve an ECS instance type parameter.

        If the template has a SystemDiskCategory parameter, queries InstanceType
        with each disk category filter (cloud_essd → cloud_ssd → cloud_efficiency)
        in priority order.  The first disk category that returns non-empty
        instance types wins, and both values are set simultaneously.
        This ensures InstanceType and SystemDiskCategory are always compatible.
        """
        zone_id = None
        for name, val in self.parameters.items():
            if self.RE_K_ZONE_ID.fullmatch(name) and isinstance(val, str) and not self.RE_V_AUTO.fullmatch(val):
                zone_id = val
                break

        # Check if template has a SystemDiskCategory parameter (by AP or name)
        ap_map = await self._get_association_properties()
        has_disk_param = any(
            ap == 'ALIYUN::ECS::Disk::SystemDiskCategory'
            for ap in ap_map.values()
        ) or any(
            self.RE_K_SYSTEM_DISK.fullmatch(k)
            for k, v in self.parameters.items()
            if isinstance(v, str) and self.RE_V_AUTO.fullmatch(v)
        )

        try:
            ecs_plugin = EcsPlugin(self.region, credential=self.credential)

            if has_disk_param:
                # Query InstanceType with each disk category filter in priority order.
                # The first category that returns non-empty results wins.
                for disk_cat in self.SAFE_DISK_CATEGORIES:
                    types = await ecs_plugin.describe_available_instance_types(
                        zone_id=zone_id, instance_charge_type='PostPaid',
                        system_disk_category=disk_cat
                    )
                    LOG.info(f'query InstanceType with SystemDiskCategory={disk_cat} in {zone_id}: got {len(types)} types')
                    if types:
                        self._resolved_disk_category = disk_cat
                        picked = pick_cheapest_instance_type(types)
                        LOG.info(f'resolved instance type {picked} with disk category {disk_cat} in {zone_id}')
                        return picked
                    LOG.info(f'no instance type found with {disk_cat} in {zone_id}, trying next disk category')

                # All disk categories exhausted — query without filter as fallback
                LOG.warning(f'no instance type found with any standard disk category in {zone_id}, using unfiltered')

            # No disk parameter, or all disk filters returned empty — query without filter
            types = await ecs_plugin.describe_available_instance_types(
                zone_id=zone_id, instance_charge_type='PostPaid'
            )
            if types:
                return pick_cheapest_instance_type(types)
        except Exception as ex:
            LOG.debug(f'failed to resolve instance type for {key}: {ex}', exc_info=True)
        return None

    async def _resolve_system_disk_category(self, key) -> str:
        """Resolve SystemDiskCategory.

        If _resolve_instance_type already determined a compatible disk category
        (via disk-aware InstanceType query), use that directly.  Otherwise
        default to cloud_essd.
        """
        if self._resolved_disk_category:
            LOG.debug(f'using disk category from instance type resolution: {self._resolved_disk_category}')
            return self._resolved_disk_category

        # Instance type was resolved without disk filter — default to cloud_essd
        LOG.debug('defaulting system disk category to cloud_essd')
        return 'cloud_essd'

    def _gen_common_name(self):
        return f'{IAC_NAME}-{uuid.uuid1().hex}'[:50]

    def _gen_password(self):
        # RDS allows only: !@#$%^&*()_+-=
        # Use this restrictive set for cross-service compatibility
        special_chars = '!@#$%^&*()_+-='
        password_chars = []
        for item in (string.ascii_lowercase, special_chars, string.digits, string.ascii_uppercase):
            password_chars.extend(random.sample(item, 4))
        random.shuffle(password_chars)
        return ''.join(password_chars)

    def _gen_uuid(self):
        return str(uuid.uuid1())

    async def _gen_sg(self, key, value):
        if self._vpc_id is None:
            await self._gen_vpc_vsw_id(key, value)
        ecs_plugin = EcsPlugin(region_id=self.region, credential=self.credential)
        sg = await ecs_plugin.get_security_group(vpc_id=self._vpc_id)
        if not sg:
            # Current VPC has no usable security group; try other VPCs in the region.
            old_vpc_id = self._vpc_id
            old_vsw_id = self._vsw_id
            LOG.debug(f'no security group found in vpc {self._vpc_id}, trying other VPCs')
            vpc_plugin = VpcPlugin(self.region, credential=self.credential)
            response = await vpc_plugin.send_request('DescribeVpcsRequest', PageSize=50)
            vpcs = response.get('Vpcs', {}).get('Vpc', [])
            for vpc in vpcs:
                candidate_vpc_id = vpc['VpcId']
                if candidate_vpc_id == old_vpc_id:
                    continue  # already tried
                sg = await ecs_plugin.get_security_group(vpc_id=candidate_vpc_id)
                if sg:
                    LOG.debug(f'found security group {sg["SecurityGroupId"]} in vpc {candidate_vpc_id}')
                    self._vpc_id = candidate_vpc_id
                    # Also update VSwitch to one in the new VPC
                    vsw = await vpc_plugin.get_one_vswitch(vpc_id=candidate_vpc_id)
                    if vsw:
                        self._vsw_id = vsw['VSwitchId']
                    # Sync parameters dict: replace old VpcId/VSwitchId with new ones
                    LOG.debug(f'syncing VpcId/VSwitchId params: old_vpc={old_vpc_id} new_vpc={self._vpc_id}, old_vsw={old_vsw_id} new_vsw={self._vsw_id}')
                    for pname in list(self.parameters.keys()):
                        if self.RE_K_VPC_ID.fullmatch(pname) and self.parameters[pname] == old_vpc_id:
                            self.parameters[pname] = self._vpc_id
                            LOG.debug(f'updated parameter {pname}: {old_vpc_id} -> {self._vpc_id}')
                        elif self.RE_K_VSW_ID.fullmatch(pname) and self._vsw_id and old_vsw_id and self.parameters[pname] == old_vsw_id:
                            self.parameters[pname] = self._vsw_id
                            LOG.debug(f'updated parameter {pname}: {old_vsw_id} -> {self._vsw_id}')
                    break
        if not sg:
            msg = f'can not find security group in any vpc in {self.region} region'
            raise Iact3Exception(_error_message(key, value, msg))
        return sg['SecurityGroupId']
