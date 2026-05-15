"""Replay websocket client for HARO."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import uuid4

from .const import CONF_HAEO_CONFIG_ENTRY_ID, CONF_REPLAY_SITE_ID, CONF_TOKEN, DEFAULT_REPLAY_URL, REPLAY_URL_LOG_ONLY

_LOGGER = logging.getLogger(__name__)

StatePayload = dict[str, Any]
ConnectFn = Callable[[str, dict[str, str]], Awaitable[Any]]


class ReplayClient(Protocol):
    """Small interface HARO uses for Replay transports."""

    stats: ReplayClientStats

    async def close(self) -> None:
        """Close the client."""
        ...

    async def send_states(self, states: list[StatePayload]) -> dict[str, Any]:
        """Send state payloads."""
        ...


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
    status_code: int | None = None


@dataclass
class ReplayWebSocketClient:
    """Small ack-based websocket client for Replay ingest."""

    url: str
    token: str
    site_id: str
    haeo_entry_id: str
    connect_fn: ConnectFn | None = None
    stats: ReplayClientStats = field(default_factory=ReplayClientStats)
    _ws: Any | None = None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @classmethod
    def from_config(cls, data: Mapping[str, Any]) -> ReplayWebSocketClient:
        """Create a client from config-entry data."""
        return cls(
            url=DEFAULT_REPLAY_URL,
            token=str(data[CONF_TOKEN]),
            site_id=str(data[CONF_REPLAY_SITE_ID]),
            haeo_entry_id=str(data[CONF_HAEO_CONFIG_ENTRY_ID]),
        )

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
                    self.stats.status_code = None
                    await self.close()
                    if attempt > 0:
                        raise
                    self.stats.reconnects += 1
            raise ReplayClientError("unreachable")

    async def _send_once(self, batch_id: str, states: list[StatePayload]) -> dict[str, Any]:
        await self.connect()
        assert self._ws is not None
        await self._ws.send_json(
            {
                "type": "states",
                "id": batch_id,
                "site_id": self.site_id,
                "haeo_entry_id": self.haeo_entry_id,
                "states": states,
            }
        )
        while True:
            msg = await self._ws.receive_json()
            if msg.get("type") == "ack" and msg.get("id") == batch_id:
                self.stats.sent_batches += 1
                self.stats.sent_states += len(states)
                self.stats.last_ack_id = batch_id
                self.stats.last_error = None
                self.stats.status_code = 200
                return msg
            if msg.get("type") == "error":
                self.stats.last_error = str(msg.get("error", "unknown"))
                status_code = msg.get("status_code")
                self.stats.status_code = status_code if isinstance(status_code, int) else None
                raise ReplayClientError(self.stats.last_error)


@dataclass
class LoggingReplayClient:
    """Replay client that logs payloads instead of sending them."""

    stats: ReplayClientStats = field(default_factory=ReplayClientStats)

    async def close(self) -> None:
        """Close the logging client."""
        return None

    async def send_states(self, states: list[StatePayload]) -> dict[str, Any]:
        """Log state payloads and return an ack-like response."""
        if not states:
            return {"inserted": 0}
        _LOGGER.info("HARO log_only Replay received %s states: %s", len(states), states)
        self.stats.sent_batches += 1
        self.stats.sent_states += len(states)
        self.stats.status_code = 200
        return {"inserted": len(states)}


def replay_client_from_config(data: Mapping[str, Any], replay_url: str = DEFAULT_REPLAY_URL) -> ReplayClient:
    """Create a Replay client from config-entry data and resolved Replay URL."""
    if replay_url == REPLAY_URL_LOG_ONLY:
        return LoggingReplayClient()
    return ReplayWebSocketClient(
        url=replay_url,
        token=str(data[CONF_TOKEN]),
        site_id=str(data[CONF_REPLAY_SITE_ID]),
        haeo_entry_id=str(data[CONF_HAEO_CONFIG_ENTRY_ID]),
    )


async def _default_connect(url: str, headers: dict[str, str]) -> Any:
    """Connect with aiohttp when running inside Home Assistant."""
    import aiohttp

    session = aiohttp.ClientSession()
    try:
        return await session.ws_connect(url, headers=headers, heartbeat=30)
    except Exception:
        await session.close()
        raise
