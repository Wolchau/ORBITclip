"""Verified HTTPS for ORBITclip public relay connections.

Explicitly uses the current Mozilla CA roots shipped by certifi. This prevents
Python.org macOS builds without configured root certificates from failing with
CERTIFICATE_VERIFY_FAILED, without weakening TLS or hostname verification.

Pinned HTTPS for private hosts remains handled separately by kinetic_transport.
"""

import ssl
import urllib.request
import urllib.error
from functools import lru_cache

import certifi


@lru_cache(maxsize=1)
def public_ssl_context():
    context = ssl.create_default_context(cafile=certifi.where())
    # Explicit defense-in-depth. Both flags are already the default.
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    return context


def public_urlopen(request, timeout=9):
    """Make a normal CA/hostname-verified HTTPS request (or local HTTP request)."""
    try:
        return urllib.request.urlopen(request, timeout=timeout, context=public_ssl_context())
    except urllib.error.URLError as exc:
        if isinstance(getattr(exc, 'reason', None), ssl.SSLCertVerificationError):
            raise ConnectionError(
                'SSL: сертификат сервера не подтверждён. '
                'Обнови certifi; проверь дату/время и VPN/прокси. '
                'Проверка HTTPS остаётся включённой.'
            ) from exc
        raise
