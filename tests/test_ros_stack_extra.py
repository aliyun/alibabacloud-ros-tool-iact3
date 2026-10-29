from types import SimpleNamespace

from iact3.config import HookExecuteTime
from iact3.exceptions import InvalidActionError
from iact3.stack import Stacks
from iact3.testing.ros_stack import StackTest
from tests.common import AsyncTestCase


class TestStackCleanup(AsyncTestCase):
    def make_test(self):
        test = object.__new__(StackTest)
        test.stacker = None
        test.no_delete = False
        test.keep_failed = False
        test.dont_wait_for_delete = False
        return test

    async def test_cleanup_without_stacks_or_with_no_delete_is_a_noop(self):
        test = self.make_test()
        await test.clean_up()
        test.stacker = object()
        test.no_delete = True
        await test.clean_up()

    async def test_keep_failed_deletes_only_successful_stacks_and_runs_hooks(self):
        good = SimpleNamespace(id='good', status='CREATE_COMPLETE')
        failed = SimpleNamespace(id='failed', status='CREATE_FAILED')
        calls = []

        class Stacker:
            stacks = Stacks([good, failed])
            async def delete_stacks(self, stacks):
                calls.append(('delete', list(stacks)))
            async def execute_hooks(self, execute_time, stacks):
                calls.append(('hooks', execute_time, list(stacks)))
            def status(self):
                return {'FAILED': {'failed': 'denied'}}

        class Printer:
            async def report_test_progress(self, stacker):
                calls.append(('progress', stacker))

        test = self.make_test()
        test.stacker = Stacker()
        test.printer = Printer()
        test.keep_failed = True
        with self.assertRaises(InvalidActionError):
            await test.clean_up()
        self.assertEqual(calls[0], ('delete', [good]))
        self.assertEqual(calls[1], ('progress', test.stacker))
        self.assertEqual(calls[2], ('hooks', HookExecuteTime.POST_DELETE, [good]))

    async def test_dont_wait_skips_progress_and_post_delete_hooks(self):
        calls = []
        class Stacker:
            stacks = Stacks()
            async def delete_stacks(self, stacks):
                calls.append(list(stacks))
            def status(self):
                return {}
        test = self.make_test()
        test.stacker = Stacker()
        test.dont_wait_for_delete = True
        await test.clean_up()
        self.assertEqual(calls, [[]])
