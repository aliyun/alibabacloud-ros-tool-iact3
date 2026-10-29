import logging
from types import SimpleNamespace
from unittest import mock

from iact3.termial_print import TerminalPrinter
from tests.common import AsyncTestCase


class TestTerminalProgress(AsyncTestCase):
    async def test_minimal_progress_reports_each_status_once_and_failure_events(self):
        event = SimpleNamespace(logical_id='resource', status_reason='denied')
        stack = SimpleNamespace(id='stack', test_name='test', region='cn-a', status='CREATE_FAILED',
                                error_events=lambda refresh: [event])
        history = {}
        with self.assertLogs('iact3.termial_print', level='INFO') as logs:
            TerminalPrinter._print_tree_minimal(stack, history)
            TerminalPrinter._print_tree_minimal(stack, history)
            stack.status = 'CREATE_COMPLETE'
            TerminalPrinter._print_tree_minimal(stack, history)
        output = '\n'.join(logs.output)
        self.assertEqual(output.count('CREATE_FAILED'), 1)
        self.assertIn('resource denied', output)
        self.assertIn('CREATE_COMPLETE', output)

    async def test_progress_polls_until_finished_and_renders_final_status(self):
        statuses = iter([{'IN_PROGRESS': {'id': ''}}, {'COMPLETE': {'id': ''}}])
        stack = SimpleNamespace(name='example', region='cn-a', id='id', status='CREATE_COMPLETE', outputs=None)
        stacker = SimpleNamespace(stacks=[stack], status=lambda: next(statuses))
        printer = TerminalPrinter(minimalist=True)
        printer.minimalist = False
        printer.buffer = []
        async def sleep(_interval):
            return None
        with mock.patch('iact3.termial_print.asyncio.sleep', sleep), \
             mock.patch.object(printer, '_display_final_status') as final:
            await printer.report_test_progress(stacker, poll_interval=0)
        final.assert_called_once_with(stacker)
        self.assertEqual(printer.buffer, [])

    async def test_minimalist_progress_reports_status_changes_without_terminal_buffer(self):
        statuses = iter([{'IN_PROGRESS': {'id': ''}}, {'COMPLETE': {'id': ''}}])
        stack = SimpleNamespace(id='id', name='example', test_name='test', region='cn-a',
                                status='CREATE_COMPLETE', outputs=None)
        stacker = SimpleNamespace(stacks=[stack], status=lambda: next(statuses))
        printer = TerminalPrinter(minimalist=True)

        async def sleep(_interval):
            return None

        with mock.patch('iact3.termial_print.asyncio.sleep', sleep), \
             self.assertLogs('iact3.termial_print', level='INFO') as logs:
            await printer.report_test_progress(stacker, poll_interval=0)
        self.assertIn('test cn-a CREATE_COMPLETE', '\n'.join(logs.output))
        self.assertFalse(hasattr(printer, 'buffer'))

    def test_final_status_with_outputs_and_tree_display(self):
        stack = SimpleNamespace(name='example', region='cn-a', id=None, status='CREATE_COMPLETE',
                                outputs=[{'OutputKey': 'IP', 'OutputValue': '127.0.0.1'}])
        buffer = []
        TerminalPrinter._print_stack_tree(stack, buffer)
        self.assertEqual(len(buffer), 4)
        self.assertIn('CREATE_COMPLETE', buffer[-1])
        with self.assertLogs('iact3.termial_print', level='INFO') as logs:
            TerminalPrinter._display_final_status(SimpleNamespace(stacks=[stack]))
        self.assertIn('127.0.0.1', '\n'.join(logs.output))

    def test_price_with_incomplete_resource_reports_available_information(self):
        stack = SimpleNamespace(test_name='test', region='cn-a', status='FAILED', status_reason='error',
                                template_price={'Instance': {'Type': 'ALIYUN::ECS::Instance', 'Result': {}}})
        with self.assertLogs('iact3.termial_print', level=logging.INFO) as logs:
            TerminalPrinter._display_price(SimpleNamespace(stacks=[stack]))
        self.assertIn('Instance', '\n'.join(logs.output))
