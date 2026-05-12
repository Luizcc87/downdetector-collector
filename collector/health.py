"""Métricas internas do scraper expostas como items Zabbix."""
from __future__ import annotations

import time
from typing import Optional


class HealthState:
    def __init__(self) -> None:
        self._started_at = time.monotonic()
        self.last_cycle_seconds: Optional[float] = None
        self._blocks: list[float] = []  # timestamps Unix
        self.browser_restarts = 0

    def uptime_seconds(self) -> float:
        return time.monotonic() - self._started_at

    def record_cycle_duration(self, seconds: float) -> None:
        self.last_cycle_seconds = seconds

    def record_block(self, timestamp: Optional[float] = None) -> None:
        self._blocks.append(timestamp if timestamp is not None else time.time())

    def record_browser_restart(self) -> None:
        self.browser_restarts += 1

    def blocks_in_last_5m(self, now: Optional[float] = None) -> int:
        cutoff = (now if now is not None else time.time()) - 300
        self._blocks = [t for t in self._blocks if t >= cutoff]
        return len(self._blocks)

    def healthy(self) -> bool:
        return self.blocks_in_last_5m() <= 10

    def as_metrics(self) -> list[tuple[str, float]]:
        return [
            ("downdetector.scraper.uptime", round(self.uptime_seconds(), 1)),
            ("downdetector.scraper.cycle_seconds", self.last_cycle_seconds or 0),
            ("downdetector.scraper.blocks_5m", self.blocks_in_last_5m()),
            ("downdetector.scraper.restarts", self.browser_restarts),
            ("downdetector.scraper.healthy", 1 if self.healthy() else 0),
        ]
