"""Verification of Meta's X-Hub-Signature-256 header.

Meta signs every webhook POST with HMAC-SHA256 over the *raw* request body, keyed with the
app secret. We must verify against the exact bytes received, before any JSON parsing.
"""

import hashlib
import hmac

_PREFIX = "sha256="


def compute_signature(body: bytes, app_secret: str) -> str:
    digest = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return f"{_PREFIX}{digest}"


def is_valid_signature(body: bytes, header_value: str | None, app_secret: str) -> bool:
    if not header_value or not header_value.startswith(_PREFIX):
        return False
    expected = compute_signature(body, app_secret)
    return hmac.compare_digest(expected, header_value)
