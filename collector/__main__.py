"""Entry point do daemon downdetector-collector.

Carrega config, instancia Scraper/Scheduler/Sink, conecta tudo e roda.
Reage a SIGHUP recarregando services.yaml.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import signal
import sys
import time
from pathlib import Path

import structlog

from collector.config import ServiceConfig, load_services_from_path
from collector.health import HealthState
from collector.latency import LatencyChecker
from collector.scheduler import Scheduler
from collector.scraper import ScrapeResult, Scraper
from collector.zabbix_sink import Metric, ZabbixSink

# Estrutura de logs JSON
structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ]
)
log = structlog.get_logger("collector")

DEFAULT_CONFIG = Path("/etc/downdetector-collector/services.yaml")
DEFAULT_ZABBIX_HOST_NAME = "Downdetector"
HEALTH_PUSH_INTERVAL = 60  # segundos
META_PUSH_EVERY_N_SCRAPES = 20  # name/company_id raramente mudam


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="downdetector-collector")
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument(
        "--flaresolverr-url",
        default=os.environ.get("FLARESOLVERR_URL", "http://localhost:8191/v1"),
    )
    ap.add_argument("--zabbix-server", default=os.environ.get("ZABBIX_SERVER", "127.0.0.1"))
    ap.add_argument("--zabbix-port", type=int, default=int(os.environ.get("ZABBIX_PORT", "10051")))
    ap.add_argument("--zabbix-host-name", default=DEFAULT_ZABBIX_HOST_NAME)
    return ap.parse_args()


class Collector:
    def __init__(self, args: argparse.Namespace) -> None:
        self._args = args
        self._services: list[ServiceConfig] = []
        self._scraper = Scraper(args.flaresolverr_url)
        self._latency = LatencyChecker()
        self._sink = ZabbixSink(args.zabbix_server, args.zabbix_port, args.zabbix_host_name)
        self._health = HealthState()
        self._scheduler: Scheduler | None = None
        self._scrape_counts: dict[str, int] = {}
        self._stop_event = asyncio.Event()

    def _load_config(self) -> None:
        self._services = load_services_from_path(self._args.config)
        log.info("config_loaded", count=len(self._services), path=str(self._args.config))

    async def _on_scrape(self, service: ServiceConfig) -> None:
        result: ScrapeResult = await self._scraper.scrape(service)
        self._health.record_cycle_duration(result.duration_seconds)
        if result.cloudflare_blocked:
            self._health.record_block()
            raise RuntimeError("cloudflare_blocked")  # triggers scheduler backoff
        if result.rate_limited:
            # Não envia métrica nessa iteração (não sobrescrever último valor bom
            # com UNKNOWN). Backoff exponencial do scheduler assume.
            self._health.record_block()
            raise RuntimeError("rate_limited")
        metrics: list[Metric] = [
            (f"downdetector.status[{service.slug}]", int(result.parse.status)),
            (f"downdetector.last_check[{service.slug}]", int(time.time())),
        ]
        if result.parse.reports is not None:
            metrics.append((f"downdetector.reports[{service.slug}]", result.parse.reports))
        latency = await self._latency.check(service)
        if latency.latency_ms is not None:
            metrics.append((f"downdetector.latency_ms[{service.slug}]", latency.latency_ms))
        # name e company_id raramente mudam — envia a cada N
        count = self._scrape_counts.get(service.slug, 0) + 1
        self._scrape_counts[service.slug] = count
        if count == 1 or count % META_PUSH_EVERY_N_SCRAPES == 0:
            if result.parse.name:
                metrics.append((f"downdetector.name[{service.slug}]", result.parse.name))
            if result.parse.company_id:
                metrics.append((f"downdetector.company_id[{service.slug}]", result.parse.company_id))
            if service.logo:
                metrics.append((f"downdetector.logo[{service.slug}]", service.logo))
        try:
            await asyncio.to_thread(self._sink.send, metrics)
        except Exception as exc:
            log.error("sink_send_failed", slug=service.slug, error=str(exc))

    async def _health_pusher(self) -> None:
        while not self._stop_event.is_set():
            try:
                # propaga restarts do scraper para o health
                self._health.browser_restarts = self._scraper.browser_restarts
                await asyncio.to_thread(self._sink.send, self._health.as_metrics())
            except Exception as exc:
                log.error("health_push_failed", error=str(exc))
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=HEALTH_PUSH_INTERVAL)
            except asyncio.TimeoutError:
                continue

    def _install_signal_handlers(self, loop: asyncio.AbstractEventLoop) -> None:
        def _handle_sighup() -> None:
            log.info("sighup_received_reloading_config")
            try:
                self._load_config()
                if self._scheduler is not None:
                    self._scheduler.stop()
                # Scheduler será recriado no loop principal
            except Exception as exc:
                log.error("config_reload_failed", error=str(exc))

        def _handle_term() -> None:
            log.info("term_received_stopping")
            self._stop_event.set()
            if self._scheduler is not None:
                self._scheduler.stop()

        loop.add_signal_handler(signal.SIGHUP, _handle_sighup)
        loop.add_signal_handler(signal.SIGTERM, _handle_term)
        loop.add_signal_handler(signal.SIGINT, _handle_term)

    async def run(self) -> None:
        self._load_config()
        await self._scraper.start()
        await self._latency.start()
        loop = asyncio.get_running_loop()
        self._install_signal_handlers(loop)
        health_task = asyncio.create_task(self._health_pusher())
        try:
            while not self._stop_event.is_set():
                self._scheduler = Scheduler(
                    self._services, self._on_scrape,
                    backoff_initial=300.0, backoff_max=7200.0,
                )
                await self._scheduler.run()
                # Scheduler.run() só retorna em SIGHUP (recarrega config) ou stop;
                # se stop_event setado, sai do loop; senão, recria scheduler com nova lista.
        finally:
            self._stop_event.set()
            health_task.cancel()
            await asyncio.gather(health_task, return_exceptions=True)
            await self._scraper.stop()
            await self._latency.stop()


def main() -> int:
    args = parse_args()
    collector = Collector(args)
    asyncio.run(collector.run())
    return 0


if __name__ == "__main__":
    sys.exit(main())
