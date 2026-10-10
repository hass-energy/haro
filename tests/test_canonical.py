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


def test_canonical_json_renders_numbers_like_replay() -> None:
    """Replay hashes with JavaScript's JSON.stringify, which has no separate float type."""
    numbers = {
        "whole": 97.0,
        "fraction": 0.27,
        "negative": -1.5,
        "negative_zero": -0.0,
        "big": 1e16,
        "huge": 1e21,
        "small": 0.000001,
        "tiny": 1e-7,
        "integer": 30,
    }

    assert canonical_json(numbers) == (
        '{"big":10000000000000000,"fraction":0.27,"huge":1e+21,"integer":30,"negative":-1.5,'
        '"negative_zero":0,"small":0.000001,"tiny":1e-7,"whole":97}'
    )


def test_canonical_config_hash_matches_replay() -> None:
    """Hash computed by Replay's canonicalConfigHash for the same config."""
    config = {
        "participants": {"Inverter": {"efficiency": {"efficiency_source_target": {"type": "constant", "value": 97.0}}}},
        "version": 1,
        "minor_version": 3,
    }

    assert canonical_config_hash(config) == "sha256:63ff45ad704cb0aec79d74bb23aa5f9589eebdc74eb223d45b1d7d4b277f11b4"
