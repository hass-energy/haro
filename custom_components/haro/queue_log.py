"""Append/rewrite queue log for HARO state payloads."""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .replay_client import StatePayload


class QueueLog:
    """Persist queued state payloads to a JSONL file."""

    def __init__(self, hass: Any, entry_id: str) -> None:
        self.hass = hass
        self.path = Path(hass.config.path(".storage", f"haro_queue.{entry_id}.jsonl"))

    async def async_load(self) -> list[StatePayload]:
        """Load queued payloads from disk."""
        return await self.hass.async_add_executor_job(self._load)

    async def async_append(self, payloads: Iterable[StatePayload]) -> None:
        """Append payloads to the log."""
        rows = list(payloads)
        if not rows:
            return
        await self.hass.async_add_executor_job(self._append, rows)

    async def async_rewrite(self, payloads: Iterable[StatePayload]) -> None:
        """Atomically rewrite the log with payloads."""
        await self.hass.async_add_executor_job(self._rewrite, list(payloads))

    async def async_truncate(self) -> None:
        """Clear the log while keeping the file path valid."""
        await self.hass.async_add_executor_job(self._truncate)

    async def async_remove(self) -> None:
        """Remove the log file if present."""
        await self.hass.async_add_executor_job(self._remove)

    def _load(self) -> list[StatePayload]:
        if not self.path.exists():
            return []
        payloads: list[StatePayload] = []
        lines = self.path.read_text(encoding="utf-8").splitlines()
        for line_number, line in enumerate(lines, start=1):
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                if line_number == len(lines):
                    break
                raise
            if isinstance(value, dict):
                payloads.append(value)
        return payloads

    def _append(self, payloads: list[StatePayload]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as file:
            for payload in payloads:
                file.write(json.dumps(payload, separators=(",", ":")))
                file.write("\n")
            file.flush()
            os.fsync(file.fileno())

    def _rewrite(self, payloads: list[StatePayload]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        with temp_path.open("w", encoding="utf-8") as file:
            for payload in payloads:
                file.write(json.dumps(payload, separators=(",", ":")))
                file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        temp_path.replace(self.path)

    def _truncate(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as file:
            file.flush()
            os.fsync(file.fileno())

    def _remove(self) -> None:
        self.path.unlink(missing_ok=True)
