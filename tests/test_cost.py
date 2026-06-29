import os

from iact3.cli_modules.cost import Cost
from iact3.config import IAC_NAME
from tests.common import BaseTest
import logging
import logging.handlers


class TestRun(BaseTest):
    async def test_cost_with_valid_config(self):
        config_file = os.path.join(self.DATA_PATH, 'test_config.iact3.yaml')

        memory_handler = logging.handlers.MemoryHandler(capacity=10240)
        logger = logging.getLogger()
        logger.addHandler(memory_handler)

        await Cost.create(config_file=config_file)

        self.assert_any_log_contains(memory_handler, "test_name: default")
        self.assert_any_log_contains(memory_handler, "ALIYUN::ECS::Instance")
        self.assert_any_log_contains(memory_handler, "ALIYUN::VPC::EIP")
        self.assert_any_log_contains(memory_handler, "VPC::EIP-AssociationFlow")

    async def test_cost_with_invalid_config(self):
        config_file = os.path.join(self.DATA_PATH, 'failed_cost_config.iact3.yaml')

        memory_handler = logging.handlers.MemoryHandler(capacity=10240)
        logger = logging.getLogger()
        logger.addHandler(memory_handler)

        await Cost.create(config_file=config_file)

        self.assert_any_log_contains(memory_handler, "test_name: default")
        self.assert_any_log_contains(memory_handler, "StackValidationFailed")
        self.assert_any_log_contains(memory_handler, "code:")

    async def test_cost_with_only_template(self):
        template = os.path.join(self.DATA_PATH, 'simple_template.yml')

        with self.assertRaises(FileNotFoundError) as cm:
            await Cost.create(template=template)
        ex = cm.exception
        self.assertEqual(ex.errno, 2)
        self.assertEqual(True, ex.filename.endswith(f'.{IAC_NAME}.yml'))

    async def test_cost_with_multi_region(self):
        config_file = os.path.join(self.DATA_PATH, 'test_config.iact3.yaml')

        memory_handler = logging.handlers.MemoryHandler(capacity=10240)
        logger = logging.getLogger()
        logger.addHandler(memory_handler)

        await Cost.create(config_file=config_file, regions="cn-hangzhou,cn-beijing")

        self.assert_any_log_contains(memory_handler, "test_name: default")
        self.assert_any_log_contains(memory_handler, "ALIYUN::ECS::Instance")
        self.assert_any_log_contains(memory_handler, "cn-hangzhou")
        self.assert_any_log_contains(memory_handler, "cn-beijing")
        self.assert_any_log_contains(memory_handler, "ALIYUN::VPC::EIP")
        self.assert_any_log_contains(memory_handler, "VPC::EIP-AssociationFlow")
