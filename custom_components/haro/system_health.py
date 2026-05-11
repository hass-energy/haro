"""System health for HARO."""

from __future__ import annotations

from typing import Any


async def async_register(hass: Any, register: Any) -> None:
    """Register HARO system health information."""

    async def info_callback() -> dict[str, Any]:
        return {"can_reach_replay": "unknown"}

    register.async_register_info(info_callback)
