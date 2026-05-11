"""HAEO input extraction tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from custom_components.haro.haeo_inputs import entity_ids_from_haeo_entries, extract_entity_ids_from_config


@dataclass
class Subentry:
    subentry_type: str
    data: dict[str, Any]


@dataclass
class Entry:
    entry_id: str
    subentries: dict[str, Subentry]


def test_extract_entity_ids_from_nested_haeo_config_values() -> None:
    config = {
        "capacity": {"type": "entity", "value": ["sensor.battery_capacity"]},
        "limits": {
            "import": {"type": "entity", "value": ["sensor.import_limit"]},
            "constant": {"type": "constant", "value": 3},
        },
    }

    assert extract_entity_ids_from_config(config) == {"sensor.battery_capacity", "sensor.import_limit"}


def test_entity_ids_from_selected_haeo_entries_skips_network_and_dedupes() -> None:
    entry = Entry(
        "selected",
        {
            "network": Subentry("network", {"ignored": {"type": "entity", "value": ["sensor.network"]}}),
            "battery": Subentry("battery", {"soc": {"type": "entity", "value": ["sensor.soc", "sensor.soc"]}}),
        },
    )
    other = Entry("other", {"load": Subentry("load", {"power": {"type": "entity", "value": ["sensor.other"]}})})

    assert entity_ids_from_haeo_entries([entry, other], ["selected"]) == {"sensor.soc"}
