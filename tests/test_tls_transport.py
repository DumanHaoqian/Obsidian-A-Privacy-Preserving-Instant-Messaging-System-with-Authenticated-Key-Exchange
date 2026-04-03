from __future__ import annotations

import ssl
import socket
import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable

import httpx
import uvicorn

import server.db as dbmod
from client.api_client import ApiClient
from client.e2ee_client import ClientE2EEManager
from client.otp import totp_now
from client.state import default_state
from client.ws_client import WebSocketListener
from server.main import app
from server.tls import ensure_dev_tls_materials


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(('127.0.0.1', 0))
        return int(sock.getsockname()[1])


class _TLSUvicornServer:
    def __init__(self, *, host: str, port: int, certfile: Path, keyfile: Path) -> None:
        config = uvicorn.Config(
            app,
            host=host,
            port=port,
            log_level='warning',
            access_log=False,
            ssl_certfile=str(certfile),
            ssl_keyfile=str(keyfile),
        )
        self.server = uvicorn.Server(config)
        self.server.install_signal_handlers = lambda: None
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=10)


class TLSTransportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.original_db_path = dbmod.DB_PATH
        self.cert_dir = Path(self.temp_dir.name) / 'certs'
        self.db_path = Path(self.temp_dir.name) / 'tls_test.db'
        dbmod.DB_PATH = self.db_path

        self.tls_material = ensure_dev_tls_materials(self.cert_dir, hostnames=['127.0.0.1', 'localhost'])
        self.port = _find_free_port()
        self.base_url = f'https://127.0.0.1:{self.port}'
        self.server = _TLSUvicornServer(
            host='127.0.0.1',
            port=self.port,
            certfile=self.tls_material.server_cert_path,
            keyfile=self.tls_material.server_key_path,
        )
        self.server.start()
        self._wait_for_server_ready()
        self.cleanup_callbacks: list[Callable[[], None]] = []

    def tearDown(self) -> None:
        for callback in reversed(self.cleanup_callbacks):
            try:
                callback()
            except Exception:
                pass
        self.server.stop()
        dbmod.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def _wait_for_server_ready(self) -> None:
        ssl_context = ssl.create_default_context(cafile=str(self.tls_material.ca_cert_path))
        deadline = time.time() + 10
        last_error: Exception | None = None
        while time.time() < deadline:
            try:
                with httpx.Client(verify=ssl_context, trust_env=False, timeout=1.0) as client:
                    response = client.get(f'{self.base_url}/openapi.json')
                if response.status_code == 200:
                    return
            except Exception as exc:  # pragma: no cover - only used while polling
                last_error = exc
                time.sleep(0.1)
        raise AssertionError(f'TLS server did not become ready in time: {last_error}')

    def _make_api_client(self) -> ApiClient:
        client = ApiClient(self.base_url, ca_cert_path=str(self.tls_material.ca_cert_path))
        self.cleanup_callbacks.append(client.close)
        return client

    def _register_and_login(self, username: str) -> tuple[ApiClient, ClientE2EEManager]:
        api = self._make_api_client()
        registration = api.register(username, 'StrongPass123')
        challenge = api.login_password(username, 'StrongPass123')
        session = api.login_otp(challenge['challenge_token'], totp_now(registration['otp_secret']))
        api.set_token(session['access_token'])

        state = default_state()
        state['username'] = username
        state['access_token'] = session['access_token']
        e2ee = ClientE2EEManager(api, state)
        e2ee.publish_identity(username)
        return api, e2ee

    def _wait_for(self, predicate, *, timeout: float = 5.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if predicate():
                return True
            time.sleep(0.05)
        return False

    def test_api_client_rejects_plain_http_by_default(self) -> None:
        with self.assertRaises(RuntimeError):
            ApiClient('http://127.0.0.1:8000')

    def test_https_and_wss_transport_support_full_secure_message_flow(self) -> None:
        alice_api, alice_e2ee = self._register_and_login('alice')
        bob_api, bob_e2ee = self._register_and_login('bob')

        bob_events: list[dict] = []
        bob_listener = WebSocketListener(
            self.base_url,
            str(bob_api.access_token),
            bob_events.append,
            ca_cert_path=str(self.tls_material.ca_cert_path),
        )
        self.cleanup_callbacks.append(bob_listener.stop)
        bob_listener.start()

        self.assertTrue(
            self._wait_for(lambda: any(event.get('event') == 'system' for event in bob_events)),
            'bob did not establish a WSS connection',
        )

        request = alice_api.send_friend_request('bob')
        bob_api.respond_friend_request(int(request['request_id']), 'accept')

        envelope, _, _ = alice_e2ee.encrypt_outbound_message('alice', 'bob', 'hello over tls')
        response = alice_api.send_message('bob', envelope, message_type='e2ee_text')
        self.assertTrue(response['ok'])

        self.assertTrue(
            self._wait_for(lambda: any(event.get('event') == 'new_message' for event in bob_events)),
            'bob did not receive the encrypted push over WSS',
        )
        pushed = next(event for event in bob_events if event.get('event') == 'new_message')
        plaintext = bob_e2ee.decrypt_message_for_user('bob', pushed['data'], context='push')
        self.assertEqual(plaintext, 'hello over tls')


if __name__ == '__main__':
    unittest.main()
