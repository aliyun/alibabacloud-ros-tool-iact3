import asyncio
import signal
import sys

from iact3 import cli_modules
from iact3.cli import CliCore, GLOBAL_ARGS, _get_log_level
from iact3.generate_params import IAC_PACKAGE_NAME, IAC_NAME
from iact3.logger import init_cli_logger
from iact3.util import exit_with_code, get_program_name

LOG = init_cli_logger(loglevel="ERROR")
DESCRIPTION = 'Infrastructure as Code Templates Validation Test.'
DEFAULT_PROFILE = '.'


def sync_run():
    """
    Run the CLI synchronously.
    """
    from iact3.exceptions import Iact3Exception

    if sys.version_info[0] == 3 and sys.version_info[1] >= 7:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        task = loop.create_task(run())
        interrupted = [False]
        previous_sigint_handler = signal.getsignal(signal.SIGINT)

        def cancel_main_task(_signum, _frame):
            interrupted[0] = True
            loop.call_soon_threadsafe(task.cancel)

        signal.signal(signal.SIGINT, cancel_main_task)
        try:
            loop.run_until_complete(task)
        except asyncio.CancelledError:
            pass
        finally:
            signal.signal(signal.SIGINT, previous_sigint_handler)
            pending = [
                pending_task
                for pending_task in asyncio.all_tasks(loop)
                if not pending_task.done()
            ]
            for pending_task in pending:
                pending_task.cancel()
            if pending:
                loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
            loop.close()
        if interrupted[0]:
            raise SystemExit(130)
    else:
        raise Iact3Exception("Please use Python 3.7+")


async def run():
    log_level = _setup_logging(sys.argv)
    args = sys.argv[1:]
    if not args:
        args.append('-h')
    try:
        version = get_installed_version()
        cli = CliCore(get_program_name(IAC_NAME), cli_modules, DESCRIPTION, version, GLOBAL_ARGS.ARGS)
        cli.parse(args)
        _default_profile = cli.parsed_args.__dict__.get('_profile')
        if _default_profile:
            GLOBAL_ARGS.profile = _default_profile

        _log_prefix = cli.parsed_args.__dict__.get('_log_prefix')
        if _log_prefix:
            GLOBAL_ARGS.log_prefix = _log_prefix
            init_cli_logger(log_prefix=_log_prefix, logger=LOG)
        await cli.run()
    except asyncio.CancelledError:
        raise
    except Exception as e:
        LOG.error('%s %s', e.__class__.__name__, str(e), exc_info=_print_tracebacks(log_level))
        exit_with_code(1)


def _setup_logging(args, exit_func=exit_with_code):
    log_level = _get_log_level(args, exit_func=exit_func)
    LOG.setLevel(log_level)
    return log_level


def _print_tracebacks(log_level):
    return log_level == 'DEBUG'


def get_installed_version():
    from iact3 import __version__

    if getattr(sys, 'frozen', False):
        return __version__
    try:
        if sys.version_info >= (3, 8):
            from importlib.metadata import version, PackageNotFoundError
        else:
            importlib_metadata = __import__('importlib_metadata')
            version = importlib_metadata.version
            PackageNotFoundError = importlib_metadata.PackageNotFoundError

        try:
            return version(IAC_PACKAGE_NAME)
        except PackageNotFoundError:
            return __version__
    except Exception:
        return __version__
