"""WebSocket connection manager for live clients."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import WebSocket

log = logging.getLogger("cozy.web.ws")


class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self.active.append(websocket)
        log.info("ws client connected (%d total)", len(self.active))

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            if websocket in self.active:
                self.active.remove(websocket)
        log.info("ws client disconnected (%d total)", len(self.active))

    async def broadcast_json(self, message: dict[str, Any]) -> None:
        dead: list[WebSocket] = []
        async with self._lock:
            clients = list(self.active)
        for ws in clients:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.disconnect(ws)


manager = ConnectionManager()
