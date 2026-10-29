import asyncio
import logging
import sys
from types import SimpleNamespace
from unittest import mock

import pytest

from iact3 import __main__ as entry
from iact3 import main
from iact3 import __version__
from tests.common import AsyncTestCase


def test_fast_path_dispatch(monkeypatch):
    calls = []
    monkeypatch.setattr(entry, '_fast_version', lambda: calls.append('version'))
    monkeypatch.setattr(entry, '_fast_help', lambda: calls.append('help'))
    monkeypatch.setattr(main, 'sync_run', lambda: calls.append('normal'))
    for args in (['iact3', '-v'], ['iact3'], ['iact3', 'test']):
        monkeypatch.setattr(sys, 'argv', args)
        entry.sync_run()
    assert calls == ['version', 'help', 'normal']


def test_version_falls_back_when_frozen(monkeypatch, capsys):
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    assert main.get_installed_version() == __version__
    entry._fast_version()
    assert capsys.readouterr().out.strip() == __version__


def test_sync_run_executes_and_restores_signal(monkeypatch):
    import signal
    calls = []
    before = signal.getsignal(signal.SIGINT)
    async def run():
        calls.append('ran')
    monkeypatch.setattr(main, 'run', run)
    main.sync_run()
    assert calls == ['ran']
    assert signal.getsignal(signal.SIGINT) == before


def test_setup_logging_and_tracebacks():
    assert main._print_tracebacks('DEBUG')
    assert not main._print_tracebacks('INFO')
    assert main._setup_logging(['iact3', '--debug']) in ('DEBUG', logging.DEBUG)


class TestMainRun(AsyncTestCase):
    async def test_run_applies_profile_and_log_prefix(self):
        captured = {}
        class FakeCli:
            parsed_args = SimpleNamespace(_profile='profile', _log_prefix='prefix')
            def __init__(self, *args):
                pass
            def parse(self, args):
                captured['args'] = args
            async def run(self):
                captured['ran'] = True
        with mock.patch.object(main, 'CliCore', FakeCli), \
             mock.patch.object(main, 'get_installed_version', return_value='1'), \
             mock.patch.object(main, 'init_cli_logger') as logger, \
             mock.patch.object(main, 'GLOBAL_ARGS', SimpleNamespace(ARGS=[], profile=None, log_prefix=None)), \
             mock.patch.object(sys, 'argv', ['iact3']):
            await main.run()
            self.assertEqual(captured, {'args': ['-h'], 'ran': True})
            self.assertEqual(main.GLOBAL_ARGS.profile, 'profile')
            self.assertEqual(main.GLOBAL_ARGS.log_prefix, 'prefix')
            logger.assert_called_once()

    async def test_error_exits_and_cancellation_propagates(self):
        with mock.patch.object(main, 'get_installed_version', side_effect=ValueError('broken')), \
             mock.patch.object(sys, 'argv', ['iact3', '--debug']):
            with self.assertRaises(SystemExit) as error:
                await main.run()
            self.assertEqual(error.exception.code, 1)
        with mock.patch.object(main, 'get_installed_version', side_effect=asyncio.CancelledError()), \
             mock.patch.object(sys, 'argv', ['iact3']):
            with self.assertRaises(asyncio.CancelledError):
                await main.run()


def test_version_lookup_uses_python37_backport_and_fallback(monkeypatch, capsys):
    class NotFound(Exception):
        pass
    module = SimpleNamespace(version=lambda name: '9.8.7', PackageNotFoundError=NotFound)
    with monkeypatch.context() as patch:
        patch.setitem(sys.modules, 'importlib_metadata', module)
        patch.setattr(sys, 'version_info', (3, 7, 0))
        assert main.get_installed_version() == '9.8.7'
        entry._fast_version()
        assert capsys.readouterr().out.strip() == '9.8.7'
        def missing(name):
            raise NotFound(name)
        module.version = missing
        assert main.get_installed_version() == __version__
        entry._fast_version()
        assert capsys.readouterr().out.strip() == __version__


def test_version_lookup_handles_unexpected_metadata_errors(monkeypatch, capsys):
    class NotFound(Exception):
        pass
    def broken(name):
        raise ValueError('bad metadata')
    module = SimpleNamespace(version=broken, PackageNotFoundError=NotFound)
    with monkeypatch.context() as patch:
        patch.setitem(sys.modules, 'importlib_metadata', module)
        patch.setattr(sys, 'version_info', (3, 7, 0))
        assert main.get_installed_version() == __version__
        entry._fast_version()
        assert capsys.readouterr().out.strip() == __version__
