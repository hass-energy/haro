"""HARO Home Assistant integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.const import __version__ as ha_version
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import issue_registry
from homeassistant.loader import async_get_integration
from homeassistant.util import dt as dt_util

from .config_events import ConfigEnvironment, config_from_haeo_entry, config_version_from_haeo_entry
from .config_flow import bind_replay_site, fetch_replay_sites
from .config_queue import ConfigEventQueue
from .config_sync import ConfigSync
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
    config_sync: ConfigSync


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
    config_sync = await _config_sync_from_haeo_entry(hass, entry, data, client)

    async def _refresh_site_info() -> None:
        entry.runtime_data.site = await _site_info_from_replay(data, replay_url)

    forwarder = HaroForwarder(hass, entry, client, on_replay_recovered=_refresh_site_info)
    entry.runtime_data = HaroRuntimeData(client=client, forwarder=forwarder, site=site, config_sync=config_sync)
    await forwarder.async_start()
    if hasattr(hass, "async_create_task"):
        hass.async_create_task(config_sync.async_reconcile_once())
    _subscribe_config_sync_updates(hass, entry, config_sync)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def _stop_forwarder_on_hass_stop(_event: Any) -> None:
        await forwarder.async_stop()

    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _stop_forwarder_on_hass_stop))
    return True


async def _config_sync_from_haeo_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    data: dict[str, Any],
    client: ReplayClient,
) -> ConfigSync:
    """Create config sync for the selected HAEO entry."""
    site_id = data.get(CONF_REPLAY_SITE_ID)
    haeo_entry_id = data.get(CONF_HAEO_CONFIG_ENTRY_ID)
    if not isinstance(site_id, str) or not isinstance(haeo_entry_id, str):
        raise ConfigEntryNotReady("HARO needs a Replay site and linked HAEO config entry")
    haeo_entry = _selected_haeo_entry(hass, haeo_entry_id)
    if haeo_entry is None:
        raise ConfigEntryNotReady(f"HAEO config entry {haeo_entry_id} is not loaded")
    queue = ConfigEventQueue(hass, entry.entry_id)
    return ConfigSync(
        client,
        queue,
        site_id,
        haeo_entry_id,
        config_from_haeo_entry(haeo_entry),
        config_version_from_haeo_entry(haeo_entry),
        await _config_environment(hass),
    )


def _subscribe_config_sync_updates(hass: HomeAssistant, entry: ConfigEntry, config_sync: ConfigSync) -> None:
    """Watch HAEO config-entry updates and queue config history events."""
    haeo_entry_id = entry.data.get(CONF_HAEO_CONFIG_ENTRY_ID)
    if not isinstance(haeo_entry_id, str):
        return
    haeo_entry = _selected_haeo_entry(hass, haeo_entry_id)
    if haeo_entry is None or not hasattr(haeo_entry, "add_update_listener"):
        return

    async def _handle_haeo_updated(*_args: Any) -> None:
        refreshed = _selected_haeo_entry(hass, haeo_entry_id)
        if refreshed is None:
            issue_registry.async_create_issue(
                hass,
                DOMAIN,
                f"haeo_removed_{entry.entry_id}",
                is_fixable=False,
                severity=issue_registry.IssueSeverity.ERROR,
                translation_key="haeo_removed",
            )
            unload = getattr(hass.config_entries, "async_unload", None)
            if unload is not None:
                await unload(entry.entry_id)
            return
        await config_sync.async_update_current_config(
            config_from_haeo_entry(refreshed),
            config_version_from_haeo_entry(refreshed),
            await _config_environment(hass),
        )
        await config_sync.async_reconcile_once()

    entry.async_on_unload(haeo_entry.add_update_listener(_handle_haeo_updated))


def _selected_haeo_entry(hass: HomeAssistant, haeo_entry_id: str) -> Any | None:
    manager = getattr(hass, "config_entries", None)
    if manager is None or not hasattr(manager, "async_entries"):
        return None
    for candidate in manager.async_entries("haeo"):
        if getattr(candidate, "entry_id", None) == haeo_entry_id:
            return candidate
    return None


async def _config_environment(hass: HomeAssistant) -> ConfigEnvironment:
    integration = await async_get_integration(hass, "haeo")
    return ConfigEnvironment(
        ha_version=ha_version,
        haeo_version=integration.version or "unknown",
        timezone=str(dt_util.get_default_time_zone()),
    )


async def _data_with_replay_site(
    hass: HomeAssistant, entry: ConfigEntry, replay_url: str
) -> tuple[dict[str, Any], list[dict[str, Any]] | None]:
    """Repair legacy config entries that predate Replay site selection."""
    data = dict(entry.data)
    if replay_url == REPLAY_URL_LOG_ONLY:
        if CONF_REPLAY_SITE_ID in data or CONF_HAEO_CONFIG_ENTRY_ID not in data:
            return data, None
        repaired = {**data, CONF_REPLAY_SITE_ID: REPLAY_URL_LOG_ONLY}
        hass.config_entries.async_update_entry(entry, data=repaired)
        return repaired, None
    if CONF_REPLAY_SITE_ID in data:
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
    await ConfigEventQueue(hass, entry.entry_id).async_remove()


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    """Return diagnostics for a HARO config entry."""
    runtime = getattr(entry, "runtime_data", None)
    if runtime is None:
        return {"domain": DOMAIN, "loaded": False}
    return {"domain": DOMAIN, "loaded": True, "stats": runtime.forwarder.diagnostics()}
