"""HARO integration setup tests."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.exceptions import ConfigEntryNotReady

from custom_components.haro import ReplaySiteInfo, async_remove_entry, async_setup, async_setup_entry
from custom_components.haro.config_events import ConfigEnvironment
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


class FakeConfig:
    def path(self, *parts: str) -> str:
        return "/tmp/haro-test/" + "/".join(parts)


class FakeHaeoEntry:
    entry_id = "haeo-entry"
    title = "Home Energy"
    subentries: dict[str, object] = {}

    def __init__(self) -> None:
        self.update_listener: Callable[..., Awaitable[None]] | None = None

    def add_update_listener(self, listener: Callable[..., Awaitable[None]]) -> Mock:
        self.update_listener = listener
        return Mock()


class FakeConfigEntries:
    def __init__(self, haeo_entries: list[FakeHaeoEntry] | None = None) -> None:
        self.haeo_entries = haeo_entries if haeo_entries is not None else [FakeHaeoEntry()]
        self.async_forward_entry_setups = AsyncMock()
        self.async_unload = AsyncMock()
        self.async_update_entry = Mock()

    def async_entries(self, domain: str) -> list[FakeHaeoEntry]:
        if domain == "haeo":
            return self.haeo_entries
        return []


def haro_entry(data: dict[str, object]) -> SimpleNamespace:
    return SimpleNamespace(entry_id="haro-entry", data=data, async_on_unload=Mock())


def haro_hass(replay_url: str, config_entries: FakeConfigEntries | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        data={DOMAIN: {CONF_REPLAY_URL: replay_url}},
        bus=FakeBus(),
        config=FakeConfig(),
        config_entries=config_entries or FakeConfigEntries(),
    )


@pytest.mark.asyncio
async def test_async_setup_stores_yaml_replay_url() -> None:
    hass = SimpleNamespace(data={})

    result = await async_setup(hass, {DOMAIN: {CONF_REPLAY_URL: REPLAY_URL_LOG_ONLY}})  # type: ignore[arg-type]

    assert result is True
    assert hass.data[DOMAIN][CONF_REPLAY_URL] == REPLAY_URL_LOG_ONLY


@pytest.mark.asyncio
async def test_async_setup_entry_uses_yaml_replay_url() -> None:
    hass = haro_hass(REPLAY_URL_LOG_ONLY)
    entry = haro_entry({CONF_TOKEN: "token", CONF_REPLAY_SITE_ID: "site-1", CONF_HAEO_CONFIG_ENTRY_ID: "haeo-entry"})
    client = Mock()
    forwarder = Mock()
    forwarder.async_start = AsyncMock()

    with (
        patch(
            "custom_components.haro._config_environment", AsyncMock(return_value=ConfigEnvironment("ha", "haeo", "UTC"))
        ),
        patch("custom_components.haro.replay_client_from_config", Mock(return_value=client)) as create_client,
        patch("custom_components.haro.HaroForwarder", Mock(return_value=forwarder)),
    ):
        result = await async_setup_entry(hass, entry)  # type: ignore[arg-type]

    assert result is True
    create_client.assert_called_once_with(entry.data, REPLAY_URL_LOG_ONLY)
    forwarder.async_start.assert_awaited_once()
    hass.config_entries.async_forward_entry_setups.assert_awaited_once()
    assert entry.runtime_data.config_sync is not None
    assert entry.runtime_data.site == ReplaySiteInfo(
        name="Log only", site_id="site-1", haeo_config_entry_id="haeo-entry"
    )


@pytest.mark.asyncio
async def test_async_setup_entry_requires_selected_haeo_entry() -> None:
    hass = haro_hass(REPLAY_URL_LOG_ONLY, FakeConfigEntries([]))
    entry = haro_entry(
        {
            CONF_TOKEN: "token",
            CONF_REPLAY_SITE_ID: "site-1",
            CONF_HAEO_CONFIG_ENTRY_ID: "missing-haeo",
        }
    )

    with pytest.raises(ConfigEntryNotReady, match="HAEO config entry missing-haeo is not loaded"):
        await async_setup_entry(hass, entry)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_async_setup_entry_unloads_and_repairs_when_selected_haeo_entry_is_removed() -> None:
    config_entries = FakeConfigEntries()
    hass = haro_hass(REPLAY_URL_LOG_ONLY, config_entries)
    entry = haro_entry(
        {
            CONF_TOKEN: "token",
            CONF_REPLAY_SITE_ID: "site-1",
            CONF_HAEO_CONFIG_ENTRY_ID: "haeo-entry",
        }
    )
    forwarder = Mock()
    forwarder.async_start = AsyncMock()

    with (
        patch(
            "custom_components.haro._config_environment", AsyncMock(return_value=ConfigEnvironment("ha", "haeo", "UTC"))
        ),
        patch("custom_components.haro.replay_client_from_config", Mock()),
        patch("custom_components.haro.HaroForwarder", Mock(return_value=forwarder)),
        patch("custom_components.haro.issue_registry.async_create_issue") as create_issue,
    ):
        await async_setup_entry(hass, entry)  # type: ignore[arg-type]
        haeo_entry = config_entries.haeo_entries[0]
        assert haeo_entry.update_listener is not None

        config_entries.haeo_entries = []
        await haeo_entry.update_listener(hass, haeo_entry)

    create_issue.assert_called_once()
    config_entries.async_unload.assert_awaited_once_with("haro-entry")


@pytest.mark.asyncio
async def test_async_setup_entry_fetches_selected_replay_site_name() -> None:
    hass = haro_hass("wss://replay.example/ws")
    entry = haro_entry(
        {
            CONF_TOKEN: "token",
            CONF_REPLAY_SITE_ID: "site-1",
            CONF_HAEO_CONFIG_ENTRY_ID: "haeo-entry",
        }
    )
    forwarder = Mock()
    forwarder.async_start = AsyncMock()

    with (
        patch(
            "custom_components.haro.fetch_replay_sites", AsyncMock(return_value=[{"id": "site-1", "name": "Home"}])
        ) as fetch,
        patch(
            "custom_components.haro._config_environment", AsyncMock(return_value=ConfigEnvironment("ha", "haeo", "UTC"))
        ),
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
    hass = haro_hass("wss://replay.example/ws")
    entry = haro_entry(
        {
            CONF_TOKEN: "token",
            CONF_REPLAY_SITE_ID: "site-1",
            CONF_HAEO_CONFIG_ENTRY_ID: "haeo-entry",
        }
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
        patch(
            "custom_components.haro._config_environment", AsyncMock(return_value=ConfigEnvironment("ha", "haeo", "UTC"))
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
    hass = haro_hass(REPLAY_URL_LOG_ONLY)
    hass.bus = bus
    entry = haro_entry({CONF_TOKEN: "token", CONF_REPLAY_SITE_ID: "site-1", CONF_HAEO_CONFIG_ENTRY_ID: "haeo-entry"})
    forwarder = Mock()
    forwarder.async_start = AsyncMock()
    forwarder.async_stop = AsyncMock()

    with (
        patch(
            "custom_components.haro._config_environment", AsyncMock(return_value=ConfigEnvironment("ha", "haeo", "UTC"))
        ),
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
    config_entries = FakeConfigEntries()
    hass = haro_hass("wss://replay.example/ws", config_entries)
    entry = haro_entry({CONF_TOKEN: "token", CONF_HAEO_CONFIG_ENTRY_ID: "haeo-entry"})
    client = Mock()
    forwarder = Mock()
    forwarder.async_start = AsyncMock()

    with (
        patch("custom_components.haro.fetch_replay_sites", AsyncMock(return_value=[{"id": "site-1"}])) as fetch,
        patch("custom_components.haro.bind_replay_site", AsyncMock()) as bind,
        patch(
            "custom_components.haro._config_environment", AsyncMock(return_value=ConfigEnvironment("ha", "haeo", "UTC"))
        ),
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
