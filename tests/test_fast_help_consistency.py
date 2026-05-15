# -*- coding: utf-8 -*-
"""Verify _fast_help() in iact3.__main__ stays in sync with iact3.cli_modules."""
import inspect
import io
import unittest
from contextlib import redirect_stdout

from iact3 import cli_modules
from iact3.__main__ import _fast_help
from iact3.cli import CliCore


class TestFastHelpConsistency(unittest.TestCase):
    def setUp(self):
        captured = io.StringIO()
        with redirect_stdout(captured):
            _fast_help()
        self.text = captured.getvalue()
        self.commands = {
            name.lower(): cls
            for name, cls in inspect.getmembers(cli_modules, inspect.isclass)
        }

    def test_all_commands_listed(self):
        for cmd in self.commands:
            self.assertIn(
                f'{cmd} -',
                self.text,
                f'Command "{cmd}" missing from _fast_help() output. '
                f'Update iact3/__main__.py:_fast_help when changing commands.',
            )

    def test_command_descriptions_match(self):
        """Each command's docstring summary must appear verbatim in _fast_help."""
        for cmd, cls in self.commands.items():
            description = CliCore._get_help(cls)
            if not description:
                continue
            self.assertIn(
                description,
                self.text,
                f'Command "{cmd}" description "{description}" not found in '
                f'_fast_help() output. Sync iact3/__main__.py:_fast_help with '
                f'the class docstring in iact3/cli_modules/{cmd}.py.',
            )

    def test_global_options_listed(self):
        for opt in ('--quiet', '--debug', '--profile', '--log-prefix', '--version', '--help'):
            self.assertIn(opt, self.text, f'Global option {opt} missing from _fast_help()')


if __name__ == '__main__':
    unittest.main()
