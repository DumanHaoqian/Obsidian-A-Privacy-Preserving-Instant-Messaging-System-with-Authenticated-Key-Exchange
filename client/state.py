import json
from pathlib import Path
from typing import Any

STATE_PATH = Path(__file__).resolve().parent / 'client_state.json'


def default_state() -> dict[str, Any]:
    return {
        'known_otp_secrets': {},
        'access_token': None,
        'username': None,
        'device_keys': {},
        'trusted_peer_keys': {},
    }


def normalize_state(state: Any) -> dict[str, Any]:
    normalized = default_state()
    if not isinstance(state, dict):
        return normalized
    for key in ('known_otp_secrets', 'device_keys', 'trusted_peer_keys'):
        value = state.get(key)
        if isinstance(value, dict):
            normalized[key] = value
    if isinstance(state.get('access_token'), str) or state.get('access_token') is None:
        normalized['access_token'] = state.get('access_token')
    if isinstance(state.get('username'), str) or state.get('username') is None:
        normalized['username'] = state.get('username')
    return normalized


def _read_state_from_disk() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return default_state()
    try:
        return normalize_state(json.loads(STATE_PATH.read_text(encoding='utf-8')))
    except Exception:
        return default_state()


def _merge_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = dict(base)
    for key, value in override.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = _merge_dicts(existing, value)
        else:
            merged[key] = value
    return merged


def load_state() -> dict[str, Any]:
    return _read_state_from_disk()


def save_state(state: dict[str, Any]) -> None:
    current = _read_state_from_disk()
    incoming = normalize_state(state)
    merged = dict(current)
    for key in ('known_otp_secrets', 'device_keys', 'trusted_peer_keys'):
        merged[key] = _merge_dicts(current.get(key, {}), incoming.get(key, {}))
    merged['access_token'] = incoming.get('access_token')
    merged['username'] = incoming.get('username')
    temp_path = STATE_PATH.with_name(f'{STATE_PATH.name}.tmp')
    temp_path.write_text(json.dumps(merged, indent=2, sort_keys=True), encoding='utf-8')
    temp_path.replace(STATE_PATH)
