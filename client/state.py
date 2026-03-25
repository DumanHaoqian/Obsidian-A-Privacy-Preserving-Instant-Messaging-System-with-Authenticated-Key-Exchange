import json
from pathlib import Path
from typing import Any

STATE_PATH = Path(__file__).resolve().parent / 'client_state.json'


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {'known_otp_secrets': {}, 'access_token': None, 'username': None}
    try:
        return json.loads(STATE_PATH.read_text())
    except Exception:
        return {'known_otp_secrets': {}, 'access_token': None, 'username': None}


def save_state(state: dict[str, Any]) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True))
