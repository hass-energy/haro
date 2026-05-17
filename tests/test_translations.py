"""Translation coverage tests."""

from __future__ import annotations

import json
from pathlib import Path

from custom_components.haro.const import (
    CONF_HAEO_CONFIG_ENTRY_ID,
    CONF_REPLAY_SITE_ID,
    CONF_REPLAY_SITE_NAME,
    CONF_TOKEN,
)

ROOT = Path(__file__).resolve().parents[1]


def test_config_flow_fields_have_human_labels() -> None:
    translations = json.loads((ROOT / "custom_components/haro/translations/en.json").read_text())
    steps = translations["config"]["step"]

    assert steps["user"]["data"][CONF_HAEO_CONFIG_ENTRY_ID] == "HAEO install"
    assert steps["user"]["data"][CONF_TOKEN] == "Replay site token"
    assert steps["site"]["data"][CONF_REPLAY_SITE_ID] == "Replay site"
    assert steps["site"]["data"][CONF_REPLAY_SITE_NAME] == "New site name"
    assert steps["site"]["data"]["replay_site_slug"] == "New site slug"


def test_sensor_entities_have_human_labels() -> None:
    translations = json.loads((ROOT / "custom_components/haro/translations/en.json").read_text())
    sensors = translations["entity"]["sensor"]

    assert set(sensors) == {"site", "api_status", "tracked_entities", "backlog", "recorded_states", "recorded_configs"}
    assert sensors["site"]["name"] == "Site"
    assert sensors["api_status"]["name"] == "API Status"
    assert sensors["tracked_entities"]["name"] == "Tracked Entities"
    assert sensors["backlog"]["name"] == "Backlog"
    assert sensors["recorded_states"]["name"] == "Recorded States"
    assert sensors["recorded_configs"]["name"] == "Recorded Configs"


def test_sensor_entities_have_icons() -> None:
    icons = json.loads((ROOT / "custom_components/haro/icons.json").read_text())
    sensors = icons["entity"]["sensor"]

    assert set(sensors) == {"site", "api_status", "tracked_entities", "backlog", "recorded_states", "recorded_configs"}
    assert all(icon["default"].startswith("mdi:") for icon in sensors.values())
