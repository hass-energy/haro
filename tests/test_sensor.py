"""HARO diagnostic sensor tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from unittest.mock import Mock

import pytest
from homeassistant.components.sensor import SensorStateClass
from homeassistant.const import EntityCategory
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.haro.const import DOMAIN
from custom_components.haro.sensor import (
    SENSOR_DESCRIPTIONS,
    HaroDiagnosticSensor,
    HaroSensorDescription,
    async_setup_entry,
)

ha = pytest.importorskip("homeassistant.components.sensor")


@dataclass
class FakeSiteInfo:
    name: str = "Home"
    site_id: str = "site-1"
    haeo_config_entry_id: str = "haeo-entry"


@dataclass
class FakeClientStats:
    last_error: str | None = None
    status_code: int | None = 200
    sent_batches: int = 4
    sent_states: int = 9
    sent_config_events: int = 2
    last_states_ack_id: str | None = "states-ack-1"
    last_config_ack_id: str | None = "config-ack-1"
    last_sync_attempt: datetime | None = datetime(2026, 1, 1, 1, 2, 3, tzinfo=UTC)
    last_sync: datetime | None = datetime(2026, 1, 1, 1, 2, 4, tzinfo=UTC)
    last_config_sync_attempt: datetime | None = datetime(2026, 1, 1, 2, 2, 3, tzinfo=UTC)
    last_config_sync: datetime | None = datetime(2026, 1, 1, 2, 2, 4, tzinfo=UTC)


class FakeClient:
    def __init__(self) -> None:
        self.stats = FakeClientStats()


class FakeForwarder:
    def __init__(self) -> None:
        self.entity_ids = {"sensor.b", "sensor.a"}
        self.values: dict[str, Any] = {
            "received": 3,
            "queued": 2,
            "sent": 1,
            "dropped": 0,
            "queue_limit": 10_000,
            "persisted": 1,
            "last_state_change": "2026-01-01T00:00:01+00:00",
            "last_disk_write": "2026-01-01T00:00:02+00:00",
            "backoff_seconds": 0.0,
            "consecutive_failures": 0,
            "last_error": None,
        }

    def diagnostics(self) -> dict[str, Any]:
        return self.values


class FakeConfigSync:
    def __init__(self) -> None:
        self.values = {"queued": 3}

    def diagnostics(self) -> dict[str, Any]:
        return self.values


class FakeRuntime:
    def __init__(self) -> None:
        self.client = FakeClient()
        self.forwarder = FakeForwarder()
        self.config_sync = FakeConfigSync()
        self.site = FakeSiteInfo()


def sensor_description(key: str) -> HaroSensorDescription:
    return next(description for description in SENSOR_DESCRIPTIONS if description.key == key)


def test_sensor_descriptions_drive_values_and_attributes() -> None:
    assert {description.key for description in SENSOR_DESCRIPTIONS} == {
        "site",
        "api_status",
        "backlog",
        "recorded_states",
        "recorded_configs",
        "tracked_entities",
    }
    assert not any(isinstance(description.name, str) for description in SENSOR_DESCRIPTIONS)
    assert {description.key: description.translation_key for description in SENSOR_DESCRIPTIONS} == {
        "site": "site",
        "api_status": "api_status",
        "backlog": "backlog",
        "recorded_states": "recorded_states",
        "recorded_configs": "recorded_configs",
        "tracked_entities": "tracked_entities",
    }
    assert not any(description.icon for description in SENSOR_DESCRIPTIONS)
    assert all(callable(description.value_fn) for description in SENSOR_DESCRIPTIONS)


def test_sensor_descriptions_include_units_and_classes() -> None:
    descriptions = {description.key: description for description in SENSOR_DESCRIPTIONS}

    assert descriptions["api_status"].device_class is None
    assert descriptions["api_status"].options is None

    assert descriptions["backlog"].native_unit_of_measurement == "states"
    assert descriptions["backlog"].state_class is SensorStateClass.MEASUREMENT

    assert descriptions["recorded_states"].native_unit_of_measurement == "states"
    assert descriptions["recorded_states"].state_class is SensorStateClass.TOTAL_INCREASING

    assert descriptions["recorded_configs"].native_unit_of_measurement == "events"
    assert descriptions["recorded_configs"].state_class is SensorStateClass.TOTAL_INCREASING

    assert descriptions["tracked_entities"].native_unit_of_measurement == "entities"
    assert descriptions["tracked_entities"].state_class is SensorStateClass.MEASUREMENT


@pytest.mark.asyncio
async def test_async_setup_entry_creates_diagnostic_sensors(hass) -> None:  # type: ignore[no-untyped-def]
    entry = MockConfigEntry(domain=DOMAIN, entry_id="haro-entry", title="HARO - Home Energy")
    entry.runtime_data = FakeRuntime()
    add_entities = Mock()

    await async_setup_entry(hass, entry, add_entities)

    add_entities.assert_called_once()
    sensors = add_entities.call_args.args[0]
    assert {sensor.entity_description.key for sensor in sensors} == {
        "site",
        "api_status",
        "backlog",
        "recorded_states",
        "recorded_configs",
        "tracked_entities",
    }
    assert all(sensor.entity_category is EntityCategory.DIAGNOSTIC for sensor in sensors)
    assert all(sensor.device_info == sensors[0].device_info for sensor in sensors)
    assert sensors[0].device_info["identifiers"] == {(DOMAIN, "haro-entry")}
    assert sensors[0].device_info["name"] == "HARO - Home Energy"


def test_site_sensor_shows_site_name_and_ids() -> None:
    entry = MockConfigEntry(domain=DOMAIN, entry_id="haro-entry", title="HARO")
    runtime = FakeRuntime()
    sensor = HaroDiagnosticSensor(entry, runtime, sensor_description("site"))

    assert sensor.unique_id == "haro-entry_site"
    assert sensor.native_value == "Home"
    assert sensor.extra_state_attributes == {
        "replay_site_id": "site-1",
        "haeo_config_entry_id": "haeo-entry",
    }


def test_api_status_sensor_labels_replay_http_status_code() -> None:
    entry = MockConfigEntry(domain=DOMAIN, entry_id="haro-entry", title="HARO")
    runtime = FakeRuntime()
    sensor = HaroDiagnosticSensor(entry, runtime, sensor_description("api_status"))

    assert sensor.unique_id == "haro-entry_api_status"
    assert sensor.native_value == "OK"
    assert sensor.extra_state_attributes == {"status_code": 200}

    runtime.client.stats.status_code = 401
    assert sensor.native_value == "Unauthorized"

    runtime.client.stats.status_code = 404
    assert sensor.native_value == "Not Found"

    runtime.client.stats.status_code = 500
    assert sensor.native_value == "Internal Server Error"

    runtime.client.stats.status_code = 999
    assert sensor.native_value == "Unknown Error"

    runtime.client.stats.status_code = None
    assert sensor.native_value is None
    assert sensor.extra_state_attributes == {"status_code": None}


def test_backlog_sensor_shows_depth_with_backlog_attributes() -> None:
    entry = MockConfigEntry(domain=DOMAIN, entry_id="haro-entry", title="HARO")
    runtime = FakeRuntime()
    sensor = HaroDiagnosticSensor(entry, runtime, sensor_description("backlog"))

    assert sensor.unique_id == "haro-entry_backlog"
    assert sensor.native_value == 2
    assert sensor.extra_state_attributes == {
        "queue_limit": 10_000,
        "persisted": 1,
        "dropped": 0,
        "received": 3,
        "last_state_change": "2026-01-01T00:00:01+00:00",
        "last_disk_write": "2026-01-01T00:00:02+00:00",
    }

    runtime.forwarder.values["queued"] = 5

    assert sensor.native_value == 5


def test_recorded_states_sensor_shows_replay_acked_state_stats() -> None:
    entry = MockConfigEntry(domain=DOMAIN, entry_id="haro-entry", title="HARO")
    runtime = FakeRuntime()
    sensor = HaroDiagnosticSensor(entry, runtime, sensor_description("recorded_states"))

    assert sensor.unique_id == "haro-entry_recorded_states"
    assert sensor.native_value == 9
    assert sensor.extra_state_attributes == {
        "last_states_ack_id": "states-ack-1",
        "sent_batches": 4,
        "last_sync_attempt": "2026-01-01T01:02:03+00:00",
        "last_sync": "2026-01-01T01:02:04+00:00",
    }


def test_recorded_configs_sensor_shows_replay_acked_config_stats() -> None:
    entry = MockConfigEntry(domain=DOMAIN, entry_id="haro-entry", title="HARO")
    runtime = FakeRuntime()
    sensor = HaroDiagnosticSensor(entry, runtime, sensor_description("recorded_configs"))

    assert sensor.unique_id == "haro-entry_recorded_configs"
    assert sensor.native_value == 2
    assert sensor.extra_state_attributes == {
        "queued": 3,
        "last_config_ack_id": "config-ack-1",
        "last_config_sync_attempt": "2026-01-01T02:02:03+00:00",
        "last_config_sync": "2026-01-01T02:02:04+00:00",
    }


def test_diagnostic_sensor_attributes_do_not_overlap_across_new_sensors() -> None:
    entry = MockConfigEntry(domain=DOMAIN, entry_id="haro-entry", title="HARO")
    runtime = FakeRuntime()
    sensors = [
        HaroDiagnosticSensor(entry, runtime, sensor_description(key))
        for key in ["backlog", "recorded_states", "recorded_configs"]
    ]

    key_sets = [set(sensor.extra_state_attributes or {}) for sensor in sensors]

    assert key_sets[0].isdisjoint(key_sets[1])
    assert key_sets[0].isdisjoint(key_sets[2])
    assert key_sets[1].isdisjoint(key_sets[2])


def test_tracked_entities_sensor_counts_and_lists_entity_ids() -> None:
    entry = MockConfigEntry(domain=DOMAIN, entry_id="haro-entry", title="HARO")
    runtime = FakeRuntime()
    sensor = HaroDiagnosticSensor(entry, runtime, sensor_description("tracked_entities"))

    assert sensor.unique_id == "haro-entry_tracked_entities"
    assert sensor.native_value == 2
    assert sensor.extra_state_attributes == {"entity_ids": ["sensor.a", "sensor.b"]}
