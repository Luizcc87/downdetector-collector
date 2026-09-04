"""Scheduler de intervalo fixo, por roteador -- deliberadamente mais simples
que collector/scheduler.py.

collector/scheduler.py implementa backoff exponencial porque, para o
Downdetector, uma falha de scrape normalmente significa "fomos bloqueados,
espera mais" -- ali, esperar mais e o comportamento certo.

Aqui e o oposto: uma falha de ping/traceroute E o dado que queremos ver
(o link caiu). Aumentar o intervalo depois de uma falha esconderia
justamente o momento em que a instabilidade esta acontecendo. Por isso este
scheduler mantem o mesmo `poll_interval` sempre, sucesso ou falha -- so loga
a falha e segue.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

import structlog

from mikrotik.config import RouterConfig

log = structlog.get_logger(__name__)

RouterCallable = Callable[[RouterConfig], Awaitable[object]]


class FixedIntervalScheduler:
    def __init__(self, routers: list[RouterConfig], run_router: RouterCallable) -> None:
        self._routers = routers
        self._run_router = run_router
        self._stop = asyncio.Event()

    def stop(self) -> None:
        self._stop.set()

    async def _loop_one_router(self, router: RouterConfig) -> None:
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                await self._run_router(router)
            except Exception as exc:
                # Falha de um roteador nao deve derrubar o loop dos outros --
                # cada `_loop_one_router` roda em sua propria task.
                log.error("router_cycle_failed", unit=router.unit, error=str(exc))
            elapsed = time.monotonic() - started
            remaining = max(0.0, router.poll_interval - elapsed)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=remaining)
            except TimeoutError:
                continue

    async def run(self) -> None:
        tasks = [asyncio.create_task(self._loop_one_router(r)) for r in self._routers]
        try:
            await self._stop.wait()
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
