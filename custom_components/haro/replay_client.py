"""Replay websocket client for HARO."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from .const import CONF_REPLAY_URL, CONF_TOKEN

StatePayload = dict[str, Any]
ConnectFn = Callable[[str, dict[str, str]], Awaitable[Any]]


class ReplayClientError(Exception):
    """Base Replay client error."""


class ReplayAuthError(ReplayClientError):
    """Replay token was rejected."""


@dataclass(slots=True)
class ReplayClientStats:
    """Replay client counters."""

    sent_batches: int = 0
    sent_states: int = 0
    dropped_states: int = 0
    reconnects: int = 0
    last_ack_id: str | None = None
    last_error: str | None = None


@dataclass
class ReplayWebSocketClient:
    """Small ack-based websocket client for Replay ingest."""

    url: str
    token: str
    connect_fn: ConnectFn | None = None
    stats: ReplayClientStats = field(default_factory=ReplayClientStats)
    _ws: Any | None = None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @classmethod
    def from_config(cls, data: Mapping[str, Any]) -> ReplayWebSocketClient:
        """Create a client from config-entry data."""
        return cls(url=str(data[CONF_REPLAY_URL]), token=str(data[CONF_TOKEN]))

    async def connect(self) -> None:
        """Connect to Replay using bearer auth."""
        if self._ws is not None:
            return
        headers = {"Authorization": f"Bearer {self.token}"}
        connect_fn = self.connect_fn or _default_connect
        self._ws = await connect_fn(self.url, headers)

    async def close(self) -> None:
        """Close the websocket if open."""
        ws = self._ws
        self._ws = None
        if ws is not None and hasattr(ws, "close"):
            result = ws.close()
            if hasattr(result, "__await__"):
                await result

    async def send_states(self, states: list[StatePayload]) -> dict[str, Any]:
        """Send states and wait for a matching ack."""
        if not states:
            return {"inserted": 0}
        async with self._lock:
            batch_id = uuid4().hex
            for attempt in range(2):
                try:
                    return await self._send_once(batch_id, states)
                except Exception as e:
                    self.stats.last_error = str(e)
                    await self.close()
                    if attempt > 0:
                        raise
                    self.stats.reconnects += 1
            raise ReplayClientError("unreachable")

    async def _send_once(self, batch_id: str, states: list[StatePayload]) -> dict[str, Any]:
        await self.connect()
        assert self._ws is not None
        await self._ws.send_json({"type": "states", "id": batch_id, "states": states})
        while True:
            msg = await self._ws.receive_json()
            if msg.get("type") == "ack" and msg.get("id") == batch_id:
                self.stats.sent_batches += 1
                self.stats.sent_states += len(states)
                self.stats.last_ack_id = batch_id
                return msg
            if msg.get("type") == "error":
                self.stats.last_error = str(msg.get("error", "unknown"))
                raise ReplayClientError(self.stats.last_error)


async def _default_connect(url: str, headers: dict[str, str]) -> Any:
    """Connect with aiohttp when running inside Home Assistant."""
    import aiohttp

    session = aiohttp.ClientSession()
    try:
        return await session.ws_connect(url, headers=headers, heartbeat=30)
    except Exception:
        await session.close()
        raise
