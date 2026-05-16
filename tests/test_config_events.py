from __future__ import annotations

from custom_components.haro.canonical import canonical_config_hash
from custom_components.haro.config_events import (
    ConfigEnvironment,
    build_checkpoint_event,
    build_patch_event,
    config_from_haeo_entry,
    reconcile_config_state,
)


def test_build_checkpoint_event_includes_version_environment_and_hash() -> None:
    """Checkpoint events carry the full config plus metadata needed by Replay."""
    config = {"version": 1, "minor_version": 3, "hub": {"name": "Home"}}
    event = build_checkpoint_event(
        site_id="site-1",
        haeo_entry_id="haeo-entry-1",
        captured_at="2026-01-01T00:00:00Z",
        config_version="1.3",
        environment=ConfigEnvironment("2026.5.0", "0.5.0", "Australia/Sydney"),
        config=config,
    )

    assert event == {
        "type": "config_checkpoint",
        "site_id": "site-1",
        "haeo_entry_id": "haeo-entry-1",
        "captured_at": "2026-01-01T00:00:00Z",
        "config_version": "1.3",
        "environment": {"ha_version": "2026.5.0", "haeo_version": "0.5.0", "timezone": "Australia/Sydney"},
        "config_hash": canonical_config_hash(config),
        "config": config,
    }


def test_build_patch_event_replaces_changed_leaves_only() -> None:
    """Value-only mutations should produce compact replace ops."""
    base = {"version": 1, "minor_version": 3, "hub": {"name": "Home"}, "values": [1, 2]}
    current = {"version": 1, "minor_version": 3, "hub": {"name": "Away"}, "values": [1, 3]}

    event = build_patch_event(
        site_id="site-1",
        haeo_entry_id="haeo-entry-1",
        captured_at="2026-01-01T00:01:00Z",
        config_version="1.3",
        base_config=base,
        current_config=current,
    )

    assert event["type"] == "config_patch"
    assert event["base_hash"] == canonical_config_hash(base)
    assert event["config_hash"] == canonical_config_hash(current)
    assert event["patch"] == [
        {"op": "replace", "path": ["hub", "name"], "value": "Away"},
        {"op": "replace", "path": ["values", 1], "value": 3},
    ]


def test_reconcile_config_state_chooses_noop_patch_drain_or_checkpoint() -> None:
    """HARO should use Replay's announced hash to pick the cheapest safe action."""
    environment = ConfigEnvironment("2026.5.0", "0.5.0", "Australia/Sydney")
    queued = [
        {"base_hash": "sha256:a", "config_hash": "sha256:b"},
        {"base_hash": "sha256:b", "config_hash": "sha256:c"},
    ]

    assert (
        reconcile_config_state("sha256:c", "1.3", environment, "sha256:c", "1.3", environment, queued).action
        == "noop"
    )
    drain = reconcile_config_state("sha256:a", "1.3", environment, "sha256:c", "1.3", environment, queued)
    assert drain.action == "drain"
    assert drain.events == queued
    assert reconcile_config_state(None, None, None, "sha256:c", "1.3", environment, queued).action == "checkpoint"
    assert (
        reconcile_config_state("sha256:a", "1.2", environment, "sha256:c", "1.3", environment, queued).action
        == "checkpoint"
    )


def test_config_from_haeo_entry_matches_diagnostics_shape() -> None:
    """HARO should send the same config shape HAEO diagnostics exposes."""

    class Subentry:
        subentry_type = "battery"
        title = "Battery"
        data = {"capacity": {"type": "constant", "value": 10}}

    class Entry:
        version = 1
        minor_version = 3
        data = {"common": {"name": "Hub"}}
        subentries = {"battery-1": Subentry()}

    assert config_from_haeo_entry(Entry()) == {
        "common": {"name": "Hub"},
        "version": 1,
        "minor_version": 3,
        "participants": {
            "Battery": {
                "capacity": {"type": "constant", "value": 10},
                "element_type": "battery",
                "name": "Battery",
            }
        },
    }
