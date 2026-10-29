import argparse
import asyncio
import logging
import types
from unittest import mock

import pytest

from iact3.cli import CliCore, CustomParser, GlobalArgs, LOG, SetVerbosity, _get_log_level


def test_log_levels_and_conflicting_options():
    assert _get_log_level([]) == 'INFO'
    assert _get_log_level(['-d']) == 'DEBUG'
    assert _get_log_level(['--quiet']) == 'ERROR'
    exit_func = mock.Mock(side_effect=ValueError('conflicting options'))
    with pytest.raises(ValueError, match='conflicting options'):
        _get_log_level(['--debug', '-q'], exit_func=exit_func)
    exit_func.assert_called_once_with(1, '--debug and --quiet cannot be specified simultaneously')


def test_verbosity_and_global_args():
    previous_level = LOG.level
    try:
        action = SetVerbosity(option_strings=['--quiet'], dest='quiet', nargs=0)
        action(None, argparse.Namespace(), None, '--quiet')
        assert LOG.level == logging.ERROR
    finally:
        LOG.setLevel(previous_level)
    args = GlobalArgs()
    args.profile = 'custom'
    args.log_prefix = 'prefix'
    assert (args.profile, args.log_prefix) == ('custom', 'prefix')


def test_parser_error_prints_help(capsys):
    parser = CustomParser(prog='example')
    with pytest.raises(SystemExit) as exc:
        parser.error('bad input')
    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert 'error: bad input' in captured.err
    assert 'usage: example' in captured.out


def test_parameter_help_and_long_form_option():
    class Plugin:
        def __init__(self, required, optional_value='default', enabled: bool = False):
            """Example plugin.

            :param optional_value: a value
            """

    core = object.__new__(CliCore)
    key = Plugin.__init__.__qualname__ + '.optional-value'
    with mock.patch.object(CliCore, 'longform_required', [key]):
        params = core._get_params(Plugin.__init__)
    assert params[0][0] == ['required']
    assert params[1][0] == ['--optional-value']
    assert params[1][1]['help'] == 'a value'
    assert params[2][1]['action'] == 'store_true'
    assert CliCore._get_param_help(lambda: None, 'missing') == ''
    assert CliCore._get_help(lambda: None) == ''
    assert CliCore._import_plugin_module('ArgumentParser', 'argparse') is argparse.ArgumentParser


def test_run_dispatches_sync_and_async_subcommands_and_create():
    class Plugin:
        @classmethod
        async def create(cls, value):
            return 'created ' + value

        def sync(self, value):
            return 'sync ' + value

        async def async_method(self, value):
            return 'async ' + value

    core = object.__new__(CliCore)
    core._modules = {'plugin': Plugin}
    for subcommand, expected in [(None, 'created x'), ('sync', 'sync x'), ('async_method', 'async x')]:
        values = {'_command': 'plugin', 'value': 'x'}
        if subcommand:
            values['_subcommand'] = subcommand
        core.parsed_args = types.SimpleNamespace(**values)
        assert asyncio.run(core.run()) == expected


def test_parser_builds_commands_with_required_and_optional_arguments(capsys):
    class Example:
        """Example command."""
        def __init__(self, region='cn-a'):
            """Configure the command.

            :param region: selected region
            """
        def run(self, name, count: int = 1):
            """Run example.

            :param name: target name
            """
            return name, count
    class NoDescription:
        def __init__(self):
            pass
    module = types.ModuleType('commands')
    module.Example = Example
    module.NoDescription = NoDescription
    core = CliCore('demo', module, 'A demonstration', version='1.0')
    parsed = core.parse(['example', '--region', 'cn-b', 'run', 'target', '--count', '2'])
    assert parsed._command == 'example'
    assert parsed._subcommand == 'run'
    assert (parsed.region, parsed.name, parsed.count) == ('cn-b', 'target', 2)
    assert 'nodescription' in core.parser.format_help()
    with pytest.raises(SystemExit) as exc:
        core.parse(['--version'])
    assert exc.value.code == 0
    assert '1.0' in capsys.readouterr().out
    with pytest.raises(SystemExit) as exc:
        core.parse([])
    assert exc.value.code == 2


def test_longform_decorator_records_normalized_parameter_name():
    class Example:
        def __init__(self, project_path=None):
            pass
    with mock.patch.object(CliCore, 'longform_required', []):
        decorated = CliCore.longform_param_required('project_path')(Example.__init__)
        assert decorated is Example.__init__
        assert CliCore.longform_required == [Example.__qualname__ + '.project-path']


def test_usage_uses_explicit_option_groups_and_optional_version():
    module = types.ModuleType('commands')
    core = CliCore('demo', module, 'A demonstration')
    usage = core._build_usage({'command': 'run', 'subcommand': '', 'global_opts': '--global ',
                               'command_opts': '--command', 'subcommand_opts': ''})
    assert usage == 'demo --global run --command '
    assert '--version' not in core.parser.format_help()
