"""HARO event forwarder tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from custom_components.haro.const import CONF_HAEO_CONFIG_ENTRY_ID
from custom_components.haro.event_forwarder import HaroForwarder, payload_from_state, selected_entity_ids


@dataclass
class Context:
    id: str


@dataclass
class State:
    state: str
    attributes: dict[str, Any]
    last_changed: datetime
    context: Context


class FakeClient:
    async def close(self) -> None:
        return None

    async def send_states(self, states: list[dict[str, Any]]) -> dict[str, Any]:
        return {"inserted": len(states)}


class FakeEntry:
    data = {"extra_entity_ids": ["sensor.energy"], "queue_limit": 1}


class FakeStates:
    def get(self, entity_id: str) -> State | None:
        if entity_id != "sensor.energy":
            return None
        return State("1", {"unit_of_measurement": "kWh"}, datetime(2026, 1, 1, tzinfo=UTC), Context("ctx"))


class FakeBus:
    def async_listen(self, event_type: str, handler: Any) -> Any:
        assert event_type == "state_changed"
        return lambda: None


class FakeHass:
    states = FakeStates()
    bus = FakeBus()


@dataclass
class FakeHaeoSubentry:
    subentry_type: str
    data: dict[str, Any]


@dataclass
class FakeHaeoEntry:
    entry_id: str
    subentries: dict[str, FakeHaeoSubentry]


class FakeConfigEntries:
    def async_entries(self, domain: str) -> list[FakeHaeoEntry]:
        assert domain == "haeo"
        return [
            FakeHaeoEntry(
                "selected",
                {"battery": FakeHaeoSubentry("battery", {"soc": {"type": "entity", "value": ["sensor.soc"]}})},
            ),
            FakeHaeoEntry(
                "other",
                {"load": FakeHaeoSubentry("load", {"power": {"type": "entity", "value": ["sensor.other"]}})},
            ),
        ]


class FakeHassWithHaeo(FakeHass):
    config_entries = FakeConfigEntries()


def test_selected_entity_ids_dedupes_haeo_inputs_and_extras() -> None:
    assert selected_entity_ids(["sensor.a", "sensor.b"], ["sensor.b", "sensor.c"]) == {
        "sensor.a",
        "sensor.b",
        "sensor.c",
    }


def test_payload_from_state_matches_replay_shape() -> None:
    state = State("1", {"unit_of_measurement": "kWh"}, datetime(2026, 1, 1, tzinfo=UTC), Context("ctx"))

    assert payload_from_state("sensor.energy", state) == {
        "time": "2026-01-01T00:00:00+00:00",
        "entity_id": "sensor.energy",
        "state": "1",
        "attributes": {"unit_of_measurement": "kWh"},
        "context_id": "ctx",
    }


def test_payload_from_state_serializes_datetime_attributes() -> None:
    state = State(
        "1",
        {
            "next_update": datetime(2026, 1, 1, 1, 2, 3, tzinfo=UTC),
            "nested": {"times": [datetime(2026, 1, 1, 4, 5, 6, tzinfo=UTC)]},
        },
        datetime(2026, 1, 1, tzinfo=UTC),
        Context("ctx"),
    )

    payload = payload_from_state("sensor.energy", state)

    assert payload is not None
    assert payload["attributes"] == {
        "next_update": "2026-01-01T01:02:03+00:00",
        "nested": {"times": ["2026-01-01T04:05:06+00:00"]},
    }


def test_queue_drops_oldest_when_full() -> None:
    forwarder = HaroForwarder(FakeHass(), FakeEntry(), FakeClient())  # type: ignore[arg-type]
    state = State("1", {}, datetime(2026, 1, 1, tzinfo=UTC), Context("ctx"))

    forwarder.handle_state_changed({"entity_id": "sensor.energy", "new_state": state})
    forwarder.handle_state_changed({"entity_id": "sensor.energy", "new_state": state})

    assert forwarder.diagnostics()["queued"] == 1
    assert forwarder.diagnostics()["dropped"] == 1


def test_forwarder_uses_one_selected_haeo_entry() -> None:
    entry = type(
        "Entry",
        (),
        {"data": {CONF_HAEO_CONFIG_ENTRY_ID: "selected", "extra_entity_ids": [], "queue_limit": 1}},
    )()

    forwarder = HaroForwarder(FakeHassWithHaeo(), entry, FakeClient())  # type: ignore[arg-type]

    assert forwarder.entity_ids == {"sensor.soc"}
