---
description: HARO project context and agent behavioral rules
alwaysApply: true
---

# HARO Agent Instructions

HARO is a Python 3.13 Home Assistant custom integration that streams selected HAEO input state to Replay.
The integration domain is `haro`, and the repository may be checked out locally as `haro2`.

## Project Boundaries

HARO is a focused companion to HAEO.
It does not optimize energy, model networks, forecast load, or control devices.
It discovers the non-derivable Home Assistant entity inputs used by selected HAEO config entries, listens for state changes, and forwards those state payloads to Replay.

Keep these responsibilities separate:

- `haeo_inputs.py` extracts entity IDs from HAEO config entry and subentry data.
- `event_forwarder.py` owns Home Assistant state subscription, queueing, batching, and diagnostics counters.
- `replay_client.py` owns Replay websocket connection, authentication headers, send/ack behavior, and reconnects.
- `config_flow.py` owns user-entered Replay connection settings and validation.

Do not import HAEO internals unless there is no stable Home Assistant config-entry surface that can express the same behavior.
HARO should remain installable as a normal HACS integration with HAEO as an optional runtime peer.

## Development Tools

- Use `uv sync --locked --dev` for dependency setup.
- Use `uv run pytest` for tests.
- Use `uv run ruff format --check`, `uv run ruff check`, and `uv run pyright` before considering work complete.
- Keep `pyproject.toml`, `custom_components/haro/manifest.json`, and `hacs.json` version requirements aligned.

## Change Style

Prefer small behavior-first changes with tests.
When fixing a bug, write or update the failing test first, confirm it fails for the expected reason, then make the smallest implementation change.

Keep HARO small.
Do not add HAEO's frontend, optimizer model, docs site, scenario harness, or import-linter boundaries unless HARO grows a real need for them.

## Release Rules

Release tags use `vX.Y.Z` or `vX.Y.ZrcN`.
The tag version, `pyproject.toml` project version, and `manifest.json` version must match.
The Home Assistant minimum version in `pyproject.toml` must match `hacs.json`.
