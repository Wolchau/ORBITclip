"""Pinned HTTPS for private self-signed KINETIC hosts.

Normal public HTTPS keeps normal CA verification. Pinned TLS explicitly compares
SHA-256 of the peer's certificate on the *same* connection before sending any
bearer token, pairing secret, or ciphertext. The pin arrives in the shared invite.
"""
import hashlib
import http.client
import ipaddress
import ssl
from urllib.parse import urlparse


def valid_pin(pin):
    return isinstance(pin, str) and len(pin) == 64 and all(c in '0123456789abcdefABCDEF' for c in pin)


def pinned_request(url, method, path, data, headers, pin, timeout=8, max_bytes=9*1024*1024):
    if not valid_pin(pin):
        raise ValueError('Неверный отпечаток TLS-сертификата в приглашении')
    parsed = urlparse(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Закреплённый сертификат допустим только для HTTPS')
    # A direct client goes to the given IP without implicit proxies.
    # This is intentionally more restrictive than a public HTTPS relay.
    try:
        ipaddress.ip_address(parsed.hostname)
    except ValueError as exc:
        raise ValueError('Для прямого HTTPS используй IP-адрес хоста') from exc
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    conn = http.client.HTTPSConnection(parsed.hostname, parsed.port or 443,
                                       context=context, timeout=timeout)
    try:
        conn.connect()
        actual = hashlib.sha256(conn.sock.getpeercert(binary_form=True)).hexdigest()
        if actual.lower() != pin.lower():
            raise ssl.SSLError('TLS-отпечаток хоста не совпадает: соединение отменено')
        conn.request(method, path, body=data, headers=headers)
        resp = conn.getresponse()
        if int(resp.getheader('Content-Length') or 0) > max_bytes:
            raise ValueError('Ответ сервера слишком большой')
        raw = resp.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise ValueError('Ответ сервера слишком большой')
        if not 200 <= resp.status < 300:
            raise RuntimeError('Сервер ответил HTTP ' + str(resp.status) + ': ' + raw[:140].decode('utf8','replace'))
        return raw
    finally:
        conn.close()
