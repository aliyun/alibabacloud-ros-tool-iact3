import logging

LOG = logging.getLogger(__name__)


class PrintMsg:
    header = "\x1b[1;41;0m"
    highlight = "\x1b[0;30;47m"
    name_color = "\x1b[0;37;44m"
    aqua = "\x1b[0;30;46m"
    green = "\x1b[0;30;42m"
    white = "\x1b[0;30;47m"
    orange = "\x1b[0;30;43m"
    red = "\x1b[0;30;41m"
    rst_color = "\x1b[0m"
    blod = "\033[1m"
    text_red = "\033[31m"
    text_green = "\033[32m"
    text_red_background_write = "\033[31;47m"
    CRITICAL = "{}[FATAL  ]{} : ".format(red, rst_color)
    ERROR = "{}[ERROR  ]{} : ".format(red, rst_color)
    DEBUG = "{}[DEBUG  ]{} : ".format(aqua, rst_color)
    PASS = "{}[PASS   ]{} : ".format(green, rst_color)
    INFO = "{}[INFO   ]{} : ".format(white, rst_color)
    WARNING = "{}[WARN   ]{} : ".format(orange, rst_color)
    left_top = "\u250f"
    right_top = "\u2513"
    left = "\u2523"
    left_bottom = "\u2517"
    right = "\u252B"
    right_bottom = "\u251B"
    top = "\u2501"


class AppFilter(logging.Filter):
    def filter(self, record):
        default = PrintMsg.INFO
        record.color_loglevel = getattr(PrintMsg, record.levelname, default)
        return True


def init_cli_logger(loglevel=None, log_prefix=None, logger=None):
    if logger:
        log = logger
    else:
        log = logging.getLogger(__package__)

    if log.hasHandlers():
        for handler in log.handlers:
            log.removeHandler(handler)

    cli_handler = logging.StreamHandler()
    fmt = "%(asctime)s %(color_loglevel)s%(message)s"

    if log_prefix:
        fmt = f"%(asctime)s {log_prefix} %(color_loglevel)s%(message)s"

    formatter = logging.Formatter(fmt)
    cli_handler.setFormatter(formatter)
    cli_handler.addFilter(AppFilter())
    log.addHandler(cli_handler)
    if loglevel:
        loglevel = getattr(logging, loglevel.upper(), 20)
        log.setLevel(loglevel)
    return log
