"""HARO event forwarder tests."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch

import pytest

from custom_components.haro.const import CONF_HAEO_CONFIG_ENTRY_ID
from custom_components.haro.event_forwarder import Backoff, HaroForwarder, payload_from_state, selected_entity_ids


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


class RecoveringClient(FakeClient):
    def __init__(self, failures: int) -> None:
        super().__init__()
        self.failures = failures
        self.calls = 0

    async def send_states(self, states: list[dict[str, Any]]) -> dict[str, Any]:
        self.calls += 1
        if self.failures:
            self.failures -= 1
            raise ConnectionError("replay down")
        return await super().send_states(states)


class BlockingClient(FakeClient):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def send_states(self, states: list[dict[str, Any]]) -> dict[str, Any]:
        self.started.set()
        await self.release.wait()
        return await super().send_states(states)


class FakeQueueLog:
    def __init__(self, loaded: list[dict[str, Any]] | None = None) -> None:
        self.loaded = loaded or []
        self.appended: list[list[dict[str, Any]]] = []
        self.rewritten: list[list[dict[str, Any]]] = []
        self.truncated = 0
        self.removed = 0
        self.fail_next_append = False

    async def async_load(self) -> list[dict[str, Any]]:
        return self.loaded

    async def async_append(self, payloads: list[dict[str, Any]]) -> None:
        if self.fail_next_append:
            self.fail_next_append = False
            raise OSError("disk full")
        self.appended.append(list(payloads))

    async def async_rewrite(self, payloads: list[dict[str, Any]]) -> None:
        self.rewritten.append(list(payloads))

    async def async_truncate(self) -> None:
        self.truncated += 1

    async def async_remove(self) -> None:
        self.removed += 1


class FakeEntry:
    entry_id = "haro-entry"
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
    assert forwarder.diagnostics()["queue_limit"] == 1
    assert forwarder.diagnostics()["dropped"] == 1


def test_forwarder_diagnostics_exposes_queue_contract_without_filtered_counter() -> None:
    forwarder = HaroForwarder(FakeHass(), FakeEntry(), FakeClient())  # type: ignore[arg-type]

    diagnostics = forwarder.diagnostics()

    assert diagnostics["received"] == 0
    assert diagnostics["queued"] == 0
    assert diagnostics["sent"] == 0
    assert diagnostics["dropped"] == 0
    assert diagnostics["queue_limit"] == 1
    assert "filtered" not in diagnostics


def test_backoff_uses_capped_exponential_delays() -> None:
    backoff = Backoff(base=1.0, cap=3.0, jitter_ratio=0.0)

    assert [backoff.next_delay() for _ in range(4)] == [1.0, 2.0, 3.0, 3.0]

    backoff.reset()

    assert backoff.current_delay == 0.0
    assert backoff.consecutive_failures == 0


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

    assert forwarder._queue[0].payload["origin_idx"] == 1


async def test_forwarder_survives_send_failure_and_retries_when_client_recovers() -> None:
    entry = type(
        "Entry", (), {"data": {"extra_entity_ids": ["sensor.energy"], "queue_limit": 10, "flush_interval": 0.001}}
    )()
    client = RecoveringClient(failures=1)
    forwarder = HaroForwarder(FakeHass(), entry, client)  # type: ignore[arg-type]
    state = FakeStates().get("sensor.energy")
    assert state is not None
    payload = payload_from_state("sensor.energy", state)
    assert payload is not None
    forwarder._append(payload)

    forwarder._stopped.clear()
    forwarder._task = asyncio.create_task(forwarder._run())
    for _ in range(50):
        if client.states:
            break
        await asyncio.sleep(0.01)
    await forwarder.async_stop()

    assert client.calls >= 2
    assert client.states == [payload]
    assert forwarder.diagnostics()["queued"] == 0


async def test_forwarder_records_last_error_but_does_not_die() -> None:
    entry = type(
        "Entry", (), {"data": {"extra_entity_ids": ["sensor.energy"], "queue_limit": 10, "flush_interval": 0.001}}
    )()
    client = RecoveringClient(failures=10)
    forwarder = HaroForwarder(FakeHass(), entry, client)  # type: ignore[arg-type]
    state = FakeStates().get("sensor.energy")
    assert state is not None
    payload = payload_from_state("sensor.energy", state)
    assert payload is not None
    forwarder._append(payload)

    forwarder._stopped.clear()
    forwarder._task = asyncio.create_task(forwarder._run())
    for _ in range(50):
        if forwarder.diagnostics()["last_error"] == "replay down":
            break
        await asyncio.sleep(0.01)

    assert forwarder.diagnostics()["last_error"] == "replay down"
    assert forwarder._task is not None
    assert not forwarder._task.done()

    await forwarder.async_stop()


async def test_forwarder_resets_backoff_on_success() -> None:
    entry = type(
        "Entry", (), {"data": {"extra_entity_ids": ["sensor.energy"], "queue_limit": 10, "flush_interval": 0.001}}
    )()
    client = RecoveringClient(failures=1)
    forwarder = HaroForwarder(FakeHass(), entry, client)  # type: ignore[arg-type]
    state = FakeStates().get("sensor.energy")
    assert state is not None
    payload = payload_from_state("sensor.energy", state)
    assert payload is not None
    forwarder._append(payload)

    forwarder._stopped.clear()
    forwarder._task = asyncio.create_task(forwarder._run())
    for _ in range(50):
        if client.states:
            break
        await asyncio.sleep(0.01)
    await forwarder.async_stop()

    diagnostics = forwarder.diagnostics()
    assert diagnostics["consecutive_failures"] == 0
    assert diagnostics["backoff_seconds"] == 0.0


async def test_forwarder_clears_last_error_after_recovered_flush() -> None:
    entry = type("Entry", (), {"data": {"extra_entity_ids": ["sensor.energy"], "queue_limit": 10}})()
    client = RecoveringClient(failures=1)
    forwarder = HaroForwarder(FakeHass(), entry, client)  # type: ignore[arg-type]
    state = FakeStates().get("sensor.energy")
    assert state is not None
    payload = payload_from_state("sensor.energy", state)
    assert payload is not None
    forwarder._append(payload)

    with pytest.raises(ConnectionError, match="replay down"):
        await forwarder._flush_once()
    await forwarder._flush_once()

    assert forwarder.diagnostics()["last_error"] is None


async def test_forwarder_requeues_in_flight_batch_when_cancelled() -> None:
    entry = type("Entry", (), {"data": {"extra_entity_ids": ["sensor.energy"], "queue_limit": 10}})()
    client = BlockingClient()
    forwarder = HaroForwarder(FakeHass(), entry, client)  # type: ignore[arg-type]
    state = FakeStates().get("sensor.energy")
    assert state is not None
    payload = payload_from_state("sensor.energy", state)
    assert payload is not None
    forwarder._append(payload)

    task = asyncio.create_task(forwarder._flush_once())
    await client.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert [item.payload for item in forwarder._queue] == [payload]


async def test_forwarder_restores_queue_from_log_on_start() -> None:
    restored = [payload_from_state("sensor.energy", FakeStates().get("sensor.energy"))]
    assert restored[0] is not None
    entry = type("Entry", (), {"entry_id": "haro-entry", "data": {"extra_entity_ids": [], "queue_limit": 10}})()
    log = FakeQueueLog([restored[0]])

    with patch("custom_components.haro.event_forwarder.async_track_state_change_event", lambda *args: lambda: None):
        forwarder = HaroForwarder(FakeHass(), entry, FakeClient(), queue_log=log)  # type: ignore[arg-type]
        await forwarder.async_start()
        await forwarder.async_stop()

    assert [item.payload for item in forwarder._queue] == [restored[0]]
    assert [item.logged for item in forwarder._queue] == [True]


async def test_forwarder_appends_only_unlogged_items_on_tick() -> None:
    log = FakeQueueLog()
    entry = type(
        "Entry", (), {"entry_id": "haro-entry", "data": {"extra_entity_ids": ["sensor.energy"], "queue_limit": 10}}
    )()
    forwarder = HaroForwarder(FakeHass(), entry, FakeClient(), queue_log=log)  # type: ignore[arg-type]
    first = payload_from_state("sensor.energy", FakeStates().get("sensor.energy"))
    second = payload_from_state("sensor.soc", FakeStates().get("sensor.soc"))
    assert first is not None
    assert second is not None

    forwarder._append(first)
    await forwarder._sync_log_once()
    forwarder._append(second)
    await forwarder._sync_log_once()

    assert log.appended == [[first], [second]]
    assert [item.logged for item in forwarder._queue] == [True, True]


async def test_forwarder_rewrites_log_when_queue_overflowed_since_last_tick() -> None:
    log = FakeQueueLog()
    entry = type(
        "Entry", (), {"entry_id": "haro-entry", "data": {"extra_entity_ids": ["sensor.energy"], "queue_limit": 2}}
    )()
    forwarder = HaroForwarder(FakeHass(), entry, FakeClient(), queue_log=log)  # type: ignore[arg-type]
    first = {"entity_id": "sensor.one"}
    second = {"entity_id": "sensor.two"}
    third = {"entity_id": "sensor.three"}

    forwarder._append(first)
    forwarder._append(second)
    await forwarder._sync_log_once()
    forwarder._append(third)
    await forwarder._sync_log_once()

    assert log.appended == [[first, second]]
    assert log.rewritten == [[second, third]]
    assert [item.payload for item in forwarder._queue] == [second, third]
    assert [item.logged for item in forwarder._queue] == [True, True]


async def test_forwarder_clears_log_drifted_flag_after_rewrite() -> None:
    log = FakeQueueLog()
    entry = type(
        "Entry", (), {"entry_id": "haro-entry", "data": {"extra_entity_ids": ["sensor.energy"], "queue_limit": 1}}
    )()
    forwarder = HaroForwarder(FakeHass(), entry, FakeClient(), queue_log=log)  # type: ignore[arg-type]

    forwarder._append({"entity_id": "sensor.one"})
    forwarder._append({"entity_id": "sensor.two"})
    await forwarder._sync_log_once()
    await forwarder._sync_log_once()

    assert log.rewritten == [[{"entity_id": "sensor.two"}]]


async def test_forwarder_truncates_log_when_flush_empties_queue() -> None:
    log = FakeQueueLog()
    client = FakeClient()
    forwarder = HaroForwarder(FakeHass(), FakeEntry(), client, queue_log=log)  # type: ignore[arg-type]
    queued = {"entity_id": "sensor.energy"}

    forwarder._append(queued)
    await forwarder._sync_log_once()
    await forwarder._flush_once()

    assert client.states == [queued]
    assert log.truncated == 1


async def test_forwarder_does_not_truncate_when_queue_still_has_items_after_flush() -> None:
    log = FakeQueueLog()
    entry = type(
        "Entry",
        (),
        {"entry_id": "haro-entry", "data": {"extra_entity_ids": ["sensor.energy"], "queue_limit": 10, "batch_size": 1}},
    )()
    client = FakeClient()
    forwarder = HaroForwarder(FakeHass(), entry, client, queue_log=log)  # type: ignore[arg-type]
    first = {"entity_id": "sensor.one"}
    second = {"entity_id": "sensor.two"}

    forwarder._append(first)
    forwarder._append(second)
    await forwarder._sync_log_once()
    await forwarder._flush_once()

    assert client.states == [first]
    assert [item.payload for item in forwarder._queue] == [second]
    assert log.truncated == 0


async def test_forwarder_log_tick_is_noop_when_no_unlogged_items() -> None:
    log = FakeQueueLog()
    forwarder = HaroForwarder(FakeHass(), FakeEntry(), FakeClient(), queue_log=log)  # type: ignore[arg-type]
    queued = {"entity_id": "sensor.energy"}

    forwarder._append(queued)
    await forwarder._sync_log_once()
    await forwarder._sync_log_once()

    assert log.appended == [[queued]]
    assert log.rewritten == []


async def test_forwarder_log_survives_append_failure() -> None:
    log = FakeQueueLog()
    log.fail_next_append = True
    forwarder = HaroForwarder(FakeHass(), FakeEntry(), FakeClient(), queue_log=log)  # type: ignore[arg-type]
    queued = {"entity_id": "sensor.energy"}

    forwarder._append(queued)
    await forwarder._sync_log_once()
    await forwarder._sync_log_once()

    assert log.appended == [[queued]]
    assert [item.logged for item in forwarder._queue] == [True]


async def test_forwarder_runs_final_append_on_stop_for_unlogged_items() -> None:
    log = FakeQueueLog()
    forwarder = HaroForwarder(FakeHass(), FakeEntry(), FakeClient(), queue_log=log)  # type: ignore[arg-type]
    queued = {"entity_id": "sensor.energy"}

    forwarder._append(queued)
    await forwarder.async_stop()

    assert log.appended == [[queued]]


async def test_forwarder_runs_final_rewrite_on_stop_when_log_drifted() -> None:
    log = FakeQueueLog()
    entry = type(
        "Entry", (), {"entry_id": "haro-entry", "data": {"extra_entity_ids": ["sensor.energy"], "queue_limit": 1}}
    )()
    forwarder = HaroForwarder(FakeHass(), entry, FakeClient(), queue_log=log)  # type: ignore[arg-type]

    forwarder._append({"entity_id": "sensor.old"})
    forwarder._append({"entity_id": "sensor.current"})
    await forwarder.async_stop()

    assert log.rewritten == [[{"entity_id": "sensor.current"}]]


async def test_async_stop_is_idempotent() -> None:
    log = FakeQueueLog()
    client = FakeClient()
    forwarder = HaroForwarder(FakeHass(), FakeEntry(), client, queue_log=log)  # type: ignore[arg-type]
    queued = {"entity_id": "sensor.energy"}

    forwarder._append(queued)
    await forwarder.async_stop()
    await forwarder.async_stop()

    assert log.appended == [[queued]]


async def test_forwarder_skips_disk_on_happy_path() -> None:
    log = FakeQueueLog()
    client = FakeClient()
    forwarder = HaroForwarder(FakeHass(), FakeEntry(), client, queue_log=log)  # type: ignore[arg-type]
    queued = {"entity_id": "sensor.energy"}

    forwarder._append(queued)
    await forwarder._flush_once()

    assert client.states == [queued]
    assert log.appended == []
    assert log.rewritten == []
    assert log.truncated == 0


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
    assert any(item.payload["entity_id"] == "sensor.added" for item in forwarder._queue)
