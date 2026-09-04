import asyncio

import pytest

from mikrotik.config import RouterConfig
from mikrotik.scheduler import FixedIntervalScheduler


def _router(unit: str, poll_interval: int = 0) -> RouterConfig:
    return RouterConfig(
        unit=unit,
        host="1.2.3.4",
        api_port=8729,
        use_ssl=True,
        username="u",
        password="p",
        branch="v7",
        zabbix_host="h",
        poll_interval=poll_interval,
        links=[],
    )


@pytest.mark.asyncio
async def test_runs_each_router_at_least_once():
    calls: list[str] = []

    async def run_router(router: RouterConfig) -> None:
        calls.append(router.unit)

    scheduler = FixedIntervalScheduler([_router("filial"), _router("matriz")], run_router)
    task = asyncio.create_task(scheduler.run())
    await asyncio.sleep(0.05)
    scheduler.stop()
    await task

    assert "filial" in calls
    assert "matriz" in calls


@pytest.mark.asyncio
async def test_failure_in_one_router_does_not_stop_others():
    calls: list[str] = []

    async def run_router(router: RouterConfig) -> None:
        calls.append(router.unit)
        if router.unit == "filial":
            raise RuntimeError("simulated failure")

    scheduler = FixedIntervalScheduler([_router("filial"), _router("matriz")], run_router)
    task = asyncio.create_task(scheduler.run())
    await asyncio.sleep(0.05)
    scheduler.stop()
    await task

    # matriz continua sendo chamado mesmo com filial falhando -- scheduler
    # nao propaga excecao de um roteador para o loop dos outros.
    assert "matriz" in calls


@pytest.mark.asyncio
async def test_failure_does_not_increase_interval():
    """Ao contrario do collector/scheduler.py (backoff exponencial), uma
    falha aqui nao deve fazer o roteador esperar mais que poll_interval."""
    calls: list[str] = []

    async def run_router(router: RouterConfig) -> None:
        calls.append(router.unit)
        raise RuntimeError("always fails")

    router = _router("filial", poll_interval=0)
    scheduler = FixedIntervalScheduler([router], run_router)
    task = asyncio.create_task(scheduler.run())
    await asyncio.sleep(0.05)
    scheduler.stop()
    await task

    # poll_interval=0 -- se houvesse backoff crescente, poucas chamadas
    # ocorreriam nesta janela; sem backoff, varias chamadas se acumulam.
    assert len(calls) > 2
