"""Build and reconcile HARO config history events."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .canonical import canonical_config_hash

ConfigPayload = dict[str, Any]


@dataclass(frozen=True, slots=True)
class ConfigEnvironment:
    """Runtime environment metadata stored with checkpoints."""

    ha_version: str
    haeo_version: str
    timezone: str

    def as_payload(self) -> dict[str, str]:
        """Return Replay wire shape."""
        return {"ha_version": self.ha_version, "haeo_version": self.haeo_version, "timezone": self.timezone}


@dataclass(frozen=True, slots=True)
class ReconcileDecision:
    """What HARO should send after Replay announces config_state."""

    action: Literal["noop", "drain", "checkpoint"]
    events: list[ConfigPayload]


def build_checkpoint_event(
    *,
    site_id: str,
    haeo_entry_id: str,
    captured_at: str,
    config_version: str,
    environment: ConfigEnvironment,
    config: ConfigPayload,
) -> ConfigPayload:
    """Build a full config checkpoint event."""
    return {
        "type": "config_checkpoint",
        "site_id": site_id,
        "haeo_entry_id": haeo_entry_id,
        "captured_at": captured_at,
        "config_version": config_version,
        "environment": environment.as_payload(),
        "config_hash": canonical_config_hash(config),
        "config": config,
    }


def config_version_from_haeo_entry(entry: Any) -> str:
    """Return the opaque version string HARO sends to Replay."""
    return f"{getattr(entry, 'version', 1)}.{getattr(entry, 'minor_version', 0)}"


def config_from_haeo_entry(entry: Any) -> ConfigPayload:
    """Build the same current-config shape HAEO diagnostics exposes."""
    config: ConfigPayload = {**dict(getattr(entry, "data", {})), "participants": {}}
    for subentry in getattr(entry, "subentries", {}).values():
        subentry_type = getattr(subentry, "subentry_type", None)
        if subentry_type == "network":
            continue
        title = str(getattr(subentry, "title", "unnamed"))
        raw_data = dict(getattr(subentry, "data", {}))
        raw_data.setdefault("element_type", subentry_type)
        raw_data.setdefault("name", title)
        config["participants"][title] = raw_data
    config["version"] = getattr(entry, "version", 1)
    config["minor_version"] = getattr(entry, "minor_version", 0)
    return config


def build_patch_event(
    *,
    site_id: str,
    haeo_entry_id: str,
    captured_at: str,
    config_version: str,
    base_config: ConfigPayload,
    current_config: ConfigPayload,
) -> ConfigPayload:
    """Build a compact replace-only patch event."""
    return {
        "type": "config_patch",
        "site_id": site_id,
        "haeo_entry_id": haeo_entry_id,
        "captured_at": captured_at,
        "config_version": config_version,
        "base_hash": canonical_config_hash(base_config),
        "config_hash": canonical_config_hash(current_config),
        "patch": replace_patch(base_config, current_config),
    }


def replace_patch(base: Any, current: Any, path: list[str | int] | None = None) -> list[ConfigPayload]:
    """Return replace ops needed to transform base into current."""
    path = [] if path is None else path
    if type(base) is not type(current):
        return [{"op": "replace", "path": path, "value": current}]
    if isinstance(base, dict) and isinstance(current, dict):
        if set(base) != set(current):
            return [{"op": "replace", "path": path, "value": current}]
        ops: list[ConfigPayload] = []
        for key in sorted(base):
            ops.extend(replace_patch(base[key], current[key], [*path, str(key)]))
        return ops
    if isinstance(base, list) and isinstance(current, list):
        if len(base) != len(current):
            return [{"op": "replace", "path": path, "value": current}]
        ops = []
        for index, (left, right) in enumerate(zip(base, current, strict=True)):
            ops.extend(replace_patch(left, right, [*path, index]))
        return ops
    return [] if base == current else [{"op": "replace", "path": path, "value": current}]


def reconcile_config_state(
    replay_hash: str | None,
    replay_version: str | None,
    replay_environment: ConfigEnvironment | None,
    local_hash: str,
    local_version: str,
    local_environment: ConfigEnvironment,
    queued_events: list[ConfigPayload],
) -> ReconcileDecision:
    """Choose whether to send nothing, queued patches, or a fresh checkpoint."""
    if replay_hash == local_hash and replay_version == local_version and replay_environment == local_environment:
        return ReconcileDecision("noop", [])
    if replay_hash is None or replay_version != local_version or replay_environment != local_environment:
        return ReconcileDecision("checkpoint", [])
    for index, event in enumerate(queued_events):
        if event.get("base_hash") == replay_hash:
            return ReconcileDecision("drain", queued_events[index:])
        if event.get("config_hash") == replay_hash:
            return ReconcileDecision("drain", queued_events[index + 1 :])
    return ReconcileDecision("checkpoint", [])
