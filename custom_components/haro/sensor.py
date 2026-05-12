"""Diagnostic sensors for HARO."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

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

    def diagnostics(self) -> dict[str, StateType]:
        """Return current diagnostic values."""
        ...

    @property
    def entity_ids(self) -> set[str]:
        """Return currently monitored entity IDs."""
        ...


DIAGNOSTIC_KEYS = ("received", "queued", "sent", "dropped", "filtered", "last_error", "monitored_entities")

SENSOR_DESCRIPTIONS: dict[str, SensorEntityDescription] = {
    "received": SensorEntityDescription(key="received", name="Received state changes"),
    "queued": SensorEntityDescription(key="queued", name="Queued states"),
    "sent": SensorEntityDescription(key="sent", name="Sent states"),
    "dropped": SensorEntityDescription(key="dropped", name="Dropped states"),
    "filtered": SensorEntityDescription(key="filtered", name="Filtered state changes"),
    "last_error": SensorEntityDescription(key="last_error", name="Last error"),
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

    async_add_entities([HaroDiagnosticSensor(entry, runtime.forwarder, key) for key in DIAGNOSTIC_KEYS])


class HaroDiagnosticSensor(SensorEntity):
    """Expose one HARO forwarder diagnostic value."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True

    def __init__(self, entry: ConfigEntry, forwarder: DiagnosticSource, key: str) -> None:
        self.entity_description = SENSOR_DESCRIPTIONS[key]
        self._forwarder = forwarder
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
        if self._key == "monitored_entities":
            return len(self._forwarder.entity_ids)
        return self._forwarder.diagnostics().get(self._key)

    @property
    def extra_state_attributes(self) -> dict[str, list[str]] | None:  # type: ignore[reportIncompatibleVariableOverride]
        """Return additional diagnostic attributes."""
        if self._key != "monitored_entities":
            return None
        return {"entity_ids": sorted(self._forwarder.entity_ids)}
