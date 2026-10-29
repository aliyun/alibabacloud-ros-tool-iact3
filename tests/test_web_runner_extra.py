import asyncio
import json
import tempfile
from pathlib import Path
from unittest import mock

from iact3.web import runner as web_runner
from tests.common import AsyncTestCase


class TestRunnerPersistence(AsyncTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patches = [
            mock.patch.object(web_runner, '_RUNS_DIR', self.root / 'state'),
            mock.patch.object(web_runner, 'DEFAULT_PROJECT_ROOT', self.root),
            mock.patch.object(web_runner, 'DEFAULT_OUTPUT_DIRECTORY', 'outputs'),
        ]
        for patch in self.patches:
            patch.start()
        self.runner = web_runner.TestRunner()

    async def asyncTearDown(self):
        await self.runner.shutdown()
        for patch in reversed(self.patches):
            patch.stop()
        self.temp.cleanup()

    def test_load_recovers_interrupted_run_and_ignores_invalid_json(self):
        state = self.root / 'state'
        state.mkdir()
        (state / 'broken.json').write_text('{')
        (state / 'run.json').write_text(json.dumps({
            'id': 'run', 'name': 'example', 'status': 'running',
            'stacks': [{'create_time': '2026-01-01T00:00:00', 'status_time': '2026-01-01T01:00:00+08:00'}],
        }))
        runner = web_runner.TestRunner()
        data = runner.get_all_runs()[0]
        self.assertEqual(data['status'], 'failed')
        self.assertIn('restarted', data['error'])
        self.assertEqual(data['stacks'][0]['create_time'], '2026-01-01T00:00:00Z')
        self.assertEqual(data['stacks'][0]['status_time'], '2026-01-01T01:00:00+08:00')
        self.assertEqual(len(runner.get_all_runs()), 1)

    def test_persistence_failure_can_be_propagated_before_cloud_operations(self):
        run = web_runner.TestRun('run', 'example', {})
        with mock.patch.object(web_runner.os, 'replace', side_effect=OSError('disk error')):
            self.assertFalse(self.runner._save_run_to_disk(run))
            with self.assertRaisesRegex(RuntimeError, 'Could not persist run'):
                self.runner._save_run_to_disk(run, raise_on_error=True)
        self.assertFalse((self.root / 'state' / 'run.json').exists())

    def test_loading_a_corrupt_run_returns_no_state(self):
        state = self.root / 'state'
        state.mkdir()
        (state / 'bad.json').write_text('{')
        self.assertIsNone(self.runner._load_single_run_from_disk('bad'))
        self.assertIsNone(self.runner.get_run('bad'))

    def test_reload_marks_persisted_in_progress_run_as_interrupted(self):
        state = self.root / 'state'
        state.mkdir()
        (state / 'run.json').write_text(json.dumps({'id': 'run', 'name': 'example', 'status': 'running',
                                                     'stacks': ['legacy', {'create_time': '2026-01-01T00:00:00'}]}))
        run = self.runner._load_single_run_from_disk('run')
        self.assertEqual(run.status, 'failed')
        self.assertIn('restarted', run.error)
        self.assertEqual(run.stacks[0], 'legacy')
        restarted = web_runner.TestRunner()
        self.assertEqual(restarted.get_all_runs()[0]['stacks'][1]['create_time'], '2026-01-01T00:00:00Z')

    def test_active_run_uses_live_state_instead_of_reloading_disk(self):
        run = web_runner.TestRun('run', 'example', {})
        run.status = 'running'
        run.update_stacks = mock.Mock()
        run.stacks = [{'stack_name': 'stack', 'status': 'CREATE_IN_PROGRESS'}]
        self.runner._runs[run.id] = run
        with mock.patch.object(self.runner, '_load_single_run_from_disk') as load:
            data = self.runner.get_run('run')
        self.assertEqual(data['status'], 'running')
        self.assertEqual(data['stacks'][0]['status'], 'CREATE_IN_PROGRESS')
        run.update_stacks.assert_called_once()
        load.assert_not_called()

    def test_serialization_preserves_legacy_non_mapping_stack_entries(self):
        run = web_runner.TestRun('run', 'example', {})
        run.stacks = ['legacy', {'status': 'CREATE_COMPLETE', 'create_time': '  '}]
        data = run.to_dict()
        self.assertEqual(data['stacks'][0], 'legacy')
        self.assertEqual(data['stacks'][1]['create_time'], '')
        self.assertEqual(run.stacks[1]['create_time'], '  ')

    def test_report_and_logs_are_serialized_and_cleanup_stays_in_root(self):
        run = web_runner.TestRun('run', 'example', {})
        run.report_path = self.root / 'outputs' / 'runs' / 'run'
        run.report_path.mkdir(parents=True)
        (run.report_path / 'index.html').write_text('report')
        (run.report_path / 'log.txt').write_text('details')
        run.log_path = self.root / 'cli.log'
        run.log_path.write_text('cli output')
        run.status = 'completed'
        self.runner._runs[run.id] = run
        self.assertTrue(self.runner._save_run_to_disk(run))
        data = self.runner.get_run('run')
        self.assertEqual(data['report_url'], '/outputs/runs/run/index.html')
        self.assertEqual(data['logs'][0]['content'], 'details')
        self.assertEqual(self.runner.get_run_logs('run'), 'cli output')
        self.assertTrue(self.runner.delete_run('run'))
        self.assertFalse(run.report_path.exists())
        self.assertIsNone(self.runner.get_run('run'))
        outside = self.root / 'outside'
        outside.mkdir()
        run.report_path = outside
        self.runner._cleanup_run_output(run)
        self.assertTrue(outside.exists())

    def test_auto_cleanup_preserves_referenced_directories(self):
        root = self.root / 'outputs' / 'runs'
        for name in ('old', 'keep', 'new'):
            (root / name).mkdir(parents=True)
        # Explicit mtimes make the order independent of filesystem precision.
        import os
        for i, name in enumerate(('old', 'keep', 'new')):
            os.utime(str(root / name), (100 + i, 100 + i))
        run = web_runner.TestRun('keep', 'example', {})
        run.report_path = root / 'keep'
        self.runner._runs[run.id] = run
        with mock.patch.object(web_runner, '_MAX_OUTPUT_RUNS', 1):
            self.runner._auto_cleanup_old_outputs()
        self.assertFalse((root / 'old').exists())
        self.assertTrue((root / 'keep').exists())
        self.assertTrue((root / 'new').exists())

    async def test_start_run_persists_and_cancel_checkpoints(self):
        started = asyncio.Event()
        async def execute(run):
            run.status = 'running'
            started.set()
            await asyncio.Event().wait()
        self.runner._execute_test = execute
        await self.runner.start_test_run({'name': 'example'}, run_id='run')
        await started.wait()
        self.assertTrue((self.root / 'state' / 'run.json').exists())
        self.assertTrue(await self.runner.cancel_run('run'))
        self.assertEqual(json.loads((self.root / 'state' / 'run.json').read_text())['status'], 'cancelled')
        self.assertFalse(await self.runner.cancel_run('missing'))
        self.assertFalse(await self.runner.cancel_run('run'))

    async def test_start_run_does_not_schedule_when_persistence_fails(self):
        with mock.patch.object(self.runner, '_save_run_to_disk', side_effect=RuntimeError('disk full')):
            with self.assertRaisesRegex(RuntimeError, 'disk full'):
                await self.runner.start_test_run({}, run_id='run')
        self.assertNotIn('run', self.runner._runs)

    async def test_execute_test_reports_success_and_stack_failure(self):
        class FakeTest:
            auth = None
            def __init__(self, report_path):
                self.report_path = report_path
                self.report_formats = []
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return False
            async def report(self, log_format):
                self.report_formats.append(log_format)
        for status, expected in [('CREATE_COMPLETE', 'completed'), ('CREATE_FAILED', 'failed')]:
            from types import SimpleNamespace
            run = web_runner.TestRun('run-' + expected, 'example', {
                'output_directory': str(self.root / expected), 'log_format': 'json',
            })
            run.stacks = [{'status': status}]
            run.update_stacks = lambda force=False: None
            fake = FakeTest(self.root / expected)
            if expected == 'completed':
                fake.auth = SimpleNamespace(credential=object())
            async def from_file(**kwargs):
                return fake
            with mock.patch.object(web_runner.StackTest, 'from_file', from_file), \
                 mock.patch.object(web_runner, 'get_credential_key_id', return_value='fingerprint'):
                await self.runner._execute_test(run)
            self.assertEqual(run.status, expected)
            self.assertEqual(run.progress, 100)
            self.assertEqual(fake.report_formats, ['json'])
            self.assertEqual(run.credential_key_id, 'fingerprint' if expected == 'completed' else None)
            saved = json.loads((self.root / 'state' / (run.id + '.json')).read_text())
            self.assertEqual(saved['status'], expected)

    async def test_execute_test_persists_exceptions(self):
        run = web_runner.TestRun('error', 'example', {'output_directory': str(self.root / 'out')})
        async def fail(**kwargs):
            raise ValueError('invalid configuration')
        with mock.patch.object(web_runner.StackTest, 'from_file', fail):
            await self.runner._execute_test(run)
        self.assertEqual(run.status, 'failed')
        self.assertEqual(run.error, 'invalid configuration')
        saved = json.loads((self.root / 'state' / 'error.json').read_text())
        self.assertEqual(saved['error'], 'invalid configuration')


    async def test_background_operation_rejects_duplicate_and_releases_on_completion(self):
        gate = asyncio.Event()
        async def operation():
            await gate.wait()
        task = self.runner.start_background_task('run', operation())
        self.assertTrue(self.runner.has_background_task('run'))
        duplicate = operation()
        with self.assertRaisesRegex(RuntimeError, 'already has a background operation'):
            self.runner.start_background_task('run', duplicate)
        self.assertIsNone(duplicate.cr_frame)
        gate.set()
        await task
        await asyncio.sleep(0)
        self.assertFalse(self.runner.has_background_task('run'))

    async def test_cancel_does_not_interrupt_an_existing_background_operation(self):
        run = web_runner.TestRun('run', 'example', {})
        self.runner._runs[run.id] = run
        gate = asyncio.Event()

        async def operation():
            await gate.wait()

        task = self.runner.start_background_task(run.id, operation())
        self.assertFalse(await self.runner.cancel_run(run.id))
        self.assertFalse(task.done())
        gate.set()
        await task

    async def test_failed_background_operation_releases_run_and_logs_error(self):
        async def operation():
            raise ValueError('operation failed')

        with mock.patch.object(web_runner.LOG, 'error') as log:
            task = self.runner.start_background_task('run', operation())
            with self.assertRaisesRegex(ValueError, 'operation failed'):
                await task
            await asyncio.sleep(0)
        self.assertFalse(self.runner.has_background_task('run'))
        self.assertIn('Background operation', log.call_args[0][0])

    async def test_cancel_run_releases_claim_when_task_cleanup_raises(self):
        started = asyncio.Event()
        async def task_body():
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                raise ValueError('cleanup failed')
        run = web_runner.TestRun('run', 'example', {})
        run.status = 'running'
        run._task = asyncio.create_task(task_body())
        self.runner._runs[run.id] = run
        await started.wait()
        self.assertTrue(await self.runner.cancel_run(run.id))
        self.assertEqual(run.status, 'cancelled')
        self.assertFalse(self.runner.has_background_task(run.id))
        self.assertEqual(json.loads((self.root / 'state' / 'run.json').read_text())['status'], 'cancelled')


class TestStackProgress(AsyncTestCase):
    def test_empty_stack_set_preserves_progress(self):
        from types import SimpleNamespace

        run = web_runner.TestRun('run', 'test', {})
        run.status = 'running'
        run.progress = 12
        run._test = SimpleNamespace(stacker=SimpleNamespace(stacks=[]))
        run.update_stacks()
        self.assertEqual(run.progress, 12)
        self.assertEqual(run.stacks, [])

    def test_progress_matches_creation_deletion_and_retention_options(self):
        from types import SimpleNamespace

        cases = [
            ('', {}, 0), ('CREATE_IN_PROGRESS', {}, 25), ('ROLLBACK_IN_PROGRESS', {}, 25),
            ('CREATE_COMPLETE', {}, 50), ('DELETE_IN_PROGRESS', {}, 75),
            ('DELETE_COMPLETE', {}, 99), ('DELETE_FAILED', {}, 99), ('DELETE_TIMEOUT', {}, 65),
            ('CREATE_COMPLETE', {'no_delete': True}, 99),
            ('CREATE_IN_PROGRESS', {'no_delete': True}, 50),
            ('DELETE_IN_PROGRESS', {'dont_wait_for_delete': True}, 99),
            ('CREATE_FAILED', {'keep_failed': True}, 99),
        ]
        for status, options, expected in cases:
            stack = SimpleNamespace(id='id', name='name', test_name='default', region='cn-a', status=status,
                                    status_reason='', launch_succeeded=True, create_time='', status_time='')
            run = web_runner.TestRun('id', 'test', options)
            run.status = 'running'
            run._test = SimpleNamespace(stacker=SimpleNamespace(stacks=[stack]))
            run.update_stacks()
            self.assertEqual(run.progress, expected, (status, options))
            self.assertEqual(run.stacks[0]['status'], status)

    def test_terminal_progress_and_last_known_status_are_preserved(self):
        from types import SimpleNamespace

        stack = SimpleNamespace(id='id', name='name', test_name='default', region='cn-a', status='',
                                status_reason='', launch_succeeded=True, create_time='', status_time='')
        run = web_runner.TestRun('id', 'test', {})
        run.stacks = [{'stack_name': 'name', 'stack_id': 'id', 'status': 'DELETE_IN_PROGRESS'}]
        run.status = 'completed'
        run.progress = 100
        run._test = SimpleNamespace(stacker=SimpleNamespace(stacks=[stack]))
        run.update_stacks()
        self.assertEqual(run.stacks[0]['status'], 'DELETE_IN_PROGRESS')
        self.assertEqual(run.progress, 100)
        run.update_stacks(force=True)
        self.assertEqual(run.progress, 75)

    def test_progress_averages_stack_lifecycle_states(self):
        from types import SimpleNamespace

        def stack(name, status):
            return SimpleNamespace(id=name, name=name, test_name='default', region='cn-a', status=status,
                                   status_reason='', launch_succeeded=True, create_time='', status_time='')

        run = web_runner.TestRun('run', 'test', {})
        run.status = 'running'
        run._test = SimpleNamespace(stacker=SimpleNamespace(stacks=[
            stack('pending', ''), stack('creating', 'CREATE_IN_PROGRESS'),
            stack('deleting', 'DELETE_IN_PROGRESS'), stack('done', 'DELETE_COMPLETE')]))
        run.update_stacks()
        self.assertEqual(run.progress, 50)
        self.assertEqual([item['status'] for item in run.stacks],
                         ['', 'CREATE_IN_PROGRESS', 'DELETE_IN_PROGRESS', 'DELETE_COMPLETE'])
