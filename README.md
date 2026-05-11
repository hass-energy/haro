# HARO

HARO is a Home Assistant custom integration for forwarding HAEO input sensors to Replay for historical recording and analysis.

## Status

HARO is currently pre-alpha and not publicly usable.

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
