import os

from iact3.cli_modules.test import Test
from iact3.config import IAC_NAME
from tests.common import BaseTest


class TestRun(BaseTest):

    async def test_run_with_no_args(self):
        with self.assertRaises(FileNotFoundError) as cm:
            await Test.run()
        ex = cm.exception
        self.assertEqual(ex.errno, 2)
        self.assertEqual(True, ex.filename.endswith(f'.{IAC_NAME}.yml'))

    async def test_run_with_simple(self):
        config_file = os.path.join(self.DATA_PATH, f'.{IAC_NAME}.yml')
        template = os.path.join(self.DATA_PATH, 'simple_template.yml')
        await Test.run(config_file=config_file, template=template)

    async def test_run_with_delete_one_stack(self):
        config_file = os.path.join(self.DATA_PATH, f'.{IAC_NAME}.yml')
        template = os.path.join(self.DATA_PATH, 'simple_template.yml')
        await Test.run(config_file=config_file, template=template, no_delete=True)

