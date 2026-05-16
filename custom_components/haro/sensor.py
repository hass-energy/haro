"""Diagnostic sensors for HARO."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING, Any, Protocol

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription, SensorStateClass
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


@dataclass(frozen=True, kw_only=True)
class HaroSensorDescription(SensorEntityDescription):
    """Description for a HARO diagnostic sensor."""

    value_fn: Callable[[Any], StateType]
    attributes_fn: Callable[[Any], dict[str, Any] | None] | None = None


def _http_status_label(status_code: int | None) -> str | None:
    """Return the human-readable phrase for an HTTP status code."""
    if status_code is None:
        return None
    try:
        return HTTPStatus(status_code).phrase
    except ValueError:
        return "Unknown Error"


def _site_value(runtime: Any) -> StateType:
    """Return the Replay site display name."""
    return getattr(runtime.site, "name", None)


def _site_attributes(runtime: Any) -> dict[str, Any]:
    """Return Replay site identity attributes."""
    return {
        "replay_site_id": getattr(runtime.site, "site_id", None),
        "haeo_config_entry_id": getattr(runtime.site, "haeo_config_entry_id", None),
    }


def _api_status_value(runtime: Any) -> StateType:
    """Return a human-readable HTTP status label for the most recent Replay reply."""
    return _http_status_label(runtime.client.stats.status_code)


def _api_status_attributes(runtime: Any) -> dict[str, Any]:
    """Return API status details."""
    return {"status_code": runtime.client.stats.status_code}


def _queue_value(runtime: Any) -> StateType:
    """Return the current forwarding queue depth."""
    return runtime.forwarder.diagnostics().get("queued")


def _queue_attributes(runtime: Any) -> dict[str, Any]:
    """Return forwarding queue counters."""
    diagnostics = runtime.forwarder.diagnostics()
    return {
        "received_total": diagnostics.get("received"),
        "sent_total": diagnostics.get("sent"),
        "dropped_total": diagnostics.get("dropped"),
        "queue_limit": diagnostics.get("queue_limit"),
        "logged_queued": diagnostics.get("logged_queued"),
    }


def _recorded_entities_value(runtime: Any) -> StateType:
    """Return the recorded entity count."""
    return len(runtime.forwarder.entity_ids)


def _recorded_entities_attributes(runtime: Any) -> dict[str, Any]:
    """Return recorded entity IDs."""
    return {"entity_ids": sorted(runtime.forwarder.entity_ids)}


SENSOR_DESCRIPTIONS: tuple[HaroSensorDescription, ...] = (
    HaroSensorDescription(
        key="site",
        translation_key="site",
        value_fn=_site_value,
        attributes_fn=_site_attributes,
    ),
    HaroSensorDescription(
        key="api_status",
        translation_key="api_status",
        value_fn=_api_status_value,
        attributes_fn=_api_status_attributes,
    ),
    HaroSensorDescription(
        key="queue",
        translation_key="queue",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="states",
        value_fn=_queue_value,
        attributes_fn=_queue_attributes,
    ),
    HaroSensorDescription(
        key="recorded_entities",
        translation_key="recorded_entities",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="entities",
        value_fn=_recorded_entities_value,
        attributes_fn=_recorded_entities_attributes,
    ),
)


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

    async_add_entities([HaroDiagnosticSensor(entry, runtime, description) for description in SENSOR_DESCRIPTIONS])


class HaroDiagnosticSensor(SensorEntity):
    """Expose one HARO diagnostic value."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True

    def __init__(self, entry: ConfigEntry, runtime: Any, description: HaroSensorDescription) -> None:
        self.entity_description = description
        self._description = description
        self._runtime = runtime
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            manufacturer=NAME,
            name=entry.title or NAME,
        )

    @property
    def native_value(self) -> StateType:  # type: ignore[reportIncompatibleVariableOverride]
        """Return the latest diagnostic value."""
        return self._description.value_fn(self._runtime)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:  # type: ignore[reportIncompatibleVariableOverride]
        """Return additional diagnostic attributes."""
        if self._description.attributes_fn is not None:
            return self._description.attributes_fn(self._runtime)
        return None
