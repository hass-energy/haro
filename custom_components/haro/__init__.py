"""HARO Home Assistant integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .const import DOMAIN
from .event_forwarder import HaroForwarder
from .replay_client import ReplayWebSocketClient

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

type HaroConfigEntry = "ConfigEntry[HaroRuntimeData]"


@dataclass
class HaroRuntimeData:
    """Runtime data owned by a HARO config entry."""

    client: ReplayWebSocketClient
    forwarder: HaroForwarder


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up HARO from a config entry."""
    client = ReplayWebSocketClient.from_config(entry.data)
    forwarder = HaroForwarder(hass, entry, client)
    entry.runtime_data = HaroRuntimeData(client=client, forwarder=forwarder)
    await forwarder.async_start()
    entry.async_on_unload(forwarder.async_stop)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload HARO."""
    runtime = getattr(entry, "runtime_data", None)
    if runtime is not None:
        await runtime.forwarder.async_stop()
    return True


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    """Return diagnostics for a HARO config entry."""
    runtime = getattr(entry, "runtime_data", None)
    if runtime is None:
        return {"domain": DOMAIN, "loaded": False}
    return {"domain": DOMAIN, "loaded": True, "stats": runtime.forwarder.diagnostics()}
