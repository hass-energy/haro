"""Diagnostics for HARO."""

from __future__ import annotations

from typing import Any

from .const import DOMAIN


async def async_get_config_entry_diagnostics(hass: Any, entry: Any) -> dict[str, Any]:
    """Return diagnostics without exposing secrets."""
    runtime = getattr(entry, "runtime_data", None)
    stats = runtime.forwarder.diagnostics() if runtime is not None else {}
    return {"domain": DOMAIN, "stats": stats}
