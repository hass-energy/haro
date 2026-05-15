"""HARO system health tests."""

from __future__ import annotations

import inspect
from typing import Any

from custom_components.haro import system_health


class FakeRegistration:
    def __init__(self) -> None:
        self.info_callback = None

    def async_register_info(self, callback: Any) -> None:
        self.info_callback = callback


def test_async_register_is_synchronous_for_home_assistant_loader() -> None:
    """Home Assistant calls system health registration without awaiting it."""
    assert not inspect.iscoroutinefunction(system_health.async_register)


def test_async_register_registers_info_callback() -> None:
    register = FakeRegistration()

    system_health.async_register(None, register)

    assert register.info_callback is not None
