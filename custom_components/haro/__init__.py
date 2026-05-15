"""HARO Home Assistant integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform

from .const import CONF_REPLAY_URL, DEFAULT_REPLAY_URL, DOMAIN
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
class HaroRuntimeData:
    """Runtime data owned by a HARO config entry."""

    client: ReplayClient
    forwarder: HaroForwarder


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up HARO YAML configuration."""
    domain_config = config.get(DOMAIN, {})
    hass.data.setdefault(DOMAIN, {})[CONF_REPLAY_URL] = domain_config.get(CONF_REPLAY_URL, DEFAULT_REPLAY_URL)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up HARO from a config entry."""
    replay_url = hass.data.setdefault(DOMAIN, {}).get(CONF_REPLAY_URL, DEFAULT_REPLAY_URL)
    client = replay_client_from_config(entry.data, replay_url)
    forwarder = HaroForwarder(hass, entry, client)
    entry.runtime_data = HaroRuntimeData(client=client, forwarder=forwarder)
    await forwarder.async_start()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def _stop_forwarder_on_hass_stop(_event: Any) -> None:
        await forwarder.async_stop()

    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _stop_forwarder_on_hass_stop))
    return True


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
