import os

from iact3.cli_modules.policy import Policy
from iact3.config import IAC_NAME
from tests.common import BaseTest
import logging
import logging.handlers

class TestRun(BaseTest):
    async def test_policy_with_valid_template(self):
        template = os.path.join(self.DATA_PATH, 'simple_template.yml')

        memory_handler = logging.handlers.MemoryHandler(capacity=10240)
        logger = logging.getLogger()
        logger.addHandler(memory_handler)

        await Policy.create(template=template)
        logs = memory_handler.buffer

        result = '{\n    "Statement": [],\n    "Version": "1"\n}'

        self.assertEqual(result, logs[2].getMessage())

    async def test_policy_with_no_args(self):
        with self.assertRaises(FileNotFoundError) as cm:
            await Policy.create()
        ex = cm.exception
        self.assertEqual(ex.errno, 2)
        self.assertEqual(True, ex.filename.endswith(f'.{IAC_NAME}.yml'))