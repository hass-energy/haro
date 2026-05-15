"""HARO diagnostic sensor tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import Mock

import pytest
from homeassistant.const import EntityCategory
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.haro.const import DOMAIN
from custom_components.haro.sensor import HaroDiagnosticSensor, async_setup_entry

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
            "backoff_seconds": 0.0,
            "consecutive_failures": 0,
            "last_error": None,
        }

    def diagnostics(self) -> dict[str, object]:
        return self.values


class FakeRuntime:
    def __init__(self) -> None:
        self.client = FakeClient()
        self.forwarder = FakeForwarder()
        self.site = FakeSiteInfo()


@pytest.mark.asyncio
async def test_async_setup_entry_creates_diagnostic_sensors(hass) -> None:  # type: ignore[no-untyped-def]
    entry = MockConfigEntry(domain=DOMAIN, entry_id="haro-entry", title="HARO - Home Energy")
    entry.runtime_data = FakeRuntime()
    add_entities = Mock()

    await async_setup_entry(hass, entry, add_entities)

    add_entities.assert_called_once()
    sensors = add_entities.call_args.args[0]
    assert {sensor.entity_description.key for sensor in sensors} == {
        "replay_site",
        "api_status",
        "forwarding_queue",
        "monitored_entities",
    }
    assert all(sensor.entity_category is EntityCategory.DIAGNOSTIC for sensor in sensors)
    assert all(sensor.device_info == sensors[0].device_info for sensor in sensors)
    assert sensors[0].device_info["identifiers"] == {(DOMAIN, "haro-entry")}
    assert sensors[0].device_info["name"] == "HARO - Home Energy"


def test_replay_site_sensor_shows_site_name_and_ids() -> None:
    entry = MockConfigEntry(domain=DOMAIN, entry_id="haro-entry", title="HARO")
    runtime = FakeRuntime()
    sensor = HaroDiagnosticSensor(entry, runtime, "replay_site")

    assert sensor.unique_id == "haro-entry_replay_site"
    assert sensor.native_value == "Home"
    assert sensor.extra_state_attributes == {
        "replay_site_id": "site-1",
        "haeo_config_entry_id": "haeo-entry",
    }


def test_api_status_sensor_combines_forwarder_and_client_status() -> None:
    entry = MockConfigEntry(domain=DOMAIN, entry_id="haro-entry", title="HARO")
    runtime = FakeRuntime()
    sensor = HaroDiagnosticSensor(entry, runtime, "api_status")

    assert sensor.unique_id == "haro-entry_api_status"
    assert sensor.native_value == "OK"
    assert sensor.extra_state_attributes == {"status_code": 200}

    runtime.forwarder.values["last_error"] = "boom"

    assert sensor.native_value == "Error"
    assert sensor.extra_state_attributes == {"status_code": 200}


def test_forwarding_queue_sensor_shows_depth_with_counter_attributes() -> None:
    entry = MockConfigEntry(domain=DOMAIN, entry_id="haro-entry", title="HARO")
    runtime = FakeRuntime()
    sensor = HaroDiagnosticSensor(entry, runtime, "forwarding_queue")

    assert sensor.unique_id == "haro-entry_forwarding_queue"
    assert sensor.native_value == 2
    assert sensor.extra_state_attributes == {
        "received_total": 3,
        "sent_total": 1,
        "dropped_total": 0,
        "queue_limit": 10_000,
    }

    runtime.forwarder.values["queued"] = 5

    assert sensor.native_value == 5


def test_monitored_entities_sensor_counts_and_lists_entity_ids() -> None:
    entry = MockConfigEntry(domain=DOMAIN, entry_id="haro-entry", title="HARO")
    runtime = FakeRuntime()
    sensor = HaroDiagnosticSensor(entry, runtime, "monitored_entities")

    assert sensor.unique_id == "haro-entry_monitored_entities"
    assert sensor.native_value == 2
    assert sensor.extra_state_attributes == {"entity_ids": ["sensor.a", "sensor.b"]}
