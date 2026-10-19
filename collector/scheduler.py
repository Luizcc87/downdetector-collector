"""Scheduler async com heap por (next_due_ts, slug).

Aceita um callable async para scraping. Implementa backoff exponencial por serviço e, para
bloqueio do site (RateLimited), pausa global: o limite do Downdetector é por IP, então
recuar só o serviço bloqueado não adianta enquanto os demais continuam consultando.
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


class RateLimited(RuntimeError):
    """Site recusou por excesso de consultas (429 / desafio do Cloudflare)."""


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
        min_gap: float = 0.0,
        cooldown_initial: Optional[float] = None,
        cooldown_max: float = 3600.0,
    ) -> None:
        """min_gap: intervalo mínimo entre duas consultas quaisquer (espalha os serviços).
        cooldown_initial: pausa global após RateLimited, dobrando a cada bloqueio seguido até
        cooldown_max; None mantém o comportamento antigo (backoff só do serviço)."""
        self._scrape = scrape
        self._heap: list[_HeapItem] = []
        self._backoff_initial = backoff_initial
        self._backoff_max = backoff_max
        self._min_gap = min_gap
        self._cooldown_initial = cooldown_initial
        self._cooldown_max = cooldown_max
        self._cooldown = 0.0
        self._paused_until = 0.0
        self._last_start = float("-inf")
        self._stop = asyncio.Event()
        now = time.monotonic()
        for svc in services:
            heapq.heappush(self._heap, _HeapItem(next_due=now, slug=svc.slug, service=svc))

    def stop(self) -> None:
        self._stop.set()

    async def _wait(self, seconds: float) -> bool:
        """Espera até `seconds` (no máximo 1 s por volta). True se pediram parada."""
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=min(seconds, 1.0))
            return True
        except asyncio.TimeoutError:
            return False

    async def run(self) -> None:
        while not self._stop.is_set():
            if not self._heap:
                await asyncio.sleep(0.1)
                continue
            now = time.monotonic()
            item = self._heap[0]
            liberado = max(item.next_due, self._paused_until, self._last_start + self._min_gap)
            if liberado > now:
                if await self._wait(liberado - now):
                    return
                continue
            heapq.heappop(self._heap)
            self._last_start = time.monotonic()
            try:
                await self._scrape(item.service)
                next_interval = item.service.poll_interval
                next_backoff = 0.0
                self._cooldown = 0.0  # consulta aceita: próximo bloqueio volta à pausa inicial
            except RateLimited as exc:
                if self._cooldown_initial is None:
                    next_backoff = self._next_backoff(item)
                    next_interval = next_backoff
                else:
                    self._cooldown = (self._cooldown_initial if self._cooldown == 0
                                      else min(self._cooldown * 2, self._cooldown_max))
                    self._paused_until = time.monotonic() + self._cooldown
                    log.warning("scrape_rate_limited_global_pause", slug=item.slug, error=str(exc),
                                pause_seconds=self._cooldown)
                    # O serviço volta à fila normal; a pausa global já segura todos.
                    next_backoff = 0.0
                    next_interval = 0.0
            except Exception as exc:
                log.warning("scrape_failed", slug=item.slug, error=str(exc))
                next_backoff = self._next_backoff(item)
                next_interval = next_backoff
            heapq.heappush(self._heap, _HeapItem(
                next_due=time.monotonic() + next_interval,
                slug=item.slug,
                service=item.service,
                backoff_seconds=next_backoff,
            ))

    def _next_backoff(self, item: _HeapItem) -> float:
        return (self._backoff_initial if item.backoff_seconds == 0
                else min(item.backoff_seconds * 2, self._backoff_max))
