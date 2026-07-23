# -*- coding: utf-8 -*-
import asyncio
import hashlib
import hmac
import logging
import os
import secrets
import sys
from pathlib import Path

from aiohttp import web

from iact3.config import DEFAULT_OUTPUT_DIRECTORY, DEFAULT_PROJECT_ROOT
from iact3.web.routes import setup_routes
from iact3.web.runner import TestRunner

LOG = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / 'static'
SESSION_COOKIE = 'iact3_session'
SERVER_LOCK = Path(DEFAULT_PROJECT_ROOT) / '.iact3' / 'server.lock'


def _session_value(token):
    return hmac.new(token.encode('utf-8'), b'iact3-web-session', hashlib.sha256).hexdigest()


def _has_bearer_token(request):
    token = request.app['api_token']
    auth_header = request.headers.get('Authorization', '')
    return auth_header.startswith('Bearer ') and hmac.compare_digest(auth_header[7:], token)


def _has_session_cookie(request):
    token = request.app['api_token']
    session = request.cookies.get(SESSION_COOKIE, '')
    return bool(session) and hmac.compare_digest(session, _session_value(token))


def _is_authenticated(request):
    return _has_bearer_token(request) or _has_session_cookie(request)


def _has_same_origin(request):
    origin = request.headers.get('Origin', '')
    expected = f'{request.scheme}://{request.host}'
    return bool(origin) and hmac.compare_digest(origin.rstrip('/'), expected)


def _print_access_token(token):
    print(f'Access token: {token}', file=sys.stderr, flush=True)


def _pid_is_running(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _acquire_server_lock(lock_path=SERVER_LOCK):
    """Prevent two local servers from managing the same persisted runs."""
    lock_path = Path(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    owner = f'{os.getpid()} {secrets.token_hex(16)}'
    for _attempt in range(2):
        try:
            fd = os.open(
                str(lock_path),
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
        except FileExistsError:
            try:
                existing = lock_path.read_text(encoding='utf-8').split()
                existing_pid = int(existing[0])
            except (OSError, ValueError, IndexError):
                existing_pid = None
            if existing_pid and _pid_is_running(existing_pid):
                raise RuntimeError(
                    'Another iact3 web server is already managing this workspace'
                )
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass
            continue
        try:
            os.write(fd, owner.encode('utf-8'))
        finally:
            os.close(fd)
        return owner
    raise RuntimeError('Could not acquire the iact3 web server lock')


def _release_server_lock(owner, lock_path=SERVER_LOCK):
    lock_path = Path(lock_path)
    try:
        if lock_path.read_text(encoding='utf-8') == owner:
            lock_path.unlink()
    except FileNotFoundError:
        pass
    except OSError as ex:
        LOG.warning('Could not release web server lock %s: %s', lock_path, ex)


async def index_handler(request):
    """Serve the SPA after the browser has established a session."""
    if _is_authenticated(request):
        response = web.FileResponse(STATIC_DIR / 'index.html')
    else:
        response = web.Response(
            text="""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>iact3 sign in</title>
  <style>
    body { font: 14px system-ui, sans-serif; margin: 0; background: #f5f7fa; color: #1f2329; }
    main { max-width: 420px; margin: 12vh auto; padding: 28px; background: #fff;
           border: 1px solid #e5e6eb; border-radius: 10px; box-shadow: 0 8px 30px #0000000d; }
    h1 { margin: 0 0 10px; font-size: 22px; }
    p { color: #646a73; line-height: 1.6; }
    input { box-sizing: border-box; width: 100%; padding: 10px 12px; margin: 8px 0 14px;
            border: 1px solid #c9cdd4; border-radius: 6px; }
    button { width: 100%; padding: 10px 12px; border: 0; border-radius: 6px;
             background: #165dff; color: #fff; cursor: pointer; }
  </style>
</head>
<body>
  <main>
    <h1>Sign in to iact3</h1>
    <p>Copy the access token shown in the terminal where the server was started.</p>
    <form method="post" action="/session">
      <input type="password" name="token" autocomplete="current-password" autofocus required>
      <button type="submit">Continue</button>
    </form>
  </main>
</body>
</html>""",
            content_type='text/html',
        )
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Referrer-Policy'] = 'no-referrer'
    return response


async def create_session_handler(request):
    """Exchange the access token for a browser-only session cookie."""
    form = await request.post()
    supplied = str(form.get('token', ''))
    if not supplied or not hmac.compare_digest(supplied, request.app['api_token']):
        return web.Response(status=401, text='Invalid access token')
    response = web.Response(status=303, headers={'Location': '/'})
    response.set_cookie(
        SESSION_COOKIE,
        _session_value(request.app['api_token']),
        httponly=True,
        secure=request.secure,
        samesite='Strict',
        path='/',
    )
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Referrer-Policy'] = 'no-referrer'
    return response


@web.middleware
async def no_cache_middleware(request, handler):
    """Prevent browser caching for static files during development."""
    response = await handler(request)
    if request.path.startswith('/static/'):
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return response


@web.middleware
async def auth_middleware(request, handler):
    """Require a browser session or bearer token for protected routes."""
    protected = request.path.startswith('/api/') or request.path.startswith('/outputs/')
    bearer_authenticated = _has_bearer_token(request)
    session_authenticated = _has_session_cookie(request)
    if protected and not (bearer_authenticated or session_authenticated):
        if request.path.startswith('/api/'):
            return web.json_response(
                {'error': 'Unauthorized', 'code': 'UNAUTHORIZED'},
                status=401,
            )
        return web.Response(status=401, text='Unauthorized')
    if (
        request.path.startswith('/api/')
        and request.method not in ('GET', 'HEAD', 'OPTIONS')
        and session_authenticated
        and not bearer_authenticated
        and not _has_same_origin(request)
    ):
        return web.json_response(
            {'error': 'Invalid request origin', 'code': 'INVALID_ORIGIN'},
            status=403,
        )
    return await handler(request)


async def runner_lifecycle(app):
    """Tie test and deletion tasks to the aiohttp application lifecycle."""
    yield
    recovery_tasks = list(app['creation_recovery_tasks'])
    for task in recovery_tasks:
        task.cancel()
    if recovery_tasks:
        await asyncio.gather(*recovery_tasks, return_exceptions=True)
    await app['runner'].shutdown()


def create_app(token=None):
    """Create and configure the web application."""
    if token is not None and (not isinstance(token, str) or not token.strip()):
        raise ValueError('The access token must not be empty')
    app = web.Application(middlewares=[no_cache_middleware, auth_middleware])
    app['api_token'] = token if token is not None else secrets.token_urlsafe(32)
    app['runner'] = TestRunner()
    app['creation_recovery_tasks'] = set()
    app.cleanup_ctx.append(runner_lifecycle)

    # Setup API routes
    setup_routes(app)

    # Serve static files
    if STATIC_DIR.exists():
        app.router.add_static('/static/', STATIC_DIR, name='static')

    # Serve generated output files (reports, logs)
    output_dir = Path(DEFAULT_OUTPUT_DIRECTORY)
    output_dir.mkdir(parents=True, exist_ok=True)
    app.router.add_static('/outputs/', output_dir, name='outputs')

    # Main page
    app.router.add_get('/', index_handler)
    app.router.add_post('/session', create_session_handler)

    return app


async def run_server(host='127.0.0.1', port=8088, token=None):
    """Start the web server (async, runs within existing event loop)."""
    if host not in ('127.0.0.1', 'localhost', '::1'):
        raise ValueError(
            'The built-in server only accepts loopback addresses. '
            'Use an SSH tunnel for remote access.'
        )
    if token is not None and (not isinstance(token, str) or not token.strip()):
        raise ValueError('The access token must not be empty')
    lock_owner = _acquire_server_lock()
    runner = None
    try:
        generated_token = token is None
        token = token if token is not None else secrets.token_urlsafe(32)
        LOG.info(f'Starting iact3 web server on {host}:{port}')
        if generated_token:
            _print_access_token(token)
        app = create_app(token=token)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host, port)
        await site.start()
        LOG.info(f'Web server is running at http://{host}:{port}')
        try:
            await asyncio.Event().wait()  # run forever
        except asyncio.CancelledError:
            pass
    finally:
        if runner is not None:
            await runner.cleanup()
        _release_server_lock(lock_owner)
