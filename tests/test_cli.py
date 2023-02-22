# -*- coding: utf-8 -*-
import sys

from iact3.main import run
from tests.common import BaseTest


class TestConfig(BaseTest):
    async def test_main(self):
        sys.argv = [
            '', 'test', 'run', '--project-path', str(self.DATA_PATH),
            '-t', 'ecs_instance.template.json', '-c', 'full_config.yml'
        ]
        await run()

    async def test_list(self):
        sys.argv = [
            '', 'test', 'list',
        ]
        await run()

    async def test_delete(self):
        sys.argv = [
            '', 'test', 'clean',
        ]
        await run()

    async def test_params(self):
        sys.argv = [
            '', 'test', 'run', '--project-path', str(self.DATA_PATH),
            '-t', 'ecs_instance.template.json', '-c', 'full_config.yml', '-g'
        ]
        await run()

    async def test_debug(self):
        sys.argv = [
            '', 'test', 'run', '--project-path', str(self.DATA_PATH),  '-c', 'real.iact3.yml'
        ]
        await run()
