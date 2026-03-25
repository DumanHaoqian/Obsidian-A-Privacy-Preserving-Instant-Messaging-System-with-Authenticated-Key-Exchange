import base64
import hashlib
import hmac
import secrets
import time
from typing import Optional

from argon2 import PasswordHasher

_password_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except Exception:
        return False


def generate_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def generate_otp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode('ascii').rstrip('=')


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


def verify_totp(secret: str, code: str, window: int = 1) -> bool:
    now = int(time.time())
    for offset in range(-window, window + 1):
        if secrets.compare_digest(totp_now(secret, t=now + offset * 30), code):
            return True
    return False


def otp_uri(secret: str, username: str, issuer: str = 'COMP3334-IM') -> str:
    return f'otpauth://totp/{issuer}:{username}?secret={secret}&issuer={issuer}'
