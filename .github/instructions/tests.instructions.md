---
applyTo: tests/**,custom_components/haro/**/tests/**
description: Testing standards for HARO
globs: [tests/**, custom_components/haro/**/tests/**]
alwaysApply: false
---

# Testing Standards

Use function-style pytest tests.
Tests should read as examples of HARO behavior: how config is validated, which HAEO inputs are selected, how state events are queued, and how Replay acknowledgements are handled.

## Red-Green TDD

For bug fixes and behavior changes:

1. Write or update a failing test that proves the desired behavior.
2. Confirm the failure is for the expected reason.
3. Make the smallest code change that passes the test.
4. Run the focused test, then the full relevant check set.

## Test Shape

Prefer parametrized tests for structured input cases, especially HAEO config extraction and Replay message handling.
Avoid tests that only duplicate Pyright or Ruff checks.

When a Home Assistant fixture creates an object, access expected properties directly.
Do not add `None` checks in tests when missing data would be a real setup failure.

## Boundaries To Cover

Cover behavior at HARO's boundaries:

- Config flow validation succeeds and reports connection errors.
- HAEO config data yields the expected entity ID set.
- State payload conversion preserves entity ID, state, attributes, timestamps, and context IDs.
- Forwarder queue limits, batching, filtering, and retry behavior are stable.
- Replay client sends batches and requires matching acknowledgements.
