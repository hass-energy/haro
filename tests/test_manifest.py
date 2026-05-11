"""Manifest/release metadata tests."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_manifest_and_pyproject_versions_match() -> None:
    manifest = json.loads((ROOT / "custom_components/haro/manifest.json").read_text())
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())

    assert manifest["domain"] == "haro"
    assert manifest["name"] == "HARO"
    assert manifest["version"] == "0.0.1rc1"
    assert pyproject["project"]["name"] == "haro"
    assert pyproject["project"]["version"] == manifest["version"]


def test_hacs_zip_release_is_named_haro() -> None:
    hacs = json.loads((ROOT / "hacs.json").read_text())

    assert hacs["name"] == "HARO"
    assert hacs["filename"] == "haro.zip"
    assert hacs["zip_release"] is True
