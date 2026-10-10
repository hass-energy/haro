from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from custom_components.haro.canonical import canonical_config_hash
from custom_components.haro.config_events import ConfigEnvironment, build_patch_event
from custom_components.haro.config_queue import ConfigEventQueue
from custom_components.haro.config_sync import ConfigSync
from custom_components.haro.replay_client import ReplayClientStats, StatePayload


class FakeConfig:
    def __init__(self, root: Path) -> None:
        self.root = root

    def path(self, *parts: str) -> str:
        return str(self.root.joinpath(*parts))


class FakeHass:
    def __init__(self, root: Path) -> None:
        self.config = FakeConfig(root)

    async def async_add_executor_job(self, func: Any, *args: Any) -> Any:
        return func(*args)


class FakeClient:
    def __init__(self, state: dict[str, Any]) -> None:
        self.state = state
        self.sent: list[dict[str, Any]] = []
        self.stats = ReplayClientStats()

    async def close(self) -> None:
        return None

    async def send_states(self, states: list[StatePayload]) -> dict[str, Any]:
        return {"inserted": 0}

    async def receive_config_state(self) -> dict[str, Any]:
        return self.state

    async def send_config_event(self, event: dict[str, Any]) -> dict[str, Any]:
        self.sent.append(event)
        return {"type": "ack", "id": event["id"], "inserted": 1}


async def test_config_sync_drains_matching_queued_patches_and_prunes_acks(tmp_path: Path) -> None:
    """Replay's announced hash should select the queue suffix to send."""
    hass = FakeHass(tmp_path)
    queue = ConfigEventQueue(hass, "entry-1")
    environment = ConfigEnvironment("2026.5.0", "0.5.0", "Australia/Sydney")
    base = {"version": 1, "minor_version": 3, "hub": {"name": "Home"}}
    current = {"version": 1, "minor_version": 3, "hub": {"name": "Away"}}
    event = await queue.async_enqueue(
        build_patch_event(
            site_id="site-1",
            haeo_entry_id="haeo-entry-1",
            captured_at="2026-01-01T00:01:00Z",
            config_version="1.3",
            base_config=base,
            current_config=current,
        )
    )
    client = FakeClient(
        {
            "type": "config_state",
            "config_hash": event["base_hash"],
            "config_version": "1.3",
            "environment": environment.as_payload(),
        }
    )
    sync = ConfigSync(client, queue, "site-1", "haeo-entry-1", current, "1.3", environment)

    await sync.async_reconcile_once()

    assert [sent["id"] for sent in client.sent] == [event["id"]]
    assert await queue.async_load() == []


async def test_config_sync_enqueues_patch_for_value_only_change(tmp_path: Path) -> None:
    """A same-version, same-environment config change should queue a patch."""
    hass = FakeHass(tmp_path)
    queue = ConfigEventQueue(hass, "entry-1")
    environment = ConfigEnvironment("2026.5.0", "0.5.0", "Australia/Sydney")
    base = {"version": 1, "minor_version": 3, "hub": {"name": "Home"}}
    current = {"version": 1, "minor_version": 3, "hub": {"name": "Away"}}
    sync = ConfigSync(FakeClient({}), queue, "site-1", "haeo-entry-1", base, "1.3", environment)

    await sync.async_update_current_config(current, "1.3", environment)

    queued = await queue.async_load()
    assert queued[0]["type"] == "config_patch"
    assert queued[0]["patch"] == [{"op": "replace", "path": ["hub", "name"], "value": "Away"}]
    assert sync.diagnostics() == {"queued": 1}


async def test_config_sync_enqueues_checkpoint_for_version_or_environment_change(tmp_path: Path) -> None:
    """Version/environment changes are structural rebase points."""
    hass = FakeHass(tmp_path)
    queue = ConfigEventQueue(hass, "entry-1")
    environment = ConfigEnvironment("2026.5.0", "0.5.0", "Australia/Sydney")
    sync = ConfigSync(
        FakeClient({}),
        queue,
        "site-1",
        "haeo-entry-1",
        {"version": 1, "minor_version": 3},
        "1.3",
        environment,
    )

    await sync.async_update_current_config({"version": 1, "minor_version": 4}, "1.4", environment)

    queued = await queue.async_load()
    assert queued[0]["type"] == "config_checkpoint"
    assert queued[0]["config_version"] == "1.4"


ENVIRONMENT = ConfigEnvironment("2026.5.0", "0.5.0", "Australia/Sydney")
HOME = {"version": 1, "minor_version": 3, "hub": {"name": "Home"}}
AWAY = {"version": 1, "minor_version": 3, "hub": {"name": "Away"}}
HOLIDAY = {"version": 1, "minor_version": 3, "hub": {"name": "Holiday"}}


async def enqueue_patch(queue: ConfigEventQueue, base: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    return await queue.async_enqueue(
        build_patch_event(
            site_id="site-1",
            haeo_entry_id="haeo-entry-1",
            captured_at="2026-01-01T00:01:00Z",
            config_version="1.3",
            base_config=base,
            current_config=current,
        )
    )


def replay_at(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "config_state",
        "config_hash": canonical_config_hash(config),
        "config_version": "1.3",
        "environment": ENVIRONMENT.as_payload(),
    }


async def test_config_sync_discards_queue_when_replay_already_matches(tmp_path: Path) -> None:
    queue = ConfigEventQueue(FakeHass(tmp_path), "entry-1")
    await enqueue_patch(queue, HOME, AWAY)
    client = FakeClient(replay_at(AWAY))
    sync = ConfigSync(client, queue, "site-1", "haeo-entry-1", AWAY, "1.3", ENVIRONMENT)

    await sync.async_reconcile_once()

    assert client.sent == []
    assert await queue.async_load() == []


async def test_config_sync_discards_events_superseded_by_a_checkpoint(tmp_path: Path) -> None:
    queue = ConfigEventQueue(FakeHass(tmp_path), "entry-1")
    await enqueue_patch(queue, HOME, AWAY)
    client = FakeClient(replay_at(HOLIDAY))
    sync = ConfigSync(client, queue, "site-1", "haeo-entry-1", AWAY, "1.3", ENVIRONMENT)

    await sync.async_reconcile_once()

    assert [sent["type"] for sent in client.sent] == ["config_checkpoint"]
    assert await queue.async_load() == []


async def test_config_sync_discards_patches_replay_already_applied(tmp_path: Path) -> None:
    queue = ConfigEventQueue(FakeHass(tmp_path), "entry-1")
    await enqueue_patch(queue, HOME, AWAY)
    pending = await enqueue_patch(queue, AWAY, HOLIDAY)
    client = FakeClient(replay_at(AWAY))
    sync = ConfigSync(client, queue, "site-1", "haeo-entry-1", HOLIDAY, "1.3", ENVIRONMENT)

    await sync.async_reconcile_once()

    assert [sent["id"] for sent in client.sent] == [pending["id"]]
    assert await queue.async_load() == []


async def test_config_sync_keeps_events_queued_while_reconciling(tmp_path: Path) -> None:
    """A HAEO change that lands mid-reconcile still needs to reach Replay."""
    queue = ConfigEventQueue(FakeHass(tmp_path), "entry-1")
    client = FakeClient(replay_at(HOME))
    sync = ConfigSync(client, queue, "site-1", "haeo-entry-1", AWAY, "1.3", ENVIRONMENT)
    acknowledge = client.send_config_event

    async def send_while_haeo_changes(event: dict[str, Any]) -> dict[str, Any]:
        await enqueue_patch(queue, AWAY, HOLIDAY)
        return await acknowledge(event)

    client.send_config_event = send_while_haeo_changes  # type: ignore[method-assign]

    await sync.async_reconcile_once()

    assert [event["base_hash"] for event in await queue.async_load()] == [canonical_config_hash(AWAY)]


async def test_config_sync_keeps_queue_when_a_send_fails(tmp_path: Path) -> None:
    queue = ConfigEventQueue(FakeHass(tmp_path), "entry-1")
    stale = await enqueue_patch(queue, HOME, AWAY)
    client = FakeClient(replay_at(HOLIDAY))
    sync = ConfigSync(client, queue, "site-1", "haeo-entry-1", AWAY, "1.3", ENVIRONMENT)

    async def reject(_event: dict[str, Any]) -> dict[str, Any]:
        raise ConnectionError("closed")

    client.send_config_event = reject  # type: ignore[method-assign]

    with pytest.raises(ConnectionError):
        await sync.async_reconcile_once()

    assert stale["id"] in [event["id"] for event in await queue.async_load()]
