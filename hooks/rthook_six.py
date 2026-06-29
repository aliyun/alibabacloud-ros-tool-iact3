import logging
import sys
import types

_LOG = logging.getLogger(__name__)


def _patch_vendored_six(prefix):
    """Pre-populate sys.modules for vendored six.moves virtual modules."""
    moves = types.ModuleType(f'{prefix}.moves')
    moves.__path__ = []
    moves.__package__ = f'{prefix}.moves'
    sys.modules[f'{prefix}.moves'] = moves

    # urllib subpackage
    moves_urllib = types.ModuleType(f'{prefix}.moves.urllib')
    moves_urllib.__path__ = []
    moves_urllib.__package__ = f'{prefix}.moves.urllib'
    sys.modules[f'{prefix}.moves.urllib'] = moves_urllib

    import urllib.parse, urllib.error, urllib.request

    moves_urllib.parse = urllib.parse
    sys.modules[f'{prefix}.moves.urllib.parse'] = urllib.parse
    moves_urllib.error = urllib.error
    sys.modules[f'{prefix}.moves.urllib.error'] = urllib.error
    moves_urllib.request = urllib.request
    sys.modules[f'{prefix}.moves.urllib.request'] = urllib.request

    # http modules
    import http.client

    sys.modules[f'{prefix}.moves.http_client'] = http.client
    moves.http_client = http.client

    from http import cookiejar

    sys.modules[f'{prefix}.moves.http_cookiejar'] = cookiejar
    moves.http_cookiejar = cookiejar

    from http import cookies

    sys.modules[f'{prefix}.moves.http_cookies'] = cookies
    moves.http_cookies = cookies

    # queue
    import queue

    sys.modules[f'{prefix}.moves.queue'] = queue
    moves.queue = queue

    # io
    import io

    moves.StringIO = io.StringIO
    moves.cStringIO = io.StringIO

    # configparser
    import configparser

    sys.modules[f'{prefix}.moves.configparser'] = configparser
    moves.configparser = configparser

    # builtins
    moves.range = range
    moves.zip = zip
    moves.map = map
    moves.filter = filter
    moves.input = input
    moves.intern = sys.intern
    moves.reduce = __import__('functools').reduce


_VENDORED_SIX_PREFIXES = [
    'aliyunsdkcore.vendored.six',
    'aliyunsdkcore.vendored.requests.packages.urllib3.packages.six',
]

for _prefix in _VENDORED_SIX_PREFIXES:
    try:
        _patch_vendored_six(_prefix)
    except Exception as _exc:
        _LOG.critical('Failed to patch vendored six at %s: %s', _prefix, _exc)
        raise
