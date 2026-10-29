import asyncio
import os
from pathlib import Path
from unittest import mock

from iact3.web import app as web_app
from tests.common import AsyncTestCase


class TestServerLifecycle(AsyncTestCase):
    async def test_static_assets_are_not_cached_but_other_responses_keep_their_headers(self):
        from types import SimpleNamespace
        from aiohttp import web

        async def handler(request):
            return web.Response(text='content')

        static = await web_app.no_cache_middleware(SimpleNamespace(path='/static/app.js'), handler)
        other = await web_app.no_cache_middleware(SimpleNamespace(path='/api/ping'), handler)
        self.assertIn('no-store', static.headers['Cache-Control'])
        self.assertNotIn('Cache-Control', other.headers)

    async def test_lifecycle_shuts_down_without_recovery_tasks(self):
        calls = []
        class Runner:
            async def shutdown(self):
                calls.append('shutdown')
        lifecycle = web_app.runner_lifecycle({'creation_recovery_tasks': set(), 'runner': Runner()})
        await lifecycle.__anext__()
        with self.assertRaises(StopAsyncIteration):
            await lifecycle.__anext__()
        self.assertEqual(calls, ['shutdown'])

    def test_stale_lock_is_replaced_and_other_owner_cannot_release_it(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'lock'
            path.write_text('invalid')
            owner = web_app._acquire_server_lock(path)
            self.assertTrue(path.exists())
            web_app._release_server_lock('different owner', path)
            self.assertTrue(path.exists())
            web_app._release_server_lock(owner, path)
            self.assertFalse(path.exists())
            web_app._release_server_lock(owner, path)

    def test_process_liveness_errors(self):
        for error, expected in [(ProcessLookupError(), False), (PermissionError(), True), (OSError(), False)]:
            with mock.patch.object(os, 'kill', side_effect=error):
                self.assertEqual(web_app._pid_is_running(123), expected)
        with mock.patch.object(os, 'kill'):
            self.assertTrue(web_app._pid_is_running(123))

    async def test_server_starts_and_cleans_up_after_cancellation(self):
        calls = []
        class Runner:
            def __init__(self, app):
                calls.append(('runner', app))
            async def setup(self):
                calls.append('setup')
            async def cleanup(self):
                calls.append('cleanup')
        class Site:
            def __init__(self, runner, host, port):
                calls.append(('site', host, port))
            async def start(self):
                calls.append('start')
        class Event:
            async def wait(self):
                raise asyncio.CancelledError()
        with mock.patch.object(web_app, '_acquire_server_lock', return_value='owner'), \
             mock.patch.object(web_app, '_release_server_lock') as release, \
             mock.patch.object(web_app, 'create_app', return_value='app') as create, \
             mock.patch.object(web_app.web, 'AppRunner', Runner), \
             mock.patch.object(web_app.web, 'TCPSite', Site), \
             mock.patch.object(web_app.asyncio, 'Event', Event):
            await web_app.run_server(port=9000, token='secret')
        create.assert_called_once_with(token='secret')
        release.assert_called_once_with('owner')
        self.assertEqual(calls, [('runner', 'app'), 'setup', ('site', '127.0.0.1', 9000), 'start', 'cleanup'])

    async def test_server_releases_lock_when_initialization_fails(self):
        with mock.patch.object(web_app, '_acquire_server_lock', return_value='owner'), \
             mock.patch.object(web_app, '_release_server_lock') as release, \
             mock.patch.object(web_app, 'create_app', side_effect=RuntimeError('cannot start')):
            with self.assertRaisesRegex(RuntimeError, 'cannot start'):
                await web_app.run_server(token='secret')
        release.assert_called_once_with('owner')

    async def test_lifecycle_cancels_recovery_and_shuts_down_runner(self):
        started = asyncio.Event()
        async def recovery():
            started.set()
            await asyncio.Event().wait()
        task = asyncio.create_task(recovery())
        await started.wait()
        shutdown = []
        class Runner:
            async def shutdown(self):
                shutdown.append(True)
        lifecycle = web_app.runner_lifecycle({'creation_recovery_tasks': {task}, 'runner': Runner()})
        await lifecycle.__anext__()
        with self.assertRaises(StopAsyncIteration):
            await lifecycle.__anext__()
        self.assertTrue(task.cancelled())
        self.assertEqual(shutdown, [True])

    def test_lock_rejects_live_owner_and_repeated_creation_races(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'lock'
            path.write_text('123 existing')
            with mock.patch.object(web_app, '_pid_is_running', return_value=True):
                with self.assertRaisesRegex(RuntimeError, 'already managing'):
                    web_app._acquire_server_lock(path)
            self.assertEqual(path.read_text(), '123 existing')
            with mock.patch.object(web_app.os, 'open', side_effect=FileExistsError), \
                 mock.patch.object(web_app, '_pid_is_running', return_value=False):
                with self.assertRaisesRegex(RuntimeError, 'Could not acquire'):
                    web_app._acquire_server_lock(path)

    async def test_server_rejects_invalid_host_and_token_before_locking(self):
        with mock.patch.object(web_app, '_acquire_server_lock') as acquire:
            with self.assertRaisesRegex(ValueError, 'loopback'):
                await web_app.run_server(host='0.0.0.0')
            for token in ('', '  ', 123):
                with self.assertRaisesRegex(ValueError, 'token'):
                    await web_app.run_server(token=token)
            acquire.assert_not_called()
        for token in ('', '  ', 123):
            with self.assertRaisesRegex(ValueError, 'token'):
                web_app.create_app(token=token)

    async def test_server_prints_generated_access_token(self):
        class Runner:
            def __init__(self, app):
                pass
            async def setup(self):
                pass
            async def cleanup(self):
                pass
        class Site:
            def __init__(self, *args):
                pass
            async def start(self):
                pass
        class Event:
            async def wait(self):
                raise asyncio.CancelledError()
        with mock.patch.object(web_app, '_acquire_server_lock', return_value='owner'), \
             mock.patch.object(web_app, '_release_server_lock'), \
             mock.patch.object(web_app, 'create_app', return_value='app') as create, \
             mock.patch.object(web_app, '_print_access_token') as printed, \
             mock.patch.object(web_app.secrets, 'token_urlsafe', return_value='generated-token'), \
             mock.patch.object(web_app.web, 'AppRunner', Runner), \
             mock.patch.object(web_app.web, 'TCPSite', Site), \
             mock.patch.object(web_app.asyncio, 'Event', Event):
            await web_app.run_server()
        printed.assert_called_once_with('generated-token')
        create.assert_called_once_with(token='generated-token')
