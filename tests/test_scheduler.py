import asyncio
import time
from dataclasses import dataclass

import pytest

from collector.config import ServiceConfig
from collector.scheduler import Scheduler


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
