from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from shared.e2ee import (
    DEFAULT_DEVICE_ID,
    DecryptionError,
    TrustError,
    decrypt_message,
    encrypt_message,
    generate_identity_keypair,
    public_key_fingerprint,
)


class ClientE2EEManager:
    def __init__(self, api: Any, state: dict[str, Any]) -> None:
        self.api = api
        self.state = state

    @staticmethod
    def _utcnow() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _device_keys(self) -> dict[str, dict[str, str]]:
        return self.state.setdefault('device_keys', {})

    def _trusted_peer_keys(self) -> dict[str, dict[str, dict[str, str]]]:
        return self.state.setdefault('trusted_peer_keys', {})

    def ensure_local_identity(self, username: str) -> dict[str, str]:
        normalized_username = username.lower()
        identities = self._device_keys()
        existing = identities.get(normalized_username)
        if existing and existing.get('private_key') and existing.get('public_key'):
            existing.setdefault('device_id', DEFAULT_DEVICE_ID)
            existing.setdefault('fingerprint', public_key_fingerprint(existing['public_key']))
            return existing
        identities[normalized_username] = generate_identity_keypair(DEFAULT_DEVICE_ID)
        return identities[normalized_username]

    def publish_identity(self, username: str) -> dict[str, str]:
        identity = self.ensure_local_identity(username)
        self.api.store_identity_key(identity['device_id'], identity['public_key'])
        return identity

    def _fetch_remote_identity(self, peer_username: str) -> dict[str, str]:
        response = self.api.get_identity_keys(peer_username.lower())
        keys = [item for item in response.get('keys', []) if item.get('is_active')]
        if not keys:
            raise RuntimeError(f'peer {peer_username.lower()} has no published identity key')
        selected = next((item for item in keys if item.get('device_id') == DEFAULT_DEVICE_ID), None)
        if selected is None:
            if len(keys) == 1:
                selected = keys[0]
            else:
                raise RuntimeError(
                    f'peer {peer_username.lower()} has multiple active devices; this prototype only supports one device'
                )
        public_key = selected.get('public_key')
        if not public_key:
            raise RuntimeError(f'peer {peer_username.lower()} returned an empty identity public key')
        try:
            fingerprint = public_key_fingerprint(str(public_key))
        except Exception as exc:
            raise RuntimeError(f'peer {peer_username.lower()} returned an invalid identity public key') from exc
        return {
            'device_id': str(selected.get('device_id') or DEFAULT_DEVICE_ID),
            'public_key': str(public_key),
            'fingerprint': fingerprint,
        }

    def _remember_trusted_peer(self, local_username: str, peer_username: str, peer_identity: dict[str, str]) -> dict[str, str]:
        trust_store = self._trusted_peer_keys().setdefault(local_username.lower(), {})
        trust_store[peer_username.lower()] = {
            'device_id': peer_identity['device_id'],
            'public_key': peer_identity['public_key'],
            'fingerprint': peer_identity['fingerprint'],
            'trusted_at': self._utcnow(),
        }
        return trust_store[peer_username.lower()]

    def _describe_key_change(self, peer_username: str, trusted: dict[str, str], current: dict[str, str]) -> str:
        return (
            f'identity key changed for {peer_username.lower()}; trusted fingerprint '
            f'{trusted["fingerprint"]}, current server fingerprint {current["fingerprint"]}. '
            'refusing to continue until trust is reset'
        )

    def resolve_peer_for_send(self, local_username: str, peer_username: str) -> dict[str, str]:
        normalized_local = local_username.lower()
        normalized_peer = peer_username.lower()
        trusted = self._trusted_peer_keys().setdefault(normalized_local, {}).get(normalized_peer)
        current = self._fetch_remote_identity(normalized_peer)
        if trusted is None:
            return self._remember_trusted_peer(normalized_local, normalized_peer, current)
        trusted.setdefault('fingerprint', public_key_fingerprint(trusted['public_key']))
        trusted.setdefault('device_id', current['device_id'])
        if trusted['public_key'] != current['public_key']:
            raise TrustError(self._describe_key_change(normalized_peer, trusted, current))
        return trusted

    def resolve_peer_for_decrypt(self, local_username: str, peer_username: str) -> dict[str, str]:
        normalized_local = local_username.lower()
        normalized_peer = peer_username.lower()
        trusted = self._trusted_peer_keys().setdefault(normalized_local, {}).get(normalized_peer)
        if trusted is not None:
            trusted.setdefault('fingerprint', public_key_fingerprint(trusted['public_key']))
            trusted.setdefault('device_id', DEFAULT_DEVICE_ID)
            return trusted
        current = self._fetch_remote_identity(normalized_peer)
        return self._remember_trusted_peer(normalized_local, normalized_peer, current)

    def encrypt_outbound_message(self, local_username: str, peer_username: str, plaintext: str) -> tuple[str, dict[str, str], dict[str, str]]:
        identity = self.ensure_local_identity(local_username)
        trusted_peer = self.resolve_peer_for_send(local_username, peer_username)
        envelope = encrypt_message(
            plaintext,
            sender_private_key_b64=identity['private_key'],
            recipient_public_key_b64=trusted_peer['public_key'],
            from_username=local_username.lower(),
            to_username=peer_username.lower(),
            sender_device_id=identity['device_id'],
        )
        return envelope, identity, trusted_peer

    def decrypt_message_for_user(self, local_username: str, message_payload: dict[str, Any]) -> str:
        normalized_local = local_username.lower()
        identity = self.ensure_local_identity(normalized_local)
        from_username = str(message_payload.get('from_username', '')).lower()
        to_username = str(message_payload.get('to_username', '')).lower()
        if from_username == normalized_local:
            peer_username = to_username
        elif to_username == normalized_local:
            peer_username = from_username
        else:
            raise RuntimeError('encrypted message does not belong to the currently selected user')
        trusted_peer = self.resolve_peer_for_decrypt(normalized_local, peer_username)
        try:
            return decrypt_message(
                str(message_payload.get('content', '')),
                local_private_key_b64=identity['private_key'],
                peer_public_key_b64=trusted_peer['public_key'],
                from_username=from_username,
                to_username=to_username,
                message_type=str(message_payload.get('message_type', '')),
            )
        except DecryptionError as exc:
            try:
                current = self._fetch_remote_identity(peer_username)
            except Exception:
                current = None
            if current and trusted_peer['public_key'] != current['public_key']:
                raise TrustError(self._describe_key_change(peer_username, trusted_peer, current)) from exc
            raise
