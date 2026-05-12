"""HARO event forwarder tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch

from custom_components.haro.const import CONF_HAEO_CONFIG_ENTRY_ID
from custom_components.haro.event_forwarder import HaroForwarder, payload_from_state, selected_entity_ids


@dataclass
class Context:
    id: str
    user_id: str | None = None
    parent_id: str | None = None


@dataclass
class State:
    state: str
    attributes: dict[str, Any]
    last_changed: datetime
    last_reported: datetime
    last_updated: datetime
    context: Context


class FakeClient:
    def __init__(self) -> None:
        self.states: list[dict[str, Any]] = []

    async def close(self) -> None:
        return None

    async def send_states(self, states: list[dict[str, Any]]) -> dict[str, Any]:
        self.states.extend(states)
        return {"inserted": len(states)}


class FakeEntry:
    data = {"extra_entity_ids": ["sensor.energy"], "queue_limit": 1}


class FakeStates:
    def get(self, entity_id: str) -> State | None:
        if entity_id not in {"sensor.energy", "sensor.soc", "sensor.added"}:
            return None
        return State(
            "1",
            {"unit_of_measurement": "kWh"},
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 1, 1, tzinfo=UTC),
            Context("ctx"),
        )


class FakeBus:
    def async_listen(self, event_type: str, handler: Any) -> Any:
        assert event_type == "state_changed"
        return lambda: None


@dataclass
class Origin:
    idx: int


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
    update_listener: Any | None = None

    def add_update_listener(self, listener: Any) -> Any:
        self.update_listener = listener
        return lambda: None


class FakeConfigEntries:
    def __init__(self) -> None:
        self.selected = FakeHaeoEntry(
            "selected",
            {"battery": FakeHaeoSubentry("battery", {"soc": {"type": "entity", "value": ["sensor.soc"]}})},
        )
        self.other = FakeHaeoEntry(
            "other",
            {"load": FakeHaeoSubentry("load", {"power": {"type": "entity", "value": ["sensor.other"]}})},
        )

    def async_entries(self, domain: str) -> list[FakeHaeoEntry]:
        assert domain == "haeo"
        return [self.selected, self.other]


class FakeHassWithHaeo(FakeHass):
    def __init__(self) -> None:
        self.config_entries = FakeConfigEntries()


def test_selected_entity_ids_dedupes_haeo_inputs_and_extras() -> None:
    assert selected_entity_ids(["sensor.a", "sensor.b"], ["sensor.b", "sensor.c"]) == {
        "sensor.a",
        "sensor.b",
        "sensor.c",
    }


def test_payload_from_state_matches_replay_shape() -> None:
    state = State(
        "1",
        {"unit_of_measurement": "kWh"},
        datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC),
        datetime(2026, 1, 1, 0, 0, 3, tzinfo=UTC),
        datetime(2026, 1, 1, 0, 0, 2, tzinfo=UTC),
        Context("ctx", "user", "parent"),
    )

    assert payload_from_state("sensor.energy", state) == {
        "entity_id": "sensor.energy",
        "state": "1",
        "attributes": {"unit_of_measurement": "kWh"},
        "last_updated_ts": 1767225602.0,
        "last_changed_ts": 1767225601.0,
        "last_reported_ts": 1767225603.0,
        "context_id": "ctx",
        "context_user_id": "user",
        "context_parent_id": "parent",
    }


def test_payload_from_state_serializes_datetime_attributes() -> None:
    state = State(
        "1",
        {
            "next_update": datetime(2026, 1, 1, 1, 2, 3, tzinfo=UTC),
            "nested": {"times": [datetime(2026, 1, 1, 4, 5, 6, tzinfo=UTC)]},
        },
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 1, 1, tzinfo=UTC),
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
    state = State(
        "1",
        {},
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 1, 1, tzinfo=UTC),
        Context("ctx"),
    )

    forwarder.handle_state_changed({"entity_id": "sensor.energy", "new_state": state})
    forwarder.handle_state_changed({"entity_id": "sensor.energy", "new_state": state})

    assert forwarder.diagnostics()["queued"] == 1
    assert forwarder.diagnostics()["dropped"] == 1


def test_state_changed_event_payload_includes_origin_idx() -> None:
    client = FakeClient()
    forwarder = HaroForwarder(FakeHass(), FakeEntry(), client)  # type: ignore[arg-type]
    state = State(
        "1",
        {},
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 1, 1, tzinfo=UTC),
        Context("ctx"),
    )

    forwarder.handle_state_changed({"entity_id": "sensor.energy", "new_state": state, "origin": Origin(1)})

    assert forwarder._queue[0]["origin_idx"] == 1


def test_forwarder_uses_one_selected_haeo_entry() -> None:
    entry = type(
        "Entry",
        (),
        {"data": {CONF_HAEO_CONFIG_ENTRY_ID: "selected", "extra_entity_ids": [], "queue_limit": 1}},
    )()

    forwarder = HaroForwarder(FakeHassWithHaeo(), entry, FakeClient())  # type: ignore[arg-type]

    assert forwarder.entity_ids == {"sensor.soc"}


async def test_forwarder_subscribes_to_selected_entity_ids() -> None:
    entry = type(
        "Entry",
        (),
        {"data": {CONF_HAEO_CONFIG_ENTRY_ID: "selected", "extra_entity_ids": ["sensor.energy"], "queue_limit": 10}},
    )()
    calls: list[set[str]] = []

    def track_state_change(hass: Any, entity_ids: set[str], handler: Any) -> Any:
        calls.append(entity_ids)
        return lambda: None

    with patch("custom_components.haro.event_forwarder.async_track_state_change_event", track_state_change):
        forwarder = HaroForwarder(FakeHassWithHaeo(), entry, FakeClient())  # type: ignore[arg-type]
        await forwarder.async_start()
        await forwarder.async_stop()

    assert calls == [{"sensor.energy", "sensor.soc"}]


async def test_forwarder_refreshes_subscription_when_haeo_entry_updates() -> None:
    entry = type(
        "Entry",
        (),
        {"data": {CONF_HAEO_CONFIG_ENTRY_ID: "selected", "extra_entity_ids": [], "queue_limit": 10}},
    )()
    hass = FakeHassWithHaeo()
    subscribed: list[set[str]] = []
    unsubscribed: list[set[str]] = []

    def track_state_change(hass: Any, entity_ids: set[str], handler: Any) -> Any:
        subscribed.append(entity_ids)
        return lambda: unsubscribed.append(entity_ids)

    with patch("custom_components.haro.event_forwarder.async_track_state_change_event", track_state_change):
        forwarder = HaroForwarder(hass, entry, FakeClient())  # type: ignore[arg-type]
        await forwarder.async_start()

        hass.config_entries.selected.subentries["load"] = FakeHaeoSubentry(
            "load", {"power": {"type": "entity", "value": ["sensor.added"]}}
        )
        assert hass.config_entries.selected.update_listener is not None
        await hass.config_entries.selected.update_listener(hass, hass.config_entries.selected)
        await forwarder.async_stop()

    assert subscribed == [{"sensor.soc"}, {"sensor.added", "sensor.soc"}]
    assert unsubscribed[0] == {"sensor.soc"}
    assert forwarder.entity_ids == {"sensor.soc", "sensor.added"}
    assert any(payload["entity_id"] == "sensor.added" for payload in forwarder._queue)
