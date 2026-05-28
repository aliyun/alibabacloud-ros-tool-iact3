import sys


def _fast_version():
    from iact3 import __version__
    if getattr(sys, 'frozen', False):
        print(__version__)
        return
    try:
        from importlib.metadata import version, PackageNotFoundError
        try:
            print(version('alibabacloud-ros-iact3'))
        except PackageNotFoundError:
            print(__version__)
    except Exception:
        print(__version__)


def _fast_help():
    # MAINTENANCE: This help text is a static copy of argparse output for fast startup.
    # When adding/removing commands or global options, update this text AND iact3/cli.py.
    from iact3.util import get_program_name
    prog = get_program_name('iact3')
    print(f"""usage: {prog} [args] <command> [args] [subcommand] [args]

Infrastructure as Code Templates Validation Test.

options:
  -h, --help            show this help message and exit
  -v, --version         show program's version number and exit
  -q, --quiet           reduce output to the minimum
  -d, --debug           adds debug output and tracebacks
  --profile _PROFILE    set the default profile used.
  --log-prefix _LOG_PREFIX
                        set the log prefix.

commands:
  base - Create or delete or list basic resources which includes vpc,security group and several switches for testing
  cost - Give the price of the templates.
  delete - Manually clean up the stacks which were created by Iact3
  list - List stacks which were created by Iact3 for all regions.
  policy - Get policies of the templates.
  preview - Preview resources of templates.
  test - Performs functional tests on IaC templates.
  validate - Validate the templates.""")


def _should_fast_path(args):
    if not args:
        return 'help'
    if args[0] in ('-v', '--version'):
        return 'version'
    if any(a in ('-h', '--help') for a in args):
        return 'help'
    return None


def sync_run():
    action = _should_fast_path(sys.argv[1:])
    if action == 'version':
        _fast_version()
        return
    if action == 'help':
        _fast_help()
        return
    from iact3.main import sync_run as _sync_run
    _sync_run()


if __name__ == "__main__":
    sync_run()
