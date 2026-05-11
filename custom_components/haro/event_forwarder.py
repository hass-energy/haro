"""State forwarding for HARO."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Iterable
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .const import (
    CONF_BATCH_SIZE,
    CONF_EXTRA_ENTITY_IDS,
    CONF_FLUSH_INTERVAL,
    CONF_HAEO_CONFIG_ENTRY_IDS,
    CONF_QUEUE_LIMIT,
    DEFAULT_BATCH_SIZE,
    DEFAULT_FLUSH_INTERVAL,
    DEFAULT_QUEUE_LIMIT,
)
from .haeo_inputs import entity_ids_from_haeo_entries
from .replay_client import ReplayWebSocketClient, StatePayload


@dataclass(slots=True)
class ForwarderStats:
    """Forwarder counters exposed through diagnostics."""

    received: int = 0
    queued: int = 0
    sent: int = 0
    dropped: int = 0
    filtered: int = 0
    last_error: str | None = None


def payload_from_state(entity_id: str, state: Any) -> StatePayload | None:
    """Convert a Home Assistant state object into Replay payload shape."""
    when = getattr(state, "last_changed", None) or getattr(state, "last_updated", None)
    if when is None:
        return None
    time = when.isoformat() if isinstance(when, datetime) else str(when)
    context = getattr(state, "context", None)
    context_id = getattr(context, "id", None)
    attributes = getattr(state, "attributes", None)
    state_value = getattr(state, "state", None)
    return {
        "time": time,
        "entity_id": entity_id,
        "state": None if state_value is None else str(state.state),
        "attributes": attributes if isinstance(attributes, dict) else {},
        "context_id": context_id,
    }


def selected_entity_ids(haeo_inputs: Iterable[str], extras: Iterable[str]) -> set[str]:
    """Build the deduped entity set HARO records."""
    return {entity_id for entity_id in [*haeo_inputs, *extras] if entity_id}


class HaroForwarder:
    """Collect selected HA states and send them to Replay."""

    def __init__(self, hass: Any, entry: Any, client: ReplayWebSocketClient) -> None:
        self.hass = hass
        self.entry = entry
        self.client = client
        self.batch_size = int(entry.data.get(CONF_BATCH_SIZE, DEFAULT_BATCH_SIZE))
        self.flush_interval = float(entry.data.get(CONF_FLUSH_INTERVAL, DEFAULT_FLUSH_INTERVAL))
        self.queue_limit = int(entry.data.get(CONF_QUEUE_LIMIT, DEFAULT_QUEUE_LIMIT))
        self.haeo_config_entry_ids = list(entry.data.get(CONF_HAEO_CONFIG_ENTRY_IDS, []))
        self.entity_ids = self._selected_entities(entry.data.get(CONF_EXTRA_ENTITY_IDS, []))
        self.stats = ForwarderStats()
        self._queue: deque[StatePayload] = deque()
        self._task: asyncio.Task[None] | None = None
        self._unsub: Any | None = None
        self._stopped = asyncio.Event()

    async def async_start(self) -> None:
        """Start forwarding."""
        self._stopped.clear()
        await self._enqueue_current_states()
        self._subscribe()
        self._task = asyncio.create_task(self._run())

    async def async_stop(self) -> None:
        """Stop forwarding and close Replay connection."""
        self._stopped.set()
        if self._unsub is not None:
            self._unsub()
            self._unsub = None
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        await self.client.close()

    def diagnostics(self) -> dict[str, Any]:
        """Return diagnostics-safe counters."""
        return {
            "received": self.stats.received,
            "queued": len(self._queue),
            "sent": self.stats.sent,
            "dropped": self.stats.dropped,
            "filtered": self.stats.filtered,
            "last_error": self.stats.last_error,
        }

    def handle_state_changed(self, event: Any) -> None:
        """Handle a Home Assistant state_changed event."""
        self.stats.received += 1
        data = getattr(event, "data", event)
        entity_id = data.get("entity_id")
        if entity_id not in self.entity_ids:
            self.stats.filtered += 1
            return
        state = data.get("new_state")
        if state is None:
            return
        payload = payload_from_state(entity_id, state)
        if payload is not None:
            self._append(payload)

    async def _enqueue_current_states(self) -> None:
        states = getattr(self.hass, "states", None)
        if states is None:
            return
        for entity_id in self.entity_ids:
            state = states.get(entity_id)
            payload = payload_from_state(entity_id, state) if state is not None else None
            if payload is not None:
                self._append(payload)

    def _append(self, payload: StatePayload) -> None:
        while len(self._queue) >= self.queue_limit:
            self._queue.popleft()
            self.stats.dropped += 1
        self._queue.append(payload)
        self.stats.queued += 1

    def _subscribe(self) -> None:
        bus = getattr(self.hass, "bus", None)
        if bus is None or not hasattr(bus, "async_listen"):
            return
        self._unsub = bus.async_listen("state_changed", self.handle_state_changed)

    def _selected_entities(self, extras: Iterable[str]) -> set[str]:
        manager = getattr(self.hass, "config_entries", None)
        entries = []
        if manager is not None and hasattr(manager, "async_entries"):
            entries = list(manager.async_entries("haeo"))
        return selected_entity_ids(entity_ids_from_haeo_entries(entries, self.haeo_config_entry_ids), extras)

    async def _run(self) -> None:
        while not self._stopped.is_set():
            await asyncio.sleep(self.flush_interval)
            await self._flush_once()

    async def _flush_once(self) -> None:
        if not self._queue:
            return
        batch: list[StatePayload] = []
        while self._queue and len(batch) < self.batch_size:
            batch.append(self._queue.popleft())
        try:
            await self.client.send_states(batch)
            self.stats.sent += len(batch)
        except Exception as e:
            self.stats.last_error = str(e)
            for payload in reversed(batch):
                self._queue.appendleft(payload)
            raise
