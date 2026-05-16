"""Durable config event queue for HARO."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

ConfigEvent = dict[str, Any]


class ConfigEventQueue:
    """Persist config events to a JSONL file with stable event ids."""

    def __init__(self, hass: Any, entry_id: str) -> None:
        self.hass = hass
        self.path = Path(hass.config.path(".storage", f"haro_config_queue.{entry_id}.jsonl"))

    async def async_load(self) -> list[ConfigEvent]:
        """Load queued config events."""
        return await self.hass.async_add_executor_job(self._load)

    async def async_enqueue(self, event: ConfigEvent) -> ConfigEvent:
        """Persist one event, allocating a stable id if needed."""
        queued = {**event, "id": str(event.get("id") or uuid4().hex)}
        await self.hass.async_add_executor_job(self._append, [queued])
        return queued

    async def async_rewrite(self, events: list[ConfigEvent]) -> None:
        """Atomically rewrite the queue."""
        await self.hass.async_add_executor_job(self._rewrite, events)

    async def async_ack(self, event_id: str) -> None:
        """Remove an event after Replay has acked its id."""
        events = [event for event in await self.async_load() if event.get("id") != event_id]
        await self.async_rewrite(events)

    async def async_remove(self) -> None:
        """Remove queue storage."""
        await self.hass.async_add_executor_job(self._remove)

    def _load(self) -> list[ConfigEvent]:
        if not self.path.exists():
            return []
        events: list[ConfigEvent] = []
        lines = self.path.read_text(encoding="utf-8").splitlines()
        for line_number, line in enumerate(lines, start=1):
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                if line_number == len(lines):
                    break
                raise
            if isinstance(value, dict):
                events.append(value)
        return events

    def _append(self, events: list[ConfigEvent]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as file:
            for event in events:
                file.write(json.dumps(event, separators=(",", ":")))
                file.write("\n")
            file.flush()
            os.fsync(file.fileno())

    def _rewrite(self, events: list[ConfigEvent]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        with temp_path.open("w", encoding="utf-8") as file:
            for event in events:
                file.write(json.dumps(event, separators=(",", ":")))
                file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        temp_path.replace(self.path)

    def _remove(self) -> None:
        self.path.unlink(missing_ok=True)
