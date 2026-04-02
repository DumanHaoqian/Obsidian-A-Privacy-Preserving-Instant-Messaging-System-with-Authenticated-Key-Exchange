from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

import server.db as dbmod
from client.e2ee_client import ClientE2EEManager, DuplicateDeliveryError, ReplayAttackError
from client.otp import totp_now
from client.state import default_state
from server.main import app, build_message_payload


class ApiAdapter:
    def __init__(self, client: TestClient, token: str | None = None) -> None:
        self.client = client
        self.access_token = token

    def _headers(self) -> dict[str, str]:
        return {'Authorization': f'Bearer {self.access_token}'} if self.access_token else {}

    def store_identity_key(self, device_id: str, public_key: str) -> dict:
        response = self.client.post(
            '/identity-key',
            json={'device_id': device_id, 'public_key': public_key},
            headers=self._headers(),
        )
        response.raise_for_status()
        return response.json()

    def get_identity_keys(self, username: str) -> dict:
        response = self.client.get(f'/identity-key/{username}', headers=self._headers())
        response.raise_for_status()
        return response.json()


class ReplayProtectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.original_db_path = dbmod.DB_PATH
        dbmod.DB_PATH = Path(self.temp_dir.name) / 'test_replay.db'
        self.client_context = TestClient(app)
        self.client = self.client_context.__enter__()

        _, self.alice_token = self._register_and_login('alice')
        _, self.bob_token = self._register_and_login('bob')

        alice_state = default_state()
        alice_state['username'] = 'alice'
        alice_state['access_token'] = self.alice_token
        bob_state = default_state()
        bob_state['username'] = 'bob'
        bob_state['access_token'] = self.bob_token

        self.alice_e2ee = ClientE2EEManager(ApiAdapter(self.client, self.alice_token), alice_state)
        self.bob_e2ee = ClientE2EEManager(ApiAdapter(self.client, self.bob_token), bob_state)
        self.alice_e2ee.publish_identity('alice')
        self.bob_e2ee.publish_identity('bob')

        self._make_contacts()

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        dbmod.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def _post(self, path: str, payload: dict | None = None, token: str | None = None) -> tuple[int, dict]:
        headers = {'Authorization': f'Bearer {token}'} if token else {}
        response = self.client.post(path, json=payload, headers=headers)
        return response.status_code, response.json()

    def _register_and_login(self, username: str) -> tuple[dict, str]:
        _, reg = self._post('/register', {'username': username, 'password': 'StrongPass123'})
        _, challenge = self._post('/login/password', {'username': username, 'password': 'StrongPass123'})
        _, session = self._post(
            '/login/otp',
            {'challenge_token': challenge['challenge_token'], 'otp_code': totp_now(reg['otp_secret'])},
        )
        return reg, session['access_token']

    def _make_contacts(self) -> None:
        status_code, response = self._post('/friend-request/send', {'target_username': 'bob'}, self.alice_token)
        self.assertEqual(status_code, 200)
        status_code, response = self._post(
            '/friend-request/respond',
            {'request_id': response['request_id'], 'action': 'accept'},
            self.bob_token,
        )
        self.assertEqual(status_code, 200)

    def _fetch_payload(self, message_id: int) -> dict:
        with dbmod.db_cursor() as cur:
            return build_message_payload(cur, message_id)

    def _fetch_user_id(self, username: str) -> int:
        with dbmod.db_cursor() as cur:
            cur.execute('SELECT id FROM users WHERE username = ?', (username,))
            row = cur.fetchone()
            if not row:
                raise AssertionError(f'user {username} not found in test database')
            return int(row['id'])

    def test_duplicate_delivery_on_reconnect_is_detected(self) -> None:
        with self.client.websocket_connect(f'/ws?token={self.bob_token}') as websocket:
            system_event = websocket.receive_json()
            self.assertEqual(system_event['event'], 'system')
            envelope, _, _ = self.alice_e2ee.encrypt_outbound_message('alice', 'bob', 'hello bob')
            status_code, response = self._post(
                '/messages/send',
                {'to_username': 'bob', 'content': envelope, 'message_type': 'e2ee_text'},
                self.alice_token,
            )
            self.assertEqual(status_code, 200)
            pushed = websocket.receive_json()

        self.assertEqual(
            self.bob_e2ee.decrypt_message_for_user('bob', pushed['data'], context='push'),
            'hello bob',
        )

        with self.client.websocket_connect(f'/ws?token={self.bob_token}') as websocket:
            replayed = websocket.receive_json()
            self.assertEqual(replayed['event'], 'new_message')
            with self.assertRaises(DuplicateDeliveryError):
                self.bob_e2ee.decrypt_message_for_user('bob', replayed['data'], context='push')

    def test_same_message_can_still_be_opened_from_history(self) -> None:
        envelope, _, _ = self.alice_e2ee.encrypt_outbound_message('alice', 'bob', 'history works')
        status_code, response = self._post(
            '/messages/send',
            {'to_username': 'bob', 'content': envelope, 'message_type': 'e2ee_text'},
            self.alice_token,
        )
        self.assertEqual(status_code, 200)
        payload = response['data']

        self.assertEqual(
            self.bob_e2ee.decrypt_message_for_user('bob', payload, context='push'),
            'history works',
        )
        self.assertEqual(
            self.bob_e2ee.decrypt_message_for_user('bob', payload, context='history'),
            'history works',
        )

    def test_replayed_ciphertext_with_new_server_message_id_is_blocked(self) -> None:
        envelope, _, _ = self.alice_e2ee.encrypt_outbound_message('alice', 'bob', 'detect replay')
        status_code, response = self._post(
            '/messages/send',
            {'to_username': 'bob', 'content': envelope, 'message_type': 'e2ee_text'},
            self.alice_token,
        )
        self.assertEqual(status_code, 200)
        original_payload = response['data']

        self.assertEqual(
            self.bob_e2ee.decrypt_message_for_user('bob', original_payload, context='history'),
            'detect replay',
        )

        with dbmod.db_cursor(commit=True) as cur:
            cur.execute(
                """
                INSERT INTO messages (
                    conversation_id, sender_id, receiver_id, content, message_type,
                    status, is_offline_queued, is_read, created_at
                ) VALUES (?, ?, ?, ?, ?, 'sent', 1, 0, ?)
                """,
                (
                    original_payload['conversation_id'],
                    self._fetch_user_id('alice'),
                    self._fetch_user_id('bob'),
                    original_payload['content'],
                    original_payload['message_type'],
                    dbmod.utcnow(),
                ),
            )
            replay_message_id = int(cur.lastrowid)

        replay_payload = self._fetch_payload(replay_message_id)
        with self.assertRaises(ReplayAttackError):
            self.bob_e2ee.decrypt_message_for_user('bob', replay_payload, context='history')


if __name__ == '__main__':
    unittest.main()
