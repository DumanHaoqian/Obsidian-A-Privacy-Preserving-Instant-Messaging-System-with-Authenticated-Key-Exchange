from __future__ import annotations

from typing import Any, Optional

import httpx


class ApiClient:
    def __init__(self, base_url: str, access_token: Optional[str] = None) -> None:
        self.base_url = base_url.rstrip('/')
        self.access_token = access_token
        self.http = httpx.Client(base_url=self.base_url, timeout=15.0)

    def close(self) -> None:
        self.http.close()

    def set_token(self, token: Optional[str]) -> None:
        self.access_token = token

    def _headers(self) -> dict[str, str]:
        headers = {'Content-Type': 'application/json'}
        if self.access_token:
            headers['Authorization'] = f'Bearer {self.access_token}'
        return headers

    def _handle(self, response: httpx.Response) -> Any:
        try:
            data = response.json()
        except Exception:
            response.raise_for_status()
            return response.text
        if response.status_code >= 400:
            detail = data.get('detail', data)
            raise RuntimeError(str(detail))
        return data

    def register(self, username: str, password: str) -> Any:
        return self._handle(self.http.post('/register', json={'username': username, 'password': password}, headers=self._headers()))

    def login_password(self, username: str, password: str) -> Any:
        return self._handle(self.http.post('/login/password', json={'username': username, 'password': password}, headers=self._headers()))

    def login_otp(self, challenge_token: str, otp_code: str) -> Any:
        return self._handle(self.http.post('/login/otp', json={'challenge_token': challenge_token, 'otp_code': otp_code}, headers=self._headers()))

    def logout(self) -> Any:
        return self._handle(self.http.post('/logout', headers=self._headers()))

    def me(self) -> Any:
        return self._handle(self.http.get('/me', headers=self._headers()))

    def store_identity_key(self, device_id: str, public_key: str) -> Any:
        return self._handle(self.http.post('/identity-key', json={'device_id': device_id, 'public_key': public_key}, headers=self._headers()))

    def get_identity_keys(self, username: str) -> Any:
        return self._handle(self.http.get(f'/identity-key/{username}', headers=self._headers()))

    def send_friend_request(self, target_username: str) -> Any:
        return self._handle(self.http.post('/friend-request/send', json={'target_username': target_username}, headers=self._headers()))

    def pending_requests(self) -> Any:
        return self._handle(self.http.get('/friend-request/pending', headers=self._headers()))

    def respond_friend_request(self, request_id: int, action: str) -> Any:
        return self._handle(self.http.post('/friend-request/respond', json={'request_id': request_id, 'action': action}, headers=self._headers()))

    def cancel_friend_request(self, request_id: int) -> Any:
        return self._handle(self.http.post('/friend-request/cancel', json={'request_id': request_id}, headers=self._headers()))

    def contacts(self) -> Any:
        return self._handle(self.http.get('/contacts', headers=self._headers()))

    def send_message(
        self,
        to_username: str,
        content: str,
        message_type: str = 'text',
        ttl_seconds: Optional[int] = None,
    ) -> Any:
        payload = {'to_username': to_username, 'content': content, 'message_type': message_type}
        if ttl_seconds is not None:
            payload['ttl_seconds'] = ttl_seconds
        return self._handle(self.http.post('/messages/send', json=payload, headers=self._headers()))

    def ack_message(self, message_id: int) -> Any:
        return self._handle(self.http.post('/messages/ack', json={'message_id': message_id, 'status': 'delivered'}, headers=self._headers()))

    def conversations(self) -> Any:
        return self._handle(self.http.get('/conversations', headers=self._headers()))

    def pull_messages(self, conversation_id: int, limit: int = 20, before_id: Optional[int] = None, mark_read: bool = True) -> Any:
        params: dict[str, Any] = {'conversation_id': conversation_id, 'limit': limit, 'mark_read': str(mark_read).lower()}
        if before_id is not None:
            params['before_id'] = before_id
        return self._handle(self.http.get('/messages/pull', params=params, headers=self._headers()))

    def mark_read(self, conversation_id: int) -> Any:
        return self._handle(self.http.post(f'/conversations/{conversation_id}/mark-read', headers=self._headers()))
