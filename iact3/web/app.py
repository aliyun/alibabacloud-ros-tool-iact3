# -*- coding: utf-8 -*-
import logging
import os
from pathlib import Path

from aiohttp import web

from iact3.config import DEFAULT_OUTPUT_DIRECTORY
from iact3.web.routes import setup_routes
from iact3.web.runner import TestRunner

LOG = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / 'static'

# Token for API authentication when binding to non-local addresses.
# When set, all /api/ requests must include "Authorization: Bearer <token>".
_API_TOKEN = None


async def index_handler(request):
    """Serve the main SPA page."""
    resp = web.FileResponse(STATIC_DIR / 'index.html')
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return resp


@web.middleware
async def no_cache_middleware(request, handler):
    """Prevent browser caching for static files during development."""
    response = await handler(request)
    if request.path.startswith('/static/'):
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return response


@web.middleware
async def auth_middleware(request, handler):
    """Require bearer token for API and output routes when a token is configured.

    When the server is bound to a non-local address, a token should be set
    via --token to prevent unauthorised access to cloud operations.
    API routes (/api/) must send the token via the Authorization header.
    Output routes (/outputs/) may also send the token via a ?token= query
    parameter so that direct browser navigation (e.g. report links) works.
    """
    if _API_TOKEN and (request.path.startswith('/api/') or request.path.startswith('/outputs/')):
        auth_header = request.headers.get('Authorization', '')
        # For /outputs/ paths, also accept ?token= query parameter to support
        # direct browser navigation (report links cannot set headers).
        query_token = request.query.get('token', '') if request.path.startswith('/outputs/') else ''
        if auth_header != f'Bearer {_API_TOKEN}' and query_token != _API_TOKEN:
            if request.path.startswith('/api/'):
                return web.json_response(
                    {'error': 'Unauthorized', 'code': 'UNAUTHORIZED'},
                    status=401,
                )
            return web.Response(status=401, text='Unauthorized')
    return await handler(request)


def create_app():
    """Create and configure the web application."""
    middlewares = [no_cache_middleware]
    if _API_TOKEN:
        middlewares.append(auth_middleware)
    app = web.Application(middlewares=middlewares)
    app['runner'] = TestRunner()

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

    return app


async def run_server(host='127.0.0.1', port=8088, token=None):
    """Start the web server (async, runs within existing event loop)."""
    import asyncio
    global _API_TOKEN
    _API_TOKEN = token
    LOG.info(f'Starting iact3 web server on {host}:{port}')
    app = create_app()

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
        await runner.cleanup()
