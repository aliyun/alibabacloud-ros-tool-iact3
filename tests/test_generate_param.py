import yaml

from iact3.config import TestConfig, TemplateConfig
from iact3.generate_params import ParamGenerator
from tests.common import BaseTest


class TestParamGen(BaseTest):

    async def test_get_template_with_url(self):
        test_url = [
            'oss://iactvt-beijing/local_file_test/ecs_instance.template.json?RegionId=cn-beijing',
            'https://iactvt-beijing.oss-cn-beijing.aliyuncs.com/ecs_instance.template.json',
            f'file://{self.DATA_PATH}/ecs_instance.template.json'
        ]
        for u in test_url:
            test_config = TestConfig.from_dict({
                'template_config': {
                    'template_url': u
                }
            })
            pg = ParamGenerator(test_config)
            result = await pg._get_template_body()
            template_body = yaml.safe_load(result)
            self._pprint_json(template_body)

    async def test_get_template_with_id(self):
        template_id = 'fe78dcd0-e5e2-4a9c-9b31-ca1e00e0f982'
        config = TestConfig.from_dict({
            'template_config': {
                'template_id': template_id,
                'template_version': 'v1'
            }
        })
        pg = ParamGenerator(config)
        result = await pg._get_template_body()
        template_body = yaml.safe_load(result)
        self._pprint_json(template_body)

    async def test_get_parameters_order(self):
        config = TestConfig.from_dict({
            'template_config': {
                'template_url': f'file://{self.DATA_PATH}/ecs_instance.template.json'
            }
        })
        pg = ParamGenerator(config)
        template_order = await pg._get_parameters_order()
        self._pprint_json(template_order)

    async def test_generate_parameters(self):
        auto = '$[iact3-auto]'
        tpl_config = TemplateConfig.from_dict({
            'template_url': f'file://{self.DATA_PATH}/ecs_instance.template.json'
        })
        tpl_args = tpl_config.generate_template_args()
        config = TestConfig.from_dict({
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
                'SecurityGroupId': auto
            }
        })
        config.region = self.REGION_ID
        config.test_name = 'default'
        resolved_parameters = await ParamGenerator.result(config)
        self._pprint_json(resolved_parameters.parameters)

    async def test_generate_parameters_time_out(self):
        auto = '$[iact3-auto]'
        tpl_config = TemplateConfig.from_dict({
            'template_url': f'file://{self.DATA_PATH}/timeout_template.yml'
        })
        tpl_args = tpl_config.generate_template_args()
        config = TestConfig.from_dict({
            'template_config': tpl_args,
            'parameters': {
                'ZoneId': 'cn-hddddd',
                'DBInstanceClass': auto,
                'DBPassword': auto
            }
        })
        config.region = self.REGION_ID
        config.test_name = 'default'
        resolved_parameters = await ParamGenerator.result(config)
        self._pprint_json(resolved_parameters.parameters)
