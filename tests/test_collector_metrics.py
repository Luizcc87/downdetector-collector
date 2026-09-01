import argparse

import pytest

from collector.__main__ import Collector
from collector.config import ServiceConfig
from collector.latency import LatencyResult
from collector.parser import ParseResult, Status
from collector.scraper import ScrapeResult


class FakeScraper:
    async def scrape(self, service):
        return ScrapeResult(
            slug=service.slug,
            parse=ParseResult(status=Status.OK, reports=42, name=service.name, company_id=1),
            http_status=200,
            duration_seconds=0.1,
            cloudflare_blocked=False,
        )


class FakeLatency:
    async def check(self, service):
        return LatencyResult(
            slug=service.slug,
            target_url=service.target_url,
            latency_ms=187,
            status_code=200,
            available=True,
        )


class FakeSink:
    def __init__(self):
        self.metrics = None

    def send(self, metrics):
        self.metrics = metrics


@pytest.mark.asyncio
async def test_collector_sends_latency_metric_with_scrape_batch():
    args = argparse.Namespace(
        flaresolverr_url="http://localhost:8191/v1",
        zabbix_server="127.0.0.1",
        zabbix_port=10051,
        zabbix_host_name="Downdetector",
    )
    collector = Collector(args)
    collector._scraper = FakeScraper()
    collector._latency = FakeLatency()
    collector._sink = FakeSink()
    service = ServiceConfig(
        name="Instagram",
        slug="instagram",
        id=1,
        logo="instagram.svg",
        poll_interval=60,
        country="br",
        target_url="https://www.instagram.com/",
    )

    await collector._on_scrape(service)

    assert ("downdetector.latency_ms[instagram]", 187) in collector._sink.metrics
