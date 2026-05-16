from __future__ import annotations

import re

from custom_components.haro.canonical import canonical_config_hash, canonical_json


def test_canonical_json_sorts_object_keys_recursively() -> None:
    """Canonical JSON should match Replay's sorted-key, no-whitespace shape."""
    left = {"z": [3, {"b": True, "a": None}], "a": "hello"}
    right = {"a": "hello", "z": [3, {"a": None, "b": True}]}

    assert canonical_json(left) == '{"a":"hello","z":[3,{"a":null,"b":true}]}'
    assert canonical_config_hash(left) == canonical_config_hash(right)
    assert re.fullmatch(r"sha256:[a-f0-9]{64}", canonical_config_hash(left))


def test_canonical_json_rejects_non_json_numbers() -> None:
    """NaN and infinities must not get serialized differently across runtimes."""
    try:
        canonical_json({"bad": float("nan")})
    except ValueError as err:
        assert "non-finite" in str(err)
    else:
        raise AssertionError("expected ValueError")
