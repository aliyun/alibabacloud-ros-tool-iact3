# -*- coding: utf-8 -*-
import sys

from iact3.main import run
from tests.common import BaseTest

import logging
import logging.handlers


class TestConfig(BaseTest):
    async def test_main(self):
        sys.argv = [
            '',
            'test',
            'run',
            '--project-path',
            str(self.DATA_PATH),
            '-t',
            'simple_template.yml',
            '-c',
            '.iact3.yml',
        ]
        await run()

    async def test_compute_hook_demo(self):
        sys.argv = [
            '',
            'test',
            'run',
            '--project-path',
            str(self.DATA_PATH),
            '-t',
            'compute_nest_hook_template.yaml',
            '-c',
            'compute_nest_hook_config.yaml',
        ]
        await run()

    async def test_list(self):
        sys.argv = [
            '',
            'test',
            'list',
        ]
        await run()

    async def test_delete(self):
        sys.argv = [
            '',
            'test',
            'clean',
        ]
        await run()

    async def test_delete_with_stack_id(self):
        sys.argv = ['', 'test', 'clean', '--stack-id', 'd5ea4c0f-3ec7-416e-afe7-06d41bdf56ba']
        await run()

    async def test_params(self):
        sys.argv = [
            '',
            'test',
            'run',
            '--project-path',
            str(self.DATA_PATH),
            '-t',
            'ecs_instance.template.json',
            '-c',
            'full_config.yml',
            '-g',
        ]
        await run()

    async def test_debug(self):
        sys.argv = ['', 'test', 'run', '--project-path', str(self.DATA_PATH), '-c', 'real.iact3.yml']
        await run()

    async def test_cost(self):
        # 创建一个 MemoryHandler
        memory_handler = logging.handlers.MemoryHandler(capacity=10240)

        # 获取日志记录器并添加 MemoryHandler
        logger = logging.getLogger()
        logger.addHandler(memory_handler)

        sys.argv = ['', 'cost', '-c', str(self.DATA_PATH / 'real.iact3.yml')]
        await run()

        # 检查日志记录是否包含特定的消息
        self.assert_any_log_contains(memory_handler, "SlaveConsulServer")

    async def test_cost_fail(self):
        memory_handler = logging.handlers.MemoryHandler(capacity=10240)

        logger = logging.getLogger()
        logger.addHandler(memory_handler)

        sys.argv = ['', 'cost', '-c', str(self.DATA_PATH / 'failed_cost_config.iact3.yaml')]
        await run()

        self.assert_any_log_contains(memory_handler, "StackValidationFailed")
        self.assert_any_log_contains(memory_handler, "code:")

    async def test_validate(self):
        memory_handler = logging.handlers.MemoryHandler(capacity=10240)
        logger = logging.getLogger()
        logger.addHandler(memory_handler)

        sys.argv = ['', 'validate', '-c', str(self.DATA_PATH / 'real.iact3.yml')]
        await run()

        self.assert_any_log_contains(memory_handler, "LegalTemplate      Check passed")

    async def test_validate_fail(self):
        memory_handler = logging.handlers.MemoryHandler(capacity=10240)
        logger = logging.getLogger()
        logger.addHandler(memory_handler)

        sys.argv = ['', 'validate', '-t', str(self.DATA_PATH / 'failed_validate_template.yml')]
        await run()

        self.assert_any_log_contains(memory_handler, "InvalidTemplate")

    async def test_preview(self):
        memory_handler = logging.handlers.MemoryHandler(capacity=10240)
        logger = logging.getLogger()
        logger.addHandler(memory_handler)

        sys.argv = ['', 'preview', '-c', str(self.DATA_PATH / 'real.iact3.yml')]
        await run()

        self.assert_any_log_contains(memory_handler, "SlaveConsulServer")
        self.assert_any_log_contains(memory_handler, "ECS::InstanceGroup")
        self.assert_any_log_contains(memory_handler, "\"AdjustmentType\": \"NoEffect\"")
        self.assert_any_log_contains(memory_handler, "RosWaitCondition")
        self.assert_any_log_contains(memory_handler, "ROS::WaitCondition")

    async def test_preview_fail(self):
        memory_handler = logging.handlers.MemoryHandler(capacity=10240)
        logger = logging.getLogger()
        logger.addHandler(memory_handler)

        sys.argv = ['', 'preview', '-c', str(self.DATA_PATH / 'failed_cost_config.iact3.yaml')]
        await run()

        self.assert_any_log_contains(memory_handler, "StackValidationFailed")
        self.assert_any_log_contains(memory_handler, "code:")

    async def test_policy(self):
        memory_handler = logging.handlers.MemoryHandler(capacity=10240)
        logger = logging.getLogger()
        logger.addHandler(memory_handler)

        sys.argv = ['', 'policy', '-c', str(self.DATA_PATH / 'real.iact3.yml')]
        await run()

        self.assert_any_log_contains(memory_handler, "Statement")
        self.assert_any_log_contains(memory_handler, "Action")

    async def test_policy_fail(self):
        memory_handler = logging.handlers.MemoryHandler(capacity=10240)
        logger = logging.getLogger()
        logger.addHandler(memory_handler)

        sys.argv = ['', 'policy', '-t', str(self.DATA_PATH / 'invalid_template.yml')]
        await run()

        self.assert_any_log_contains(memory_handler, "\"Statement\": []")
