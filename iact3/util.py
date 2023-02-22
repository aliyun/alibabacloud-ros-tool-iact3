import logging
import os
import re
import sys
import uuid


LOG = logging.getLogger(__name__)


FIRST_CAP_RE = re.compile("(.)([A-Z][a-z]+)")
ALL_CAP_RE = re.compile("([a-z0-9])([A-Z])")


def exit_with_code(code, msg=""):
    if msg:
        LOG.error(msg)
    sys.exit(code)


def make_dir(path, ignore_exists=True):
    path = os.path.abspath(path)
    if ignore_exists and os.path.isdir(path):
        return
    os.makedirs(path)


def pascal_to_snake(pascal):
    sub = ALL_CAP_RE.sub(r"\1_\2", pascal)
    return ALL_CAP_RE.sub(r"\1_\2", sub).lower()


def generate_client_token_ex(prefix: str, suffix: str):
    if prefix:
        t = [prefix]
    else:
        t = []
    t.append(str(uuid.uuid1())[:-13])
    t.append(suffix)
    r = '_'.join(t)
    if len(r) > 64:
        r = r[:64]
    return r
