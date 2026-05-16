"""HARO integration setup tests."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from custom_components.haro import ReplaySiteInfo, async_remove_entry, async_setup, async_setup_entry
from custom_components.haro.const import (
    CONF_HAEO_CONFIG_ENTRY_ID,
    CONF_REPLAY_SITE_ID,
    CONF_REPLAY_URL,
    CONF_TOKEN,
    DOMAIN,
    REPLAY_URL_LOG_ONLY,
)


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
    assert entry.runtime_data.site == ReplaySiteInfo(name="Log only", site_id=None, haeo_config_entry_id=None)


@pytest.mark.asyncio
async def test_async_setup_entry_fetches_selected_replay_site_name() -> None:
    hass = SimpleNamespace(
        data={DOMAIN: {CONF_REPLAY_URL: "wss://replay.example/ws"}},
        bus=FakeBus(),
        config_entries=SimpleNamespace(async_forward_entry_setups=AsyncMock()),
    )
    entry = SimpleNamespace(
        data={
            CONF_TOKEN: "token",
            CONF_REPLAY_SITE_ID: "site-1",
            CONF_HAEO_CONFIG_ENTRY_ID: "haeo-entry",
        },
        async_on_unload=Mock(),
    )
    forwarder = Mock()
    forwarder.async_start = AsyncMock()

    with (
        patch(
            "custom_components.haro.fetch_replay_sites", AsyncMock(return_value=[{"id": "site-1", "name": "Home"}])
        ) as fetch,
        patch("custom_components.haro.replay_client_from_config", Mock()),
        patch("custom_components.haro.HaroForwarder", Mock(return_value=forwarder)),
    ):
        await async_setup_entry(hass, entry)  # type: ignore[arg-type]

    fetch.assert_awaited_once_with("wss://replay.example/ws", "token")
    assert entry.runtime_data.site == ReplaySiteInfo(
        name="Home",
        site_id="site-1",
        haeo_config_entry_id="haeo-entry",
    )


@pytest.mark.asyncio
async def test_async_setup_entry_refreshes_replay_site_name_after_recovery() -> None:
    hass = SimpleNamespace(
        data={DOMAIN: {CONF_REPLAY_URL: "wss://replay.example/ws"}},
        bus=FakeBus(),
        config_entries=SimpleNamespace(async_forward_entry_setups=AsyncMock()),
    )
    entry = SimpleNamespace(
        data={
            CONF_TOKEN: "token",
            CONF_REPLAY_SITE_ID: "site-1",
            CONF_HAEO_CONFIG_ENTRY_ID: "haeo-entry",
        },
        async_on_unload=Mock(),
    )
    forwarder = Mock()
    forwarder.async_start = AsyncMock()
    created_forwarder: Mock | None = None

    def create_forwarder(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal created_forwarder
        created_forwarder = Mock()
        created_forwarder.async_start = AsyncMock()
        created_forwarder.on_replay_recovered = kwargs["on_replay_recovered"]
        return created_forwarder

    with (
        patch(
            "custom_components.haro.fetch_replay_sites",
            AsyncMock(
                side_effect=[
                    [{"id": "site-1", "name": "Home"}],
                    [{"id": "site-1", "name": "Updated Home"}],
                ]
            ),
        ),
        patch("custom_components.haro.replay_client_from_config", Mock()),
        patch("custom_components.haro.HaroForwarder", create_forwarder),
    ):
        await async_setup_entry(hass, entry)  # type: ignore[arg-type]
        assert created_forwarder is not None
        await created_forwarder.on_replay_recovered()

    assert entry.runtime_data.site.name == "Updated Home"


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
async def test_async_setup_entry_repairs_legacy_entry_with_one_replay_site() -> None:
    config_entries = SimpleNamespace(async_forward_entry_setups=AsyncMock())
    config_entries.async_update_entry = Mock()
    hass = SimpleNamespace(
        data={DOMAIN: {CONF_REPLAY_URL: "wss://replay.example/ws"}},
        bus=FakeBus(),
        config_entries=config_entries,
    )
    entry = SimpleNamespace(
        data={CONF_TOKEN: "token", CONF_HAEO_CONFIG_ENTRY_ID: "haeo-entry"},
        async_on_unload=Mock(),
    )
    client = Mock()
    forwarder = Mock()
    forwarder.async_start = AsyncMock()

    with (
        patch("custom_components.haro.fetch_replay_sites", AsyncMock(return_value=[{"id": "site-1"}])) as fetch,
        patch("custom_components.haro.bind_replay_site", AsyncMock()) as bind,
        patch("custom_components.haro.replay_client_from_config", Mock(return_value=client)) as create_client,
        patch("custom_components.haro.HaroForwarder", Mock(return_value=forwarder)),
    ):
        result = await async_setup_entry(hass, entry)  # type: ignore[arg-type]

    repaired_data = {
        CONF_TOKEN: "token",
        CONF_HAEO_CONFIG_ENTRY_ID: "haeo-entry",
        CONF_REPLAY_SITE_ID: "site-1",
    }
    assert result is True
    fetch.assert_awaited_once_with("wss://replay.example/ws", "token")
    bind.assert_awaited_once_with("wss://replay.example/ws", "token", "site-1", "haeo-entry", confirm=True)
    config_entries.async_update_entry.assert_called_once_with(entry, data=repaired_data)
    create_client.assert_called_once_with(repaired_data, "wss://replay.example/ws")


@pytest.mark.asyncio
async def test_async_remove_entry_removes_queue_log() -> None:
    hass = SimpleNamespace()
    entry = SimpleNamespace(entry_id="haro-entry")
    queue_log = Mock()
    queue_log.async_remove = AsyncMock()
    config_queue = Mock()
    config_queue.async_remove = AsyncMock()

    with (
        patch("custom_components.haro.QueueLog", Mock(return_value=queue_log)),
        patch("custom_components.haro.ConfigEventQueue", Mock(return_value=config_queue)),
    ):
        result = await async_remove_entry(hass, entry)  # type: ignore[arg-type]

    assert result is None
    queue_log.async_remove.assert_awaited_once()
    config_queue.async_remove.assert_awaited_once()
