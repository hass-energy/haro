"""Diagnostic sensors for HARO."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.helpers.typing import StateType

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback


class DiagnosticSource(Protocol):
    """Source of HARO diagnostics."""

    def diagnostics(self) -> dict[str, StateType]:
        """Return current diagnostic values."""
        ...


DIAGNOSTIC_KEYS = ("received", "queued", "sent", "dropped", "filtered", "last_error")

SENSOR_DESCRIPTIONS: dict[str, SensorEntityDescription] = {
    "received": SensorEntityDescription(key="received", name="Received state changes"),
    "queued": SensorEntityDescription(key="queued", name="Queued states"),
    "sent": SensorEntityDescription(key="sent", name="Sent states"),
    "dropped": SensorEntityDescription(key="dropped", name="Dropped states"),
    "filtered": SensorEntityDescription(key="filtered", name="Filtered state changes"),
    "last_error": SensorEntityDescription(key="last_error", name="Last error"),
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

    @property
    def native_value(self) -> StateType:  # type: ignore[reportIncompatibleVariableOverride]
        """Return the latest diagnostic value."""
        return self._forwarder.diagnostics().get(self._key)
