"""HARO Home Assistant integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform

from .config_flow import bind_replay_site, fetch_replay_sites
from .const import (
    CONF_HAEO_CONFIG_ENTRY_ID,
    CONF_REPLAY_SITE_ID,
    CONF_REPLAY_URL,
    CONF_TOKEN,
    DEFAULT_REPLAY_URL,
    DOMAIN,
    REPLAY_URL_LOG_ONLY,
)
from .event_forwarder import HaroForwarder
from .queue_log import QueueLog
from .replay_client import ReplayClient, replay_client_from_config

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

type HaroConfigEntry = "ConfigEntry[HaroRuntimeData]"

PLATFORMS = [Platform.SENSOR]
CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Optional(CONF_REPLAY_URL, default=DEFAULT_REPLAY_URL): cv.string,
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


@dataclass
class ReplaySiteInfo:
    """Replay site metadata exposed by HARO diagnostics."""

    name: str
    site_id: str | None
    haeo_config_entry_id: str | None


@dataclass
class HaroRuntimeData:
    """Runtime data owned by a HARO config entry."""

    client: ReplayClient
    forwarder: HaroForwarder
    site: ReplaySiteInfo


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up HARO YAML configuration."""
    domain_config = config.get(DOMAIN, {})
    hass.data.setdefault(DOMAIN, {})[CONF_REPLAY_URL] = domain_config.get(CONF_REPLAY_URL, DEFAULT_REPLAY_URL)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up HARO from a config entry."""
    replay_url = hass.data.setdefault(DOMAIN, {}).get(CONF_REPLAY_URL, DEFAULT_REPLAY_URL)
    data, sites = await _data_with_replay_site(hass, entry, replay_url)
    site = await _site_info_from_replay(data, replay_url, sites)
    client = replay_client_from_config(data, replay_url)

    async def _refresh_site_info() -> None:
        entry.runtime_data.site = await _site_info_from_replay(data, replay_url)

    forwarder = HaroForwarder(hass, entry, client, on_replay_recovered=_refresh_site_info)
    entry.runtime_data = HaroRuntimeData(client=client, forwarder=forwarder, site=site)
    await forwarder.async_start()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def _stop_forwarder_on_hass_stop(_event: Any) -> None:
        await forwarder.async_stop()

    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _stop_forwarder_on_hass_stop))
    return True


async def _data_with_replay_site(
    hass: HomeAssistant, entry: ConfigEntry, replay_url: str
) -> tuple[dict[str, Any], list[dict[str, Any]] | None]:
    """Repair legacy config entries that predate Replay site selection."""
    data = dict(entry.data)
    if replay_url == REPLAY_URL_LOG_ONLY or CONF_REPLAY_SITE_ID in data:
        return data, None

    token = str(data[CONF_TOKEN])
    haeo_entry_id = str(data[CONF_HAEO_CONFIG_ENTRY_ID])
    sites = await fetch_replay_sites(replay_url, token)
    site_ids = [str(site.get("id", "")).strip() for site in sites if site.get("id")]
    if len(site_ids) != 1:
        raise RuntimeError("HARO config entry must be recreated to select a Replay site")

    site_id = site_ids[0]
    await bind_replay_site(replay_url, token, site_id, haeo_entry_id, confirm=True)
    repaired = {**data, CONF_REPLAY_SITE_ID: site_id}
    hass.config_entries.async_update_entry(entry, data=repaired)
    return repaired, sites


async def _site_info_from_replay(
    data: dict[str, Any], replay_url: str, sites: list[dict[str, Any]] | None = None
) -> ReplaySiteInfo:
    """Fetch the selected Replay site name for runtime diagnostics."""
    site_id = data.get(CONF_REPLAY_SITE_ID)
    haeo_entry_id = data.get(CONF_HAEO_CONFIG_ENTRY_ID)
    if replay_url == REPLAY_URL_LOG_ONLY:
        return ReplaySiteInfo(
            name="Log only",
            site_id=str(site_id) if site_id is not None else None,
            haeo_config_entry_id=str(haeo_entry_id) if haeo_entry_id is not None else None,
        )

    token = str(data[CONF_TOKEN])
    selected_site_id = str(data[CONF_REPLAY_SITE_ID])
    available_sites = sites if sites is not None else await fetch_replay_sites(replay_url, token)
    site = next((site for site in available_sites if str(site.get("id")) == selected_site_id), None)
    name = selected_site_id if site is None else str(site.get("name") or selected_site_id)
    return ReplaySiteInfo(
        name=name,
        site_id=selected_site_id,
        haeo_config_entry_id=str(haeo_entry_id) if haeo_entry_id is not None else None,
    )


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload HARO."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False
    runtime = getattr(entry, "runtime_data", None)
    if runtime is not None:
        await runtime.forwarder.async_stop()
    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove HARO queue storage for an entry."""
    await QueueLog(hass, entry.entry_id).async_remove()


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    """Return diagnostics for a HARO config entry."""
    runtime = getattr(entry, "runtime_data", None)
    if runtime is None:
        return {"domain": DOMAIN, "loaded": False}
    return {"domain": DOMAIN, "loaded": True, "stats": runtime.forwarder.diagnostics()}
