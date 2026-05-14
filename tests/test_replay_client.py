"""Replay websocket client tests."""

from __future__ import annotations

from typing import Any

import pytest

from custom_components.haro.const import DEFAULT_REPLAY_URL, REPLAY_URL_LOG_ONLY
from custom_components.haro.replay_client import LoggingReplayClient, ReplayWebSocketClient, replay_client_from_config


class FakeWebSocket:
    def __init__(self, *, fail_receive: bool = False) -> None:
        self.sent: list[dict[str, Any]] = []
        self.fail_receive = fail_receive

    async def send_json(self, payload: dict[str, Any]) -> None:
        self.sent.append(payload)

    async def receive_json(self) -> dict[str, Any]:
        if self.fail_receive:
            raise ConnectionError("closed")
        return {"type": "ack", "id": self.sent[-1]["id"], "inserted": len(self.sent[-1]["states"])}

    async def close(self) -> None:
        return None


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


@pytest.mark.asyncio
async def test_client_reconnects_and_resends_unacked_batch() -> None:
    sockets = [FakeWebSocket(fail_receive=True), FakeWebSocket()]

    async def connect(url: str, headers: dict[str, str]) -> FakeWebSocket:
        return sockets.pop(0)

    client = ReplayWebSocketClient(DEFAULT_REPLAY_URL, "token", "site-1", "haeo-entry", connect)
    ack = await client.send_states([{"entity_id": "sensor.energy", "time": "2026-01-01T00:00:00Z"}])

    assert ack["type"] == "ack"
    assert client.stats.reconnects == 1
    assert sockets == []
