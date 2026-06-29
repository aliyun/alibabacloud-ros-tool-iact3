import os

from iact3.cli_modules.preview import Preview
from iact3.config import IAC_NAME
from tests.common import BaseTest
import logging
import logging.handlers


class TestRun(BaseTest):
    async def test_preview_with_valid_config(self):
        config_file = os.path.join(self.DATA_PATH, 'test_config.iact3.yaml')

        memory_handler = logging.handlers.MemoryHandler(capacity=10240)
        logger = logging.getLogger()
        logger.addHandler(memory_handler)

        await Preview.create(config_file=config_file)

        self.assert_any_log_contains(memory_handler, "test_name: default")
        self.assert_any_log_contains(memory_handler, "VPC::EIPAssociation")
        self.assert_any_log_contains(memory_handler, "\"AllocationId\": \"EIP\",")

    async def test_preview_with_invalid_config(self):
        config_file = os.path.join(self.DATA_PATH, 'failed_cost_config.iact3.yaml')

        memory_handler = logging.handlers.MemoryHandler(capacity=10240)
        logger = logging.getLogger()
        logger.addHandler(memory_handler)

        await Preview.create(config_file=config_file)

        self.assert_any_log_contains(memory_handler, "test_name: default")
        self.assert_any_log_contains(memory_handler, "region: cn-hangzhou")
        self.assert_any_log_contains(memory_handler, "StackValidationFailed")
        self.assert_any_log_contains(memory_handler, "code:")

    async def test_preview_with_only_template(self):
        template = os.path.join(self.DATA_PATH, 'simple_template.yml')

        with self.assertRaises(FileNotFoundError) as cm:
            await Preview.create(template=template)
        ex = cm.exception
        self.assertEqual(ex.errno, 2)
        self.assertEqual(True, ex.filename.endswith(f'.{IAC_NAME}.yml'))

    async def test_preview_with_multi_region(self):
        config_file = os.path.join(self.DATA_PATH, 'test_config.iact3.yaml')

        memory_handler = logging.handlers.MemoryHandler(capacity=10240)
        logger = logging.getLogger()
        logger.addHandler(memory_handler)

        await Preview.create(config_file=config_file, regions="cn-hangzhou,cn-beijing")

        messages = [message for message in self._log_messages(memory_handler) if "test_name: default" in message]
        self.assertGreaterEqual(len(messages), 2)
