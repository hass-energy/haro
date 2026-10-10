"""Replay websocket client tests."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import pytest

from custom_components.haro.const import DEFAULT_REPLAY_URL, REPLAY_URL_LOG_ONLY
from custom_components.haro.replay_client import (
    LoggingReplayClient,
    ReplayWebSocketClient,
    _default_connect,
    replay_client_from_config,
)


class FakeWebSocket:
    def __init__(
        self, *, fail_receive: bool = False, hang: bool = False, messages: list[dict[str, Any]] | None = None
    ) -> None:
        self.sent: list[dict[str, Any]] = []
        self.fail_receive = fail_receive
        self.hang = hang
        self.messages = list(messages or [])
        self.closed = False

    async def send_json(self, payload: dict[str, Any]) -> None:
        self.sent.append(payload)

    async def receive_json(self) -> dict[str, Any]:
        if self.fail_receive:
            raise ConnectionError("closed")
        if self.messages:
            return self.messages.pop(0)
        if self.hang:
            await asyncio.Event().wait()
        sent = self.sent[-1]
        inserted = len(sent["states"]) if "states" in sent else 1
        return {"type": "ack", "id": sent["id"], "inserted": inserted}

    async def close(self) -> None:
        self.closed = True


def config_state(site_id: str, config_hash: str) -> dict[str, Any]:
    return {
        "type": "config_state",
        "site_id": site_id,
        "haeo_entry_id": "haeo-entry",
        "config_hash": config_hash,
        "config_version": "1.3",
        "environment": None,
    }


def test_client_from_config_uses_default_replay_url() -> None:
    client = ReplayWebSocketClient.from_config(
        {"token": "token", "replay_site_id": "site-1", "haeo_config_entry_id": "haeo-entry"}
    )

    assert client.url == DEFAULT_REPLAY_URL
    assert client.token == "token"
    assert client.site_id == "site-1"
    assert client.haeo_entry_id == "haeo-entry"


def test_replay_client_factory_uses_default_replay_url() -> None:
    client = replay_client_from_config(
        {"token": "token", "replay_site_id": "site-1", "haeo_config_entry_id": "haeo-entry"}
    )

    assert isinstance(client, ReplayWebSocketClient)
    assert client.url == DEFAULT_REPLAY_URL
    assert client.token == "token"
    assert client.site_id == "site-1"
    assert client.haeo_entry_id == "haeo-entry"


@pytest.mark.asyncio
async def test_log_only_client_acknowledges_without_websocket() -> None:
    client = replay_client_from_config({"token": "token"}, REPLAY_URL_LOG_ONLY)

    assert isinstance(client, LoggingReplayClient)

    ack = await client.send_states([{"entity_id": "sensor.energy", "time": "2026-01-01T00:00:00Z"}])

    assert ack == {"inserted": 1}
    assert client.stats.sent_batches == 1
    assert client.stats.sent_states == 1
    assert client.stats.last_states_ack_id is None
    assert isinstance(client.stats.last_sync_attempt, datetime)
    assert isinstance(client.stats.last_sync, datetime)
    assert client.stats.status_code == 200


@pytest.mark.asyncio
async def test_log_only_client_records_config_event_stats() -> None:
    client = replay_client_from_config({"token": "token"}, REPLAY_URL_LOG_ONLY)
    event = {"type": "config_checkpoint", "id": "event-1"}

    ack = await client.send_config_event(event)

    assert ack == {"type": "ack", "id": "event-1", "inserted": 1}
    assert client.stats.sent_config_events == 1
    assert client.stats.last_config_ack_id == "event-1"
    assert isinstance(client.stats.last_config_sync_attempt, datetime)
    assert isinstance(client.stats.last_config_sync, datetime)
    assert not hasattr(client.stats, "last_ack_id")


@pytest.mark.asyncio
async def test_client_uses_bearer_auth_and_waits_for_ack() -> None:
    calls: list[tuple[str, dict[str, str]]] = []
    ws = FakeWebSocket()

    async def connect(url: str, headers: dict[str, str]) -> FakeWebSocket:
        calls.append((url, headers))
        return ws

    client = ReplayWebSocketClient(DEFAULT_REPLAY_URL, "token", "site-1", "haeo-entry", connect)
    ack = await client.send_states([{"entity_id": "sensor.energy", "time": "2026-01-01T00:00:00Z"}])

    assert calls == [(DEFAULT_REPLAY_URL, {"Authorization": "Bearer token"})]
    assert ws.sent[0]["type"] == "states"
    assert ws.sent[0]["site_id"] == "site-1"
    assert ws.sent[0]["haeo_entry_id"] == "haeo-entry"
    assert ack["type"] == "ack"
    assert client.stats.sent_batches == 1
    assert client.stats.sent_states == 1
    assert client.stats.last_states_ack_id == ws.sent[0]["id"]
    assert isinstance(client.stats.last_sync_attempt, datetime)
    assert isinstance(client.stats.last_sync, datetime)
    assert client.stats.status_code == 200


@pytest.mark.asyncio
async def test_client_reconnects_and_resends_unacked_batch() -> None:
    sockets = [FakeWebSocket(fail_receive=True), FakeWebSocket()]

    async def connect(url: str, headers: dict[str, str]) -> FakeWebSocket:
        return sockets.pop(0)

    client = ReplayWebSocketClient(DEFAULT_REPLAY_URL, "token", "site-1", "haeo-entry", connect)
    ack = await client.send_states([{"entity_id": "sensor.energy", "time": "2026-01-01T00:00:00Z"}])

    assert ack["type"] == "ack"
    assert client.stats.reconnects == 1
    assert client.stats.last_error is None
    assert client.stats.status_code == 200
    assert sockets == []


@pytest.mark.asyncio
async def test_client_receives_config_state_after_connect() -> None:
    ws = FakeWebSocket(
        messages=[
            {
                "type": "config_state",
                "site_id": "site-1",
                "haeo_entry_id": "haeo-entry",
                "config_hash": "sha256:known",
                "config_version": "1.3",
                "environment": {"ha_version": "2026.5.0", "haeo_version": "0.5.0", "timezone": "Australia/Sydney"},
            }
        ]
    )

    async def connect(_url: str, _headers: dict[str, str]) -> FakeWebSocket:
        return ws

    client = ReplayWebSocketClient(DEFAULT_REPLAY_URL, "token", "site-1", "haeo-entry", connect)

    state = await client.receive_config_state()

    assert state == {
        "type": "config_state",
        "site_id": "site-1",
        "haeo_entry_id": "haeo-entry",
        "config_hash": "sha256:known",
        "config_version": "1.3",
        "environment": {"ha_version": "2026.5.0", "haeo_version": "0.5.0", "timezone": "Australia/Sydney"},
    }


@pytest.mark.asyncio
async def test_client_sends_config_event_and_waits_for_matching_ack() -> None:
    ws = FakeWebSocket()

    async def connect(_url: str, _headers: dict[str, str]) -> FakeWebSocket:
        return ws

    client = ReplayWebSocketClient(DEFAULT_REPLAY_URL, "token", "site-1", "haeo-entry", connect)
    event = {"type": "config_checkpoint", "id": "event-1", "site_id": "site-1", "haeo_entry_id": "haeo-entry"}

    ack = await client.send_config_event(event)

    assert ws.sent == [event]
    assert ack["type"] == "ack"
    assert ack["id"] == "event-1"
    assert client.stats.sent_config_events == 1
    assert client.stats.last_config_ack_id == "event-1"
    assert isinstance(client.stats.last_config_sync_attempt, datetime)
    assert isinstance(client.stats.last_config_sync, datetime)


@pytest.mark.asyncio
async def test_config_state_is_requested_on_a_fresh_connection() -> None:
    """Replay only announces config_state right after connecting, so an open socket is replaced."""
    first, second = FakeWebSocket(), FakeWebSocket(messages=[config_state("site-1", "sha256:current")])
    sockets = [first, second]

    async def connect(_url: str, _headers: dict[str, str]) -> FakeWebSocket:
        return sockets.pop(0)

    client = ReplayWebSocketClient(DEFAULT_REPLAY_URL, "token", "site-1", "haeo-entry", connect)
    await client.send_states([{"entity_id": "sensor.energy", "time": "2026-01-01T00:00:00Z"}])

    state = await client.receive_config_state()

    assert state["config_hash"] == "sha256:current"
    assert first.closed
    assert sockets == []


@pytest.mark.asyncio
async def test_config_state_skips_announcements_for_other_sites() -> None:
    """A token owning several sites receives one announcement per site."""
    ws = FakeWebSocket(messages=[config_state("site-2", "sha256:other"), config_state("site-1", "sha256:mine")])

    async def connect(_url: str, _headers: dict[str, str]) -> FakeWebSocket:
        return ws

    client = ReplayWebSocketClient(DEFAULT_REPLAY_URL, "token", "site-1", "haeo-entry", connect)

    state = await client.receive_config_state()

    assert state["config_hash"] == "sha256:mine"


@pytest.mark.asyncio
async def test_config_state_times_out_without_blocking_state_uploads() -> None:
    silent, healthy = FakeWebSocket(hang=True), FakeWebSocket()
    sockets = [silent, healthy]

    async def connect(_url: str, _headers: dict[str, str]) -> FakeWebSocket:
        return sockets.pop(0)

    client = ReplayWebSocketClient(
        DEFAULT_REPLAY_URL, "token", "site-1", "haeo-entry", connect, config_state_timeout=0.01
    )

    with pytest.raises(TimeoutError):
        await client.receive_config_state()
    ack = await client.send_states([{"entity_id": "sensor.energy", "time": "2026-01-01T00:00:00Z"}])

    assert silent.closed
    assert ack["type"] == "ack"
    assert healthy.sent[0]["type"] == "states"


class FakeSession:
    def __init__(self) -> None:
        self.ws = FakeWebSocket()
        self.closed = False

    async def ws_connect(self, _url: str, **_kwargs: Any) -> FakeWebSocket:
        return self.ws

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_default_connection_closes_its_session_with_the_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    import aiohttp

    session = FakeSession()
    monkeypatch.setattr(aiohttp, "ClientSession", lambda: session)

    ws = await _default_connect(DEFAULT_REPLAY_URL, {"Authorization": "Bearer token"})
    await ws.close()

    assert session.ws.closed
    assert session.closed
