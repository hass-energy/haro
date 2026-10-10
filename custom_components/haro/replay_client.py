"""Replay websocket client for HARO."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol
from uuid import uuid4

from homeassistant.util import dt as dt_util

from .const import CONF_HAEO_CONFIG_ENTRY_ID, CONF_REPLAY_SITE_ID, CONF_TOKEN, DEFAULT_REPLAY_URL, REPLAY_URL_LOG_ONLY

_LOGGER = logging.getLogger(__name__)

StatePayload = dict[str, Any]
ConfigPayload = dict[str, Any]
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

    async def receive_config_state(self) -> dict[str, Any]:
        """Receive Replay's config_state announcement."""
        ...

    async def send_config_event(self, event: ConfigPayload) -> dict[str, Any]:
        """Send a config checkpoint or patch event."""
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
    sent_config_events: int = 0
    dropped_states: int = 0
    reconnects: int = 0
    last_states_ack_id: str | None = None
    last_config_ack_id: str | None = None
    last_sync_attempt: datetime | None = None
    last_sync: datetime | None = None
    last_config_sync_attempt: datetime | None = None
    last_config_sync: datetime | None = None
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
    config_state_timeout: float = 30.0
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

    async def receive_config_state(self) -> dict[str, Any]:
        """Receive this site's config_state, which Replay only announces right after connecting."""
        async with self._lock:
            await self.close()
            try:
                async with asyncio.timeout(self.config_state_timeout):
                    await self.connect()
                    return await self._receive_own_config_state()
            except Exception as e:
                self.stats.last_error = str(e) or type(e).__name__
                await self.close()
                raise

    async def _receive_own_config_state(self) -> dict[str, Any]:
        assert self._ws is not None
        while True:
            msg = await self._ws.receive_json()
            if msg.get("type") == "config_state" and msg.get("site_id") == self.site_id:
                return msg
            if msg.get("type") == "error":
                raise ReplayClientError(str(msg.get("error", "unknown")))

    async def send_config_event(self, event: ConfigPayload) -> dict[str, Any]:
        """Send one queued config event and wait for its matching ack."""
        event_id = event.get("id")
        if not isinstance(event_id, str) or not event_id:
            raise ReplayClientError("config event id is required")
        async with self._lock:
            for attempt in range(2):
                try:
                    return await self._send_config_once(event)
                except Exception as e:
                    self.stats.last_error = str(e)
                    self.stats.status_code = None
                    await self.close()
                    if attempt > 0:
                        raise
                    self.stats.reconnects += 1
            raise ReplayClientError("unreachable")

    async def _send_once(self, batch_id: str, states: list[StatePayload]) -> dict[str, Any]:
        self.stats.last_sync_attempt = dt_util.utcnow()
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
                self.stats.last_states_ack_id = batch_id
                self.stats.last_sync = dt_util.utcnow()
                self.stats.last_error = None
                self.stats.status_code = 200
                return msg
            if msg.get("type") == "error":
                self.stats.last_error = str(msg.get("error", "unknown"))
                status_code = msg.get("status_code")
                self.stats.status_code = status_code if isinstance(status_code, int) else None
                raise ReplayClientError(self.stats.last_error)

    async def _send_config_once(self, event: ConfigPayload) -> dict[str, Any]:
        self.stats.last_config_sync_attempt = dt_util.utcnow()
        await self.connect()
        assert self._ws is not None
        await self._ws.send_json(event)
        event_id = event["id"]
        while True:
            msg = await self._ws.receive_json()
            if msg.get("type") == "ack" and msg.get("id") == event_id:
                self.stats.sent_config_events += 1
                self.stats.last_config_ack_id = str(event_id)
                self.stats.last_config_sync = dt_util.utcnow()
                self.stats.last_error = None
                self.stats.status_code = 200
                return msg
            if msg.get("type") == "needs_checkpoint" and msg.get("id") == event_id:
                self.stats.last_error = str(msg.get("error", "needs_checkpoint"))
                raise ReplayClientError(self.stats.last_error)
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
        now = dt_util.utcnow()
        self.stats.sent_batches += 1
        self.stats.sent_states += len(states)
        self.stats.last_sync_attempt = now
        self.stats.last_sync = now
        self.stats.status_code = 200
        return {"inserted": len(states)}

    async def receive_config_state(self) -> dict[str, Any]:
        """Return an empty config state in log-only mode."""
        return {"type": "config_state", "config_hash": None, "config_version": None, "environment": None}

    async def send_config_event(self, event: ConfigPayload) -> dict[str, Any]:
        """Log config event payloads and return an ack-like response."""
        _LOGGER.info("HARO log_only Replay received config event: %s", event)
        event_id = event.get("id")
        now = dt_util.utcnow()
        self.stats.sent_config_events += 1
        self.stats.last_config_ack_id = str(event_id) if event_id is not None else None
        self.stats.last_config_sync_attempt = now
        self.stats.last_config_sync = now
        self.stats.status_code = 200
        return {"type": "ack", "id": event_id, "inserted": 1}


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
        ws = await session.ws_connect(url, headers=headers, heartbeat=30)
    except Exception:
        await session.close()
        raise
    return _SessionWebSocket(ws, session)


@dataclass
class _SessionWebSocket:
    """Websocket that owns its aiohttp session, so closing one closes both."""

    ws: Any
    session: Any

    async def send_json(self, payload: dict[str, Any]) -> None:
        await self.ws.send_json(payload)

    async def receive_json(self) -> dict[str, Any]:
        return await self.ws.receive_json()

    async def close(self) -> None:
        try:
            await self.ws.close()
        finally:
            await self.session.close()
