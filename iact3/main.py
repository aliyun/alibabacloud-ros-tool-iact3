import signal
import sys

from pkg_resources import get_distribution

from iact3 import cli_modules
from iact3.cli import CliCore, GLOBAL_ARGS, _get_log_level
from iact3.generate_params import IAC_PACKAGE_NAME, IAC_NAME
from iact3.logger import init_cli_logger
from iact3.util import exit_with_code

LOG = init_cli_logger(loglevel="ERROR")
DESCRIPTION = 'Infrastructure as Code Templates Validation Test.'
DEFAULT_PROFILE = '.'


def sync_run():
    """
    Run the CLI synchronously.
    """
    import asyncio
    from iact3.exceptions import Iact3Exception
    if sys.version_info[0] == 3 and sys.version_info[1] >= 7:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(run())
        finally:
            loop.close()
    else:
        raise Iact3Exception("Please use Python 3.7+")


async def run():
    signal.signal(signal.SIGINT, _sigint_handler)
    log_level = _setup_logging(sys.argv)
    args = sys.argv[1:]
    if not args:
        args.append('-h')
    try:
        version = get_installed_version()
        cli = CliCore(IAC_NAME, cli_modules, DESCRIPTION, version, GLOBAL_ARGS.ARGS)
        cli.parse(args)
        _default_profile = cli.parsed_args.__dict__.get('_profile')
        if _default_profile:
            GLOBAL_ARGS.profile = _default_profile

        _log_prefix = cli.parsed_args.__dict__.get('_log_prefix')
        if _log_prefix:
            GLOBAL_ARGS.log_prefix = _log_prefix
            init_cli_logger(log_prefix=_log_prefix, logger=LOG)
        await cli.run()
    except Exception as e:
        LOG.error(
            '%s %s', e.__class__.__name__, str(e), exc_info=_print_tracebacks(log_level)
        )
        exit_with_code(1)


def _setup_logging(args, exit_func=exit_with_code):
    log_level = _get_log_level(args, exit_func=exit_func)
    LOG.setLevel(log_level)
    return log_level


def _print_tracebacks(log_level):
    return log_level == 'DEBUG'


def get_installed_version():
    try:
        return get_distribution(IAC_PACKAGE_NAME).version
    except Exception:
        return '[local source] no pip module installed'


def _sigint_handler(signum, frame):
    LOG.debug(f'SIGNAL {signum} caught at {frame}')
    exit_with_code(1)
