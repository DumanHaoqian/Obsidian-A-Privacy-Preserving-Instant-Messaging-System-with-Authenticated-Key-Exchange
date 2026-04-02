from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from shared.e2ee import (
    DEFAULT_DEVICE_ID,
    DecryptionError,
    E2EE_MESSAGE_TYPE,
    TrustError,
    decrypt_message,
    encrypt_message,
    extract_replay_token,
    generate_identity_keypair,
    public_key_fingerprint,
)


MAX_REPLAY_CACHE_ENTRIES_PER_PEER = 2048


class ReplayDetectedError(RuntimeError):
    def __init__(self, message: str, *, canonical_message_id: Optional[int], current_message_id: Optional[int]) -> None:
        super().__init__(message)
        self.canonical_message_id = canonical_message_id
        self.current_message_id = current_message_id


class DuplicateDeliveryError(ReplayDetectedError):
    pass


class ReplayAttackError(ReplayDetectedError):
    pass


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

    def _verified_peer_keys(self) -> dict[str, dict[str, dict[str, str]]]:
        return self.state.setdefault('verified_peer_keys', {})

    def _reverify_required_peer_keys(self) -> dict[str, dict[str, dict[str, str]]]:
        return self.state.setdefault('reverify_required_peer_keys', {})

    def _replay_cache(self) -> dict[str, dict[str, dict[str, dict[str, Any]]]]:
        return self.state.setdefault('replay_cache', {})

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
        verified_store = self._verified_peer_keys().setdefault(local_username.lower(), {})
        verified = verified_store.get(peer_username.lower())
        if verified is not None and verified.get('public_key') != peer_identity['public_key']:
            del verified_store[peer_username.lower()]
        reverify_store = self._reverify_required_peer_keys().setdefault(local_username.lower(), {})
        pending = reverify_store.get(peer_username.lower())
        if pending is not None and pending.get('public_key') != peer_identity['public_key']:
            del reverify_store[peer_username.lower()]
        return trust_store[peer_username.lower()]

    def _describe_key_change(self, peer_username: str, trusted: dict[str, str], current: dict[str, str]) -> str:
        return (
            f'identity key changed for {peer_username.lower()}; trusted fingerprint '
            f'{trusted["fingerprint"]}, current server fingerprint {current["fingerprint"]}. '
            'refusing to continue until trust is reset'
        )

    @staticmethod
    def _describe_reverify_required(peer_username: str, fingerprint: str) -> str:
        return (
            f'peer {peer_username.lower()} must be re-verified before secure messaging continues; '
            f'current trusted fingerprint {fingerprint}. run: fingerprint {peer_username.lower()} then verify {peer_username.lower()}'
        )

    def _get_verified_peer(self, local_username: str, peer_username: str, trusted: Optional[dict[str, str]] = None) -> Optional[dict[str, str]]:
        verified_store = self._verified_peer_keys().setdefault(local_username.lower(), {})
        verified = verified_store.get(peer_username.lower())
        if verified is None:
            return None
        if trusted is None:
            del verified_store[peer_username.lower()]
            return None
        if trusted is not None and verified.get('public_key') != trusted.get('public_key'):
            del verified_store[peer_username.lower()]
            return None
        return verified

    def _get_reverify_required_peer(
        self,
        local_username: str,
        peer_username: str,
        trusted: Optional[dict[str, str]] = None,
    ) -> Optional[dict[str, str]]:
        reverify_store = self._reverify_required_peer_keys().setdefault(local_username.lower(), {})
        pending = reverify_store.get(peer_username.lower())
        if pending is None:
            return None
        if trusted is None:
            del reverify_store[peer_username.lower()]
            return None
        if pending.get('public_key') != trusted.get('public_key'):
            del reverify_store[peer_username.lower()]
            return None
        return pending

    def _peer_replay_cache(self, local_username: str, peer_username: str) -> dict[str, dict[str, Any]]:
        return self._replay_cache().setdefault(local_username.lower(), {}).setdefault(peer_username.lower(), {})

    def _trim_peer_replay_cache(self, cache: dict[str, dict[str, Any]]) -> None:
        while len(cache) > MAX_REPLAY_CACHE_ENTRIES_PER_PEER:
            oldest_token = min(
                cache,
                key=lambda token: (
                    str(cache[token].get('last_seen_at') or cache[token].get('first_seen_at') or ''),
                    int(cache[token].get('message_id') or 0),
                ),
            )
            del cache[oldest_token]

    def _record_replay_token(self, local_username: str, peer_username: str, replay_token: str, message_id: Optional[int]) -> None:
        if message_id is None:
            return
        peer_cache = self._peer_replay_cache(local_username, peer_username)
        now = self._utcnow()
        existing = peer_cache.get(replay_token)
        if existing is None:
            peer_cache[replay_token] = {
                'message_id': int(message_id),
                'first_seen_at': now,
                'last_seen_at': now,
            }
            self._trim_peer_replay_cache(peer_cache)
            return
        existing['last_seen_at'] = now

    @staticmethod
    def _message_id_from_payload(message_payload: dict[str, Any]) -> Optional[int]:
        message_id = message_payload.get('message_id')
        if isinstance(message_id, int):
            return message_id
        try:
            return int(message_id)
        except (TypeError, ValueError):
            return None

    def _classify_replay_token(
        self,
        *,
        local_username: str,
        peer_username: str,
        replay_token: Optional[str],
        message_id: Optional[int],
        context: str,
    ) -> None:
        if replay_token is None or message_id is None:
            return
        peer_cache = self._peer_replay_cache(local_username, peer_username)
        existing = peer_cache.get(replay_token)
        if existing is None:
            self._record_replay_token(local_username, peer_username, replay_token, message_id)
            return

        canonical_message_id = int(existing.get('message_id')) if existing.get('message_id') is not None else None
        existing['last_seen_at'] = self._utcnow()
        if canonical_message_id == message_id:
            if context == 'push':
                raise DuplicateDeliveryError(
                    f'duplicate delivery detected for message {message_id}; already processed locally',
                    canonical_message_id=canonical_message_id,
                    current_message_id=message_id,
                )
            return
        raise ReplayAttackError(
            f'replay detected: token already seen in message {canonical_message_id}; current server message id {message_id}',
            canonical_message_id=canonical_message_id,
            current_message_id=message_id,
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
        self._get_verified_peer(normalized_local, normalized_peer, trusted)
        pending = self._get_reverify_required_peer(normalized_local, normalized_peer, trusted)
        if pending is not None:
            raise TrustError(self._describe_reverify_required(normalized_peer, trusted['fingerprint']))
        return trusted

    def resolve_peer_for_decrypt(self, local_username: str, peer_username: str) -> dict[str, str]:
        normalized_local = local_username.lower()
        normalized_peer = peer_username.lower()
        trusted = self._trusted_peer_keys().setdefault(normalized_local, {}).get(normalized_peer)
        if trusted is not None:
            trusted.setdefault('fingerprint', public_key_fingerprint(trusted['public_key']))
            trusted.setdefault('device_id', DEFAULT_DEVICE_ID)
            self._get_verified_peer(normalized_local, normalized_peer, trusted)
            pending = self._get_reverify_required_peer(normalized_local, normalized_peer, trusted)
            if pending is not None:
                raise TrustError(self._describe_reverify_required(normalized_peer, trusted['fingerprint']))
            return trusted
        current = self._fetch_remote_identity(normalized_peer)
        return self._remember_trusted_peer(normalized_local, normalized_peer, current)

    def get_peer_verification_status(self, local_username: str, peer_username: str) -> dict[str, Any]:
        normalized_local = local_username.lower()
        normalized_peer = peer_username.lower()
        trusted = self._trusted_peer_keys().setdefault(normalized_local, {}).get(normalized_peer)
        if trusted is not None:
            trusted.setdefault('fingerprint', public_key_fingerprint(trusted['public_key']))
            trusted.setdefault('device_id', DEFAULT_DEVICE_ID)
        current = self._fetch_remote_identity(normalized_peer)
        verified = self._get_verified_peer(normalized_local, normalized_peer, trusted)
        reverify_required = self._get_reverify_required_peer(normalized_local, normalized_peer, trusted)

        trust_state = 'untrusted'
        if trusted is not None:
            trust_state = 'trusted' if trusted['public_key'] == current['public_key'] else 'mismatch'

        is_verified = bool(verified is not None and trust_state == 'trusted')
        status: dict[str, Any] = {
            'peer_username': normalized_peer,
            'server_device_id': current['device_id'],
            'server_fingerprint': current['fingerprint'],
            'trusted_fingerprint': trusted['fingerprint'] if trusted is not None else None,
            'trusted_at': trusted.get('trusted_at') if trusted is not None else None,
            'verified': is_verified,
            'verified_at': verified.get('verified_at') if verified is not None else None,
            'verification_required': reverify_required is not None,
            'reverify_required_at': reverify_required.get('reset_at') if reverify_required is not None else None,
            'trust_state': trust_state,
        }
        if trust_state == 'mismatch' and trusted is not None:
            status['warning'] = self._describe_key_change(normalized_peer, trusted, current)
        elif reverify_required is not None and trusted is not None:
            status['warning'] = self._describe_reverify_required(normalized_peer, trusted['fingerprint'])
        return status

    def mark_peer_verified(self, local_username: str, peer_username: str) -> dict[str, str]:
        normalized_local = local_username.lower()
        normalized_peer = peer_username.lower()
        current = self._fetch_remote_identity(normalized_peer)
        trusted = self._trusted_peer_keys().setdefault(normalized_local, {}).get(normalized_peer)
        if trusted is None:
            trusted = self._remember_trusted_peer(normalized_local, normalized_peer, current)
        else:
            trusted.setdefault('fingerprint', public_key_fingerprint(trusted['public_key']))
            trusted.setdefault('device_id', current['device_id'])
        if trusted['public_key'] != current['public_key']:
            raise TrustError(self._describe_key_change(normalized_peer, trusted, current))

        verified_store = self._verified_peer_keys().setdefault(normalized_local, {})
        verified_store[normalized_peer] = {
            'device_id': trusted['device_id'],
            'public_key': trusted['public_key'],
            'fingerprint': trusted['fingerprint'],
            'verified_at': self._utcnow(),
        }
        self._reverify_required_peer_keys().setdefault(normalized_local, {}).pop(normalized_peer, None)
        return verified_store[normalized_peer]

    def reset_peer_trust(self, local_username: str, peer_username: str) -> dict[str, str]:
        normalized_local = local_username.lower()
        normalized_peer = peer_username.lower()
        current = self._fetch_remote_identity(normalized_peer)
        trusted = self._remember_trusted_peer(normalized_local, normalized_peer, current)
        self._verified_peer_keys().setdefault(normalized_local, {}).pop(normalized_peer, None)
        reverify_store = self._reverify_required_peer_keys().setdefault(normalized_local, {})
        reverify_store[normalized_peer] = {
            'device_id': trusted['device_id'],
            'public_key': trusted['public_key'],
            'fingerprint': trusted['fingerprint'],
            'reset_at': self._utcnow(),
        }
        return reverify_store[normalized_peer]

    def encrypt_outbound_message(
        self,
        local_username: str,
        peer_username: str,
        plaintext: str,
        *,
        ttl_seconds: Optional[int] = None,
    ) -> tuple[str, dict[str, str], dict[str, str]]:
        identity = self.ensure_local_identity(local_username)
        trusted_peer = self.resolve_peer_for_send(local_username, peer_username)
        envelope = encrypt_message(
            plaintext,
            sender_private_key_b64=identity['private_key'],
            recipient_public_key_b64=trusted_peer['public_key'],
            from_username=local_username.lower(),
            to_username=peer_username.lower(),
            sender_device_id=identity['device_id'],
            ttl_seconds=ttl_seconds,
        )
        return envelope, identity, trusted_peer

    def decrypt_message_for_user(self, local_username: str, message_payload: dict[str, Any], *, context: str = 'history') -> str:
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
        replay_token: Optional[str] = None
        if str(message_payload.get('message_type', '')) == E2EE_MESSAGE_TYPE:
            replay_token = extract_replay_token(str(message_payload.get('content', '')))
        try:
            plaintext = decrypt_message(
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
        self._classify_replay_token(
            local_username=normalized_local,
            peer_username=peer_username,
            replay_token=replay_token,
            message_id=self._message_id_from_payload(message_payload),
            context=context,
        )
        return plaintext
