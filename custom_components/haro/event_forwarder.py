"""State forwarding for HARO."""

from __future__ import annotations

import asyncio
import secrets
from collections import deque
from collections.abc import Awaitable, Callable, Iterable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    CONF_BATCH_SIZE,
    CONF_EXTRA_ENTITY_IDS,
    CONF_FLUSH_INTERVAL,
    CONF_HAEO_CONFIG_ENTRY_ID,
    CONF_QUEUE_LIMIT,
    DEFAULT_BATCH_SIZE,
    DEFAULT_FLUSH_INTERVAL,
    DEFAULT_LOG_SYNC_INTERVAL,
    DEFAULT_MAX_BACKOFF,
    DEFAULT_QUEUE_LIMIT,
)
from .haeo_inputs import entity_ids_from_haeo_entry
from .queue_log import QueueLog
from .replay_client import ReplayClient, StatePayload


@dataclass(slots=True)
class ForwarderStats:
    """Forwarder counters exposed through diagnostics."""

    received: int = 0
    sent: int = 0
    dropped: int = 0
    backoff_seconds: float = 0.0
    consecutive_failures: int = 0
    last_error: str | None = None


@dataclass(slots=True)
class Backoff:
    """Capped exponential backoff for Replay retry delays."""

    base: float
    cap: float
    jitter_ratio: float = 0.25
    current_delay: float = 0.0
    consecutive_failures: int = 0

    def next_delay(self) -> float:
        """Return the next capped delay and advance the sequence."""
        delay = min(self.cap, self.base * (2**self.consecutive_failures))
        self.consecutive_failures += 1
        if self.jitter_ratio:
            jitter = delay * self.jitter_ratio
            delay = secrets.SystemRandom().uniform(max(0.0, delay - jitter), delay + jitter)
        self.current_delay = min(self.cap, delay)
        return self.current_delay

    def reset(self) -> None:
        """Reset the sequence after a successful flush."""
        self.current_delay = 0.0
        self.consecutive_failures = 0


@dataclass(slots=True)
class QueuedPayload:
    """Payload waiting to be sent, plus whether it is already on disk."""

    payload: StatePayload
    logged: bool = False


def json_safe(value: Any) -> Any:
    """Return a JSON-safe copy of common Home Assistant state values."""
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): json_safe(nested) for key, nested in value.items()}
    if isinstance(value, list | tuple):
        return [json_safe(nested) for nested in value]
    return value


def timestamp_from_state(state: Any, attr: str) -> float | None:
    """Read a Home Assistant state timestamp as epoch seconds."""
    timestamp = getattr(state, f"{attr}_timestamp", None)
    if isinstance(timestamp, int | float):
        return float(timestamp)
    when = getattr(state, attr, None)
    if isinstance(when, datetime):
        return when.timestamp()
    return None


def payload_from_state(entity_id: str, state: Any, origin_idx: int | None = None) -> StatePayload | None:
    """Convert a Home Assistant state object into Replay payload shape."""
    last_updated_ts = timestamp_from_state(state, "last_updated")
    if last_updated_ts is None:
        return None
    context = getattr(state, "context", None)
    context_id = getattr(context, "id", None)
    context_user_id = getattr(context, "user_id", None)
    context_parent_id = getattr(context, "parent_id", None)
    attributes = getattr(state, "attributes", None)
    state_value = getattr(state, "state", None)
    payload = {
        "entity_id": entity_id,
        "state": None if state_value is None else str(state.state),
        "attributes": json_safe(attributes) if isinstance(attributes, Mapping) else {},
        "last_updated_ts": last_updated_ts,
        "last_changed_ts": timestamp_from_state(state, "last_changed"),
        "last_reported_ts": timestamp_from_state(state, "last_reported"),
        "context_id": context_id,
        "context_user_id": context_user_id,
        "context_parent_id": context_parent_id,
    }
    if origin_idx is not None:
        payload["origin_idx"] = origin_idx
    return payload


def selected_entity_ids(haeo_inputs: Iterable[str], extras: Iterable[str]) -> set[str]:
    """Build the deduped entity set HARO records."""
    return {entity_id for entity_id in [*haeo_inputs, *extras] if entity_id}


class HaroForwarder:
    """Collect selected HA states and send them to Replay."""

    def __init__(
        self,
        hass: Any,
        entry: Any,
        client: ReplayClient,
        queue_log: Any | None = None,
        on_replay_recovered: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.client = client
        self.batch_size = int(entry.data.get(CONF_BATCH_SIZE, DEFAULT_BATCH_SIZE))
        self.flush_interval = float(entry.data.get(CONF_FLUSH_INTERVAL, DEFAULT_FLUSH_INTERVAL))
        self.queue_limit = int(entry.data.get(CONF_QUEUE_LIMIT, DEFAULT_QUEUE_LIMIT))
        self.log_sync_interval = DEFAULT_LOG_SYNC_INTERVAL
        self._backoff = Backoff(self.flush_interval, DEFAULT_MAX_BACKOFF)
        self.haeo_config_entry_id = entry.data.get(CONF_HAEO_CONFIG_ENTRY_ID)
        self.entity_ids = self._selected_entities(entry.data.get(CONF_EXTRA_ENTITY_IDS, []))
        self.stats = ForwarderStats()
        self._queue: deque[QueuedPayload] = deque()
        self._log = queue_log if queue_log is not None else self._default_queue_log()
        self._log_has_content = False
        self._log_drifted = False
        self._task: asyncio.Task[None] | None = None
        self._log_task: asyncio.Task[None] | None = None
        self._unsub_state_changes: Any | None = None
        self._unsub_haeo_updates: Any | None = None
        self._stopped = asyncio.Event()
        self.on_replay_recovered = on_replay_recovered
        self._last_seen_reconnects = self._client_reconnects()

    def _default_queue_log(self) -> QueueLog | None:
        entry_id = getattr(self.entry, "entry_id", None)
        config = getattr(self.hass, "config", None)
        if entry_id is None or config is None or not hasattr(config, "path"):
            return None
        if not hasattr(self.hass, "async_add_executor_job"):
            return None
        return QueueLog(self.hass, str(entry_id))

    async def async_start(self) -> None:
        """Start forwarding."""
        self._stopped.clear()
        await self._restore_logged_queue()
        await self._enqueue_current_states()
        self._subscribe()
        self._subscribe_haeo_updates()
        self._task = asyncio.create_task(self._run())
        if self._log is not None:
            self._log_task = asyncio.create_task(self._log_run())

    async def async_stop(self) -> None:
        """Stop forwarding and close Replay connection."""
        self._stopped.set()
        self._unsubscribe_haeo_updates()
        self._unsubscribe_state_changes()
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        if self._log_task is not None:
            self._log_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._log_task
            self._log_task = None
        await self._sync_log_once()
        await self.client.close()

    def diagnostics(self) -> dict[str, Any]:
        """Return diagnostics-safe counters."""
        return {
            "received": self.stats.received,
            "queued": len(self._queue),
            "sent": self.stats.sent,
            "dropped": self.stats.dropped,
            "queue_limit": self.queue_limit,
            "logged_queued": sum(1 for item in self._queue if item.logged),
            "backoff_seconds": self.stats.backoff_seconds,
            "consecutive_failures": self.stats.consecutive_failures,
            "last_error": self.stats.last_error,
        }

    def handle_state_changed(self, event: Any) -> None:
        """Handle a Home Assistant state_changed event."""
        self.stats.received += 1
        data = getattr(event, "data", event)
        entity_id = data.get("entity_id")
        if entity_id not in self.entity_ids:
            return
        state = data.get("new_state")
        if state is None:
            return
        origin = data.get("origin") or getattr(event, "origin", None)
        origin_idx = getattr(origin, "idx", None)
        payload = payload_from_state(entity_id, state, origin_idx if isinstance(origin_idx, int) else None)
        if payload is not None:
            self._append(payload)

    async def _enqueue_current_states(self, entity_ids: Iterable[str] | None = None) -> None:
        states = getattr(self.hass, "states", None)
        if states is None:
            return
        for entity_id in self.entity_ids if entity_ids is None else entity_ids:
            state = states.get(entity_id)
            payload = payload_from_state(entity_id, state) if state is not None else None
            if payload is not None:
                self._append(payload)

    def _append(self, payload: StatePayload, *, logged: bool = False) -> None:
        while len(self._queue) >= self.queue_limit:
            self._queue.popleft()
            self.stats.dropped += 1
            self._log_drifted = True
        self._queue.append(QueuedPayload(payload, logged))

    def _subscribe(self) -> None:
        self._unsubscribe_state_changes()
        self._unsub_state_changes = async_track_state_change_event(
            self.hass, self.entity_ids, self.handle_state_changed
        )

    def _unsubscribe_state_changes(self) -> None:
        if self._unsub_state_changes is not None:
            self._unsub_state_changes()
            self._unsub_state_changes = None

    def _subscribe_haeo_updates(self) -> None:
        entry = self._selected_haeo_entry()
        if entry is None or not hasattr(entry, "add_update_listener"):
            return
        self._unsub_haeo_updates = entry.add_update_listener(self._handle_haeo_updated)

    def _unsubscribe_haeo_updates(self) -> None:
        if self._unsub_haeo_updates is not None:
            self._unsub_haeo_updates()
            self._unsub_haeo_updates = None

    async def _handle_haeo_updated(self, *_args: Any) -> None:
        refreshed = self._selected_entities(self.entry.data.get(CONF_EXTRA_ENTITY_IDS, []))
        if refreshed == self.entity_ids:
            return
        added = refreshed - self.entity_ids
        self.entity_ids = refreshed
        self._subscribe()
        await self._enqueue_current_states(added)

    def _selected_haeo_entry(self) -> Any | None:
        for entry in self._haeo_entries():
            if getattr(entry, "entry_id", None) == self.haeo_config_entry_id:
                return entry
        return None

    def _haeo_entries(self) -> list[Any]:
        manager = getattr(self.hass, "config_entries", None)
        if manager is not None and hasattr(manager, "async_entries"):
            return list(manager.async_entries("haeo"))
        return []

    def _selected_entities(self, extras: Iterable[str]) -> set[str]:
        return selected_entity_ids(entity_ids_from_haeo_entry(self._haeo_entries(), self.haeo_config_entry_id), extras)

    async def _run(self) -> None:
        while not self._stopped.is_set():
            await asyncio.sleep(self.flush_interval)
            try:
                await self._flush_once()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.stats.last_error = str(e)
                delay = self._backoff.next_delay()
                self.stats.backoff_seconds = delay
                self.stats.consecutive_failures = self._backoff.consecutive_failures
                await asyncio.sleep(delay)
            else:
                self._backoff.reset()
                self.stats.backoff_seconds = self._backoff.current_delay
                self.stats.consecutive_failures = self._backoff.consecutive_failures

    async def _log_run(self) -> None:
        while not self._stopped.is_set():
            await asyncio.sleep(self.log_sync_interval)
            await self._sync_log_once()

    async def _restore_logged_queue(self) -> None:
        if self._log is None:
            return
        payloads = await self._log.async_load()
        self._log_has_content = bool(payloads)
        for payload in payloads:
            self._append(payload, logged=True)

    async def _sync_log_once(self) -> None:
        if self._log is None:
            return
        if self._log_drifted and self._queue:
            try:
                await self._log.async_rewrite([item.payload for item in self._queue])
            except Exception as e:
                self.stats.last_error = str(e)
                return
            for item in self._queue:
                item.logged = True
            self._log_has_content = True
            self._log_drifted = False
            return
        unlogged = [item for item in self._queue if not item.logged]
        if not unlogged:
            return
        try:
            await self._log.async_append([item.payload for item in unlogged])
        except Exception as e:
            self.stats.last_error = str(e)
            return
        for item in unlogged:
            item.logged = True
        self._log_has_content = True

    async def _truncate_log_if_synced(self) -> None:
        if self._log is None or not self._log_has_content:
            return
        try:
            await self._log.async_truncate()
        except Exception as e:
            self.stats.last_error = str(e)
            return
        self._log_has_content = False
        self._log_drifted = False

    def _client_reconnects(self) -> int:
        stats = getattr(self.client, "stats", None)
        reconnects = getattr(stats, "reconnects", 0)
        return reconnects if isinstance(reconnects, int) else 0

    async def _refresh_replay_site_after_recovery(self, had_error: bool) -> None:
        reconnects = self._client_reconnects()
        reconnected = reconnects != self._last_seen_reconnects
        self._last_seen_reconnects = reconnects
        if self.on_replay_recovered is not None and (had_error or reconnected):
            await self.on_replay_recovered()

    async def _flush_once(self) -> None:
        if not self._queue:
            return
        batch: list[QueuedPayload] = []
        while self._queue and len(batch) < self.batch_size:
            batch.append(self._queue.popleft())
        sent = False
        had_error = self.stats.last_error is not None
        try:
            await self.client.send_states([item.payload for item in batch])
            sent = True
            self.stats.sent += len(batch)
            self.stats.last_error = None
            await self._refresh_replay_site_after_recovery(had_error)
            if not self._queue:
                await self._truncate_log_if_synced()
        except Exception as e:
            self.stats.last_error = str(e)
            raise
        finally:
            if not sent:
                for payload in reversed(batch):
                    self._queue.appendleft(payload)
