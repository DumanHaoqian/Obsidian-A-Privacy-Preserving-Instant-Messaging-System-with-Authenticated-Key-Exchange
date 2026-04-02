from __future__ import annotations

import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from client.api_client import ApiClient
from client.e2ee_client import ClientE2EEManager, DuplicateDeliveryError, ReplayAttackError
from client.otp import totp_now
from client.state import load_state, save_state
from client.ws_client import WebSocketListener
from shared.e2ee import E2EE_MESSAGE_TYPE, MAX_TTL_SECONDS, MIN_TTL_SECONDS, TrustError


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
  send-ttl <username> <ttl_seconds> <message text>
  mark-read <conversation_id>
  store-dev-key                # ensures and republishes the real E2EE identity key for this device
  exit
""".strip()

MAX_PLAINTEXT_MESSAGE_LENGTH = 4000


class ExitRequested(Exception):
    pass


class IMCli:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url
        self.state = load_state()
        self.api = ApiClient(base_url, self.state.get('access_token'))
        self.e2ee = ClientE2EEManager(self.api, self.state)
        self.ws: Optional[WebSocketListener] = None
        self._expiry_timers: dict[int, threading.Timer] = {}
        if self.state.get('access_token') and self.state.get('username'):
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

    @staticmethod
    def _parse_iso_ts(value: Any) -> Optional[datetime]:
        if not isinstance(value, str) or not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    def _is_message_expired(self, message_payload: dict[str, Any]) -> bool:
        expires_at = self._parse_iso_ts(message_payload.get('expires_at'))
        return expires_at is not None and expires_at <= datetime.now(timezone.utc)

    def _schedule_self_destruct_notice(self, message_payload: dict[str, Any]) -> None:
        expires_at = self._parse_iso_ts(message_payload.get('expires_at'))
        if expires_at is None:
            return
        if expires_at <= datetime.now(timezone.utc):
            return
        try:
            message_id = int(message_payload.get('message_id'))
        except (TypeError, ValueError):
            return
        if message_id in self._expiry_timers:
            return

        delay = max(0.0, (expires_at - datetime.now(timezone.utc)).total_seconds())

        def _notify() -> None:
            self._expiry_timers.pop(message_id, None)
            print(f"\n[expire] self-destruct message {message_id} expired and will no longer appear in history")

        timer = threading.Timer(delay, _notify)
        timer.daemon = True
        self._expiry_timers[message_id] = timer
        timer.start()

    def _clear_expiry_timers(self) -> None:
        for timer in self._expiry_timers.values():
            timer.cancel()
        self._expiry_timers.clear()

    def _current_username(self) -> str:
        username = self.state.get('username')
        if not username:
            raise RuntimeError('login required before using end-to-end encrypted messaging')
        return str(username).lower()

    def _ensure_identity_ready(self) -> tuple[dict[str, Any], dict[str, str]]:
        username = self._current_username()
        identity = self.e2ee.publish_identity(username)
        self._persist()
        return {'ok': True, 'message': 'identity public key stored'}, identity

    def _display_message_content(self, message_payload: dict[str, Any], *, context: str = 'history') -> str:
        if self._is_message_expired(message_payload):
            return '[expired self-destruct message]'
        if message_payload.get('message_type') != E2EE_MESSAGE_TYPE:
            return str(message_payload.get('content', ''))
        username = self.state.get('username')
        if not username:
            return '[encrypted message unavailable without a logged-in local user context]'
        try:
            return self.e2ee.decrypt_message_for_user(str(username), message_payload, context=context)
        except DuplicateDeliveryError as exc:
            return f'[duplicate delivery ignored: {exc}]'
        except ReplayAttackError as exc:
            return f'[replay blocked: {exc}]'
        except TrustError as exc:
            return f'[encrypted message blocked: {exc}]'
        except Exception as exc:
            return f'[encrypted message unavailable: {exc}]'

    def _display_message_payload(self, message_payload: dict[str, Any], *, context: str = 'history') -> dict[str, Any]:
        rendered = dict(message_payload)
        rendered['content'] = self._display_message_content(rendered, context=context)
        return rendered

    def _display_pull_response(self, response: dict[str, Any]) -> dict[str, Any]:
        rendered = dict(response)
        rendered_messages = []
        for message in response.get('messages', []):
            if not isinstance(message, dict) or self._is_message_expired(message):
                continue
            rendered_message = self._display_message_payload(message, context='history')
            self._schedule_self_destruct_notice(rendered_message)
            rendered_messages.append(rendered_message)
        rendered['messages'] = rendered_messages
        self._persist()
        return rendered

    def _display_send_response(self, response: dict[str, Any], plaintext: str) -> dict[str, Any]:
        rendered = dict(response)
        data = response.get('data')
        if isinstance(data, dict):
            message_payload = dict(data)
            if message_payload.get('message_type') == E2EE_MESSAGE_TYPE:
                message_payload['content'] = plaintext
            else:
                message_payload = self._display_message_payload(message_payload)
            self._schedule_self_destruct_notice(message_payload)
            rendered['data'] = message_payload
        return rendered

    def _handle_event(self, payload: dict) -> None:
        event = payload.get('event')
        data = payload.get('data', {})
        if event == 'new_message':
            if isinstance(data, dict):
                try:
                    if self._is_message_expired(data):
                        print(f"\n[push] self-destruct message {data.get('message_id')} already expired and was ignored")
                    else:
                        rendered_content = self._display_message_content(data, context='push')
                        if rendered_content.startswith('[duplicate delivery ignored:'):
                            print(f"\n[push] {rendered_content}")
                        elif rendered_content.startswith('[replay blocked:'):
                            print(f"\n[push] {rendered_content}")
                        else:
                            print(f"\n[push] new message from {data.get('from_username')}: {rendered_content}")
                        self._schedule_self_destruct_notice(data)
                finally:
                    self._persist()
            else:
                print(f"\n[push] new message payload: {data}")
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
            except ExitRequested:
                print('bye')
                break
            except Exception as exc:
                print(f'error: {exc}')
        self._stop_ws()
        self._clear_expiry_timers()
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
            _, identity = self._ensure_identity_ready()
            self._start_ws()
            print(session)
            print(
                f"E2EE ready on device {identity['device_id']} "
                f"(fingerprint {identity['fingerprint']})"
            )
        elif cmd == 'logout':
            print(self.api.logout())
            self.api.set_token(None)
            self.state['access_token'] = None
            self.state['username'] = None
            self._persist()
            self._stop_ws()
            self._clear_expiry_timers()
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
            response = self.api.pull_messages(int(parts[1]), limit=limit, mark_read=True)
            print(self._display_pull_response(response))
        elif cmd == 'send':
            if len(parts) < 3:
                raise RuntimeError('usage: send <username> <message text>')
            username = parts[1]
            content = raw.split(None, 2)[2]
            if len(content) > MAX_PLAINTEXT_MESSAGE_LENGTH:
                raise RuntimeError(f'plaintext message too large; limit is {MAX_PLAINTEXT_MESSAGE_LENGTH} characters')
            envelope, identity, peer = self.e2ee.encrypt_outbound_message(self._current_username(), username, content)
            self._persist()
            response = self.api.send_message(username, envelope, message_type=E2EE_MESSAGE_TYPE)
            print(self._display_send_response(response, content))
            print(
                f"(E2EE sender fingerprint {identity['fingerprint']}; "
                f"trusted peer fingerprint {peer['fingerprint']})"
            )
        elif cmd == 'send-ttl':
            if len(parts) < 4:
                raise RuntimeError('usage: send-ttl <username> <ttl_seconds> <message text>')
            username = parts[1]
            ttl_seconds = int(parts[2])
            if ttl_seconds < MIN_TTL_SECONDS or ttl_seconds > MAX_TTL_SECONDS:
                raise RuntimeError(
                    f'ttl_seconds must be between {MIN_TTL_SECONDS} and {MAX_TTL_SECONDS}'
                )
            content = raw.split(None, 3)[3]
            if len(content) > MAX_PLAINTEXT_MESSAGE_LENGTH:
                raise RuntimeError(f'plaintext message too large; limit is {MAX_PLAINTEXT_MESSAGE_LENGTH} characters')
            envelope, identity, peer = self.e2ee.encrypt_outbound_message(
                self._current_username(),
                username,
                content,
                ttl_seconds=ttl_seconds,
            )
            self._persist()
            response = self.api.send_message(
                username,
                envelope,
                message_type=E2EE_MESSAGE_TYPE,
                ttl_seconds=ttl_seconds,
            )
            print(self._display_send_response(response, content))
            print(f"(self-destruct after {ttl_seconds} seconds)")
            print(
                f"(E2EE sender fingerprint {identity['fingerprint']}; "
                f"trusted peer fingerprint {peer['fingerprint']})"
            )
        elif cmd == 'mark-read':
            if len(parts) < 2:
                raise RuntimeError('usage: mark-read <conversation_id>')
            print(self.api.mark_read(int(parts[1])))
        elif cmd == 'store-dev-key':
            response, identity = self._ensure_identity_ready()
            display = dict(response)
            display['device_id'] = identity['device_id']
            display['fingerprint'] = identity['fingerprint']
            print(display)
            print('Published the local E2EE identity key for this device.')
        elif cmd == 'exit':
            raise ExitRequested
        else:
            raise RuntimeError('unknown command; type help')


def main() -> None:
    base_url = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8000'
    IMCli(base_url).run()


if __name__ == '__main__':
    main()
