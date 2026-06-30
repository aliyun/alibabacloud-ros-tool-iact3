"""iact3 — Infrastructure as Code Templates Validation Test for Alibaba Cloud ROS."""

__version__ = '0.1.14'

# --- Monkey-patch: Fix Tea SDK SSL bug on Python 3.12+ ---
# The Tea SDK (alibabacloud-tea) incorrectly uses ssl.Purpose.CLIENT_AUTH
# (a server-side context) for client HTTPS connections.  Python 3.12 with
# OpenSSL 3.x enforces this strictly and raises:
#   "Cannot create a client socket with a PROTOCOL_TLS_SERVER context"
# We wrap ssl.create_default_context to silently correct the Purpose.
import ssl as _ssl

_original_create_default_context = _ssl.create_default_context


def _patched_create_default_context(purpose=_ssl.Purpose.SERVER_AUTH, **kwargs):
    if purpose == _ssl.Purpose.CLIENT_AUTH:
        purpose = _ssl.Purpose.SERVER_AUTH
    return _original_create_default_context(purpose, **kwargs)


_ssl.create_default_context = _patched_create_default_context
