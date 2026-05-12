"""HARO diagnostic sensor tests."""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from homeassistant.const import EntityCategory
from homeassistant.helpers.typing import StateType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.haro.const import DOMAIN
from custom_components.haro.sensor import HaroDiagnosticSensor, async_setup_entry

ha = pytest.importorskip("homeassistant.components.sensor")


class FakeForwarder:
    def __init__(self) -> None:
        self.values: dict[str, StateType] = {
            "received": 3,
            "queued": 2,
            "sent": 1,
            "dropped": 0,
            "filtered": 4,
            "last_error": "boom",
        }

    def diagnostics(self) -> dict[str, StateType]:
        return self.values


class FakeRuntime:
    def __init__(self) -> None:
        self.forwarder = FakeForwarder()


@pytest.mark.asyncio
async def test_async_setup_entry_creates_diagnostic_sensors(hass) -> None:  # type: ignore[no-untyped-def]
    entry = MockConfigEntry(domain=DOMAIN, entry_id="haro-entry", title="HARO - Home Energy")
    entry.runtime_data = FakeRuntime()
    add_entities = Mock()

    await async_setup_entry(hass, entry, add_entities)

    add_entities.assert_called_once()
    sensors = add_entities.call_args.args[0]
    assert {sensor.entity_description.key for sensor in sensors} == {
        "received",
        "queued",
        "sent",
        "dropped",
        "filtered",
        "last_error",
    }
    assert all(sensor.entity_category is EntityCategory.DIAGNOSTIC for sensor in sensors)


def test_diagnostic_sensor_reads_latest_forwarder_value() -> None:
    entry = MockConfigEntry(domain=DOMAIN, entry_id="haro-entry", title="HARO")
    runtime = FakeRuntime()
    sensor = HaroDiagnosticSensor(entry, runtime.forwarder, "sent")

    assert sensor.unique_id == "haro-entry_sent"
    assert sensor.native_value == 1

    runtime.forwarder.values["sent"] = 5

    assert sensor.native_value == 5
