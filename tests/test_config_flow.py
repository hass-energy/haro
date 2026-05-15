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
    CONF_REPLAY_SITE_ID,
    CONF_REPLAY_SITE_NAME,
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


def schema_key(schema, field: str):  # type: ignore[no-untyped-def]
    return next(key for key in schema.schema if key.schema == field)


@pytest.mark.asyncio
async def test_config_flow_does_not_show_replay_url(hass) -> None:  # type: ignore[no-untyped-def]
    add_haeo_entry(hass)
    module = importlib.import_module("custom_components.haro.config_flow")
    flow = create_flow(module, hass)

    result = await flow.async_step_user()

    fields = {key.schema for key in result["data_schema"].schema}
    assert fields == {CONF_HAEO_CONFIG_ENTRY_ID, CONF_TOKEN}


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

    with patch(
        "custom_components.haro.config_flow.fetch_replay_sites",
        AsyncMock(return_value=[{"id": "site-1", "name": "Home"}]),
    ) as fetch:
        result = await flow.async_step_user(
            {
                CONF_HAEO_CONFIG_ENTRY_ID: haeo_entry.entry_id,
                CONF_TOKEN: "token",
            }
        )

    fetch.assert_awaited_once_with(DEFAULT_REPLAY_URL, "token")
    assert result["type"] == "form"
    assert result["step_id"] == "site"

    with patch("custom_components.haro.config_flow.bind_replay_site", AsyncMock()) as bind:
        created = await flow.async_step_site({CONF_REPLAY_SITE_ID: "site-1"})

    bind.assert_awaited_once_with(DEFAULT_REPLAY_URL, "token", "site-1", haeo_entry.entry_id, confirm=True)
    assert created["type"] == "create_entry"
    assert created["title"] == "HARO - Home Energy"
    assert created["data"][CONF_HAEO_CONFIG_ENTRY_ID] == haeo_entry.entry_id
    assert created["data"] == {
        CONF_HAEO_CONFIG_ENTRY_ID: haeo_entry.entry_id,
        CONF_TOKEN: "token",
        CONF_REPLAY_SITE_ID: "site-1",
    }
    assert DOMAIN == "haro"


@pytest.mark.asyncio
async def test_config_flow_defaults_site_matching_selected_haeo_entry(hass) -> None:  # type: ignore[no-untyped-def]
    haeo_entry = add_haeo_entry(hass)
    module = importlib.import_module("custom_components.haro.config_flow")
    flow = create_flow(module, hass)

    with patch(
        "custom_components.haro.config_flow.fetch_replay_sites",
        AsyncMock(
            return_value=[
                {"id": "site-other", "name": "Other", "haeo_entry_id": "other-haeo-entry"},
                {"id": "site-home", "name": "Home", "haeo_entry_id": haeo_entry.entry_id},
            ]
        ),
    ):
        result = await flow.async_step_user(
            {
                CONF_HAEO_CONFIG_ENTRY_ID: haeo_entry.entry_id,
                CONF_TOKEN: "token",
            }
        )

    replay_site_key = schema_key(result["data_schema"], CONF_REPLAY_SITE_ID)

    assert replay_site_key.default() == "site-home"


@pytest.mark.asyncio
async def test_config_flow_defaults_to_create_site_when_no_site_matches_selected_haeo_entry(hass) -> None:  # type: ignore[no-untyped-def]
    haeo_entry = add_haeo_entry(hass)
    module = importlib.import_module("custom_components.haro.config_flow")
    flow = create_flow(module, hass)

    with patch(
        "custom_components.haro.config_flow.fetch_replay_sites",
        AsyncMock(return_value=[{"id": "site-other", "name": "Other", "haeo_entry_id": "other-haeo-entry"}]),
    ):
        result = await flow.async_step_user(
            {
                CONF_HAEO_CONFIG_ENTRY_ID: haeo_entry.entry_id,
                CONF_TOKEN: "token",
            }
        )

    replay_site_key = schema_key(result["data_schema"], CONF_REPLAY_SITE_ID)

    assert replay_site_key.default() == "__create_site__"


@pytest.mark.asyncio
async def test_config_flow_rejects_no_haeo_placeholder(hass) -> None:  # type: ignore[no-untyped-def]
    module = importlib.import_module("custom_components.haro.config_flow")
    flow = create_flow(module, hass)

    with patch("custom_components.haro.config_flow.fetch_replay_sites", AsyncMock()) as fetch:
        result = await flow.async_step_user(
            {
                CONF_HAEO_CONFIG_ENTRY_ID: "__no_haeo_entries__",
                CONF_TOKEN: "token",
            }
        )

    fetch.assert_not_called()
    assert result["type"] == "form"
    assert result["errors"] == {"base": "invalid_haeo_entry"}


@pytest.mark.asyncio
async def test_config_flow_rejects_duplicate_haeo_entry(hass) -> None:  # type: ignore[no-untyped-def]
    haeo_entry = add_haeo_entry(hass)
    MockConfigEntry(domain=DOMAIN, unique_id=haeo_entry.entry_id).add_to_hass(hass)
    module = importlib.import_module("custom_components.haro.config_flow")
    flow = create_flow(module, hass)

    with patch("custom_components.haro.config_flow.fetch_replay_sites", AsyncMock()):
        result = await flow.async_step_user(
            {
                CONF_HAEO_CONFIG_ENTRY_ID: haeo_entry.entry_id,
                CONF_TOKEN: "token",
            }
        )

    assert result["type"] == "abort"
    assert result["reason"] == "already_configured"


@pytest.mark.asyncio
async def test_config_flow_can_create_replay_site(hass) -> None:  # type: ignore[no-untyped-def]
    haeo_entry = add_haeo_entry(hass)
    module = importlib.import_module("custom_components.haro.config_flow")
    flow = create_flow(module, hass)

    with patch("custom_components.haro.config_flow.fetch_replay_sites", AsyncMock(return_value=[])):
        site_form = await flow.async_step_user({CONF_HAEO_CONFIG_ENTRY_ID: haeo_entry.entry_id, CONF_TOKEN: "token"})
    site_fields = {key.schema for key in site_form["data_schema"].schema}
    assert site_fields == {CONF_REPLAY_SITE_ID, CONF_REPLAY_SITE_NAME}
    with (
        patch(
            "custom_components.haro.config_flow.create_replay_site",
            AsyncMock(return_value={"id": "site-new"}),
        ) as create,
        patch("custom_components.haro.config_flow.bind_replay_site", AsyncMock()) as bind,
    ):
        result = await flow.async_step_site(
            {
                CONF_REPLAY_SITE_ID: "__create_site__",
                CONF_REPLAY_SITE_NAME: "Home",
            }
        )

    create.assert_awaited_once_with(DEFAULT_REPLAY_URL, "token", "Home")
    bind.assert_awaited_once_with(DEFAULT_REPLAY_URL, "token", "site-new", haeo_entry.entry_id, confirm=True)
    assert result["type"] == "create_entry"
    assert result["data"][CONF_REPLAY_SITE_ID] == "site-new"
