"""Collect non-derivable HAEO input entity IDs."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


def extract_entity_ids_from_config(config: Mapping[str, Any]) -> set[str]:
    """Extract HA entity IDs from HAEO element config values."""
    entity_ids: set[str] = set()

    def collect(value: Any) -> None:
        match value:
            case {"type": "entity", "value": values} if isinstance(values, list):
                for entity_id in values:
                    if isinstance(entity_id, str) and "." in entity_id:
                        entity_ids.add(entity_id)
            case {"type": _}:
                return
            case Mapping():
                for nested in value.values():
                    collect(nested)
            case list():
                for nested in value:
                    collect(nested)
            case _:
                return

    collect(dict(config))
    return entity_ids


def entity_ids_from_haeo_entry(entries: Iterable[Any], selected_entry_id: str | None) -> set[str]:
    """Collect deduped HAEO input entities from one selected config entry."""
    if not selected_entry_id:
        return set()

    entity_ids: set[str] = set()
    for entry in entries:
        entry_id = getattr(entry, "entry_id", None)
        if entry_id != selected_entry_id:
            continue
        subentries = getattr(entry, "subentries", {})
        for subentry in subentries.values() if isinstance(subentries, Mapping) else subentries:
            if getattr(subentry, "subentry_type", None) == "network":
                continue
            data = getattr(subentry, "data", {})
            if isinstance(data, Mapping):
                entity_ids.update(extract_entity_ids_from_config(data))
    return entity_ids
