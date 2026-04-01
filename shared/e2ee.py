from __future__ import annotations

import base64
import json
import secrets
from hashlib import sha256
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

ALGORITHM = 'x25519-hkdf-sha256-aesgcm'
ENVELOPE_VERSION = 1
E2EE_MESSAGE_TYPE = 'e2ee_text'
DEFAULT_DEVICE_ID = 'cli-device-1'
HKDF_INFO = b'comp3334-im-e2ee-v1'


class E2EEError(RuntimeError):
    pass


class EnvelopeError(E2EEError):
    pass


class DecryptionError(E2EEError):
    pass


class TrustError(E2EEError):
    pass


def _b64encode(value: bytes) -> str:
    return base64.b64encode(value).decode('ascii')


def _b64decode(value: str, label: str = 'base64 data') -> bytes:
    try:
        return base64.b64decode(value.encode('ascii'), validate=True)
    except Exception as exc:
        raise EnvelopeError(f'invalid base64 data in {label}') from exc


def _load_private_key(private_key_b64: str) -> X25519PrivateKey:
    try:
        return X25519PrivateKey.from_private_bytes(_b64decode(private_key_b64, 'local private key'))
    except Exception as exc:
        raise E2EEError('invalid local private key material') from exc


def _load_public_key(public_key_b64: str) -> X25519PublicKey:
    try:
        return X25519PublicKey.from_public_bytes(_b64decode(public_key_b64, 'peer public key'))
    except Exception as exc:
        raise E2EEError('invalid peer public key material') from exc


def public_key_fingerprint(public_key_b64: str) -> str:
    return sha256(_b64decode(public_key_b64, 'public key fingerprint')).hexdigest()


def generate_identity_keypair(device_id: str = DEFAULT_DEVICE_ID) -> dict[str, str]:
    private_key = X25519PrivateKey.generate()
    public_key = private_key.public_key()
    private_key_b64 = _b64encode(
        private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    public_key_b64 = _b64encode(
        public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    )
    return {
        'device_id': device_id,
        'private_key': private_key_b64,
        'public_key': public_key_b64,
        'fingerprint': public_key_fingerprint(public_key_b64),
    }


def build_aad(
    *,
    from_username: str,
    to_username: str,
    sender_device_id: str,
    message_type: str,
) -> bytes:
    payload = {
        'from_username': from_username.lower(),
        'message_type': message_type,
        'sender_device_id': sender_device_id,
        'to_username': to_username.lower(),
    }
    return json.dumps(payload, separators=(',', ':'), sort_keys=True).encode('utf-8')


def _derive_content_key(shared_secret: bytes, salt: bytes) -> bytes:
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        info=HKDF_INFO,
    )
    return hkdf.derive(shared_secret)


def parse_envelope(envelope_text: str) -> dict[str, Any]:
    try:
        payload = json.loads(envelope_text)
    except json.JSONDecodeError as exc:
        raise EnvelopeError('encrypted message is not valid JSON') from exc
    if not isinstance(payload, dict):
        raise EnvelopeError('encrypted message must be a JSON object')
    required = {'alg', 'ciphertext', 'nonce', 'salt', 'sender_device_id', 'v'}
    missing = [key for key in required if key not in payload]
    if missing:
        raise EnvelopeError(f'encrypted envelope missing fields: {", ".join(sorted(missing))}')
    if payload['v'] != ENVELOPE_VERSION:
        raise EnvelopeError(f'unsupported encrypted envelope version: {payload["v"]}')
    if payload['alg'] != ALGORITHM:
        raise EnvelopeError(f'unsupported encryption algorithm: {payload["alg"]}')
    return payload


def encrypt_message(
    plaintext: str,
    *,
    sender_private_key_b64: str,
    recipient_public_key_b64: str,
    from_username: str,
    to_username: str,
    sender_device_id: str = DEFAULT_DEVICE_ID,
    message_type: str = E2EE_MESSAGE_TYPE,
) -> str:
    sender_private_key = _load_private_key(sender_private_key_b64)
    recipient_public_key = _load_public_key(recipient_public_key_b64)
    salt = secrets.token_bytes(16)
    nonce = secrets.token_bytes(12)
    shared_secret = sender_private_key.exchange(recipient_public_key)
    content_key = _derive_content_key(shared_secret, salt)
    aad = build_aad(
        from_username=from_username,
        to_username=to_username,
        sender_device_id=sender_device_id,
        message_type=message_type,
    )
    ciphertext = AESGCM(content_key).encrypt(nonce, plaintext.encode('utf-8'), aad)
    envelope = {
        'v': ENVELOPE_VERSION,
        'alg': ALGORITHM,
        'sender_device_id': sender_device_id,
        'salt': _b64encode(salt),
        'nonce': _b64encode(nonce),
        'ciphertext': _b64encode(ciphertext),
    }
    return json.dumps(envelope, separators=(',', ':'), sort_keys=True)


def decrypt_message(
    envelope_text: str,
    *,
    local_private_key_b64: str,
    peer_public_key_b64: str,
    from_username: str,
    to_username: str,
    message_type: str = E2EE_MESSAGE_TYPE,
) -> str:
    envelope = parse_envelope(envelope_text)
    local_private_key = _load_private_key(local_private_key_b64)
    peer_public_key = _load_public_key(peer_public_key_b64)
    salt = _b64decode(envelope['salt'], 'encrypted envelope salt')
    nonce = _b64decode(envelope['nonce'], 'encrypted envelope nonce')
    ciphertext = _b64decode(envelope['ciphertext'], 'encrypted envelope ciphertext')
    shared_secret = local_private_key.exchange(peer_public_key)
    content_key = _derive_content_key(shared_secret, salt)
    aad = build_aad(
        from_username=from_username,
        to_username=to_username,
        sender_device_id=envelope['sender_device_id'],
        message_type=message_type,
    )
    try:
        plaintext = AESGCM(content_key).decrypt(nonce, ciphertext, aad)
    except Exception as exc:
        raise DecryptionError('encrypted message could not be decrypted with the trusted peer key') from exc
    try:
        return plaintext.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise DecryptionError('encrypted message decrypted to invalid UTF-8') from exc
