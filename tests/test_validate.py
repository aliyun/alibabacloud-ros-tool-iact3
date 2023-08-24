import os

from iact3.cli_modules.validate import Validate
from iact3.config import IAC_NAME
from tests.common import BaseTest
import logging
import logging.handlers

class TestRun(BaseTest):

    async def test_validate_with_valid_template(self):
        template = os.path.join(self.DATA_PATH, 'simple_template.yml')

        memory_handler = logging.handlers.MemoryHandler(capacity=10240)
        logger = logging.getLogger()
        logger.addHandler(memory_handler)

        await Validate.create(template=template)
        logs = memory_handler.buffer

        self.assertEqual("validate_result    result_reason", logs[2].getMessage())
        self.assertEqual("-----------------  ---------------", logs[3].getMessage())
        self.assertEqual("LegalTemplate      Check passed", logs[4].getMessage())

    async def test_validate_with_invalid_template(self):
        template = os.path.join(self.DATA_PATH, 'failed_validate_template.yml')

        memory_handler = logging.handlers.MemoryHandler(capacity=10240)
        logger = logging.getLogger()
        logger.addHandler(memory_handler)

        await Validate.create(template=template)
        logs = memory_handler.buffer

        self.assertEqual("validate_result    result_reason", logs[2].getMessage())
        self.assertIn("Invalid", logs[4].getMessage())

    async def test_validate_with_valid_config(self):
        config_file = os.path.join(self.DATA_PATH, 'test_config.iact3.yaml')

        memory_handler = logging.handlers.MemoryHandler(capacity=10240)
        logger = logging.getLogger()
        logger.addHandler(memory_handler)

        await Validate.create(config_file=config_file)
        logs = memory_handler.buffer

        self.assertEqual("validate_result    result_reason", logs[2].getMessage())
        self.assertEqual("-----------------  ---------------", logs[3].getMessage())
        self.assertEqual("LegalTemplate      Check passed", logs[4].getMessage())

    async def test_validate_with_invalid_config(self):
        config_file = os.path.join(self.DATA_PATH, 'failed_test_validate_config.yml')

        memory_handler = logging.handlers.MemoryHandler(capacity=10240)
        logger = logging.getLogger()
        logger.addHandler(memory_handler)

        await Validate.create(config_file=config_file)
        logs = memory_handler.buffer

        self.assertEqual("validate_result    result_reason", logs[2].getMessage())
        self.assertIn("Invalid", logs[4].getMessage())

    async def test_validate_with_no_args(self):
        with self.assertRaises(FileNotFoundError) as cm:
            await Validate.create()
        ex = cm.exception
        self.assertEqual(ex.errno, 2)
        self.assertEqual(True, ex.filename.endswith(f'.{IAC_NAME}.yml'))