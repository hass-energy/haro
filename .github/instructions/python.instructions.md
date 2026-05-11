---
applyTo: '**/*.py'
description: Python coding standards for HARO
globs: ['**/*.py']
alwaysApply: false
---

# Python Coding Standards

## Language

Use Python 3.13 features consistently:

- Use modern union syntax such as `str | None`.
- Use `type` aliases for complex types at module boundaries.
- Prefer dataclasses for small value containers.
- Use pattern matching when it clarifies structured data handling.

Add type hints to functions, methods, and variables where Pyright needs help.
Prefer precise boundary types over broad `Any`, especially where Home Assistant data enters HARO.

## Home Assistant Async

Do not block the event loop.
Use async APIs for I/O, `asyncio.sleep()` for waits, and Home Assistant executor helpers for blocking work.

Keep event subscriptions paired with unload cleanup.
Store unsubscribe callbacks and register cleanup with `entry.async_on_unload()` or the entity lifecycle where appropriate.

## Error Handling

Use Home Assistant exception types for setup and user-facing failures.
Use custom integration exceptions for Replay transport errors when tests need to distinguish failure causes.

Keep try blocks minimal.
Only catch broad exceptions at Home Assistant boundaries where the UI needs a translated or stable error result.

## Logging And Secrets

Never log Replay tokens or full authentication headers.
Use lazy logging with `%s` placeholders.
Do not include terminal punctuation in log messages.

## Comments

Prefer code that reads directly.
Add comments only for non-obvious intent or Home Assistant lifecycle constraints.
