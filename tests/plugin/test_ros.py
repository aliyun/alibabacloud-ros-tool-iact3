import asyncio
import json

from iact3.plugin.ros import StackPlugin
from tests.common import BaseTest


class TestRosPlugin(BaseTest):

    def setUp(self) -> None:
        super(TestRosPlugin, self).setUp()
        self.plugin = StackPlugin(region_id=self.REGION_ID)

    async def test_create_stack(self):
        tpl = {
            'ROSTemplateFormatVersion': '2015-09-01',
            'Parameters': {
                'A': {'Type': 'String'},
                'B': {'Type': 'Number'}
            }
        }
        params = {
            'A': 'a',
            'B': 1
        }
        stack_id = await self.plugin.create_stack(
            stack_name='ros-test', template_body=json.dumps(tpl), parameters=params)
        print(stack_id)

    async def test_get_stack(self):
        ret = await self.plugin.get_stack(stack_id='0a37cb51-800c-4b64-98a7-4e352a5b30d2')
        self._pprint_json(ret)

    async def test_delete_stack(self):
        await self.plugin.delete_stack(stack_id='e6edc4ff-c228-4f37-a622-004ef45fba34')

    async def test_list_stacks(self):
        ret = await self.plugin.list_stacks()
        self._pprint_json(ret)

    async def test_fetch_all(self):
        regions = ['cn-beijing', 'cn-hangzhou']
        tags = {}
        tasks = []
        for region in regions:
            plugin = StackPlugin(region_id=region)
            tasks.append(
                asyncio.create_task(plugin.fetch_all_stacks(tags))
            )
        result = await asyncio.gather(*tasks)
        print(result)

    async def test_list_and_delete_stacks(self):
        regions = ['cn-beijing', 'cn-hangzhou']
        tags = {'CreateBy': 'iact3'}
        tasks = []
        for region in regions:
            plugin = StackPlugin(region_id=region)
            stacks = await plugin.fetch_all_stacks(tags)
            tasks = [asyncio.create_task(plugin.delete_stack(stack.get('StackId'))) for stack in stacks]
        result = await asyncio.gather(*tasks)
        print(result)

    async def test_get_regions(self):
        result = await self.plugin.get_regions()
        print(result)

    async def test_get_parameters_constraints(self):
        tpl = {
            'Parameters': {
                'ZoneId': {'Type': 'String'},
                'InstanceType': {'Type': 'String'}
            },
            'ROSTemplateFormatVersion': '2015-09-01',
            'Resources': {
                'ECS': {
                    'Properties': {
                        'ZoneId': {'Ref': 'ZoneId'},
                        'InstanceType': {'Ref': 'InstanceType'},
                        'ImageId': 'CentOs_7'
                    },
                    'Type': 'ALIYUN::ECS::Instance'
                }
            }
        }
        tpl_path = self.DATA_PATH / 'ecs_instance.template.json'
        with open(tpl_path, 'r', encoding='utf-8') as file_handle:
            tpl = json.load(file_handle)
        params1 = {
            'NetworkType': 'vpc',
            'InstanceChargeType': 'PostPaid',
            'ZoneId': 'cn-shanghai-h'
        }
        result1 = await self.plugin.get_parameter_constraints(
            template_body=json.dumps(tpl), parameters_key_filter=['InstanceType'], parameters=params1
        )
        self._pprint_json(result1)
        params2 = {
            'NetworkType': 'vpc',
            'InstanceChargeType': 'PostPaid',
            'ZoneId': 'cn-shanghai-l'
        }
        result2 = await self.plugin.get_parameter_constraints(
            template_body=json.dumps(tpl), parameters_key_filter=['InstanceType'], parameters=params2
        )
        self._pprint_json(result2)

    async def test_get_template(self):
        result = await self.plugin.get_template(template_id='fe08e732-0b38-454c-9314-8aa9735cf6bc')
        self._pprint_json(result)

    async def test_get_template_estimate_cost(self):
        tpl = {
            'Parameters': {
                'ZoneId': {'Type': 'String'},
                'InstanceType': {'Type': 'String'}
            },
            'ROSTemplateFormatVersion': '2015-09-01',
            'Resources': {
                'ECS': {
                    'Properties': {
                        'ZoneId': {'Ref': 'ZoneId'},
                        'InstanceType': {'Ref': 'InstanceType'},
                        'ImageId': 'CentOs_7'
                    },
                    'Type': 'ALIYUN::ECS::Instance'
                }
            }
        }
        params = {
            'InstanceType': 'ecs.g6e.large',
            'ZoneId': 'cn-hangzhou-h'
        }
        region_id = 'cn-hangzhou'
        result = await self.plugin.get_template_estimate_cost(
             template_body=json.dumps(tpl), parameters=params, region_id=region_id)
        self._pprint_json(result)

    async def test_validate_template(self):
        tpl = {
            'ROSTemplateFormatVersion': '2015-09-01',
            'Parameters': {
                'A': {'Type': 'String'},
                'B': {'Type': 'Number'}
            }
        }

        result = await self.plugin.validate_template(template_body=json.dumps(tpl))
        self._pprint_json(result)

    async def test_preview_stack(self):
        tpl = {
            "ROSTemplateFormatVersion": "2015-09-01",
            "Resources": {
                "ElasticIp": {
                    "Type": "ALIYUN::VPC::EIP",
                    "Properties": {
                        "InstanceChargeType": "Postpaid",
                        "Name": "TestEIP",
                        "InternetChargeType": "PayByBandwidth",
                        "Netmode": "public",
                        "Bandwidth": 5
                    }
                }
            }
        }
        params = {}
        region_id = 'cn-shanghai'
        result = await self.plugin.preview_stack(
            stack_name='ros-test-preview', template_body=json.dumps(tpl), parameters=params, region_id=region_id)
        self._pprint_json(result)

    async def test_generate_template_policy(self):
        tpl = {
            'Parameters': {
                'ZoneId': {'Type': 'String'},
                'InstanceType': {'Type': 'String'}
            },
            'ROSTemplateFormatVersion': '2015-09-01',
            'Resources': {
                'ECS': {
                    'Properties': {
                        'ZoneId': {'Ref': 'ZoneId'},
                        'InstanceType': {'Ref': 'InstanceType'},
                        'ImageId': 'centos_7'
                    },
                    'Type': 'ALIYUN::ECS::Instance'
                }
            }
        }

        result = await self.plugin.generate_template_policy(template_body=json.dumps(tpl))
        self._pprint_json(result)