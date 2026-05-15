"""HARO integration setup tests."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from custom_components.haro import async_remove_entry, async_setup, async_setup_entry
from custom_components.haro.const import CONF_REPLAY_URL, DOMAIN, REPLAY_URL_LOG_ONLY


class FakeBus:
    def __init__(self) -> None:
        self.event_type: str | None = None
        self.handler: Callable[[object], Awaitable[None]] | None = None
        self.unsubscribe = Mock()

    def async_listen_once(self, event_type: str, handler: Callable[[object], Awaitable[None]]) -> Mock:
        self.event_type = event_type
        self.handler = handler
        return self.unsubscribe


@pytest.mark.asyncio
async def test_async_setup_stores_yaml_replay_url() -> None:
    hass = SimpleNamespace(data={})

    result = await async_setup(hass, {DOMAIN: {CONF_REPLAY_URL: REPLAY_URL_LOG_ONLY}})  # type: ignore[arg-type]

    assert result is True
    assert hass.data[DOMAIN][CONF_REPLAY_URL] == REPLAY_URL_LOG_ONLY


@pytest.mark.asyncio
async def test_async_setup_entry_uses_yaml_replay_url() -> None:
    hass = SimpleNamespace(
        data={DOMAIN: {CONF_REPLAY_URL: REPLAY_URL_LOG_ONLY}},
        bus=FakeBus(),
        config_entries=SimpleNamespace(async_forward_entry_setups=AsyncMock()),
    )
    entry = SimpleNamespace(data={"token": "token"}, async_on_unload=Mock())
    client = Mock()
    forwarder = Mock()
    forwarder.async_start = AsyncMock()

    with (
        patch("custom_components.haro.replay_client_from_config", Mock(return_value=client)) as create_client,
        patch("custom_components.haro.HaroForwarder", Mock(return_value=forwarder)),
    ):
        result = await async_setup_entry(hass, entry)  # type: ignore[arg-type]

    assert result is True
    create_client.assert_called_once_with(entry.data, REPLAY_URL_LOG_ONLY)
    forwarder.async_start.assert_awaited_once()
    hass.config_entries.async_forward_entry_setups.assert_awaited_once()


@pytest.mark.asyncio
async def test_async_setup_entry_stops_forwarder_on_home_assistant_stop() -> None:
    bus = FakeBus()
    hass = SimpleNamespace(
        data={DOMAIN: {CONF_REPLAY_URL: REPLAY_URL_LOG_ONLY}},
        bus=bus,
        config_entries=SimpleNamespace(async_forward_entry_setups=AsyncMock()),
    )
    entry = SimpleNamespace(data={"token": "token"}, async_on_unload=Mock())
    forwarder = Mock()
    forwarder.async_start = AsyncMock()
    forwarder.async_stop = AsyncMock()

    with (
        patch("custom_components.haro.replay_client_from_config", Mock()),
        patch("custom_components.haro.HaroForwarder", Mock(return_value=forwarder)),
    ):
        await async_setup_entry(hass, entry)  # type: ignore[arg-type]

    assert bus.event_type == "homeassistant_stop"
    assert bus.handler is not None
    await bus.handler(None)
    forwarder.async_stop.assert_awaited_once()
    entry.async_on_unload.assert_any_call(bus.unsubscribe)


@pytest.mark.asyncio
async def test_async_remove_entry_removes_queue_log() -> None:
    hass = SimpleNamespace()
    entry = SimpleNamespace(entry_id="haro-entry")
    queue_log = Mock()
    queue_log.async_remove = AsyncMock()

    with patch("custom_components.haro.QueueLog", Mock(return_value=queue_log)):
        result = await async_remove_entry(hass, entry)  # type: ignore[arg-type]

    assert result is None
    queue_log.async_remove.assert_awaited_once()
