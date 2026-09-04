"""Entry point do daemon de teste de link por rota (Mikrotik).

Modulo irmao de collector/__main__.py -- processo/servico Swarm separado,
com seu proprio ciclo de vida. Reaproveita apenas collector/zabbix_sink.py
(generico o bastante: um ZabbixSink por host Zabbix de destino).

Ver 07-Propostas-Melhoria/2026-09-04_geral_monitoramento_links-wan-pbr-rotas-mikrotik.md
no repo Analise-TI-CCZaleski para o desenho completo (secoes 2-4).
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

from collector.zabbix_sink import Metric, ZabbixSink
from mikrotik.client import MikrotikClient
from mikrotik.config import GATEWAY_SENTINEL, RouterConfig, load_routers_from_path
from mikrotik.scheduler import FixedIntervalScheduler

structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ]
)
log = structlog.get_logger("mikrotik")

DEFAULT_CONFIG = Path("/etc/downdetector-collector/routers.yaml")


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="mikrotik-link-monitor")
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument("--zabbix-server", default=os.environ.get("ZABBIX_SERVER", "127.0.0.1"))
    ap.add_argument("--zabbix-port", type=int, default=int(os.environ.get("ZABBIX_PORT", "10051")))
    return ap.parse_args()


def _metric_suffix(link_name: str, target_label: str) -> str:
    # target_label pode ser IP, hostname, ou "gateway" (alvo dinamico) --
    # normaliza pra nao quebrar a chave Zabbix.
    return f"{link_name}.{target_label.replace(':', '_')}"


async def _run_router(router: RouterConfig, args: argparse.Namespace) -> None:
    sink = ZabbixSink(args.zabbix_server, args.zabbix_port, router.zabbix_host)
    client = MikrotikClient(router)
    metrics: list[Metric] = []
    any_link_ok = False

    for link in router.links:
        for target in link.targets:
            if target == GATEWAY_SENTINEL:
                resolved = await asyncio.to_thread(client.resolve_gateway, link)
                if resolved is None:
                    log.warning(
                        "gateway_resolve_skipped",
                        unit=router.unit,
                        link=link.name,
                    )
                    continue
                actual_target = resolved
                # chave Zabbix estavel ("gateway"), independente do IP CGNAT
                # mudar entre reconexoes PPPoE -- so o log mostra o IP real
                # resolvido nesta rodada.
                metric_label = "gateway"
            else:
                actual_target = target
                metric_label = target

            result = await asyncio.to_thread(client.ping_link, link, actual_target)
            suffix = _metric_suffix(link.name, metric_label)
            metrics.append((f"mikrotik.link.available[{suffix}]", 1 if result.ok else 0))
            metrics.append((f"mikrotik.link.loss_pct[{suffix}]", result.packet_loss_pct))
            if result.avg_rtt_ms is not None:
                metrics.append((f"mikrotik.link.rtt_ms[{suffix}]", result.avg_rtt_ms))
            any_link_ok = any_link_ok or result.ok
            log.info(
                "link_probe_done",
                unit=router.unit,
                link=link.name,
                target=actual_target,
                target_label=metric_label,
                ok=result.ok,
                rtt_ms=result.avg_rtt_ms,
                loss_pct=result.packet_loss_pct,
            )

    # Heartbeat sempre enviado, mesmo se todos os links falharem -- distingue
    # "link caido" (dado chegou, valor ruim) de "coletor quebrado" (dado nao
    # chega mais), mesmo padrao ja usado no template Downdetector.
    metrics.append(("mikrotik.collector_heartbeat", int(time.time())))
    if not any_link_ok and router.links:
        log.warning("router_all_links_down", unit=router.unit)

    try:
        await asyncio.to_thread(sink.send, metrics)
    except Exception as exc:
        log.error("sink_send_failed", unit=router.unit, error=str(exc))


async def run(args: argparse.Namespace) -> None:
    routers = load_routers_from_path(args.config)
    log.info("config_loaded", count=len(routers), path=str(args.config))

    scheduler = FixedIntervalScheduler(
        routers, lambda router: _run_router(router, args)
    )

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _handle_term() -> None:
        log.info("term_received_stopping")
        stop_event.set()
        scheduler.stop()

    loop.add_signal_handler(signal.SIGTERM, _handle_term)
    loop.add_signal_handler(signal.SIGINT, _handle_term)

    await scheduler.run()


def main() -> int:
    args = parse_args()
    asyncio.run(run(args))
    return 0


if __name__ == "__main__":
    sys.exit(main())
