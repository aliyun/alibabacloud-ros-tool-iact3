import yaml
from unittest import mock

from iact3.config import TestConfig, TemplateConfig
from iact3.generate_params import ParamGenerator
from tests.common import BaseTest


class TestParamGen(BaseTest):
    async def test_multi_zone_vswitches_keep_their_zone_pairing(self):
        auto = '$[iact3-auto]'
        config = TestConfig.from_dict(
            {
                'parameters': {
                    'ZoneId1': auto,
                    'ZoneId2': auto,
                    'VSwitchId1': auto,
                    'VSwitchId2': auto,
                },
            }
        )
        config.region = self.REGION_ID
        config.test_name = 'default'
        generator = ParamGenerator(config)
        generator._unresolved_parameters = dict(config.parameters)
        generator._zone_list_cache = ['zone-a', 'zone-b']

        class MultiZoneVpcPlugin:
            def __init__(self, _region, credential=None):
                pass

            async def get_one_vswitch(self, vpc_id=None, zone_id=None):
                by_zone = {
                    'zone-a': {
                        'VpcId': 'vpc-shared',
                        'VSwitchId': 'vsw-a',
                        'ZoneId': 'zone-a',
                    },
                    'zone-b': {
                        'VpcId': 'vpc-shared',
                        'VSwitchId': 'vsw-b',
                        'ZoneId': 'zone-b',
                    },
                }
                result = by_zone.get(zone_id)
                if result and (vpc_id is None or result['VpcId'] == vpc_id):
                    return result
                return None

        with mock.patch('iact3.generate_params.VpcPlugin', MultiZoneVpcPlugin):
            await generator.resolve_auto_key()

        self.assertEqual('zone-a', generator.parameters['ZoneId1'])
        self.assertEqual('vsw-a', generator.parameters['VSwitchId1'])
        self.assertEqual('zone-b', generator.parameters['ZoneId2'])
        self.assertEqual('vsw-b', generator.parameters['VSwitchId2'])
        self.assertEqual('vpc-shared', generator._vpc_id)

    async def test_candidate_vpc_must_cover_every_vswitch_zone(self):
        auto = '$[iact3-auto]'
        config = TestConfig.from_dict(
            {
                'parameters': {
                    'ZoneId1': 'zone-a',
                    'ZoneId2': 'zone-b',
                    'VSwitchId1': auto,
                    'VSwitchId2': auto,
                },
            }
        )
        generator = ParamGenerator(config)
        generator._vsw_assignments = {
            'VSwitchId1': {'vswitch_id': 'vsw-old-a', 'zone_id': 'zone-a'},
        }

        class CandidateVpcPlugin:
            async def get_one_vswitch(self, vpc_id=None, zone_id=None):
                available = {
                    ('vpc-partial', 'zone-a'): {
                        'VpcId': 'vpc-partial',
                        'VSwitchId': 'vsw-partial-a',
                        'ZoneId': 'zone-a',
                    },
                    ('vpc-complete', 'zone-a'): {
                        'VpcId': 'vpc-complete',
                        'VSwitchId': 'vsw-complete-a',
                        'ZoneId': 'zone-a',
                    },
                    ('vpc-complete', 'zone-b'): {
                        'VpcId': 'vpc-complete',
                        'VSwitchId': 'vsw-complete-b',
                        'ZoneId': 'zone-b',
                    },
                }
                return available.get((vpc_id, zone_id))

        plugin = CandidateVpcPlugin()
        self.assertIsNone(
            await generator._vswitch_assignments_for_vpc('vpc-partial', plugin)
        )
        assignments = await generator._vswitch_assignments_for_vpc(
            'vpc-complete',
            plugin,
        )
        self.assertEqual(
            {'VSwitchId1', 'VSwitchId2'},
            set(assignments),
        )
        self.assertEqual('vsw-complete-b', assignments['VSwitchId2']['vswitch_id'])

    async def test_auto_zone_avoids_an_explicit_zone(self):
        auto = '$[iact3-auto]'
        config = TestConfig.from_dict(
            {
                'parameters': {
                    'ZoneId1': 'zone-a',
                    'ZoneId2': auto,
                },
            }
        )
        generator = ParamGenerator(config)
        generator._zone_list_cache = ['zone-a', 'zone-b']

        resolved = await generator._resolve_zone_id('ZoneId2')

        self.assertEqual('zone-b', resolved)

    async def test_get_template_with_url(self):
        test_url = [
            'oss://iactvt-beijing/local_file_test/ecs_instance.template.json?RegionId=cn-beijing',
            'https://iactvt-beijing.oss-cn-beijing.aliyuncs.com/ecs_instance.template.json',
            f'file://{self.DATA_PATH}/ecs_instance.template.json',
        ]
        for u in test_url:
            test_config = TestConfig.from_dict({'template_config': {'template_url': u}})
            pg = ParamGenerator(test_config)
            result = await pg._get_template_body()
            template_body = yaml.safe_load(result)
            self._pprint_json(template_body)

    async def test_get_template_with_id(self):
        template_id = 'fe78dcd0-e5e2-4a9c-9b31-ca1e00e0f982'
        config = TestConfig.from_dict({'template_config': {'template_id': template_id, 'template_version': 'v1'}})
        pg = ParamGenerator(config)
        result = await pg._get_template_body()
        template_body = yaml.safe_load(result)
        self._pprint_json(template_body)

    async def test_get_parameters_order(self):
        config = TestConfig.from_dict(
            {'template_config': {'template_url': f'file://{self.DATA_PATH}/ecs_instance.template.json'}}
        )
        pg = ParamGenerator(config)
        template_order = await pg._get_parameters_order()
        self._pprint_json(template_order)

    async def test_generate_parameters(self):
        auto = '$[iact3-auto]'
        tpl_config = TemplateConfig.from_dict({'template_url': f'file://{self.DATA_PATH}/ecs_instance.template.json'})
        tpl_args = tpl_config.generate_template_args()
        config = TestConfig.from_dict(
            {
                'template_config': tpl_args,
                'parameters': {
                    'ZoneId': auto,
                    'InstanceType': auto,
                    'SystemDiskCategory': auto,
                    'DataDiskCategory': auto,
                    'VpcId': auto,
                    'VswitchId': auto,
                    'CommonName': auto,
                    'Password': auto,
                    'NetworkType': 'vpc',
                    'InstanceChargeType': 'Postpaid',
                    'AllocatePublicIP': False,
                    'SecurityGroupId': auto,
                },
            }
        )
        config.region = self.REGION_ID
        config.test_name = 'default'
        resolved_parameters = await ParamGenerator.result(config)
        self._pprint_json(resolved_parameters.parameters)

    async def test_generate_parameters_time_out(self):
        auto = '$[iact3-auto]'
        tpl_config = TemplateConfig.from_dict({'template_url': f'file://{self.DATA_PATH}/timeout_template.yml'})
        tpl_args = tpl_config.generate_template_args()
        config = TestConfig.from_dict(
            {
                'template_config': tpl_args,
                'parameters': {'ZoneId': 'cn-hddddd', 'DBInstanceClass': auto, 'DBPassword': auto},
            }
        )
        config.region = self.REGION_ID
        config.test_name = 'default'
        resolved_parameters = await ParamGenerator.result(config)
        self._pprint_json(resolved_parameters.parameters)

    async def test_generate_parameters_for_error_log(self):
        auto = '$[iact3-auto]'
        tpl_config = TemplateConfig.from_dict({'template_url': f'file://{self.DATA_PATH}/ecs_instance.template.json'})
        tpl_args = tpl_config.generate_template_args()
        config = TestConfig.from_dict(
            {
                'template_config': tpl_args,
                'parameters': {
                    'ZoneId': auto,
                    'InstanceType': auto,
                    'SystemDiskCategory': 'cloud_ssd',
                    'DataDiskCategory': 'cloud_ssd',
                    'CommonName': auto,
                    'Password': auto,
                    'NetworkType': 'vpc',
                    'InstanceChargeType': 'Postpaid',
                    'AllocatePublicIP': False,
                    'ImageId': 'm-not-exist',
                },
            }
        )
        config.region = self.REGION_ID
        config.test_name = 'default'
        resolved_parameters = await ParamGenerator.result(config)
        self._pprint_json(resolved_parameters.parameters)
