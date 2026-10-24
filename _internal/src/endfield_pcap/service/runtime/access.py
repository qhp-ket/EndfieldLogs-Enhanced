"""Require an explicit capability for browser WebSocket clients.

Native loopback clients without Origin remain compatible. This is a browser
cross-origin boundary, not an authentication boundary against local programs.
"""
from hmac import compare_digest
from collections.abc import Mapping
from urllib.parse import parse_qs, urlsplit


def browser_request_allowed(request, token, *, path=None):
    # asyncio passes a Request; legacy passes the Headers directly. An unknown
    # shape must never be confused with a recognized request without Origin.
    headers = getattr(request, 'headers', request)
    if not isinstance(headers, Mapping):
        return False
    if hasattr(headers, 'get_all'):
        origins = headers.get_all('Origin')
    else:
        origins = [value for key, value in headers.items() if key.lower() == 'origin']
    if not origins:
        return True
    if len(origins) != 1 or not isinstance(token, str) or len(token) < 43:
        return False
    path = getattr(request, 'path', None) if path is None else path
    if not isinstance(path, str):
        return False
    values = parse_qs(urlsplit(path).query, keep_blank_values=True).get('access_token', [])
    return (len(values) == 1 and len(values[0]) <= 256
            and compare_digest(values[0].encode('utf8'), token.encode('utf8')))
