"""Development Home Assistant config tests."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_home_assistant_dev_config_exists() -> None:
    config = ROOT / "config/configuration.yaml"

    assert config.is_file()
    assert "custom_components.haro: debug" in config.read_text()
