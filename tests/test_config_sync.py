from __future__ import annotations

from pathlib import Path
from typing import Any

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
