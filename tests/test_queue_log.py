"""Queue log persistence tests."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from custom_components.haro.queue_log import QueueLog


class FakeConfig:
    def __init__(self, root: Path) -> None:
        self.root = root

    def path(self, *parts: str) -> str:
        return str(self.root.joinpath(*parts))


class FakeHass:
    def __init__(self, root: Path) -> None:
        self.config = FakeConfig(root)

    async def async_add_executor_job(self, target: Callable[..., Any], *args: Any) -> Any:
        return target(*args)


def payload(entity_id: str) -> dict[str, Any]:
    return {"entity_id": entity_id, "state": "1", "attributes": {"unit_of_measurement": "kWh"}}


async def test_load_returns_empty_when_file_missing(tmp_path: Path) -> None:
    log = QueueLog(FakeHass(tmp_path), "entry-1")  # type: ignore[arg-type]

    assert await log.async_load() == []


async def test_append_then_load_round_trips_payloads(tmp_path: Path) -> None:
    log = QueueLog(FakeHass(tmp_path), "entry-1")  # type: ignore[arg-type]
    payloads = [payload("sensor.one"), payload("sensor.two")]

    await log.async_append(payloads)

    assert await log.async_load() == payloads


async def test_load_skips_malformed_trailing_line(tmp_path: Path) -> None:
    log = QueueLog(FakeHass(tmp_path), "entry-1")  # type: ignore[arg-type]

    await log.async_append([payload("sensor.one")])
    log.path.write_text(f"{log.path.read_text(encoding='utf-8')}{{", encoding="utf-8")

    assert await log.async_load() == [payload("sensor.one")]


async def test_rewrite_replaces_file_contents_atomically(tmp_path: Path) -> None:
    log = QueueLog(FakeHass(tmp_path), "entry-1")  # type: ignore[arg-type]

    await log.async_append([payload("sensor.old")])
    await log.async_rewrite([payload("sensor.new"), payload("sensor.latest")])

    assert await log.async_load() == [payload("sensor.new"), payload("sensor.latest")]


async def test_truncate_clears_file_without_removing_it(tmp_path: Path) -> None:
    log = QueueLog(FakeHass(tmp_path), "entry-1")  # type: ignore[arg-type]

    await log.async_append([payload("sensor.one")])
    await log.async_truncate()

    assert log.path.exists()
    assert log.path.read_text(encoding="utf-8") == ""
    assert await log.async_load() == []


async def test_remove_unlinks_file(tmp_path: Path) -> None:
    log = QueueLog(FakeHass(tmp_path), "entry-1")  # type: ignore[arg-type]

    await log.async_append([payload("sensor.one")])
    await log.async_remove()

    assert not log.path.exists()
