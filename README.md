# HARO

HARO is a Home Assistant custom integration that streams the non-derivable inputs required by selected HAEO configurations to Replay.

This repository replaces the old standalone `haro` recorder. The local folder may be named `haro2` during development, but the integration name and domain are `HARO` / `haro`.

## Scope

HARO is intentionally small.
It discovers selected HAEO input entities, listens for Home Assistant state changes, batches those state payloads, and sends them to Replay.
It does not optimize energy, forecast load, control devices, or provide a frontend.

## Development

Install dependencies with uv:

```bash
uv sync --locked --dev
```

Run the standard checks:

```bash
uv run ruff format --check
uv run ruff check
uv run pyright
uv run pytest
```

When changing dependencies or the project version, update the lockfile:

```bash
uv lock
```

## Release Metadata

The HARO version must match in `pyproject.toml`, `custom_components/haro/manifest.json`, and the GitHub Release tag.
Release tags use `vX.Y.Z` or `vX.Y.ZrcN`.

The Home Assistant minimum version must match between `pyproject.toml` and `hacs.json`.

