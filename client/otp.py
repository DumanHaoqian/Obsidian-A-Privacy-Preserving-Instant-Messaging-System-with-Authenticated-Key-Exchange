import base64
import hashlib
import hmac
import time
from typing import Optional


def _normalize_secret(secret: str) -> bytes:
    padding = '=' * ((8 - len(secret) % 8) % 8)
    return base64.b32decode(secret + padding, casefold=True)


def totp_now(secret: str, interval: int = 30, digits: int = 6, t: Optional[int] = None) -> str:
    if t is None:
        t = int(time.time())
    counter = t // interval
    key = _normalize_secret(secret)
    msg = counter.to_bytes(8, 'big')
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = ((digest[offset] & 0x7F) << 24) | ((digest[offset + 1] & 0xFF) << 16) | ((digest[offset + 2] & 0xFF) << 8) | (digest[offset + 3] & 0xFF)
    return str(code % (10**digits)).zfill(digits)
