"""Diagnostic sensors for HARO."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.typing import StateType

from .const import DOMAIN, NAME

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback


class DiagnosticSource(Protocol):
    """Source of HARO diagnostics."""

    def diagnostics(self) -> dict[str, Any]:
        """Return current diagnostic values."""
        ...

    @property
    def entity_ids(self) -> set[str]:
        """Return currently monitored entity IDs."""
        ...


DIAGNOSTIC_KEYS = ("replay_site", "api_status", "forwarding_queue", "monitored_entities")

SENSOR_DESCRIPTIONS: dict[str, SensorEntityDescription] = {
    "replay_site": SensorEntityDescription(key="replay_site", name="Replay site"),
    "api_status": SensorEntityDescription(key="api_status", name="API status"),
    "forwarding_queue": SensorEntityDescription(key="forwarding_queue", name="Forwarding queue"),
    "monitored_entities": SensorEntityDescription(key="monitored_entities", name="Monitored entities"),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up HARO diagnostic sensor entities."""
    runtime = getattr(entry, "runtime_data", None)
    if runtime is None:
        msg = "Runtime data not set - integration setup incomplete"
        raise RuntimeError(msg)

    async_add_entities([HaroDiagnosticSensor(entry, runtime, key) for key in DIAGNOSTIC_KEYS])


class HaroDiagnosticSensor(SensorEntity):
    """Expose one HARO diagnostic value."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True

    def __init__(self, entry: ConfigEntry, runtime: Any, key: str) -> None:
        self.entity_description = SENSOR_DESCRIPTIONS[key]
        self._runtime = runtime
        self._key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            manufacturer=NAME,
            name=entry.title or NAME,
        )

    @property
    def native_value(self) -> StateType:  # type: ignore[reportIncompatibleVariableOverride]
        """Return the latest diagnostic value."""
        diagnostics = self._runtime.forwarder.diagnostics()
        if self._key == "replay_site":
            return getattr(self._runtime.site, "name", None)
        if self._key == "api_status":
            return "Error" if self._last_error(diagnostics) or diagnostics.get("consecutive_failures", 0) else "OK"
        if self._key == "forwarding_queue":
            return diagnostics.get("queued")
        if self._key == "monitored_entities":
            return len(self._runtime.forwarder.entity_ids)
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:  # type: ignore[reportIncompatibleVariableOverride]
        """Return additional diagnostic attributes."""
        diagnostics = self._runtime.forwarder.diagnostics()
        if self._key == "replay_site":
            return {
                "replay_site_id": getattr(self._runtime.site, "site_id", None),
                "haeo_config_entry_id": getattr(self._runtime.site, "haeo_config_entry_id", None),
            }
        if self._key == "api_status":
            client_stats = self._runtime.client.stats
            return {"status_code": client_stats.status_code}
        if self._key == "forwarding_queue":
            return {
                "received_total": diagnostics.get("received"),
                "sent_total": diagnostics.get("sent"),
                "dropped_total": diagnostics.get("dropped"),
                "queue_limit": diagnostics.get("queue_limit"),
            }
        if self._key == "monitored_entities":
            return {"entity_ids": sorted(self._runtime.forwarder.entity_ids)}
        return None

    def _last_error(self, diagnostics: dict[str, Any]) -> str | None:
        """Return the most relevant error from the forwarder or Replay client."""
        forwarder_error = diagnostics.get("last_error")
        if isinstance(forwarder_error, str) and forwarder_error:
            return forwarder_error
        client_error = self._runtime.client.stats.last_error
        return client_error if isinstance(client_error, str) and client_error else None
