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

        logs = memory_handler.buffer

        self.assertIn("test_name: default", logs[6].getMessage())
        self.assertIn("ALIYUN::ECS::Instance", logs[9].getMessage())
        self.assertIn("ALIYUN::VPC::EIP", logs[10].getMessage())
        self.assertIn("VPC::EIP-AssociationFlow", logs[11].getMessage())

    async def test_cost_with_invalid_config(self):
        config_file = os.path.join(self.DATA_PATH, 'failed_cost_config.iact3.yaml')

        memory_handler = logging.handlers.MemoryHandler(capacity=10240)
        logger = logging.getLogger()
        logger.addHandler(memory_handler)

        await Cost.create(config_file=config_file)

        logs = memory_handler.buffer

        self.assertIn("test_name: default", logs[6].getMessage())
        self.assertIn("StackValidationFailed", logs[7].getMessage())
        self.assertIn("code:", logs[8].getMessage())

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

        await Cost.create(config_file=config_file,regions="cn-hangzhou,cn-beijing")

        logs = memory_handler.buffer

        self.assertIn("test_name: default", logs[11].getMessage())
        self.assertIn("ALIYUN::ECS::Instance", logs[14].getMessage())
        self.assertIn("cn-hangzhou", logs[14].getMessage())
        self.assertIn("ALIYUN::VPC::EIP", logs[15].getMessage())
        self.assertIn("VPC::EIP-AssociationFlow", logs[16].getMessage())

        self.assertIn("test_name: default", logs[18].getMessage())
        self.assertIn("ALIYUN::ECS::Instance", logs[21].getMessage())
        self.assertIn("cn-beijing", logs[21].getMessage())
        self.assertIn("ALIYUN::VPC::EIP", logs[22].getMessage())
        self.assertIn("VPC::EIP-AssociationFlow", logs[23].getMessage())
