import asyncio
from collections import defaultdict
from typing import Any

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[int, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, user_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections[user_id].add(websocket)

    async def disconnect(self, user_id: int, websocket: WebSocket) -> None:
        async with self._lock:
            if user_id in self._connections:
                self._connections[user_id].discard(websocket)
                if not self._connections[user_id]:
                    del self._connections[user_id]

    async def send_to_user(self, user_id: int, payload: dict[str, Any]) -> bool:
        async with self._lock:
            sockets = list(self._connections.get(user_id, set()))
        delivered = False
        stale: list[WebSocket] = []
        for ws in sockets:
            try:
                await ws.send_json(payload)
                delivered = True
            except Exception:
                stale.append(ws)
        for ws in stale:
            await self.disconnect(user_id, ws)
        return delivered

    async def broadcast_users(self) -> list[int]:
        async with self._lock:
            return list(self._connections.keys())

    async def is_online(self, user_id: int) -> bool:
        async with self._lock:
            return bool(self._connections.get(user_id))
