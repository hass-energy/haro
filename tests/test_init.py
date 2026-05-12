"""HARO integration setup tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from custom_components.haro import async_setup, async_setup_entry
from custom_components.haro.const import CONF_REPLAY_URL, DOMAIN, REPLAY_URL_LOG_ONLY


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
