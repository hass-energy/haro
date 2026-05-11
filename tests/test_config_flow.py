"""Home Assistant config-flow tests."""

from __future__ import annotations

import importlib
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.haro.const import CONF_REPLAY_URL, CONF_TOKEN, DOMAIN

ha = pytest.importorskip("homeassistant.config_entries")


@pytest.mark.asyncio
async def test_config_flow_requires_replay_validation(hass) -> None:  # type: ignore[no-untyped-def]
    module = importlib.import_module("custom_components.haro.config_flow")
    flow = module.HaroConfigFlow()
    flow.hass = hass

    with patch("custom_components.haro.config_flow.validate_replay_connection", AsyncMock()) as validate:
        result = await flow.async_step_user(
            {CONF_REPLAY_URL: "wss://replay.example/api/ingest/ws", CONF_TOKEN: "token"}
        )

    validate.assert_awaited_once_with("wss://replay.example/api/ingest/ws", "token")
    assert result["type"] == "create_entry"
    assert result["title"] == "HARO"
    assert result["data"][CONF_REPLAY_URL] == "wss://replay.example/api/ingest/ws"
    assert DOMAIN == "haro"
