# -*- coding: utf-8 -*-
import logging
import os
from pathlib import Path

from aiohttp import web

from iact3.web.routes import setup_routes
from iact3.web.runner import TestRunner

LOG = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / 'static'


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


def create_app():
    """Create and configure the web application."""
    app = web.Application(middlewares=[no_cache_middleware])
    app['runner'] = TestRunner()

    # Setup API routes
    setup_routes(app)

    # Serve static files
    if STATIC_DIR.exists():
        app.router.add_static('/static/', STATIC_DIR, name='static')

    # Main page
    app.router.add_get('/', index_handler)

    return app


async def run_server(host='0.0.0.0', port=8088):
    """Start the web server (async, runs within existing event loop)."""
    import asyncio
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
