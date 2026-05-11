---
applyTo: custom_components/haro/**
description: Home Assistant integration standards for HARO
globs: [custom_components/haro/**]
alwaysApply: false
---

# HARO Integration Standards

HARO is a Home Assistant integration boundary around Replay forwarding.
Keep Home Assistant lifecycle code, HAEO config inspection, and Replay transport responsibilities separate.

## Module Boundaries

- `config_flow.py` validates user-provided Replay connection settings and creates config entries.
- `haeo_inputs.py` reads selected HAEO config entries and extracts non-derivable entity IDs from config-shaped data.
- `event_forwarder.py` subscribes to Home Assistant state changes, filters selected entities, queues payloads, and flushes batches.
- `replay_client.py` owns websocket connection setup, bearer authentication, batch send, acknowledgement matching, reconnects, and close behavior.
- `diagnostics.py` and `system_health.py` expose operational state without leaking secrets.

Do not make `event_forwarder.py` understand Replay protocol details.
Do not make `replay_client.py` understand Home Assistant state objects.
Do not make `haeo_inputs.py` import HAEO internals unless a stable config-entry representation is not enough.

## Config And Runtime Data

Use typed runtime data on the config entry for objects created during setup.
Register unload cleanup for background tasks and connections.

Treat the Replay token as secret config data.
Diagnostics must redact it.

## State Forwarding

Only forward entities selected by HAEO config entries plus explicit user extras.
When a state lacks a usable timestamp, skip it instead of inventing one.
Queue overflow should drop oldest payloads first so the newest state remains available for Replay.

## Home Assistant Metadata

Keep `manifest.json`, translations, diagnostics, and system health aligned with Home Assistant custom integration expectations.
Do not add platforms unless HARO exposes Home Assistant entities.
