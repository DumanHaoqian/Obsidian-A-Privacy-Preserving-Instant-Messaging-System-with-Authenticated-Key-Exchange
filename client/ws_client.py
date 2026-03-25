from __future__ import annotations

import json
import threading
import time
from typing import Callable, Optional
from urllib.parse import urlencode, urlparse, urlunparse

from websockets.sync.client import connect

EventHandler = Callable[[dict], None]


class WebSocketListener:
    def __init__(self, http_base_url: str, access_token: str, on_event: EventHandler) -> None:
        self.http_base_url = http_base_url.rstrip('/')
        self.access_token = access_token
        self.on_event = on_event
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def _ws_url(self) -> str:
        parsed = urlparse(self.http_base_url)
        scheme = 'wss' if parsed.scheme == 'https' else 'ws'
        path = '/ws'
        query = urlencode({'token': self.access_token})
        return urlunparse((scheme, parsed.netloc, path, '', query, ''))

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    @staticmethod
    def _is_auth_error(exc: Exception) -> bool:
        # websockets raises different exception types by version; message match is stable enough here.
        message = str(exc).lower()
        return 'http 401' in message or 'http 403' in message

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                with connect(self._ws_url(), open_timeout=5) as websocket:
                    while not self._stop.is_set():
                        try:
                            message = websocket.recv(timeout=1)
                        except TimeoutError:
                            # No message yet; keep listening (do not treat as disconnect).
                            continue
                        self.on_event(json.loads(message))
            except Exception as exc:
                if self._stop.is_set():
                    break
                if self._is_auth_error(exc):
                    self.on_event(
                        {
                            'event': 'auth_failed',
                            'data': {
                                'message': 'websocket authentication failed (token invalid or expired); please login again'
                            },
                        }
                    )
                    break
                self.on_event({'event': 'system', 'data': {'message': f'websocket reconnecting after error: {exc}'}})
                time.sleep(2)
