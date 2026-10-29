from types import SimpleNamespace
from unittest import mock

from iact3.generate_params import LinkedList, ParamGenerator
from tests.common import AsyncTestCase


class TestParamGeneratorFallbacks(AsyncTestCase):
    def make_generator(self, parameters=None):
        config = SimpleNamespace(region='cn-test', parameters=parameters or {}, template_config=None,
                                 parameters_order=None, auth=SimpleNamespace(credential=object()))
        with mock.patch('iact3.generate_params.StackPlugin'):
            return ParamGenerator(config)

    async def test_template_defaults_and_properties_are_cached(self):
        generator = self.make_generator()
        calls = []
        async def template():
            calls.append(True)
            return '''Parameters:
  A: {Default: 3, AssociationProperty: ALIYUN::ECS::VPC::VPCId}
  B: {Default: null}
  C: value
'''
        generator._get_template_body = template
        self.assertEqual(await generator._get_template_defaults(), {'A': '3'})
        self.assertEqual(await generator._get_template_defaults(), {'A': '3'})
        self.assertEqual(await generator._get_association_properties(), {'A': 'ALIYUN::ECS::VPC::VPCId'})
        self.assertEqual(await generator._get_association_properties(), {'A': 'ALIYUN::ECS::VPC::VPCId'})
        self.assertEqual(len(calls), 2)

    async def test_non_mapping_template_parameters_produce_empty_cached_metadata(self):
        generator = self.make_generator()
        calls = []

        async def template():
            calls.append(True)
            return 'Parameters: [unexpected]'

        generator._get_template_body = template
        self.assertEqual(await generator._get_template_defaults(), {})
        self.assertEqual(await generator._get_association_properties(), {})
        self.assertEqual(await generator._get_template_defaults(), {})
        self.assertEqual(await generator._get_association_properties(), {})
        self.assertEqual(len(calls), 2)

    async def test_unresolved_parameters_use_defaults_then_zone_and_known_names(self):
        auto = '$[iact3-auto]'
        generator = self.make_generator({'A': auto, 'ZoneId': auto, 'InstanceChargeType': auto, 'Keep': 'value'})
        async def defaults():
            return {'A': 'template-default'}
        async def zone(key):
            return 'zone-a'
        generator._get_template_defaults = defaults
        generator._resolve_zone_id = zone
        await generator.resolve_unresolved_with_defaults()
        self.assertEqual(generator.parameters, {'A': 'template-default', 'ZoneId': 'zone-a',
                                                 'InstanceChargeType': 'PostPaid', 'Keep': 'value'})

    async def test_zone_final_fallback_uses_vswitch(self):
        generator = self.make_generator({'ZoneId': '$[iact3-auto]'})
        async def defaults():
            return {}
        async def zone(key):
            return None
        async def vswitch():
            return {'ZoneId': 'zone-from-switch'}
        generator._get_template_defaults = defaults
        generator._resolve_zone_id = zone
        plugin = mock.Mock()
        plugin.get_one_vswitch = vswitch
        with mock.patch('iact3.generate_params.VpcPlugin', return_value=plugin):
            await generator.resolve_unresolved_with_defaults()
        self.assertEqual(generator.parameters['ZoneId'], 'zone-from-switch')

    async def test_disk_query_filters_status_and_zone(self):
        generator = self.make_generator()
        calls = []
        async def send(action, **kwargs):
            calls.append((action, kwargs))
            return {'AvailableZones': {'AvailableZone': [
                {'ZoneId': 'wrong', 'AvailableResources': {'AvailableResource': [
                    {'SupportedResources': {'SupportedResource': [{'Status': 'Available', 'Value': 'wrong'}]}}]}},
                {'ZoneId': 'zone-a', 'AvailableResources': {'AvailableResource': [
                    {'SupportedResources': {'SupportedResource': [{'Status': 'Available', 'Value': 'cloud_ssd'},
                                                                   {'Status': 'SoldOut', 'Value': 'no'}]}}]}},
            ]}}
        plugin = mock.Mock()
        plugin.send_request = send
        with mock.patch('iact3.generate_params.EcsPlugin', return_value=plugin):
            self.assertEqual(await generator._query_disk_available('zone-a', 'ecs.t6.small'), ['cloud_ssd'])
        self.assertEqual(calls[0][1]['InstanceType'], 'ecs.t6.small')
        self.assertEqual(calls[0][1]['ZoneId'], 'zone-a')

    async def test_instance_type_selects_first_compatible_disk_and_cheapest_type(self):
        generator = self.make_generator({'ZoneId': 'zone-a', 'SystemDiskCategory': '$[iact3-auto]'})
        async def props():
            return {}
        calls = []
        async def types(**kwargs):
            calls.append(kwargs)
            return ['ecs.g7.large', 'ecs.t6.small'] if kwargs.get('system_disk_category') == 'cloud_ssd' else []
        generator._get_association_properties = props
        plugin = mock.Mock()
        plugin.describe_available_instance_types = types
        with mock.patch('iact3.generate_params.EcsPlugin', return_value=plugin):
            self.assertEqual(await generator._resolve_instance_type('InstanceType'), 'ecs.t6.small')
        self.assertEqual([call['system_disk_category'] for call in calls], ['cloud_essd', 'cloud_ssd'])
        self.assertEqual(await generator._resolve_system_disk_category('SystemDiskCategory'), 'cloud_ssd')
        generator._resolved_disk_category = None
        self.assertEqual(await generator._resolve_system_disk_category('SystemDiskCategory'), 'cloud_essd')


def test_linked_list_selectors_update_parameters_and_remove_nodes():
    values = {}
    linked = LinkedList()
    assert linked.is_empty()
    linked.remove('missing')
    linked.append('a', 'old', ['new'], values)
    linked.append('b', 'old', [], values)
    linked.append('c', 'old', ['last'], values)
    linked.first().refresh_parameters()
    assert values == {'a': 'new'}
    linked.remove('b')
    assert list(linked) == ['a', 'c']
    linked.remove('a')
    assert list(linked) == ['c']
    linked.remove('c')
    assert linked.is_empty()


class TestConstraintSelection(AsyncTestCase):
    def make_generator(self):
        config = SimpleNamespace(region='cn-test', parameters={}, parameters_order=None, test_name='default',
                                 template_config=SimpleNamespace(to_dict=lambda: {}),
                                 auth=SimpleNamespace(credential=object()))
        with mock.patch('iact3.generate_params.StackPlugin'):
            return ParamGenerator(config)

    async def test_constraint_timeouts_are_retried_and_not_supported_returns_none(self):
        generator = self.make_generator()
        responses = [
            [{'Behavior': 'QueryError', 'BehaviorReason': 'query timeout'}],
            [{'Behavior': 'QueryError', 'BehaviorReason': 'query timeout'}],
            [{'Behavior': 'Available', 'AllowedValues': ['one', 'two']}],
            [{'Behavior': 'NotSupport'}],
        ]
        async def constraints(**kwargs):
            return responses.pop(0)
        generator.plugin.get_parameter_constraints = constraints
        self.assertEqual(await generator._get_constraints(), ['one', 'two'])
        self.assertIsNone(await generator._get_constraints())
        async def timeout(**kwargs):
            return [{'Behavior': 'QueryError', 'BehaviorReason': 'timeout'}]
        generator.plugin.get_parameter_constraints = timeout
        self.assertEqual(await generator._get_constraints(), 'timeout')

    async def test_non_timeout_constraint_response_is_not_retried(self):
        generator = self.make_generator()
        calls = []

        async def constraints(**kwargs):
            calls.append(kwargs)
            return [{'Behavior': 'QueryError', 'BehaviorReason': 'access denied', 'AllowedValues': []}]

        generator.plugin.get_parameter_constraints = constraints
        self.assertEqual(await generator._get_constraints(parameters_key_filter=['VpcId']), [])
        self.assertEqual(len(calls), 1)

    async def test_selection_backtracks_when_later_constraint_is_empty(self):
        generator = self.make_generator()
        values = {}
        generator._linked_list.append('first', '$[iact3-auto]', parameters=values)
        generator._linked_list.append('second', '$[iact3-auto]', parameters=values)
        calls = []
        async def constraints(**kwargs):
            key = kwargs['parameters_key_filter'][0]
            calls.append((key, dict(kwargs['parameters'])))
            if key == 'first':
                return ['bad', 'good']
            return ['selected'] if kwargs['parameters'].get('first') == 'good' else []
        async def defaults():
            return {}
        generator._get_constraints = constraints
        generator._get_template_defaults = defaults
        result = await generator._select_value(generator._linked_list.first())
        self.assertEqual(result, {'first': 'good', 'second': 'selected'})
        self.assertEqual([call[0] for call in calls], ['first', 'second', 'second'])

    async def test_selection_uses_defaults_and_leaves_unsupported_values_unresolved(self):
        generator = self.make_generator()
        values = {}
        generator._linked_list.append('defaulted', 'auto', parameters=values)
        generator._linked_list.append('unsupported', 'auto', parameters=values)
        async def constraints(**kwargs):
            return [] if kwargs['parameters_key_filter'] == ['defaulted'] else None
        async def defaults():
            return {'defaulted': 'fallback'}
        generator._get_constraints = constraints
        generator._get_template_defaults = defaults
        result = await generator._select_value(generator._linked_list.first())
        self.assertEqual(result['defaulted'], 'fallback')
        self.assertEqual(generator._unresolved_parameters['unsupported'], 'auto')

    async def test_empty_zone_constraints_keep_unresolved_zone_and_continue(self):
        generator = self.make_generator()
        values = {}
        generator._linked_list.append('ZoneId', '$[iact3-auto]', parameters=values)
        generator._linked_list.append('Name', '$[iact3-auto]', parameters=values)

        async def constraints(**kwargs):
            return [] if kwargs['parameters_key_filter'] == ['ZoneId'] else ['example']

        async def defaults():
            return {}

        async def no_zone(key):
            return None

        generator._get_constraints = constraints
        generator._get_template_defaults = defaults
        generator._resolve_zone_id = no_zone
        result = await generator._select_value(generator._linked_list.first())
        self.assertEqual(result['Name'], 'example')
        self.assertEqual(generator._unresolved_parameters['ZoneId'], '$[iact3-auto]')

    async def test_unsupported_parameter_does_not_stop_following_selection(self):
        generator = self.make_generator()
        values = {}
        generator._linked_list.append('Unsupported', '$[iact3-auto]', parameters=values)
        generator._linked_list.append('Name', '$[iact3-auto]', parameters=values)

        async def constraints(**kwargs):
            return None if kwargs['parameters_key_filter'] == ['Unsupported'] else ['example']

        generator._get_constraints = constraints
        result = await generator._select_value(generator._linked_list.first())
        self.assertEqual(result['Name'], 'example')
        self.assertEqual(generator._unresolved_parameters['Unsupported'], '$[iact3-auto]')

    async def test_constraint_timeout_is_an_error(self):
        from iact3.exceptions import Iact3Exception
        generator = self.make_generator()
        generator._linked_list.append('key', 'auto', parameters={})
        async def timeout(**kwargs):
            return 'timeout'
        generator._get_constraints = timeout
        with self.assertRaises(Iact3Exception):
            await generator._select_value(generator._linked_list.first())

    async def test_selection_reports_error_after_all_parent_values_fail(self):
        from iact3.exceptions import Iact3Exception
        generator = self.make_generator()
        values = {}
        generator._linked_list.append('First', '$[iact3-auto]', parameters=values)
        generator._linked_list.append('Second', '$[iact3-auto]', parameters=values)
        attempted = []

        async def constraints(**kwargs):
            if kwargs['parameters_key_filter'] == ['First']:
                return ['one', 'two']
            attempted.append(kwargs['parameters']['First'])
            return []

        async def defaults():
            return {}

        generator._get_constraints = constraints
        generator._get_template_defaults = defaults
        with self.assertRaises(Iact3Exception) as error:
            await generator._select_value(generator._linked_list.first())
        self.assertEqual(attempted, ['one', 'two'])
        self.assertIn('Second', error.exception.message)


class TestAutomaticParameters(AsyncTestCase):
    def make_generator(self, parameters):
        config = SimpleNamespace(region='cn-test', parameters=parameters, parameters_order=list(parameters),
                                 test_name='example', template_config=None,
                                 auth=SimpleNamespace(credential=object()))
        with mock.patch('iact3.generate_params.StackPlugin'):
            return ParamGenerator(config)

    async def test_current_region_is_applied_even_without_auto_parameters(self):
        generator = self.make_generator({'Region': '$[iact3-current-region]', 'Count': 3})
        result = await generator.resolve_auto_value()
        self.assertEqual(result, {'Region': 'cn-test', 'Count': 3})
        self.assertEqual(generator.parameters, result)

    async def test_deferred_instance_parameters_remain_available_for_second_pass(self):
        generator = self.make_generator({'InstanceType': '$[iact3-auto]'})
        result = await generator.resolve_auto_value()
        self.assertEqual(result['InstanceType'], '$[iact3-auto]')
        self.assertEqual(generator._unresolved_parameters['InstanceType'], '$[iact3-auto]')

    async def test_auto_key_generates_values_after_zone_resolution(self):
        auto = '$[iact3-auto]'
        generator = self.make_generator({'ZoneId': auto, 'Name': auto, 'Password': auto, 'UUID': auto,
                                         'InstanceType': auto, 'SystemDiskCategory': auto})
        generator._unresolved_parameters = dict(generator.parameters)
        async def props():
            return {}
        async def zone(key):
            return 'zone-a'
        async def instance(key):
            self.assertEqual(generator.parameters['ZoneId'], 'zone-a')
            return 'ecs.t6.small'
        async def disk(key):
            return 'cloud_ssd'
        generator._get_association_properties = props
        generator._resolve_zone_id = zone
        generator._resolve_instance_type = instance
        generator._resolve_system_disk_category = disk
        result = await generator.resolve_auto_key()
        self.assertEqual(result['ZoneId'], 'zone-a')
        self.assertEqual(result['InstanceType'], 'ecs.t6.small')
        self.assertEqual(result['SystemDiskCategory'], 'cloud_ssd')
        self.assertTrue(result['Name'].startswith('iact3-'))
        self.assertEqual(len(result['Password']), 16)
        self.assertNotEqual(result['UUID'], auto)

    async def test_zone_sorting_and_vswitch_fallback(self):
        generator = self.make_generator({})
        plugin = mock.Mock(endpoint='ecs.example')
        async def zones():
            return ['cn-test-a', 'cn-test-x2', 'cn-test-b']
        plugin.describe_zones = zones
        with mock.patch('iact3.generate_params.EcsPlugin', return_value=plugin):
            self.assertEqual(await generator._fetch_available_zones(), ['cn-test-b', 'cn-test-a', 'cn-test-x2'])
        async def fail():
            raise ValueError('network')
        async def vswitch():
            return {'ZoneId': 'fallback-zone'}
        plugin.describe_zones = fail
        vpc = mock.Mock(endpoint='vpc.example')
        vpc.get_one_vswitch = vswitch
        with mock.patch('iact3.generate_params.EcsPlugin', return_value=plugin), \
             mock.patch('iact3.generate_params.VpcPlugin', return_value=vpc):
            self.assertEqual(await generator._fetch_available_zones(), ['fallback-zone'])

    async def test_zone_lookup_with_no_zones_and_no_switch_returns_empty(self):
        generator = self.make_generator({})
        ecs = mock.Mock(endpoint='ecs.example')
        vpc = mock.Mock(endpoint='vpc.example')

        async def zones():
            return []

        async def switch():
            return {'VSwitchId': 'id-without-zone'}

        ecs.describe_zones = zones
        vpc.get_one_vswitch = switch
        with mock.patch('iact3.generate_params.EcsPlugin', return_value=ecs), \
             mock.patch('iact3.generate_params.VpcPlugin', return_value=vpc):
            self.assertEqual(await generator._fetch_available_zones(), [])

    async def test_reuses_network_assignments_and_resolves_property_based_types(self):
        auto = '$[iact3-auto]'
        generator = self.make_generator({'VpcId': auto, 'VSwitchId': auto, 'Flavor': auto,
                                         'Disk': auto, 'ZoneId': auto, 'Count': 3})
        generator._unresolved_parameters = dict(generator.parameters)
        generator._vpc_id = 'vpc-existing'
        generator._vsw_assignments['VSwitchId'] = {'vswitch_id': 'vsw-existing'}
        calls = []

        async def properties():
            return {'Flavor': 'ALIYUN::ECS::Instance::ECSInstanceType',
                    'Disk': 'ALIYUN::ECS::Disk::SystemDiskCategory'}

        async def zone(key):
            return None

        async def instance(key):
            calls.append(key)
            return 'ecs.t6.small'

        async def disk(key):
            calls.append(key)
            return None

        generator._get_association_properties = properties
        generator._resolve_zone_id = zone
        generator._resolve_instance_type = instance
        generator._resolve_system_disk_category = disk
        result = await generator.resolve_auto_key()
        self.assertEqual(result['VpcId'], 'vpc-existing')
        self.assertEqual(result['VSwitchId'], 'vsw-existing')
        self.assertEqual(result['Flavor'], 'ecs.t6.small')
        self.assertEqual(result['Disk'], auto)
        self.assertEqual(result['ZoneId'], auto)
        self.assertEqual(result['Count'], 3)
        self.assertEqual(calls, ['Flavor', 'Disk'])

    async def test_auto_key_resolves_vpc_switch_and_security_group_in_dependency_order(self):
        auto = '$[iact3-auto]'
        generator = self.make_generator({'VSwitchId': auto, 'VpcId': auto, 'SecurityGroupId': auto})
        generator._unresolved_parameters = dict(generator.parameters)
        calls = []

        async def properties():
            return {}

        async def network(key, value):
            calls.append(('network', key))
            generator._vpc_id = 'vpc'
            generator._vsw_assignments['VSwitchId'] = {'vswitch_id': 'vsw'}
            return 'vpc', 'vsw'

        async def security_group(key, value):
            calls.append(('security_group', generator._vpc_id))
            return 'sg'

        generator._get_association_properties = properties
        generator._gen_vpc_vsw_id = network
        generator._gen_sg = security_group
        result = await generator.resolve_auto_key()
        self.assertEqual(result, {'VSwitchId': 'vsw', 'VpcId': 'vpc', 'SecurityGroupId': 'sg'})
        self.assertEqual(calls, [('network', 'VSwitchId'), ('security_group', 'vpc')])


class TestNetworkParameterResolution(AsyncTestCase):
    def make_generator(self, params):
        config = SimpleNamespace(region='cn-test', parameters=params, parameters_order=None, test_name='test',
                                 template_config=None, auth=SimpleNamespace(credential=object()))
        with mock.patch('iact3.generate_params.StackPlugin'):
            return ParamGenerator(config)

    async def test_switch_falls_back_to_other_zone_and_updates_zone(self):
        auto = '$[iact3-auto]'
        generator = self.make_generator({'ZoneId1': 'zone-a', 'VSwitchId1': auto})
        generator._zone_list_cache = ['zone-a', 'zone-b']
        calls = []
        class Vpc:
            def __init__(self, *args, **kwargs):
                pass
            async def get_one_vswitch(self, vpc_id=None, zone_id=None):
                calls.append((vpc_id, zone_id))
                if zone_id == 'zone-b':
                    return {'VpcId': 'vpc-b', 'VSwitchId': 'vsw-b', 'ZoneId': 'zone-b'}
        with mock.patch('iact3.generate_params.VpcPlugin', Vpc):
            self.assertEqual(await generator._gen_vpc_vsw_id('VSwitchId1', auto), ('vpc-b', 'vsw-b'))
        self.assertEqual(calls, [(None, 'zone-a'), (None, 'zone-b')])
        self.assertEqual(generator.parameters['ZoneId1'], 'zone-b')
        self.assertEqual(generator._vsw_assignments['VSwitchId1']['vswitch_id'], 'vsw-b')

    async def test_unresolved_zone_is_backfilled_from_discovered_vswitch(self):
        auto = '$[iact3-auto]'
        generator = self.make_generator({'ZoneId': auto, 'VSwitchId': auto})
        calls = []

        async def no_zone(key):
            return None

        class Vpc:
            def __init__(self, *args, **kwargs):
                pass
            async def get_one_vswitch(self, vpc_id=None, zone_id=None):
                calls.append((vpc_id, zone_id))
                return {'VpcId': 'vpc-a', 'VSwitchId': 'vsw-a', 'ZoneId': 'zone-a'}

        generator._resolve_zone_id = no_zone
        with mock.patch('iact3.generate_params.VpcPlugin', Vpc):
            self.assertEqual(await generator._gen_vpc_vsw_id('VSwitchId', auto), ('vpc-a', 'vsw-a'))
        self.assertEqual(calls, [(None, None)])
        self.assertEqual(generator.parameters['ZoneId'], 'zone-a')
        self.assertEqual(generator._zone_assignments['ZoneId'], 'zone-a')

    async def test_zone_fallback_skips_unavailable_candidates_then_reports_failure(self):
        from iact3.exceptions import Iact3Exception
        auto = '$[iact3-auto]'
        generator = self.make_generator({'ZoneId': 'zone-a', 'VSwitchId': auto})
        generator._zone_list_cache = None
        calls = []

        async def zones():
            return ['zone-a', 'zone-b', 'zone-c']

        class Vpc:
            def __init__(self, *args, **kwargs):
                pass
            async def get_one_vswitch(self, vpc_id=None, zone_id=None):
                calls.append(zone_id)
                if zone_id == 'zone-b':
                    raise ValueError('unavailable')
                return None

        generator._fetch_available_zones = zones
        with mock.patch('iact3.generate_params.VpcPlugin', Vpc):
            with self.assertRaises(Iact3Exception) as error:
                await generator._gen_vpc_vsw_id('VSwitchId', auto)
        self.assertIn('can not find any vswitch in zone zone-a', error.exception.message)
        self.assertEqual(calls, ['zone-a', 'zone-b', 'zone-c'])

    async def test_vpc_with_security_group_must_also_have_matching_vswitch(self):
        auto = '$[iact3-auto]'
        generator = self.make_generator({'VpcId': auto, 'VSwitchId': auto, 'ZoneId': 'zone-a',
                                         'SecurityGroupId': auto})
        class Vpc:
            def __init__(self, *args, **kwargs):
                pass
            async def get_one_vswitch(self, vpc_id=None, zone_id=None):
                if vpc_id in (None, 'vpc-old'):
                    return {'VpcId': 'vpc-old', 'VSwitchId': 'vsw-old', 'ZoneId': 'zone-a'}
                if vpc_id == 'vpc-good':
                    return {'VpcId': 'vpc-good', 'VSwitchId': 'vsw-good', 'ZoneId': 'zone-a'}
            async def send_request(self, *args, **kwargs):
                return {'Vpcs': {'Vpc': [{'VpcId': 'vpc-old'}, {'VpcId': 'vpc-no-switch'}, {'VpcId': 'vpc-good'}]}}
        class Ecs:
            def __init__(self, *args, **kwargs):
                pass
            async def get_security_group(self, vpc_id=None):
                return {'SecurityGroupId': 'sg-good'} if vpc_id != 'vpc-old' else None
        with mock.patch('iact3.generate_params.VpcPlugin', Vpc), mock.patch('iact3.generate_params.EcsPlugin', Ecs):
            self.assertEqual(await generator._gen_vpc_vsw_id('VSwitchId', auto), ('vpc-good', 'vsw-good'))
            self.assertEqual(await generator._gen_sg('SecurityGroupId', auto), 'sg-good')
        self.assertEqual(generator.parameters['VpcId'], 'vpc-good')
        self.assertEqual(generator.parameters['VSwitchId'], 'vsw-good')
        self.assertEqual(generator.parameters['ZoneId'], 'zone-a')

    async def test_missing_network_resources_produce_clear_errors(self):
        from iact3.exceptions import Iact3Exception
        generator = self.make_generator({'VSwitchId': '$[iact3-auto]'})
        class EmptyVpc:
            def __init__(self, *args, **kwargs):
                pass
            async def get_one_vpc(self):
                return None
            async def get_one_vswitch(self, **kwargs):
                return None
        with mock.patch('iact3.generate_params.VpcPlugin', EmptyVpc):
            with self.assertRaises(Iact3Exception) as error:
                await generator._gen_vpc_id('VpcId', '$[iact3-auto]')
            self.assertIn('can not find any vpc', error.exception.message)
            with self.assertRaises(Iact3Exception) as error:
                await generator._gen_vpc_vsw_id('VSwitchId', '$[iact3-auto]')
            self.assertIn('can not find any vswitch', error.exception.message)

    async def test_security_group_reselects_vpc_and_synchronizes_switches(self):
        auto = '$[iact3-auto]'
        generator = self.make_generator({'VpcId': 'vpc-old', 'VSwitchId': 'vsw-old', 'ZoneId': 'zone-a'})
        generator._vpc_id = 'vpc-old'
        class Vpc:
            def __init__(self, *args, **kwargs):
                pass
            async def send_request(self, *args, **kwargs):
                return {'Vpcs': {'Vpc': [{'VpcId': 'vpc-old'}, {'VpcId': 'vpc-new'}]}}
            async def get_one_vswitch(self, vpc_id=None, zone_id=None):
                return {'VpcId': vpc_id, 'VSwitchId': 'vsw-new', 'ZoneId': zone_id}
        class Ecs:
            def __init__(self, *args, **kwargs):
                pass
            async def get_security_group(self, vpc_id=None):
                return {'SecurityGroupId': 'sg-new'} if vpc_id == 'vpc-new' else None
        with mock.patch('iact3.generate_params.VpcPlugin', Vpc), mock.patch('iact3.generate_params.EcsPlugin', Ecs):
            self.assertEqual(await generator._gen_sg('SecurityGroupId', auto), 'sg-new')
        self.assertEqual(generator.parameters['VpcId'], 'vpc-new')
        self.assertEqual(generator.parameters['VSwitchId'], 'vsw-new')

    async def test_security_group_skips_vpcs_without_group_or_matching_switch(self):
        auto = '$[iact3-auto]'
        generator = self.make_generator({'VpcId': 'old', 'VSwitchId': 'vsw-old', 'ZoneId': 'zone-a'})
        generator._vpc_id = 'old'
        looked_up = []

        class Vpc:
            def __init__(self, *args, **kwargs):
                pass
            async def send_request(self, *args, **kwargs):
                return {'Vpcs': {'Vpc': [{'VpcId': 'old'}, {'VpcId': 'no-group'},
                                         {'VpcId': 'no-switch'}, {'VpcId': 'good'}]}}
            async def get_one_vswitch(self, vpc_id=None, zone_id=None):
                if vpc_id == 'good':
                    return {'VpcId': vpc_id, 'VSwitchId': 'vsw-good', 'ZoneId': zone_id}
                return None

        class Ecs:
            def __init__(self, *args, **kwargs):
                pass
            async def get_security_group(self, vpc_id=None):
                looked_up.append(vpc_id)
                return {'SecurityGroupId': 'sg-' + vpc_id} if vpc_id in ('no-switch', 'good') else None

        with mock.patch('iact3.generate_params.VpcPlugin', Vpc), mock.patch('iact3.generate_params.EcsPlugin', Ecs):
            self.assertEqual(await generator._gen_sg('SecurityGroupId', auto), 'sg-good')
        self.assertEqual(looked_up, ['old', 'no-group', 'no-switch', 'good'])
        self.assertEqual(generator.parameters['VpcId'], 'good')
        self.assertEqual(generator.parameters['VSwitchId'], 'vsw-good')

    async def test_security_group_resolves_network_first_when_no_vpc_is_known(self):
        auto = '$[iact3-auto]'
        generator = self.make_generator({'SecurityGroupId': auto})
        network_calls = []

        async def network(key, value):
            network_calls.append((key, value))
            generator._vpc_id = 'resolved-vpc'

        class Ecs:
            def __init__(self, *args, **kwargs):
                pass
            async def get_security_group(self, vpc_id=None):
                self_vpc.append(vpc_id)
                return {'SecurityGroupId': 'sg'}

        self_vpc = []
        generator._gen_vpc_vsw_id = network
        with mock.patch('iact3.generate_params.EcsPlugin', Ecs):
            self.assertEqual(await generator._gen_sg('SecurityGroupId', auto), 'sg')
        self.assertEqual(network_calls, [('SecurityGroupId', auto)])
        self.assertEqual(self_vpc, ['resolved-vpc'])

    async def test_auto_security_group_resolves_network_before_group(self):
        auto = '$[iact3-auto]'
        generator = self.make_generator({'SecurityGroupId': auto})
        generator._unresolved_parameters = dict(generator.parameters)

        async def properties():
            return {}

        async def network(key, value):
            return 'vpc-a', 'vsw-a'

        async def security_group(key, value):
            self.assertEqual(generator._vpc_id, 'vpc-a')
            return 'sg-a'

        generator._get_association_properties = properties
        generator._gen_vpc_vsw_id = network
        generator._gen_sg = security_group
        result = await generator.resolve_auto_key()
        self.assertEqual(result['SecurityGroupId'], 'sg-a')

    async def test_vpc_lookup_returns_discovered_identifier(self):
        generator = self.make_generator({'VpcId': '$[iact3-auto]'})
        class Vpc:
            def __init__(self, *args, **kwargs):
                pass
            async def get_one_vpc(self):
                return {'VpcId': 'vpc-a'}
        with mock.patch('iact3.generate_params.VpcPlugin', Vpc):
            self.assertEqual(await generator._gen_vpc_id('VpcId', '$[iact3-auto]'), 'vpc-a')

    async def test_security_group_reports_failure_if_no_vpc_is_usable(self):
        from iact3.exceptions import Iact3Exception
        generator = self.make_generator({'VpcId': 'vpc-old'})
        generator._vpc_id = 'vpc-old'
        class Vpc:
            def __init__(self, *args, **kwargs):
                pass
            async def send_request(self, *args, **kwargs):
                return {'Vpcs': {'Vpc': [{'VpcId': 'vpc-old'}]}}
        class Ecs:
            def __init__(self, *args, **kwargs):
                pass
            async def get_security_group(self, vpc_id=None):
                return None
        with mock.patch('iact3.generate_params.VpcPlugin', Vpc), mock.patch('iact3.generate_params.EcsPlugin', Ecs):
            with self.assertRaises(Iact3Exception) as error:
                await generator._gen_sg('SecurityGroupId', '$[iact3-auto]')
        self.assertIn('can not find security group', error.exception.message)


class TestTemplateLoading(AsyncTestCase):
    def make_generator(self, **template_fields):
        defaults = dict(template_body=None, template_id=None, template_version=None, template_url=None)
        defaults.update(template_fields)
        config = SimpleNamespace(region='cn-test', parameters={}, parameters_order=None, test_name='test',
                                 template_config=SimpleNamespace(**defaults),
                                 auth=SimpleNamespace(credential=object()))
        with mock.patch('iact3.generate_params.StackPlugin'):
            return ParamGenerator(config)

    async def test_loads_template_body_and_remote_template_id(self):
        generator = self.make_generator(template_body='body')
        self.assertEqual(await generator._get_template_body(), 'body')
        generator = self.make_generator(template_id='id', template_version='v1')
        calls = []
        async def get_template(**kwargs):
            calls.append(kwargs)
            return {'TemplateBody': 'remote body'}
        generator.plugin.get_template = get_template
        self.assertEqual(await generator._get_template_body(), 'remote body')
        self.assertEqual(calls, [{'template_id': 'id', 'template_version': 'v1'}])

    async def test_http_template_size_limit_and_request_failures(self):
        from iact3.exceptions import Iact3Exception
        generator = self.make_generator(template_url='https://example.invalid/template')
        response = mock.Mock()
        response.iter_content.return_value = [b'abc', b'def']
        with mock.patch('iact3.generate_params.requests.get', return_value=response):
            self.assertEqual(await generator._get_template_body(), b'abcdef')
            generator.template_max_size = 5
            with self.assertRaises(Iact3Exception) as error:
                await generator._get_template_body()
            self.assertIn('exceeds maximum', error.exception.message)
        with mock.patch('iact3.generate_params.requests.get', side_effect=ValueError('network')):
            with self.assertRaises(Iact3Exception) as error:
                await generator._get_template_body()
            self.assertIn('network', error.exception.message)

    async def test_oss_template_validates_size_and_reads_content(self):
        from iact3.exceptions import Iact3Exception
        generator = self.make_generator(template_url='oss://bucket/template?RegionId=cn-other')
        plugin = mock.Mock()
        plugin.get_object_meta.return_value = SimpleNamespace(content_length=4)
        plugin.get_object_content.return_value.read.return_value = b'body'
        with mock.patch('iact3.generate_params.OssPlugin', return_value=plugin) as factory:
            self.assertEqual(await generator._get_template_body(), b'body')
            self.assertEqual(factory.call_args[1]['region_id'], 'cn-other')
            plugin.get_object_meta.return_value = SimpleNamespace(content_length=generator.template_max_size + 1)
            with self.assertRaises(Iact3Exception):
                await generator._get_template_body()
            plugin.get_object_meta.return_value = None
            with self.assertRaises(Iact3Exception):
                await generator._get_template_body()

    async def test_template_parameter_order_includes_ungrouped_parameters(self):
        generator = self.make_generator(template_body='''
Metadata:
  ALIYUN::ROS::Interface:
    ParameterGroups:
      - Parameters: [Second, First]
''')
        generator.parameters = {'First': 1, 'Second': 2, 'Third': 3}
        self.assertEqual(await generator._get_parameters_order(), ['Second', 'First', 'Third'])
        generator.template_config.template_body = 'Parameters: {}'
        self.assertIsNone(await generator._get_parameters_order())


class TestGeneratorResult(AsyncTestCase):
    def config(self):
        return SimpleNamespace(region='cn-test', test_name='example',
                               parameters={'VpcId': 'old', 'VSwitchId': 'old'}, parameters_order=[],
                               template_config=None, auth=SimpleNamespace(credential=object()))

    async def test_result_synchronizes_network_ids_after_resolution(self):
        async def resolve_value(self):
            return self.parameters
        async def resolve_key(self):
            self._vpc_id = 'vpc-new'
            self._vsw_assignments = {'VSwitchId': {'vswitch_id': 'vsw-new'}}
        async def fallback(self):
            self.parameters['fallback'] = 'resolved'
        with mock.patch('iact3.generate_params.StackPlugin'), \
             mock.patch.object(ParamGenerator, 'resolve_auto_value', resolve_value), \
             mock.patch.object(ParamGenerator, 'resolve_auto_key', resolve_key), \
             mock.patch.object(ParamGenerator, 'resolve_unresolved_with_defaults', fallback):
            result = await ParamGenerator.result(self.config())
        self.assertEqual(result.parameters, {'VpcId': 'vpc-new', 'VSwitchId': 'vsw-new', 'fallback': 'resolved'})
        self.assertIsNone(result.error)

    async def test_partial_error_keeps_fallback_results(self):
        async def resolve_value(self):
            return self.parameters
        async def resolve_key(self):
            raise ValueError('missing switch')
        async def fallback(self):
            self.parameters['fallback'] = 'resolved'
        with mock.patch('iact3.generate_params.StackPlugin'), \
             mock.patch.object(ParamGenerator, 'resolve_auto_value', resolve_value), \
             mock.patch.object(ParamGenerator, 'resolve_auto_key', resolve_key), \
             mock.patch.object(ParamGenerator, 'resolve_unresolved_with_defaults', fallback):
            result = await ParamGenerator.result(self.config())
        self.assertEqual(str(result.error), 'missing switch')
        self.assertEqual(result.parameters['fallback'], 'resolved')

    async def test_initial_resolution_error_is_returned(self):
        async def fail(self):
            raise ValueError('constraint error')
        with mock.patch('iact3.generate_params.StackPlugin'), \
             mock.patch.object(ParamGenerator, 'resolve_auto_value', fail):
            result = await ParamGenerator.result(self.config())
        self.assertEqual(str(result.error), 'constraint error')
        self.assertEqual(result.region, 'cn-test')


class TestAdditionalParameterBranches(AsyncTestCase):
    make_generator = TestConstraintSelection.make_generator
    async def test_selection_uses_zone_fallback_for_unsupported_and_empty_constraints(self):
        for values in (None, []):
            generator = self.make_generator()
            parameters = {}
            generator._linked_list.append('ZoneId', '$[iact3-auto]', parameters=parameters)
            async def constraints(**kwargs):
                return values
            async def defaults():
                return {}
            async def zone(key):
                return 'zone-a'
            generator._get_constraints = constraints
            generator._get_template_defaults = defaults
            generator._resolve_zone_id = zone
            result = await generator._select_value(generator._linked_list.first())
            self.assertEqual(result['ZoneId'], 'zone-a')

    async def test_selection_raises_when_all_prior_choices_are_exhausted(self):
        from iact3.exceptions import Iact3Exception
        generator = self.make_generator()
        parameters = {}
        generator._linked_list.append('first', 'auto', parameters=parameters)
        generator._linked_list.append('second', 'auto', parameters=parameters)
        async def constraints(**kwargs):
            return ['only'] if kwargs['parameters_key_filter'][0] == 'first' else []
        async def defaults():
            return {}
        generator._get_constraints = constraints
        generator._get_template_defaults = defaults
        with self.assertRaises(Iact3Exception) as error:
            await generator._select_value(generator._linked_list.first())
        self.assertIn('second', error.exception.message)

    async def test_database_class_constraints_choose_cheapest(self):
        generator = self.make_generator()
        generator._linked_list.append('DBInstanceClass', 'auto', parameters={})
        async def constraints(**kwargs):
            return ['mysql.x8.large.1c', 'mysql.n1.micro.1c']
        generator._get_constraints = constraints
        result = await generator._select_value(generator._linked_list.first())
        self.assertEqual(result['DBInstanceClass'], 'mysql.n1.micro.1c')


class TestInstanceFallbacks(AsyncTestCase):
    make_generator = TestParamGeneratorFallbacks.make_generator

    async def test_instance_resolution_returns_none_when_no_types_are_available(self):
        generator = self.make_generator({'ZoneId': 'zone-a'})
        calls = []

        async def properties():
            return {}

        async def types(**kwargs):
            calls.append(kwargs)
            return []

        generator._get_association_properties = properties
        plugin = mock.Mock()
        plugin.describe_available_instance_types = types
        with mock.patch('iact3.generate_params.EcsPlugin', return_value=plugin):
            self.assertIsNone(await generator._resolve_instance_type('InstanceType'))
        self.assertEqual(calls, [{'zone_id': 'zone-a', 'instance_charge_type': 'PostPaid'}])

    async def test_unfiltered_instance_query_after_disk_categories_are_exhausted(self):
        generator = self.make_generator({'ZoneId': 'zone-a', 'SystemDiskCategory': '$[iact3-auto]'})
        async def props():
            return {}
        calls = []
        async def types(**kwargs):
            calls.append(kwargs)
            return [] if 'system_disk_category' in kwargs else ['ecs.g7.large', 'ecs.t6.small']
        generator._get_association_properties = props
        plugin = mock.Mock()
        plugin.describe_available_instance_types = types
        with mock.patch('iact3.generate_params.EcsPlugin', return_value=plugin):
            self.assertEqual(await generator._resolve_instance_type('InstanceType'), 'ecs.t6.small')
        self.assertEqual(len(calls), len(generator.SAFE_DISK_CATEGORIES) + 1)
        self.assertNotIn('system_disk_category', calls[-1])
        self.assertIsNone(generator._resolved_disk_category)

    async def test_disk_association_property_enables_compatible_instance_search(self):
        generator = self.make_generator({'CustomDisk': '$[iact3-auto]', 'ZoneId': '$[iact3-auto]'})
        calls = []

        async def properties():
            return {'CustomDisk': 'ALIYUN::ECS::Disk::SystemDiskCategory'}

        async def types(**kwargs):
            calls.append(kwargs)
            return ['ecs.t6.small']

        generator._get_association_properties = properties
        plugin = mock.Mock()
        plugin.describe_available_instance_types = types
        with mock.patch('iact3.generate_params.EcsPlugin', return_value=plugin):
            self.assertEqual(await generator._resolve_instance_type('InstanceType'), 'ecs.t6.small')
        self.assertIsNone(calls[0]['zone_id'])
        self.assertEqual(calls[0]['system_disk_category'], generator.SAFE_DISK_CATEGORIES[0])
        self.assertEqual(generator._resolved_disk_category, generator.SAFE_DISK_CATEGORIES[0])

    async def test_instance_resolution_returns_none_on_api_failure(self):
        generator = self.make_generator({'ZoneId': 'zone-a'})
        async def props():
            return {}
        generator._get_association_properties = props
        with mock.patch('iact3.generate_params.EcsPlugin', side_effect=ValueError('unavailable')):
            self.assertIsNone(await generator._resolve_instance_type('InstanceType'))


class TestParameterResolutionEdgeCases(AsyncTestCase):
    make_generator = TestConstraintSelection.make_generator

    async def test_invalid_or_missing_template_is_cached_as_empty(self):
        for body in ('', 'Parameters: ['):
            generator = self.make_generator()
            calls = []
            async def template():
                calls.append(True)
                return body
            generator._get_template_body = template
            self.assertEqual(await generator._get_template_defaults(), {})
            self.assertEqual(await generator._get_template_defaults(), {})
            self.assertEqual(await generator._get_association_properties(), {})
            self.assertEqual(await generator._get_association_properties(), {})
            self.assertEqual(len(calls), 2)

    async def test_template_parameter_metadata_ignores_non_mapping_definitions(self):
        generator = self.make_generator()

        async def template():
            return '''Parameters:
  Text: {Default: existing, AssociationProperty: ALIYUN::ECS::VPC::VPCId}
  Number: {Default: 12}
  Empty: {Default: null}
  Invalid: plain
'''

        generator._get_template_body = template
        self.assertEqual(await generator._get_template_defaults(), {'Text': 'existing', 'Number': '12'})
        self.assertEqual(await generator._get_association_properties(), {'Text': 'ALIYUN::ECS::VPC::VPCId'})

    async def test_zone_fallback_propagates_to_next_constraint(self):
        for values in (None, []):
            generator = self.make_generator()
            params = {}
            generator._linked_list.append('ZoneId', '$[iact3-auto]', parameters=params)
            generator._linked_list.append('Second', '$[iact3-auto]', parameters=params)
            async def constraints(**kwargs):
                if kwargs['parameters_key_filter'] == ['ZoneId']:
                    return values
                self.assertEqual(kwargs['parameters']['ZoneId'], 'zone-a')
                return ['chosen']
            async def defaults():
                return {}
            async def zone(key):
                return 'zone-a'
            generator._get_constraints = constraints
            generator._get_template_defaults = defaults
            generator._resolve_zone_id = zone
            result = await generator._select_value(generator._linked_list.first())
            self.assertEqual(result, {'ZoneId': 'zone-a', 'Second': 'chosen'})

    async def test_failed_final_zone_lookup_keeps_placeholder(self):
        generator = self.make_generator()
        generator.parameters = {'ZoneId': '$[iact3-auto]'}
        async def defaults():
            return {}
        async def zone(key):
            return None
        generator._get_template_defaults = defaults
        generator._resolve_zone_id = zone
        with mock.patch('iact3.generate_params.VpcPlugin', side_effect=ValueError('not available')):
            await generator.resolve_unresolved_with_defaults()
        self.assertEqual(generator.parameters['ZoneId'], '$[iact3-auto]')


class TestTemplateLoadingFailures(AsyncTestCase):
    make_generator = TestTemplateLoading.make_generator

    async def test_template_id_and_file_failures_are_reported(self):
        from iact3.exceptions import Iact3Exception
        generator = self.make_generator(template_id='template-id')
        async def fail(**kwargs):
            raise ValueError('service unavailable')
        generator.plugin.get_template = fail
        with self.assertRaises(Iact3Exception) as error:
            await generator._get_template_body()
        self.assertIn('service unavailable', error.exception.message)
        generator = self.make_generator(template_url='file:///missing-template')
        with mock.patch('iact3.generate_params.urlopen', side_effect=OSError('file missing')):
            with self.assertRaises(Iact3Exception) as error:
                await generator._get_template_body()
        self.assertIn('file missing', error.exception.message)
        with mock.patch('iact3.generate_params.urlopen') as opened:
            opened.return_value.read.return_value = b'template'
            self.assertEqual(await generator._get_template_body(), b'template')

    async def test_oss_template_rejects_invalid_location_and_read_failures(self):
        from iact3.exceptions import Iact3Exception
        generator = self.make_generator(template_url='oss://bucket/template')
        plugin = mock.Mock()
        with mock.patch('iact3.generate_params.OssPlugin', return_value=plugin):
            plugin.get_object_meta.side_effect = ValueError('metadata denied')
            with self.assertRaises(Iact3Exception) as error:
                await generator._get_template_body()
            self.assertIn('metadata denied', error.exception.message)
            plugin.get_object_meta.side_effect = None
            plugin.get_object_meta.return_value = SimpleNamespace(content_length=1)
            plugin.get_object_content.side_effect = ValueError('read denied')
            with self.assertRaises(Iact3Exception) as error:
                await generator._get_template_body()
            self.assertIn('read denied', error.exception.message)
            plugin.get_object_content.side_effect = None
            plugin.get_object_content.return_value = None
            with self.assertRaises(Iact3Exception):
                await generator._get_template_body()
        generator.template_config.template_url = 'oss://bucket/'
        with self.assertRaises(Iact3Exception):
            await generator._get_template_body()


class TestConstraintFallbackContinuation(AsyncTestCase):
    make_generator = TestConstraintSelection.make_generator

    async def test_empty_first_constraint_continues_with_other_parameters(self):
        generator = self.make_generator()
        generator._linked_list.append('First', '$[iact3-auto]', parameters={})
        generator._linked_list.append('Second', '$[iact3-auto]', parameters={})
        async def constraints(**kwargs):
            return [] if kwargs['parameters_key_filter'] == ['First'] else ['resolved']
        async def defaults():
            return {}
        generator._get_constraints = constraints
        generator._get_template_defaults = defaults
        result = await generator._select_value(generator._linked_list.first())
        self.assertEqual(result['Second'], 'resolved')
        self.assertEqual(generator._unresolved_parameters['First'], '$[iact3-auto]')
        self.assertEqual(list(generator._linked_list), ['Second'])

    async def test_missing_zone_fallback_stays_unresolved_when_constraints_unsupported(self):
        generator = self.make_generator()
        generator._linked_list.append('ZoneId', '$[iact3-auto]', parameters={})
        async def constraints(**kwargs):
            return None
        async def zone(key):
            return None
        generator._get_constraints = constraints
        generator._resolve_zone_id = zone
        result = await generator._select_value(generator._linked_list.first())
        self.assertNotIn('ZoneId', result)
        self.assertEqual(generator._unresolved_parameters['ZoneId'], '$[iact3-auto]')
        self.assertTrue(generator._linked_list.is_empty())

    async def test_single_zone_and_default_fallbacks_return_resolved_values(self):
        for values, key, expected in [(None, 'ZoneId', 'zone-a'), ([], 'ZoneId', 'zone-a'),
                                      ([], 'Other', 'template-default')]:
            generator = self.make_generator()
            generator._linked_list.append(key, '$[iact3-auto]', parameters={})

            async def constraints(**kwargs):
                return values

            async def zone(name):
                return 'zone-a'

            async def defaults():
                return {'Other': 'template-default'}

            generator._get_constraints = constraints
            generator._resolve_zone_id = zone
            generator._get_template_defaults = defaults
            result = await generator._select_value(generator._linked_list.first())
            self.assertEqual(result[key], expected)

    async def test_template_order_ignores_empty_groups_and_non_string_members(self):
        generator = TestTemplateLoading.make_generator(self, template_body='''
Metadata:
  ALIYUN::ROS::Interface:
    ParameterGroups:
      - null
      - Parameters: [First, 123, Second]
''')
        generator.parameters = {'First': 1, 'Second': 2, 'Third': 3}
        self.assertEqual(await generator._get_parameters_order(), ['First', 'Second', 'Third'])
        generator.template_config.template_body = ''
        from iact3.exceptions import Iact3Exception
        with self.assertRaises(Iact3Exception):
            await generator._get_parameters_order()


class TestNetworkResolutionEdgeCases(AsyncTestCase):
    make_generator = TestParamGeneratorFallbacks.make_generator

    async def test_switch_assignments_use_existing_zone_or_accept_provider_zone(self):
        generator = self.make_generator({'ZoneId1': '$[iact3-auto]', 'ZoneId2': 'zone-b',
                                         'VSwitchId1': '$[iact3-auto]', 'VSwitchId2': '$[iact3-auto]'})
        generator._zone_assignments['ZoneId1'] = 'zone-a'
        calls = []

        class Vpc:
            async def get_one_vswitch(self, vpc_id=None, zone_id=None):
                calls.append((vpc_id, zone_id))
                return {'VSwitchId': 'vsw-' + zone_id}

        assignments = await generator._vswitch_assignments_for_vpc('vpc-new', Vpc())
        self.assertEqual(calls, [('vpc-new', 'zone-a'), ('vpc-new', 'zone-b')])
        generator._apply_vswitch_assignments('vpc-new', assignments)
        self.assertEqual(generator.parameters['VSwitchId1'], 'vsw-zone-a')
        self.assertEqual(generator.parameters['VSwitchId2'], 'vsw-zone-b')
        self.assertEqual(generator.parameters['ZoneId1'], 'zone-a')
        self.assertEqual(generator._vsw_id, 'vsw-zone-a')

    async def test_switch_without_resolved_zone_uses_provider_zone(self):
        generator = self.make_generator({'ZoneId': '$[iact3-auto]', 'VSwitchId': '$[iact3-auto]'})
        class Vpc:
            async def get_one_vswitch(self, vpc_id=None, zone_id=None):
                self.zone_id = zone_id
                return {'VSwitchId': 'vsw', 'ZoneId': 'zone-from-provider'}
        plugin = Vpc()
        assignments = await generator._vswitch_assignments_for_vpc('vpc', plugin)
        self.assertIsNone(plugin.zone_id)
        generator._apply_vswitch_assignments('vpc', assignments)
        self.assertEqual(generator.parameters['ZoneId'], 'zone-from-provider')

    async def test_zone_mapping_handles_missing_or_unequal_counts(self):
        generator = self.make_generator({'ZoneId1': 'zone-a', 'ZoneId2': 'zone-b',
                                         'VSwitchId1': 'one', 'VSwitchId2': 'two', 'VSwitchId3': 'three'})
        self.assertEqual(generator._zone_key_for_vswitch('VSwitchId2'), 'ZoneId2')
        self.assertIsNone(generator._zone_key_for_vswitch('VSwitchId3'))
        generator.parameters = {'ZoneId': 'only', 'VSwitchId1': 'one', 'VSwitchId2': 'two'}
        self.assertEqual(generator._zone_key_for_vswitch('VSwitchId2'), 'ZoneId')
        generator.parameters = {'VSwitchId': 'one'}
        self.assertIsNone(generator._zone_key_for_vswitch('VSwitchId'))

    async def test_alternative_zones_skip_used_and_continue_after_query_error(self):
        generator = self.make_generator({'ZoneId1': 'zone-a', 'VSwitchId1': '$[iact3-auto]',
                                         'ZoneId2': 'zone-used', 'VSwitchId2': 'existing'})
        generator._zone_list_cache = ['zone-a', 'zone-used', 'zone-error', 'zone-b']
        generator._zone_assignments = {'ZoneId2': 'zone-used'}
        calls = []
        class Vpc:
            def __init__(self, *args, **kwargs):
                pass
            async def get_one_vswitch(self, vpc_id=None, zone_id=None):
                calls.append(zone_id)
                if zone_id == 'zone-error':
                    raise ValueError('zone unavailable')
                if zone_id == 'zone-b':
                    return {'VpcId': 'vpc', 'VSwitchId': 'vsw', 'ZoneId': 'zone-b'}
                return None
        with mock.patch('iact3.generate_params.VpcPlugin', Vpc):
            self.assertEqual(await generator._gen_vpc_vsw_id('VSwitchId1', '$[iact3-auto]'), ('vpc', 'vsw'))
        self.assertEqual(calls, ['zone-a', 'zone-error', 'zone-b'])
        self.assertEqual(generator.parameters['ZoneId1'], 'zone-b')
        self.assertEqual(generator.parameters['ZoneId2'], 'zone-used')

    async def test_rejects_vswitch_from_another_vpc(self):
        from iact3.exceptions import Iact3Exception
        generator = self.make_generator({'VpcId': 'expected', 'VSwitchId': '$[iact3-auto]'})
        generator._vpc_id = 'expected'
        class Vpc:
            def __init__(self, *args, **kwargs):
                pass
            async def get_one_vswitch(self, **kwargs):
                return {'VpcId': 'other', 'VSwitchId': 'vsw'}
        with mock.patch('iact3.generate_params.VpcPlugin', Vpc):
            with self.assertRaises(Iact3Exception) as error:
                await generator._gen_vpc_vsw_id('VSwitchId', '$[iact3-auto]')
        self.assertIn('does not belong to vpc', error.exception.message)


class TestZoneResolutionEdgeCases(AsyncTestCase):
    make_generator = TestParamGeneratorFallbacks.make_generator

    async def test_zone_assignments_are_cached_exclusive_then_reused(self):
        generator = self.make_generator({'ZoneId1': 'zone-a', 'ZoneId2': '$[iact3-auto]',
                                         'ZoneId3': '$[iact3-auto]'})
        calls = []
        async def zones():
            calls.append(True)
            return ['zone-a', 'zone-b']
        generator._fetch_available_zones = zones
        self.assertEqual(await generator._resolve_zone_id('ZoneId2'), 'zone-b')
        self.assertEqual(await generator._resolve_zone_id('ZoneId2'), 'zone-b')
        self.assertEqual(await generator._resolve_zone_id('ZoneId3'), 'zone-a')
        self.assertEqual(len(calls), 1)

    async def test_zone_and_disk_queries_return_empty_when_providers_fail(self):
        generator = self.make_generator()
        with mock.patch('iact3.generate_params.EcsPlugin', side_effect=ValueError('ecs unavailable')), \
             mock.patch('iact3.generate_params.VpcPlugin', side_effect=ValueError('vpc unavailable')):
            self.assertEqual(await generator._fetch_available_zones(), [])
            self.assertEqual(await generator._query_disk_available(None, None), [])
            self.assertIsNone(await generator._resolve_zone_id('ZoneId'))
        self.assertEqual(generator._safe_endpoint('ecs'), 'ecs.cn-test.aliyuncs.com')

    async def test_zone_fallback_handles_existing_provider_query_failures(self):
        generator = self.make_generator()
        ecs = mock.Mock(endpoint='ecs.example')
        vpc = mock.Mock(endpoint='vpc.example')

        async def fail():
            raise RuntimeError('request failed')

        ecs.describe_zones = fail
        vpc.get_one_vswitch = fail
        with mock.patch('iact3.generate_params.EcsPlugin', return_value=ecs), \
             mock.patch('iact3.generate_params.VpcPlugin', return_value=vpc):
            self.assertEqual(await generator._fetch_available_zones(), [])
