from __future__ import annotations

import secrets
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from client.api_client import ApiClient
from client.otp import totp_now
from client.state import load_state, save_state
from client.ws_client import WebSocketListener


HELP_TEXT = """
Commands:
  help
  register <username> <password>
  login <username> <password>
  logout
  me
  contacts
  pending
  send-request <username>      # must match the recipient's registered username exactly
  respond <request_id> <accept|decline>
  cancel-request <request_id>
  conversations
  open <conversation_id> [limit]
  send <username> <message text>
  mark-read <conversation_id>
  store-dev-key                # stores a placeholder identity public key for later phases
  exit
""".strip()


class IMCli:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url
        self.state = load_state()
        self.api = ApiClient(base_url, self.state.get('access_token'))
        self.ws: Optional[WebSocketListener] = None
        if self.state.get('access_token'):
            self._start_ws()

    def _start_ws(self) -> None:
        if not self.api.access_token:
            return
        if self.ws:
            self.ws.stop()
        self.ws = WebSocketListener(self.base_url, self.api.access_token, self._handle_event)
        self.ws.start()

    def _stop_ws(self) -> None:
        if self.ws:
            self.ws.stop()
            self.ws = None

    def _persist(self) -> None:
        save_state(self.state)

    def _handle_event(self, payload: dict) -> None:
        event = payload.get('event')
        data = payload.get('data', {})
        if event == 'new_message':
            print(f"\n[push] new message from {data.get('from_username')}: {data.get('content')}")
            try:
                self.api.ack_message(data['message_id'])
                print(f"[push] auto-acked message {data['message_id']} as delivered")
            except Exception as exc:
                print(f"[push] failed to ack message {data.get('message_id')}: {exc}")
        elif event == 'message_ack':
            print(f"\n[push] your message {data.get('message_id')} is {data.get('status')}")
        elif event == 'friend_request_update':
            print(f"\n[push] friend request update: {data}")
        elif event == 'auth_failed':
            # Local token is stale/invalid; stop reconnect loop and require a fresh login.
            print(f"\n[push] auth failed: {data.get('message')}")
            self._stop_ws()
            self.api.set_token(None)
            self.state['access_token'] = None
            self.state['username'] = None
            self._persist()
            print('[push] local session cleared. run: login <username> <password>')
        else:
            print(f"\n[push] {event}: {data}")

    def run(self) -> None:
        print(f'Connected to {self.base_url}')
        print(HELP_TEXT)
        while True:
            try:
                raw = input('\nim> ').strip()
            except (EOFError, KeyboardInterrupt):
                print('\nbye')
                break
            if not raw:
                continue
            try:
                self.execute(raw)
            except Exception as exc:
                print(f'error: {exc}')
        self._stop_ws()
        self.api.close()

    def execute(self, raw: str) -> None:
        parts = raw.split()
        cmd = parts[0].lower()
        if cmd == 'help':
            print(HELP_TEXT)
        elif cmd == 'register':
            if len(parts) < 3:
                raise RuntimeError('usage: register <username> <password>')
            username, password = parts[1], parts[2]
            data = self.api.register(username, password)
            self.state.setdefault('known_otp_secrets', {})[username.lower()] = data['otp_secret']
            self._persist()
            print(data)
            print(f"Current OTP code: {totp_now(data['otp_secret'])}")
        elif cmd == 'login':
            if len(parts) < 3:
                raise RuntimeError('usage: login <username> <password>')
            username, password = parts[1], parts[2]
            challenge = self.api.login_password(username, password)
            secret = self.state.get('known_otp_secrets', {}).get(username.lower())
            if secret:
                otp_code = totp_now(secret)
                print(f'Using locally stored OTP code for demo: {otp_code}')
            else:
                otp_code = input('OTP code: ').strip()
            session = self.api.login_otp(challenge['challenge_token'], otp_code)
            self.api.set_token(session['access_token'])
            self.state['access_token'] = session['access_token']
            self.state['username'] = username.lower()
            self._persist()
            self._start_ws()
            print(session)
        elif cmd == 'logout':
            print(self.api.logout())
            self.api.set_token(None)
            self.state['access_token'] = None
            self.state['username'] = None
            self._persist()
            self._stop_ws()
        elif cmd == 'me':
            print(self.api.me())
        elif cmd == 'contacts':
            print(self.api.contacts())
        elif cmd == 'pending':
            print(self.api.pending_requests())
        elif cmd == 'send-request':
            if len(parts) < 2:
                raise RuntimeError('usage: send-request <username>')
            data = self.api.send_friend_request(parts[1])
            print(data)
            if isinstance(data, dict) and data.get('target_username'):
                print(
                    f"(Request #{data.get('request_id')} sent to user "
                    f"@{data['target_username']}, id={data.get('target_user_id')})"
                )
        elif cmd == 'respond':
            if len(parts) < 3:
                raise RuntimeError('usage: respond <request_id> <accept|decline>')
            print(self.api.respond_friend_request(int(parts[1]), parts[2]))
        elif cmd == 'cancel-request':
            if len(parts) < 2:
                raise RuntimeError('usage: cancel-request <request_id>')
            print(self.api.cancel_friend_request(int(parts[1])))
        elif cmd == 'conversations':
            print(self.api.conversations())
        elif cmd == 'open':
            if len(parts) < 2:
                raise RuntimeError('usage: open <conversation_id> [limit]')
            limit = int(parts[2]) if len(parts) >= 3 else 20
            print(self.api.pull_messages(int(parts[1]), limit=limit, mark_read=True))
        elif cmd == 'send':
            if len(parts) < 3:
                raise RuntimeError('usage: send <username> <message text>')
            username = parts[1]
            content = raw.split(None, 2)[2]
            print(self.api.send_message(username, content))
        elif cmd == 'mark-read':
            if len(parts) < 2:
                raise RuntimeError('usage: mark-read <conversation_id>')
            print(self.api.mark_read(int(parts[1])))
        elif cmd == 'store-dev-key':
            fake_public_key = secrets.token_hex(32)
            print(self.api.store_identity_key('cli-device-1', fake_public_key))
            print('Stored a placeholder identity public key for later E2EE phases.')
        elif cmd == 'exit':
            raise KeyboardInterrupt
        else:
            raise RuntimeError('unknown command; type help')


def main() -> None:
    base_url = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8000'
    IMCli(base_url).run()


if __name__ == '__main__':
    main()
