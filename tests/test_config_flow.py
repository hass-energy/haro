"""Home Assistant config-flow tests."""

from __future__ import annotations

import importlib
from unittest.mock import AsyncMock, patch

import pytest
import voluptuous as vol
from homeassistant.helpers.selector import SelectSelectorMode
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.haro.const import (
    CONF_HAEO_CONFIG_ENTRY_ID,
    CONF_REPLAY_URL,
    CONF_TOKEN,
    DEFAULT_REPLAY_URL,
    DOMAIN,
)

ha = pytest.importorskip("homeassistant.config_entries")


def add_haeo_entry(hass, entry_id: str = "haeo-entry", title: str = "Home Energy") -> MockConfigEntry:  # type: ignore[no-untyped-def]
    entry = MockConfigEntry(domain="haeo", entry_id=entry_id, title=title)
    entry.add_to_hass(hass)
    return entry


def create_flow(module, hass):  # type: ignore[no-untyped-def]
    flow = module.HaroConfigFlow()
    flow.hass = hass
    flow.handler = DOMAIN
    flow.context = {"source": "user"}
    return flow


@pytest.mark.asyncio
async def test_config_flow_defaults_to_hosted_replay_url(hass) -> None:  # type: ignore[no-untyped-def]
    add_haeo_entry(hass)
    module = importlib.import_module("custom_components.haro.config_flow")
    flow = create_flow(module, hass)

    result = await flow.async_step_user()

    replay_url_key = next(key for key in result["data_schema"].schema if key.schema == CONF_REPLAY_URL)
    assert replay_url_key.default() == DEFAULT_REPLAY_URL


@pytest.mark.asyncio
async def test_config_flow_shows_dropdown_placeholder_without_haeo_entries(hass) -> None:  # type: ignore[no-untyped-def]
    module = importlib.import_module("custom_components.haro.config_flow")
    flow = create_flow(module, hass)

    result = await flow.async_step_user()

    assert result["type"] == "form"
    haeo_entry_key = next(key for key in result["data_schema"].schema if key.schema == CONF_HAEO_CONFIG_ENTRY_ID)
    assert isinstance(haeo_entry_key, vol.Required)
    haeo_entry_selector = result["data_schema"].schema[haeo_entry_key]
    assert haeo_entry_selector.config["mode"] == SelectSelectorMode.DROPDOWN
    assert haeo_entry_selector.config["options"] == [
        {"value": "__no_haeo_entries__", "label": "No HAEO installs found"}
    ]


@pytest.mark.asyncio
async def test_config_flow_requires_replay_validation(hass) -> None:  # type: ignore[no-untyped-def]
    haeo_entry = add_haeo_entry(hass)
    module = importlib.import_module("custom_components.haro.config_flow")
    flow = create_flow(module, hass)

    with patch("custom_components.haro.config_flow.validate_replay_connection", AsyncMock()) as validate:
        result = await flow.async_step_user(
            {
                CONF_HAEO_CONFIG_ENTRY_ID: haeo_entry.entry_id,
                CONF_REPLAY_URL: DEFAULT_REPLAY_URL,
                CONF_TOKEN: "token",
            }
        )

    validate.assert_awaited_once_with(DEFAULT_REPLAY_URL, "token")
    assert result["type"] == "create_entry"
    assert result["title"] == "HARO - Home Energy"
    assert result["data"][CONF_HAEO_CONFIG_ENTRY_ID] == haeo_entry.entry_id
    assert result["data"][CONF_REPLAY_URL] == DEFAULT_REPLAY_URL
    assert DOMAIN == "haro"


@pytest.mark.asyncio
async def test_config_flow_rejects_no_haeo_placeholder(hass) -> None:  # type: ignore[no-untyped-def]
    module = importlib.import_module("custom_components.haro.config_flow")
    flow = create_flow(module, hass)

    with patch("custom_components.haro.config_flow.validate_replay_connection", AsyncMock()) as validate:
        result = await flow.async_step_user(
            {
                CONF_HAEO_CONFIG_ENTRY_ID: "__no_haeo_entries__",
                CONF_REPLAY_URL: DEFAULT_REPLAY_URL,
                CONF_TOKEN: "token",
            }
        )

    validate.assert_not_called()
    assert result["type"] == "form"
    assert result["errors"] == {"base": "invalid_haeo_entry"}


@pytest.mark.asyncio
async def test_config_flow_rejects_duplicate_haeo_entry(hass) -> None:  # type: ignore[no-untyped-def]
    haeo_entry = add_haeo_entry(hass)
    MockConfigEntry(domain=DOMAIN, unique_id=haeo_entry.entry_id).add_to_hass(hass)
    module = importlib.import_module("custom_components.haro.config_flow")
    flow = create_flow(module, hass)

    with patch("custom_components.haro.config_flow.validate_replay_connection", AsyncMock()):
        result = await flow.async_step_user(
            {
                CONF_HAEO_CONFIG_ENTRY_ID: haeo_entry.entry_id,
                CONF_REPLAY_URL: DEFAULT_REPLAY_URL,
                CONF_TOKEN: "token",
            }
        )

    assert result["type"] == "abort"
    assert result["reason"] == "already_configured"
