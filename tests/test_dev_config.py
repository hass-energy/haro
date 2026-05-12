"""Development Home Assistant config tests."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_home_assistant_dev_config_exists() -> None:
    config = ROOT / "config/configuration.yaml"

    assert config.is_file()
    content = config.read_text()
    assert "replay_url: log_only" in content
    assert "custom_components.haro: debug" in content
    assert "custom_components.haeo: debug" in content
