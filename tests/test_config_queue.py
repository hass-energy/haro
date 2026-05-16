from __future__ import annotations

from pathlib import Path
from typing import Any

from custom_components.haro.config_queue import ConfigEventQueue


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


async def test_config_event_queue_persists_events_and_prunes_by_ack(tmp_path: Path) -> None:
    """Queued config events survive restart and are removed only by explicit ack."""
    hass = FakeHass(tmp_path)
    queue = ConfigEventQueue(hass, "entry-1")
    event = await queue.async_enqueue(
        {
            "type": "config_checkpoint",
            "site_id": "site-1",
            "haeo_entry_id": "haeo-entry-1",
            "config": {"version": 1},
        }
    )

    restored = await ConfigEventQueue(hass, "entry-1").async_load()
    assert restored == [event]
    assert event["id"]

    await queue.async_ack(event["id"])
    assert await ConfigEventQueue(hass, "entry-1").async_load() == []
