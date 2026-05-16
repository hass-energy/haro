"""HARO config reconciliation loop."""

from __future__ import annotations

from typing import Any

from .canonical import canonical_config_hash
from .config_events import (
    ConfigEnvironment,
    build_checkpoint_event,
    build_patch_event,
    reconcile_config_state,
)
from .config_queue import ConfigEventQueue
from .replay_client import ReplayClient


class ConfigSync:
    """Reconcile HARO config queue with Replay's announced config_state."""

    def __init__(
        self,
        client: ReplayClient,
        queue: ConfigEventQueue,
        site_id: str,
        haeo_entry_id: str,
        current_config: dict[str, Any],
        config_version: str,
        environment: ConfigEnvironment,
    ) -> None:
        self.client = client
        self.queue = queue
        self.site_id = site_id
        self.haeo_entry_id = haeo_entry_id
        self.current_config = current_config
        self.config_version = config_version
        self.environment = environment

    async def async_update_current_config(
        self,
        current_config: dict[str, Any],
        config_version: str,
        environment: ConfigEnvironment,
    ) -> None:
        """Queue a patch or checkpoint after HARO observes a committed config change."""
        if canonical_config_hash(current_config) == canonical_config_hash(self.current_config):
            return
        if config_version == self.config_version and environment == self.environment:
            await self.queue.async_enqueue(build_patch_event(
                site_id=self.site_id,
                haeo_entry_id=self.haeo_entry_id,
                captured_at=utc_now_iso(),
                config_version=config_version,
                base_config=self.current_config,
                current_config=current_config,
            ))
        else:
            await self.queue.async_enqueue(build_checkpoint_event(
                site_id=self.site_id,
                haeo_entry_id=self.haeo_entry_id,
                captured_at=utc_now_iso(),
                config_version=config_version,
                environment=environment,
                config=current_config,
            ))
        self.current_config = current_config
        self.config_version = config_version
        self.environment = environment

    async def async_reconcile_once(self) -> None:
        """Receive config_state, send needed events, and prune after ack."""
        state = await self.client.receive_config_state()
        replay_environment = environment_from_payload(state.get("environment"))
        queued = await self.queue.async_load()
        local_hash = canonical_config_hash(self.current_config)
        decision = reconcile_config_state(
            state.get("config_hash") if isinstance(state.get("config_hash"), str) else None,
            state.get("config_version") if isinstance(state.get("config_version"), str) else None,
            replay_environment,
            local_hash,
            self.config_version,
            self.environment,
            queued,
        )
        events = decision.events
        if decision.action == "checkpoint":
            checkpoint = await self.queue.async_enqueue(build_checkpoint_event(
                site_id=self.site_id,
                haeo_entry_id=self.haeo_entry_id,
                captured_at=utc_now_iso(),
                config_version=self.config_version,
                environment=self.environment,
                config=self.current_config,
            ))
            events = [checkpoint]
        for event in events:
            ack = await self.client.send_config_event(event)
            if ack.get("type") == "ack" and ack.get("id") == event.get("id"):
                await self.queue.async_ack(str(event["id"]))


def environment_from_payload(value: Any) -> ConfigEnvironment | None:
    """Parse Replay config_state environment payload."""
    if not isinstance(value, dict):
        return None
    ha_version = value.get("ha_version")
    haeo_version = value.get("haeo_version")
    timezone = value.get("timezone")
    if not isinstance(ha_version, str) or not isinstance(haeo_version, str) or not isinstance(timezone, str):
        return None
    return ConfigEnvironment(ha_version, haeo_version, timezone)


def utc_now_iso() -> str:
    """Return current UTC ISO string with Z suffix."""
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
