"""Canonical JSON and config hashing shared with Replay."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from typing import Any


def canonical_json(value: Any) -> str:
    """Serialize JSON-compatible values with sorted keys and no whitespace."""
    _validate_json_value(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def canonical_config_hash(config: Any) -> str:
    """Return the sha256-prefixed canonical config hash."""
    digest = hashlib.sha256(canonical_json(config).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _validate_json_value(value: Any) -> None:
    if value is None or isinstance(value, str | bool):
        return
    if isinstance(value, int):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("config contains non-finite number")
        return
    if isinstance(value, list | tuple):
        for item in value:
            _validate_json_value(item)
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise TypeError("config object keys must be strings")
            _validate_json_value(child)
        return
    raise TypeError(f"config contains non-json value: {type(value).__name__}")
