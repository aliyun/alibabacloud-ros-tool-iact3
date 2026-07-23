# -*- coding: utf-8 -*-
import io
import logging
import tempfile
from contextlib import redirect_stderr
from pathlib import Path

from aiohttp import CookieJar, web
from aiohttp.test_utils import TestClient, TestServer

from iact3.cli_modules.server import Server
from iact3.web.app import (
    SESSION_COOKIE,
    auth_middleware,
    create_app,
    create_session_handler,
    index_handler,
    _acquire_server_lock,
    _print_access_token,
    _release_server_lock,
    run_server,
)
from tests.common import AsyncTestCase


class TestWebAuthentication(AsyncTestCase):
    async def asyncSetUp(self):
        self.mutation_count = 0

        async def ping_handler(_request):
            return web.json_response({'status': 'ok'})

        async def mutate_handler(_request):
            self.mutation_count += 1
            return web.json_response({'status': 'changed'})

        async def report_handler(_request):
            return web.Response(text='report')

        self.app = web.Application(middlewares=[auth_middleware])
        self.app['api_token'] = 'test-access-token'
        self.app.router.add_get('/', index_handler)
        self.app.router.add_post('/session', create_session_handler)
        self.app.router.add_get('/api/ping', ping_handler)
        self.app.router.add_post('/api/mutate', mutate_handler)
        self.app.router.add_get('/outputs/report', report_handler)
        self.client = TestClient(TestServer(self.app), cookie_jar=CookieJar(unsafe=True))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def test_api_requires_session_or_bearer_token(self):
        response = await self.client.get('/api/ping')
        self.assertEqual(401, response.status)

        response = await self.client.get('/api/ping?token=test-access-token')
        self.assertEqual(401, response.status)

        response = await self.client.get(
            '/api/ping',
            headers={'Authorization': 'Bearer test-access-token'},
        )
        self.assertEqual(200, response.status)
        self.assertEqual({'status': 'ok'}, await response.json())

    async def test_login_creates_http_only_session_cookie(self):
        response = await self.client.get('/')
        self.assertEqual(200, response.status)
        self.assertIn('Sign in to iact3', await response.text())

        response = await self.client.post(
            '/session',
            data={'token': 'wrong-token'},
            allow_redirects=False,
        )
        self.assertEqual(401, response.status)

        response = await self.client.post(
            '/session',
            data={'token': 'test-access-token'},
            allow_redirects=False,
        )
        self.assertEqual(303, response.status)
        cookie = response.cookies[SESSION_COOKIE]
        self.assertTrue(cookie['httponly'])
        self.assertEqual('Strict', cookie['samesite'])

        response = await self.client.get('/api/ping')
        self.assertEqual(200, response.status)
        response = await self.client.get('/outputs/report')
        self.assertEqual(200, response.status)

    async def test_cookie_authenticated_writes_require_same_origin(self):
        response = await self.client.post(
            '/session',
            data={'token': 'test-access-token'},
            allow_redirects=False,
        )
        self.assertEqual(303, response.status)

        response = await self.client.post(
            '/api/mutate',
            json={'value': 'changed'},
            headers={'Origin': 'http://127.0.0.1:65530'},
        )
        self.assertEqual(403, response.status)
        self.assertEqual(0, self.mutation_count)

        response = await self.client.post(
            '/api/mutate',
            json={'value': 'changed'},
            headers={'Origin': str(self.client.make_url('/')).rstrip('/')},
        )
        self.assertEqual(200, response.status)
        self.assertEqual(1, self.mutation_count)

    async def test_bearer_authenticated_writes_do_not_require_browser_origin(self):
        response = await self.client.post(
            '/api/mutate',
            json={'value': 'changed'},
            headers={'Authorization': 'Bearer test-access-token'},
        )

        self.assertEqual(200, response.status)
        self.assertEqual(1, self.mutation_count)


class TestServerBinding(AsyncTestCase):
    def test_second_server_cannot_manage_the_same_workspace(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            lock_path = Path(temp_dir) / 'server.lock'
            owner = _acquire_server_lock(lock_path)
            try:
                with self.assertRaisesRegex(RuntimeError, 'already managing'):
                    _acquire_server_lock(lock_path)
            finally:
                _release_server_lock(owner, lock_path)

            next_owner = _acquire_server_lock(lock_path)
            _release_server_lock(next_owner, lock_path)
            self.assertFalse(lock_path.exists())

    def test_generated_token_is_visible_even_when_logging_is_quiet(self):
        logger = logging.getLogger('iact3')
        original_level = logger.level
        output = io.StringIO()
        try:
            logger.setLevel(logging.ERROR)
            with redirect_stderr(output):
                _print_access_token('generated-token')
        finally:
            logger.setLevel(original_level)

        self.assertEqual('Access token: generated-token\n', output.getvalue())

    async def test_cli_rejects_external_binding_even_with_a_token(self):
        with self.assertRaisesRegex(ValueError, 'loopback'):
            await Server.start(host='0.0.0.0', token='explicit-token')

    async def test_direct_server_entrypoint_rejects_external_binding(self):
        with self.assertRaisesRegex(ValueError, 'loopback'):
            await run_server(host='0.0.0.0', token='explicit-token')

    async def test_empty_explicit_token_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'must not be empty'):
            await Server.start(token='')
        with self.assertRaisesRegex(ValueError, 'must not be empty'):
            await run_server(token='   ')
        with self.assertRaisesRegex(ValueError, 'must not be empty'):
            create_app(token='')
