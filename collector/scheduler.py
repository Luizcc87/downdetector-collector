"""Scheduler async com heap por (next_due_ts, slug).

Aceita um callable async para scraping. Implementa backoff exponencial por serviço.
"""
from __future__ import annotations

import asyncio
import heapq
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

import structlog

from collector.config import ServiceConfig

log = structlog.get_logger(__name__)

ScrapeCallable = Callable[[ServiceConfig], Awaitable[object]]


@dataclass(order=True)
class _HeapItem:
    next_due: float
    slug: str = field(compare=False)
    service: ServiceConfig = field(compare=False)
    backoff_seconds: float = field(default=0.0, compare=False)


class Scheduler:
    def __init__(
        self,
        services: list[ServiceConfig],
        scrape: ScrapeCallable,
        backoff_initial: float = 60.0,
        backoff_max: float = 3600.0,
    ) -> None:
        self._scrape = scrape
        self._heap: list[_HeapItem] = []
        self._backoff_initial = backoff_initial
        self._backoff_max = backoff_max
        self._stop = asyncio.Event()
        now = time.monotonic()
        for svc in services:
            heapq.heappush(self._heap, _HeapItem(next_due=now, slug=svc.slug, service=svc))

    def stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        while not self._stop.is_set():
            if not self._heap:
                await asyncio.sleep(0.1)
                continue
            item = self._heap[0]
            wait = item.next_due - time.monotonic()
            if wait > 0:
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=min(wait, 1.0))
                    return
                except asyncio.TimeoutError:
                    continue
            heapq.heappop(self._heap)
            try:
                await self._scrape(item.service)
                next_interval = item.service.poll_interval
                next_backoff = 0.0
            except Exception as exc:
                log.warning("scrape_failed", slug=item.slug, error=str(exc))
                next_backoff = (
                    self._backoff_initial if item.backoff_seconds == 0
                    else min(item.backoff_seconds * 2, self._backoff_max)
                )
                next_interval = next_backoff
            next_item = _HeapItem(
                next_due=time.monotonic() + next_interval,
                slug=item.slug,
                service=item.service,
                backoff_seconds=next_backoff,
            )
            heapq.heappush(self._heap, next_item)
