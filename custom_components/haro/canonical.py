"""Canonical JSON and config hashing shared with Replay."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from decimal import Decimal
from typing import Any


def canonical_json(value: Any) -> str:
    """Serialize JSON-compatible values with sorted keys and no whitespace, rendered as Replay's JS does."""
    _validate_json_value(value)
    return _render(value)


def canonical_config_hash(config: Any) -> str:
    """Return the sha256-prefixed canonical config hash."""
    digest = hashlib.sha256(canonical_json(config).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _render(value: Any) -> str:
    if value is None or isinstance(value, str | bool):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, int | float):
        return _js_number(float(value))
    if isinstance(value, list | tuple):
        return f"[{','.join(_render(item) for item in value)}]"
    pairs = (f"{json.dumps(key, ensure_ascii=False)}:{_render(child)}" for key, child in sorted(value.items()))
    return f"{{{','.join(pairs)}}}"


def _js_number(value: float) -> str:
    """Render a double the way ECMAScript's Number::toString does (no ``.0``, exponent only beyond 1e21 / 1e-7)."""
    if value == 0:
        return "0"
    sign = "-" if value < 0 else ""
    _, digit_tuple, exponent = Decimal(repr(abs(value))).normalize().as_tuple()
    digits = "".join(str(digit) for digit in digit_tuple)
    point = int(exponent) + len(digits)
    if len(digits) <= point <= 21:
        return sign + digits + "0" * (point - len(digits))
    if 0 < point <= 21:
        return f"{sign}{digits[:point]}.{digits[point:]}"
    if -6 < point <= 0:
        return f"{sign}0.{'0' * -point}{digits}"
    mantissa = digits[0] + (f".{digits[1:]}" if len(digits) > 1 else "")
    return f"{sign}{mantissa}e{'+' if point > 0 else '-'}{abs(point - 1)}"


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
