# -*- coding: utf-8 -*-
import sys

from iact3.main import run
from tests.common import BaseTest

from io import StringIO
import logging
import logging.handlers


class TestConfig(BaseTest):
    async def test_main(self):
        sys.argv = [
            '', 'test', 'run', '--project-path', str(self.DATA_PATH),
            '-t', 'simple_template.yml', '-c', '.iact3.yml', '--no-delete'
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

    async def test_delete_with_stack_id(self):
        sys.argv = [
            '', 'test', 'clean', '--stack-id', 'd5ea4c0f-3ec7-416e-afe7-06d41bdf56ba'
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
            '', 'test', 'run', '--project-path', str(self.DATA_PATH), '-c', 'real.iact3.yml'
        ]
        await run()

    async def test_cost(self):
        # 创建一个 MemoryHandler
        memory_handler = logging.handlers.MemoryHandler(capacity=10240)

        # 获取日志记录器并添加 MemoryHandler
        logger = logging.getLogger()
        logger.addHandler(memory_handler)

        sys.argv = [
            '', 'cost', '-c', str(self.DATA_PATH / 'real.iact3.yml')
        ]
        await run()

        # 获取 MemoryHandler 中的日志记录
        logs = memory_handler.buffer

        # 检查日志记录是否包含特定的消息
        self.assertIn("SlaveConsulServer", logs[4].getMessage())
        self.assertIn("SlaveConsulServer", logs[4].getMessage())

    async def test_cost_fail(self):
        memory_handler = logging.handlers.MemoryHandler(capacity=10240)

        logger = logging.getLogger()
        logger.addHandler(memory_handler)

        sys.argv = [
            '', 'cost', '-c', str(self.DATA_PATH / 'failed_cost_config.iact3.yaml')
        ]
        await run()

        logs = memory_handler.buffer

        self.assertIn("StackValidationFailed", logs[2].getMessage())
        self.assertIn("code:", logs[3].getMessage())

    async def test_validate(self):
        memory_handler = logging.handlers.MemoryHandler(capacity=10240)
        logger = logging.getLogger()
        logger.addHandler(memory_handler)

        sys.argv = [
            '', 'validate', '-c', str(self.DATA_PATH / 'real.iact3.yml')
        ]
        await run()

        logs = memory_handler.buffer
        self.assertIn("LegalTemplate      Check passed", logs[3].getMessage())

    async def test_validate_fail(self):
        memory_handler = logging.handlers.MemoryHandler(capacity=10240)
        logger = logging.getLogger()
        logger.addHandler(memory_handler)

        sys.argv = [
            '', 'validate', '-t', str(self.DATA_PATH / 'failed_validate_template.yml')
        ]
        await run()

        logs = memory_handler.buffer
        self.assertIn("InvalidTemplate", logs[3].getMessage())

    async def test_preview(self):
        memory_handler = logging.handlers.MemoryHandler(capacity=10240)
        logger = logging.getLogger()
        logger.addHandler(memory_handler)

        sys.argv = [
            '', 'preview', '-c', str(self.DATA_PATH / 'real.iact3.yml')
        ]
        await run()

        logs = memory_handler.buffer
        self.assertIn("SlaveConsulServer          ECS::InstanceGroup        {", logs[5].getMessage())
        self.assertIn("\"AdjustmentType\": \"NoEffect\",", logs[6].getMessage())
        self.assertIn("RosWaitCondition           ROS::WaitCondition  ", logs[89].getMessage())

    async def test_preview_fail(self):
        memory_handler = logging.handlers.MemoryHandler(capacity=10240)
        logger = logging.getLogger()
        logger.addHandler(memory_handler)

        sys.argv = [
            '', 'preview', '-c', str(self.DATA_PATH / 'failed_cost_config.iact3.yaml')
        ]
        await run()

        logs = memory_handler.buffer
        self.assertIn("StackValidationFailed", logs[3].getMessage())
        self.assertIn("code:", logs[4].getMessage())

    async def test_policy(self):
        memory_handler = logging.handlers.MemoryHandler(capacity=10240)
        logger = logging.getLogger()
        logger.addHandler(memory_handler)

        sys.argv = [
            '', 'policy', '-c', str(self.DATA_PATH / 'real.iact3.yml')
        ]
        await run()

        logs = memory_handler.buffer
        self.assertIn("Statement", logs[1].getMessage())
        self.assertIn("Action", logs[1].getMessage())

    async def test_policy_fail(self):
        memory_handler = logging.handlers.MemoryHandler(capacity=10240)
        logger = logging.getLogger()
        logger.addHandler(memory_handler)

        sys.argv = [
            '', 'policy', '-t', str(self.DATA_PATH / 'invalid_template.yml')
        ]
        await run()

        logs = memory_handler.buffer
        self.assertIn("\"Statement\": []", logs[1].getMessage())
