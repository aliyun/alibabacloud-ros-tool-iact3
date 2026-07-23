# -*- coding: utf-8 -*-
import asyncio
import json
import logging
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from uuid import uuid4

from Tea.exceptions import TeaException
from alibabacloud_credentials.client import Client as CredentialClient
from alibabacloud_credentials.models import Config as CredentialConfig
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from iact3.stack import Stack, Stacker
from iact3.web import routes
from iact3.web import runner as runner_module
from iact3.web.runner import TestRun as WebTestRun
from iact3.web.runner import TestRunner as WebTestRunner
from iact3.web.runner import capture_iact3_logs
from iact3.web.runner import get_credential_key_id
from tests.common import AsyncTestCase


class TestIncrementalStackCreation(AsyncTestCase):
    @staticmethod
    def _test_config():
        return SimpleNamespace(
            parameters={'Name': 'example'},
            template_config=SimpleNamespace(to_dict=lambda: {'template_body': '{}'}),
            test_name='default',
            region='cn-hangzhou',
            auth=SimpleNamespace(credential=SimpleNamespace()),
            error=None,
            hooks={},
        )

    async def test_create_is_checkpointed_before_the_cloud_response(self):
        request_started = asyncio.Event()
        response_ready = asyncio.Event()
        plugin = SimpleNamespace()

        async def create_stack(**_kwargs):
            request_started.set()
            await response_ready.wait()
            return 'stack-created'

        plugin.create_stack = mock.AsyncMock(side_effect=create_stack)
        plugin.list_stacks = mock.AsyncMock(return_value=[])
        plugin.get_stack = mock.AsyncMock(return_value={'Status': 'CREATE_IN_PROGRESS'})
        observed = []

        with mock.patch('iact3.stack.StackPlugin', return_value=plugin):
            task = asyncio.create_task(Stack.create(
                self._test_config(),
                uuid=uuid4(),
                stack_created_callback=lambda stack: observed.append(
                    (stack.id, stack.name, stack.status)
                ),
            ))
            await request_started.wait()
            self.assertIsNone(observed[0][0])
            self.assertTrue(observed[0][1])
            self.assertEqual('CREATE_REQUESTING', observed[0][2])
            response_ready.set()
            stack = await task

        stack.timer.cancel()
        self.assertEqual('stack-created', stack.id)
        self.assertTrue(any(item[0] == 'stack-created' for item in observed))

    async def test_failed_pre_create_checkpoint_stops_the_cloud_request(self):
        plugin = SimpleNamespace(
            create_stack=mock.AsyncMock(return_value='must-not-be-created'),
            list_stacks=mock.AsyncMock(return_value=[]),
            get_stack=mock.AsyncMock(return_value={'Status': 'CREATE_IN_PROGRESS'}),
        )

        def fail_checkpoint(_stack):
            raise RuntimeError('checkpoint failed')

        with mock.patch('iact3.stack.StackPlugin', return_value=plugin):
            with self.assertRaisesRegex(RuntimeError, 'checkpoint failed'):
                await Stack.create(
                    self._test_config(),
                    uuid=uuid4(),
                    stack_created_callback=fail_checkpoint,
                )

        plugin.create_stack.assert_not_awaited()

    async def test_response_error_recovers_stack_by_exact_name(self):
        plugin = SimpleNamespace()
        plugin.create_stack = mock.AsyncMock(
            side_effect=TeaException({'code': 'Timeout', 'message': 'response lost'})
        )

        async def list_stacks(stack_name=None):
            return [{
                'StackId': 'stack-recovered',
                'StackName': stack_name,
                'Status': 'CREATE_IN_PROGRESS',
            }]

        plugin.list_stacks = mock.AsyncMock(side_effect=list_stacks)
        plugin.get_stack = mock.AsyncMock(return_value={'Status': 'CREATE_IN_PROGRESS'})
        observed = []

        with mock.patch('iact3.stack.StackPlugin', return_value=plugin):
            stack = await Stack.create(
                self._test_config(),
                uuid=uuid4(),
                stack_created_callback=lambda current: observed.append(current.id),
            )

        stack.timer.cancel()
        self.assertEqual('stack-recovered', stack.id)
        self.assertEqual([None, 'stack-recovered'], observed)

    async def test_completed_stacks_survive_a_later_failure(self):
        observed = []
        stacker = Stacker(
            project_name='example',
            tests=['first', 'second'],
            stack_observer=lambda: observed.append([stack.id for stack in stacker.stacks]),
        )

        async def create_stack(test, _tags, _uid, _report_path, stack_created_callback=None):
            if test == 'first':
                stack = SimpleNamespace(id='stack-first')
                stack_created_callback(stack)
                return stack
            await asyncio.sleep(0.01)
            raise RuntimeError('second stack failed unexpectedly')

        with mock.patch.object(Stack, 'create', new=create_stack):
            with self.assertRaisesRegex(RuntimeError, 'second stack'):
                await stacker.create_stacks()

        self.assertEqual(['stack-first'], [stack.id for stack in stacker.stacks])
        self.assertTrue(observed)
        self.assertTrue(all(item == ['stack-first'] for item in observed))

    async def test_sibling_request_settles_after_another_create_fails(self):
        stacker = Stacker(
            project_name='example',
            tests=['failing', 'delayed'],
        )

        async def create_stack(test, _tags, _uid, _report_path, stack_created_callback=None):
            if test == 'failing':
                raise RuntimeError('first stack failed unexpectedly')
            await asyncio.sleep(0.01)
            stack = SimpleNamespace(id='stack-delayed')
            stack_created_callback(stack)
            return stack

        with mock.patch.object(Stack, 'create', new=create_stack):
            with self.assertRaisesRegex(RuntimeError, 'first stack'):
                await stacker.create_stacks()

        self.assertEqual(['stack-delayed'], [stack.id for stack in stacker.stacks])

    async def test_failed_sibling_cancels_a_stuck_create_after_timeout(self):
        stacker = Stacker(
            project_name='example',
            tests=['stuck', 'failing'],
        )
        stacker.SETTLE_TIMEOUT_SECONDS = 0.01
        stacker.CANCELLATION_GRACE_SECONDS = 0.01
        stuck_started = asyncio.Event()
        stuck_cancelled = asyncio.Event()

        async def create_stack(test, _tags, _uid, _report_path, stack_created_callback=None):
            if test == 'failing':
                await stuck_started.wait()
                raise RuntimeError('create failed')
            stuck_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                stuck_cancelled.set()
                raise

        with mock.patch.object(Stack, 'create', new=create_stack):
            with self.assertRaisesRegex(RuntimeError, 'create failed'):
                await stacker.create_stacks()

        self.assertTrue(stuck_cancelled.is_set())

    async def test_delete_is_checkpointed_before_the_cloud_request(self):
        stack = SimpleNamespace(
            id='stack-delete',
            status='CREATE_COMPLETE',
        )
        observed = []
        stacker = Stacker(
            project_name='example',
            stacks=[stack],
            stack_observer=lambda: observed.append(stack.status),
        )
        stacker.execute_hooks = mock.AsyncMock()

        async def delete_stack(current):
            self.assertEqual('DELETE_REQUESTING', current.status)
            current.status = 'DELETE_IN_PROGRESS'

        with mock.patch.object(Stack, 'delete', new=delete_stack):
            await stacker.delete_stacks()

        self.assertEqual(
            ['DELETE_REQUESTING', 'DELETE_IN_PROGRESS'],
            observed,
        )

    async def test_failed_delete_checkpoint_stops_the_cloud_request(self):
        stack = SimpleNamespace(
            id='stack-delete',
            status='CREATE_COMPLETE',
        )
        stacker = Stacker(
            project_name='example',
            stacks=[stack],
            stack_observer=mock.Mock(side_effect=RuntimeError('checkpoint failed')),
        )
        stacker.execute_hooks = mock.AsyncMock()

        with mock.patch.object(Stack, 'delete', new=mock.AsyncMock()) as delete:
            with self.assertRaisesRegex(RuntimeError, 'checkpoint failed'):
                await stacker.delete_stacks()

        delete.assert_not_awaited()

    async def test_accepted_delete_marks_a_missing_stack_complete(self):
        stack = Stack(
            region='cn-hangzhou',
            stack_id='stack-deleted',
            test_name='default',
        )
        stack.status = 'CREATE_COMPLETE'
        stack.plugin = SimpleNamespace(
            delete_stack=mock.AsyncMock(return_value=True),
            get_stack=mock.AsyncMock(return_value=None),
        )

        await Stack.delete(stack)

        self.assertEqual('DELETE_COMPLETE', stack.status)

    async def test_rejected_delete_request_stays_unconfirmed(self):
        stack = Stack(
            region='cn-hangzhou',
            stack_id='stack-unknown',
            test_name='default',
        )
        stack.status = 'CREATE_COMPLETE'
        stack.plugin = SimpleNamespace(
            delete_stack=mock.AsyncMock(return_value=False),
        )

        await Stack.delete(stack)

        self.assertEqual('DELETE_UNCONFIRMED', stack.status)

    async def test_stack_id_is_recorded_before_post_create_refresh_finishes(self):
        stacker = Stacker(project_name='example', tests=['only'])
        refresh_wait = asyncio.Event()

        async def create_stack(_test, _tags, _uid, _report_path, stack_created_callback=None):
            stack = SimpleNamespace(id='stack-created')
            stack_created_callback(stack)
            await refresh_wait.wait()
            return stack

        with mock.patch.object(Stack, 'create', new=create_stack):
            task = asyncio.create_task(stacker.create_stacks())
            await asyncio.sleep(0)
            task.cancel()
            refresh_wait.set()
            with self.assertRaises(asyncio.CancelledError):
                await task

        self.assertEqual(['stack-created'], [stack.id for stack in stacker.stacks])

    async def test_cancelled_parent_waits_for_inflight_create_response(self):
        stacker = Stacker(project_name='example', tests=['only'])
        request_started = asyncio.Event()
        response_ready = asyncio.Event()

        async def create_stack(_test, _tags, _uid, _report_path, stack_created_callback=None):
            request_started.set()
            await response_ready.wait()
            stack = SimpleNamespace(id='stack-after-cancel')
            stack_created_callback(stack)
            return stack

        with mock.patch.object(Stack, 'create', new=create_stack):
            task = asyncio.create_task(stacker.create_stacks())
            await request_started.wait()
            task.cancel()
            response_ready.set()
            with self.assertRaises(asyncio.CancelledError):
                await task

        self.assertEqual(
            ['stack-after-cancel'],
            [stack.id for stack in stacker.stacks],
        )


class TestRunCheckpointing(AsyncTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.runs_dir_patch = mock.patch.object(
            runner_module,
            '_RUNS_DIR',
            Path(self.temp_dir.name) / 'runs',
        )
        self.runs_dir_patch.start()
        self.runner = WebTestRunner()

    async def asyncTearDown(self):
        await self.runner.shutdown()
        self.runs_dir_patch.stop()
        self.temp_dir.cleanup()

    def test_stack_checkpoint_persists_credential_reference(self):
        credential = CredentialClient(CredentialConfig(
            type='access_key',
            access_key_id='LTAI-example-1234',
            access_key_secret='secret',
        ))
        auth = SimpleNamespace(
            name='profile-a',
            location='/tmp/credentials.json',
            credential=credential,
        )
        stack = SimpleNamespace(
            id='stack-1',
            name='iact3-stack-1',
            test_name='default',
            region='cn-hangzhou',
            status='CREATE_COMPLETE',
            status_reason='',
            launch_succeeded=True,
            create_time='2026-01-01T00:00:00',
            status_time='2026-01-01T00:01:00',
            test_config=SimpleNamespace(auth=auth),
        )
        run = WebTestRun('run-1', 'example', {})
        run.status = 'running'
        run._test = SimpleNamespace(
            stacker=SimpleNamespace(stacks=[stack]),
        )
        self.runner._runs[run.id] = run

        self.runner._checkpoint_run(run)

        self.assertEqual(
            {'name': 'profile-a', 'location': '/tmp/credentials.json'},
            run.stacks[0]['credential_ref'],
        )
        self.assertEqual('1234', run.stacks[0]['credential_key_id'])
        run_file = Path(self.temp_dir.name) / 'runs' / 'run-1.json'
        persisted = json.loads(run_file.read_text(encoding='utf-8'))
        self.assertEqual('stack-1', persisted['stacks'][0]['stack_id'])
        self.assertFalse(run_file.with_suffix('.json.tmp').exists())

    def test_stack_checkpoint_failure_is_not_silently_ignored(self):
        run = WebTestRun('run-checkpoint-failure', 'example', {})
        self.runner._runs[run.id] = run

        with mock.patch.object(
            runner_module.os,
            'replace',
            side_effect=PermissionError('read-only filesystem'),
        ):
            with self.assertRaisesRegex(RuntimeError, 'before the cloud operation'):
                self.runner._checkpoint_run(run)

    def test_stack_checkpoint_uses_the_credential_selected_by_plugin(self):
        credential = CredentialClient(CredentialConfig(
            type='access_key',
            access_key_id='LTAI-provider-5678',
            access_key_secret='secret',
        ))
        auth = SimpleNamespace(
            name='missing-profile',
            location='/missing/credentials.json',
            credential=None,
        )
        stack = SimpleNamespace(
            id='stack-provider',
            name='iact3-stack-provider',
            test_name='default',
            region='cn-hangzhou',
            status='CREATE_COMPLETE',
            status_reason='',
            launch_succeeded=True,
            create_time='',
            status_time='',
            test_config=SimpleNamespace(auth=auth),
            plugin=SimpleNamespace(credential=credential),
        )
        run = WebTestRun('run-provider', 'example', {})
        run.status = 'running'
        run._test = SimpleNamespace(stacker=SimpleNamespace(stacks=[stack]))

        run.update_stacks()

        self.assertEqual({}, run.stacks[0]['credential_ref'])
        self.assertEqual('5678', run.stacks[0]['credential_key_id'])

    def test_credential_key_id_supports_the_sdk_client_wrapper(self):
        credential = CredentialClient(CredentialConfig(
            type='access_key',
            access_key_id='LTAI-real-shape-9876',
            access_key_secret='secret',
        ))

        self.assertEqual('9876', get_credential_key_id(credential))

    def test_credential_key_id_ignores_rotating_credentials(self):
        credential = SimpleNamespace(
            cloud_credential=SimpleNamespace(
                credential_type='ecs_ram_role',
                access_key_id='STS-temporary-1357',
            ),
        )

        self.assertEqual('', get_credential_key_id(credential))

    async def test_background_operation_blocks_run_deletion(self):
        run = WebTestRun('run-2', 'example', {})
        self.runner._runs[run.id] = run
        waiting = asyncio.Event()

        async def background_operation():
            await waiting.wait()

        task = self.runner.start_background_task(run.id, background_operation())
        self.assertFalse(self.runner.delete_run(run.id))
        await self.runner.shutdown()
        self.assertTrue(task.cancelled())

    async def test_cancel_claim_blocks_concurrent_run_deletion(self):
        run = WebTestRun('run-cancel-race', 'example', {})
        cancellation_started = asyncio.Event()
        release_cancellation = asyncio.Event()

        async def active_test():
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancellation_started.set()
                await release_cancellation.wait()
                raise

        run._task = asyncio.create_task(active_test())
        self.runner._runs[run.id] = run
        cancel_task = asyncio.create_task(self.runner.cancel_run(run.id))
        await cancellation_started.wait()

        self.assertFalse(self.runner.delete_run(run.id))
        release_cancellation.set()
        self.assertTrue(await cancel_task)
        self.assertIn(run.id, self.runner._runs)

    def test_run_with_live_stack_cannot_discard_cleanup_metadata(self):
        run = WebTestRun('run-live-stack', 'example', {})
        run.stacks = [{
            'stack_id': 'stack-live',
            'stack_name': 'iact3-stack-live',
            'status': 'CREATE_COMPLETE',
        }]
        self.runner._runs[run.id] = run

        self.assertFalse(self.runner.delete_run(run.id))
        self.assertIn(run.id, self.runner._runs)

        run.stacks[0]['status'] = 'DELETE_COMPLETE'
        self.assertTrue(self.runner.delete_run(run.id))

    async def test_get_run_keeps_object_owned_by_background_operation(self):
        run = WebTestRun('run-3', 'example', {})
        run.status = 'completed'
        run.stacks = [{
            'stack_id': 'stack-3',
            'stack_name': 'iact3-stack-3',
            'status': 'DELETE_IN_PROGRESS',
        }]
        self.runner._runs[run.id] = run
        self.runner._save_run_to_disk(run)
        waiting = asyncio.Event()

        async def background_operation():
            await waiting.wait()

        self.runner.start_background_task(run.id, background_operation())
        data = self.runner.get_run(run.id)

        self.assertIs(run, self.runner.get_run_raw(run.id))
        self.assertEqual('DELETE_IN_PROGRESS', data['stacks'][0]['status'])
        self.assertEqual('', self.runner.get_run_logs(run.id))
        self.assertIs(run, self.runner.get_run_raw(run.id))
        waiting.set()

    async def test_shutdown_checkpoints_cancelled_execution(self):
        run = WebTestRun('run-shutdown', 'example', {})
        run.status = 'running'
        waiting = asyncio.Event()

        async def active_test():
            await waiting.wait()

        run._task = asyncio.create_task(active_test())
        self.runner._runs[run.id] = run
        self.runner._save_run_to_disk(run)

        await self.runner.shutdown()

        persisted = json.loads(
            (Path(self.temp_dir.name) / 'runs' / 'run-shutdown.json').read_text(encoding='utf-8')
        )
        self.assertEqual('cancelled', persisted['status'])

    async def test_overlapping_log_capture_restores_logger_level_once(self):
        logger = logging.getLogger('iact3')
        original_level = logger.level
        first_path = Path(self.temp_dir.name) / 'first.log'
        second_path = Path(self.temp_dir.name) / 'second.log'
        first_active = asyncio.Event()
        second_active = asyncio.Event()
        release_first = asyncio.Event()
        release_second = asyncio.Event()

        async def first_capture():
            with capture_iact3_logs(first_path):
                first_active.set()
                await release_first.wait()

        async def second_capture():
            await first_active.wait()
            with capture_iact3_logs(second_path):
                second_active.set()
                await release_second.wait()
                logger.info('second capture remains active')

        try:
            logger.setLevel(logging.ERROR)
            first_task = asyncio.create_task(first_capture())
            second_task = asyncio.create_task(second_capture())
            await second_active.wait()
            release_first.set()
            await first_task
            self.assertEqual(logging.INFO, logger.level)
            release_second.set()
            await second_task
            self.assertEqual(logging.ERROR, logger.level)
            self.assertIn(
                'second capture remains active',
                second_path.read_text(encoding='utf-8'),
            )
        finally:
            logger.setLevel(original_level)


class TestDeletionRecovery(AsyncTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.runs_dir_patch = mock.patch.object(
            runner_module,
            '_RUNS_DIR',
            Path(self.temp_dir.name) / 'runs',
        )
        self.runs_dir_patch.start()
        self.runner = WebTestRunner()

    async def asyncTearDown(self):
        await self.runner.shutdown()
        self.runs_dir_patch.stop()
        self.temp_dir.cleanup()

    def test_stacks_are_grouped_by_credential_reference(self):
        credentials = {
            'profile-a': SimpleNamespace(access_key_id='LTAI-1111'),
            'profile-b': SimpleNamespace(access_key_id='LTAI-2222'),
        }

        def auth_factory(name=None, location=None):
            return SimpleNamespace(credential=credentials[name])

        stacks = [
            {
                'stack_id': 'stack-a',
                'region': 'cn-hangzhou',
                'credential_ref': {'name': 'profile-a'},
                'credential_key_id': '1111',
            },
            {
                'stack_id': 'stack-b',
                'region': 'cn-hangzhou',
                'credential_ref': {'name': 'profile-b'},
                'credential_key_id': '2222',
            },
        ]
        with mock.patch('iact3.config.Auth', side_effect=auth_factory):
            groups = routes._build_deletion_groups(stacks)

        self.assertEqual(2, len(groups))
        self.assertEqual(
            {'stack-a', 'stack-b'},
            {group['stacks'][0]['stack_id'] for group in groups},
        )

    async def test_startup_recovers_stack_id_from_saved_stack_name(self):
        run = WebTestRun('run-create-recovery', 'example', {})
        run.status = 'failed'
        run.stacks = [{
            'stack_id': '',
            'stack_name': 'iact3-default-cn-hangzhou-recover',
            'test_name': 'default',
            'region': 'cn-hangzhou',
            'status': 'CREATE_REQUESTING',
            'credential_ref': {},
        }]
        self.runner._runs[run.id] = run
        plugin = SimpleNamespace(
            list_stacks=mock.AsyncMock(return_value=[{
                'StackId': 'stack-recovered-after-restart',
                'StackName': 'iact3-default-cn-hangzhou-recover',
                'Status': 'CREATE_COMPLETE',
            }]),
        )

        with mock.patch.object(
            routes,
            '_resolve_stack_credential',
            return_value=(('', ''), SimpleNamespace()),
        ), mock.patch.object(routes, 'StackPlugin', return_value=plugin):
            await routes._resume_pending_creations({'runner': self.runner})

        self.assertEqual(
            'stack-recovered-after-restart',
            run.stacks[0]['stack_id'],
        )
        persisted = json.loads(
            (Path(self.temp_dir.name) / 'runs' / f'{run.id}.json').read_text(encoding='utf-8')
        )
        self.assertEqual('CREATE_COMPLETE', persisted['stacks'][0]['status'])

    async def test_unconfirmed_creation_remains_retryable_after_restart(self):
        run = WebTestRun('run-create-unconfirmed', 'example', {})
        run.status = 'failed'
        run.stacks = [{
            'stack_id': '',
            'stack_name': 'iact3-default-cn-hangzhou-unconfirmed',
            'test_name': 'default',
            'region': 'cn-hangzhou',
            'status': 'CREATE_UNCONFIRMED',
            'credential_ref': {},
        }]
        self.runner._runs[run.id] = run
        plugin = SimpleNamespace(list_stacks=mock.AsyncMock(return_value=[]))

        with mock.patch.object(
            routes,
            '_resolve_stack_credential',
            return_value=(('', ''), SimpleNamespace()),
        ), mock.patch.object(
            routes,
            'StackPlugin',
            return_value=plugin,
        ), mock.patch.object(routes.asyncio, 'sleep', new=mock.AsyncMock()):
            await routes._resume_pending_creations({'runner': self.runner})

        self.assertEqual('CREATE_UNCONFIRMED', run.stacks[0]['status'])
        self.assertIn('Check ROS', run.stacks[0]['status_reason'])

    async def test_unconfirmed_creation_is_rechecked_without_another_restart(self):
        run = WebTestRun('run-create-background-retry', 'example', {})
        run.status = 'failed'
        run.stacks = [{
            'stack_id': '',
            'stack_name': 'iact3-default-cn-hangzhou-background',
            'test_name': 'default',
            'region': 'cn-hangzhou',
            'status': 'CREATE_UNCONFIRMED',
            'credential_ref': {},
        }]
        self.runner._runs[run.id] = run
        plugin = SimpleNamespace(
            list_stacks=mock.AsyncMock(side_effect=[
                [],
                [{
                    'StackId': 'stack-found-in-background',
                    'StackName': 'iact3-default-cn-hangzhou-background',
                    'Status': 'CREATE_COMPLETE',
                }],
            ]),
        )

        with mock.patch.object(
            routes,
            '_resolve_stack_credential',
            return_value=(('', ''), SimpleNamespace()),
        ), mock.patch.object(routes, 'StackPlugin', return_value=plugin):
            await routes._retry_pending_creations(
                self.runner,
                run.id,
                poll_interval=0,
                max_polls=2,
            )

        self.assertEqual('stack-found-in-background', run.stacks[0]['stack_id'])
        self.assertEqual('CREATE_COMPLETE', run.stacks[0]['status'])

    def test_rotated_static_credential_can_still_attempt_cleanup(self):
        credential = SimpleNamespace(access_key_id='LTAI-new-9999')
        stack = {
            'stack_id': 'stack-rotated-key',
            'region': 'cn-hangzhou',
            'credential_ref': {'name': 'profile-a'},
            'credential_key_id': '1111',
        }

        with mock.patch(
            'iact3.config.Auth',
            return_value=SimpleNamespace(credential=credential),
        ):
            groups = routes._build_deletion_groups([stack])

        self.assertIs(credential, groups[0]['credential'])

    def test_default_provider_is_used_when_no_profile_reference_was_saved(self):
        credential = CredentialClient(CredentialConfig(
            type='access_key',
            access_key_id='LTAI-provider-2468',
            access_key_secret='secret',
        ))
        stack = {
            'stack_id': 'stack-provider',
            'region': 'cn-hangzhou',
            'credential_ref': {},
            'credential_key_id': '2468',
        }

        with mock.patch(
            'iact3.cli_modules.list.List.get_credential',
            return_value=None,
        ), mock.patch(
            'iact3.plugin.base_plugin.CredentialClient',
            return_value=credential,
        ):
            groups = routes._build_deletion_groups([stack])

        self.assertIs(credential, groups[0]['credential'])

    async def test_poll_timeout_remains_retryable(self):
        stack = {
            'stack_id': 'stack-timeout',
            'region': 'cn-hangzhou',
            'status': 'DELETE_IN_PROGRESS',
        }
        run = WebTestRun('run-timeout', 'example', {})
        run.stacks = [stack]
        self.runner._runs[run.id] = run
        credential = SimpleNamespace(access_key_id='LTAI-1234')
        groups = [{'region': 'cn-hangzhou', 'credential': credential, 'stacks': [stack]}]

        class PendingStackPlugin:
            def __init__(self, region_id, credential):
                self.region_id = region_id

            async def get_stack(self, _stack_id):
                return {'Status': 'DELETE_IN_PROGRESS'}

        with mock.patch.object(routes, 'StackPlugin', PendingStackPlugin):
            await routes._poll_stack_deletion(
                self.runner,
                run.id,
                groups,
                poll_interval=0,
                max_polls=1,
            )

        self.assertEqual('DELETE_TIMEOUT', stack['status'])
        self.assertIn('Timed out', stack['delete_error'])

    async def test_unconfirmed_delete_request_keeps_polling_until_timeout(self):
        stack = {
            'stack_id': 'stack-requesting',
            'region': 'cn-hangzhou',
            'status': 'DELETE_REQUESTING',
        }
        run = WebTestRun('run-requesting', 'example', {})
        run.stacks = [stack]
        self.runner._runs[run.id] = run
        credential = SimpleNamespace(access_key_id='LTAI-1234')
        groups = [{'region': 'cn-hangzhou', 'credential': credential, 'stacks': [stack]}]

        class UnchangedStackPlugin:
            def __init__(self, region_id, credential):
                self.region_id = region_id

            async def get_stack(self, _stack_id):
                return {'Status': 'CREATE_COMPLETE'}

        with mock.patch.object(routes, 'StackPlugin', UnchangedStackPlugin):
            await routes._poll_stack_deletion(
                self.runner,
                run.id,
                groups,
                poll_interval=0,
                max_polls=3,
            )

        self.assertEqual('DELETE_TIMEOUT', stack['status'])
        self.assertIn('Timed out', stack['delete_error'])

    async def test_missing_stack_does_not_confirm_a_new_delete_request(self):
        stack = {
            'stack_id': 'stack-request-unconfirmed',
            'region': 'cn-hangzhou',
            'status': 'DELETE_REQUESTING',
        }
        run = WebTestRun('run-delete-unconfirmed', 'example', {})
        run.stacks = [stack]
        self.runner._runs[run.id] = run
        groups = [{
            'region': 'cn-hangzhou',
            'credential': SimpleNamespace(),
            'stacks': [stack],
        }]

        class MissingStackPlugin:
            def __init__(self, region_id, credential):
                self.region_id = region_id

            async def get_stack(self, _stack_id):
                return None

        with mock.patch.object(routes, 'StackPlugin', MissingStackPlugin):
            await routes._poll_stack_deletion(
                self.runner,
                run.id,
                groups,
                poll_interval=0,
                max_polls=1,
            )

        self.assertEqual('DELETE_UNCONFIRMED', stack['status'])
        self.assertIn('could not confirm', stack['delete_error'])

    async def test_startup_recovery_failure_becomes_retryable(self):
        stack = {
            'stack_id': 'stack-recovery',
            'region': 'cn-hangzhou',
            'status': 'DELETE_IN_PROGRESS',
        }
        run = WebTestRun('run-recovery', 'example', {})
        run.stacks = [stack]
        self.runner._runs[run.id] = run
        app = {'runner': self.runner}

        with mock.patch.object(
            routes,
            '_build_deletion_groups',
            side_effect=ValueError('profile is unavailable'),
        ):
            await routes._resume_pending_deletions(app)

        self.assertEqual('DELETE_FAILED', stack['status'])
        self.assertIn('profile is unavailable', stack['delete_error'])
        self.assertFalse(self.runner.has_background_task(run.id))


class TestDeletionEndpoint(AsyncTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.patches = [
            mock.patch.object(runner_module, '_RUNS_DIR', root / 'runs'),
            mock.patch.object(routes, '_UPLOAD_DIR', root),
            mock.patch.object(routes, '_PROJECTS_DIR', root / 'projects'),
            mock.patch.object(routes, '_HISTORY_DIR', root / 'history'),
            mock.patch.object(routes, '_SETTINGS_FILE', root / 'settings.json'),
        ]
        for patcher in self.patches:
            patcher.start()
        self.runner = WebTestRunner()
        self.app = web.Application()
        self.app['runner'] = self.runner
        routes.setup_routes(self.app)
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        await self.runner.shutdown()
        for patcher in reversed(self.patches):
            patcher.stop()
        self.temp_dir.cleanup()

    async def test_delete_failed_stack_can_be_retried_and_is_owned_by_runner(self):
        stack = {
            'stack_id': 'stack-retry',
            'region': 'cn-hangzhou',
            'status': 'DELETE_FAILED',
        }
        run = WebTestRun('run-retry', 'example', {})
        run.stacks = [stack]
        self.runner._runs[run.id] = run
        poll_release = asyncio.Event()
        deleted = []

        class RetryStackPlugin:
            def __init__(self, region_id, credential):
                self.region_id = region_id

            async def delete_stack(self, stack_id):
                deleted.append(stack_id)

            async def get_stack(self, _stack_id):
                await poll_release.wait()
                return None

        credential = SimpleNamespace(access_key_id='LTAI-1234')

        def build_groups(stacks, _legacy_key_id=None):
            return [{'region': 'cn-hangzhou', 'credential': credential, 'stacks': stacks}]

        with mock.patch.object(routes, 'StackPlugin', RetryStackPlugin), mock.patch.object(
            routes,
            '_build_deletion_groups',
            side_effect=build_groups,
        ):
            response = await self.client.post(f'/api/runs/{run.id}/delete-stacks')
            self.assertEqual(200, response.status)
            self.assertEqual(['stack-retry'], deleted)
            self.assertTrue(self.runner.has_background_task(run.id))
            task = self.runner._background_tasks[run.id]
            poll_release.set()
            await task

        self.assertEqual('DELETE_COMPLETE', stack['status'])
        self.assertFalse(self.runner.has_background_task(run.id))

    async def test_running_test_cannot_start_manual_stack_deletion(self):
        run = WebTestRun('run-active', 'example', {})
        run.stacks = [{
            'stack_id': 'stack-active',
            'region': 'cn-hangzhou',
            'status': 'CREATE_IN_PROGRESS',
        }]
        waiting = asyncio.Event()

        async def active_test():
            await waiting.wait()

        run._task = asyncio.create_task(active_test())
        self.runner._runs[run.id] = run

        response = await self.client.post(f'/api/runs/{run.id}/delete-stacks')

        self.assertEqual(409, response.status)
        self.assertEqual('RUN_IN_PROGRESS', (await response.json())['code'])
        waiting.set()

    async def test_confirmed_delete_failure_is_reported_as_an_error(self):
        stack = {
            'stack_id': 'stack-failed',
            'region': 'cn-hangzhou',
            'status': 'DELETE_FAILED',
        }
        run = WebTestRun('run-delete-failed', 'example', {})
        run.stacks = [stack]
        self.runner._runs[run.id] = run

        class FailedDeletePlugin:
            def __init__(self, region_id, credential):
                self.region_id = region_id

            async def delete_stack(self, _stack_id):
                raise RuntimeError('ROS rejected the delete request')

            async def get_stack(self, _stack_id):
                return {'Status': 'DELETE_FAILED'}

        credential = SimpleNamespace(access_key_id='LTAI-1234')

        def build_groups(stacks, _legacy_key_id=None):
            return [{'region': 'cn-hangzhou', 'credential': credential, 'stacks': stacks}]

        with mock.patch.object(routes, 'StackPlugin', FailedDeletePlugin), mock.patch.object(
            routes,
            '_build_deletion_groups',
            side_effect=build_groups,
        ):
            response = await self.client.post(
                f'/api/runs/{run.id}/delete-stacks'
            )

        data = await response.json()
        self.assertEqual(0, data['deleted'])
        self.assertEqual(1, data['errors'])
        self.assertEqual('DELETE_FAILED', stack['status'])

    async def test_concurrent_manual_deletion_is_rejected_before_cloud_call(self):
        run = WebTestRun('run-concurrent', 'example', {})
        run.stacks = [{
            'stack_id': 'stack-concurrent',
            'region': 'cn-hangzhou',
            'status': 'DELETE_FAILED',
        }]
        self.runner._runs[run.id] = run
        entered_delete = asyncio.Event()
        release_delete = asyncio.Event()
        release_poll = asyncio.Event()
        delete_calls = []

        class SlowDeletePlugin:
            def __init__(self, region_id, credential):
                self.region_id = region_id

            async def delete_stack(self, stack_id):
                delete_calls.append(stack_id)
                entered_delete.set()
                await release_delete.wait()

            async def get_stack(self, _stack_id):
                await release_poll.wait()
                return None

        credential = SimpleNamespace(access_key_id='LTAI-1234')

        def build_groups(stacks, _legacy_key_id=None):
            return [{'region': 'cn-hangzhou', 'credential': credential, 'stacks': stacks}]

        with mock.patch.object(routes, 'StackPlugin', SlowDeletePlugin), mock.patch.object(
            routes,
            '_build_deletion_groups',
            side_effect=build_groups,
        ):
            first_request = asyncio.create_task(
                self.client.post(f'/api/runs/{run.id}/delete-stacks')
            )
            await entered_delete.wait()
            persisted = json.loads(
                (Path(self.temp_dir.name) / 'runs' / f'{run.id}.json').read_text(
                    encoding='utf-8'
                )
            )
            self.assertEqual('DELETE_REQUESTING', persisted['stacks'][0]['status'])
            second_response = await self.client.post(
                f'/api/runs/{run.id}/delete-stacks'
            )
            self.assertEqual(409, second_response.status)
            release_delete.set()
            first_response = await first_request
            self.assertEqual(200, first_response.status)
            poll_task = self.runner._background_tasks[run.id]
            release_poll.set()
            await poll_task

        self.assertEqual(['stack-concurrent'], delete_calls)
