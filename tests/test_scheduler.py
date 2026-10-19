import asyncio
import time
from dataclasses import dataclass

import pytest

from collector.config import ServiceConfig
from collector.scheduler import RateLimited, Scheduler


def make_service(slug: str, interval: int = 60) -> ServiceConfig:
    return ServiceConfig(
        name=slug.upper(), slug=slug, id=1, logo=f"{slug}.svg",
        poll_interval=interval, country="br",
    )


@pytest.mark.asyncio
async def test_scheduler_calls_scrape_for_each_service():
    services = [make_service("a"), make_service("b")]
    called = []

    async def fake_scrape(svc):
        called.append(svc.slug)

    sch = Scheduler(services, fake_scrape)
    task = asyncio.create_task(sch.run())
    await asyncio.sleep(0.5)
    sch.stop()
    await task
    assert "a" in called and "b" in called


@pytest.mark.asyncio
async def test_scheduler_respects_per_service_interval():
    services = [make_service("fast", interval=1), make_service("slow", interval=10)]
    called = []

    async def fake_scrape(svc):
        called.append((time.monotonic(), svc.slug))

    sch = Scheduler(services, fake_scrape)
    task = asyncio.create_task(sch.run())
    await asyncio.sleep(2.5)
    sch.stop()
    await task
    fast_count = sum(1 for _, s in called if s == "fast")
    slow_count = sum(1 for _, s in called if s == "slow")
    assert fast_count >= 2, f"fast should run at least twice in 2.5s, got {fast_count}"
    assert slow_count <= 2, f"slow should run at most twice, got {slow_count}"


@pytest.mark.asyncio
async def test_scheduler_backoff_on_failure():
    services = [make_service("flaky", interval=1)]
    call_times = []

    async def failing_scrape(svc):
        call_times.append(time.monotonic())
        raise RuntimeError("simulated cloudflare block")

    sch = Scheduler(services, failing_scrape, backoff_initial=2)
    task = asyncio.create_task(sch.run())
    await asyncio.sleep(3.5)
    sch.stop()
    await task
    # primeira chamada imediata, depois backoff de 2s — deve haver ~2 chamadas em 3.5s,
    # não ~3 que seria sem backoff
    assert 1 <= len(call_times) <= 2, f"got {len(call_times)} calls"


# --- Limite global (2026-10-19): o rate limit do Downdetector é por IP ---


@pytest.mark.asyncio
async def test_min_gap_espaca_consultas_entre_servicos():
    services = [make_service(s, interval=60) for s in ("a", "b", "c")]
    inicios = []

    async def fake_scrape(svc):
        inicios.append(time.monotonic())

    sch = Scheduler(services, fake_scrape, min_gap=0.4)
    task = asyncio.create_task(sch.run())
    await asyncio.sleep(1.1)
    sch.stop()
    await task
    assert len(inicios) == 3, f"3 serviços em ~0.8s com gap 0.4, got {len(inicios)}"
    gaps = [b - a for a, b in zip(inicios, inicios[1:])]
    assert all(g >= 0.38 for g in gaps), gaps


@pytest.mark.asyncio
async def test_rate_limited_pausa_todos_os_servicos():
    services = [make_service("bloq", interval=60), make_service("outro", interval=60)]
    chamadas = []

    async def fake_scrape(svc):
        chamadas.append((time.monotonic(), svc.slug))
        if svc.slug == "bloq" and len(chamadas) == 1:
            raise RateLimited("rate_limited")

    sch = Scheduler(services, fake_scrape, cooldown_initial=1.0)
    task = asyncio.create_task(sch.run())
    await asyncio.sleep(0.6)
    durante = list(chamadas)
    await asyncio.sleep(1.2)
    sch.stop()
    await task
    # Durante a pausa ninguém consulta (nem o serviço que não foi bloqueado).
    assert [s for _, s in durante] == ["bloq"], durante
    # Depois da pausa os dois voltam, inclusive o bloqueado (sem backoff individual longo).
    assert {s for _, s in chamadas[1:]} == {"bloq", "outro"}, chamadas


@pytest.mark.asyncio
async def test_pausa_dobra_com_bloqueios_seguidos_e_zera_ao_ter_sucesso():
    services = [make_service("x", interval=60)]
    resultados = iter([True, True, False])  # bloqueia, bloqueia, aceita
    pausas = []

    async def fake_scrape(svc):
        if next(resultados, False):
            raise RateLimited("rate_limited")

    sch = Scheduler(services, fake_scrape, cooldown_initial=0.2, cooldown_max=10)
    task = asyncio.create_task(sch.run())
    await asyncio.sleep(0.05)
    pausas.append(sch._cooldown)
    await asyncio.sleep(0.3)
    pausas.append(sch._cooldown)
    await asyncio.sleep(0.6)
    pausas.append(sch._cooldown)
    sch.stop()
    await task
    assert pausas == [0.2, 0.4, 0.0], pausas


@pytest.mark.asyncio
async def test_sem_cooldown_rate_limited_mantem_backoff_por_servico():
    services = [make_service("flaky", interval=1)]
    call_times = []

    async def scrape(svc):
        call_times.append(time.monotonic())
        raise RateLimited("rate_limited")

    sch = Scheduler(services, scrape, backoff_initial=2)
    task = asyncio.create_task(sch.run())
    await asyncio.sleep(3.5)
    sch.stop()
    await task
    assert 1 <= len(call_times) <= 2, f"got {len(call_times)} calls"
