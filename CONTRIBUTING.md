# Contribution Guidelines

HARO is a focused Home Assistant integration for forwarding selected HAEO input state to Replay.
Keep changes small, tested, and within that boundary.

## Development Setup

Install dependencies with uv:

```bash
uv sync --locked --dev
```

Run the core checks before opening a pull request:

```bash
uv run ruff format --check
uv run ruff check
uv run pyright
uv run pytest
```

## Testing

Use red-green TDD for behavior changes and bug fixes:

1. Add or update a failing test.
2. Confirm it fails for the expected reason.
3. Make the smallest implementation change.
4. Re-run the focused test and then the full check set.

Tests should document HARO's public behavior: config flow validation, HAEO input discovery, forwarding, queueing, and Replay acknowledgement handling.

## Scope

Do not add HAEO optimizer concepts, frontend tooling, scenario harnesses, or documentation infrastructure unless HARO gains a concrete product need for them.
Prefer improving the small existing module boundaries over adding new layers.

## Releases

Releases are created from GitHub Releases with tags like `v0.1.0` or `v0.1.0rc1`.
The release workflow validates that:

- the tag version matches `pyproject.toml`
- the tag version matches `custom_components/haro/manifest.json`
- the Home Assistant minimum version matches `hacs.json`

Run `uv lock` when changing dependency constraints or the project version.
