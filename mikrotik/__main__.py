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
from mikrotik.health import RouterHealthClient
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

# Estado de paginacao dos logs por unidade -- vive no processo, nao e
# persistido entre restarts do coletor (aceitavel: na pior hipotese perde-se
# o log do intervalo entre a queda e o restart, nao um dado critico de
# disponibilidade como o teste de link).
_last_log_id: dict[str, str | None] = {}

# Timestamp (monotonic) da ultima rodada de traceroute por unidade -- controla
# o intervalo maior (router.traceroute_interval_s), independente do
# poll_interval do ping. Tambem em memoria, mesmo raciocinio do log acima.
_last_traceroute_run: dict[str, float] = {}

TRACEROUTE_MAX_HOPS = 15


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


async def _collect_links(router: RouterConfig, client: MikrotikClient, metrics: list[Metric]) -> bool:
    any_link_ok = False
    for link in router.links:
        for target in link.targets:
            if target == GATEWAY_SENTINEL:
                resolved = await asyncio.to_thread(client.resolve_gateway, link)
                if resolved is None:
                    log.warning("gateway_resolve_skipped", unit=router.unit, link=link.name)
                    continue
                actual_target = resolved
                metric_label = "gateway"  # chave estavel -- ver mikrotik/config.py
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
                unit=router.unit, link=link.name, target=actual_target, target_label=metric_label,
                ok=result.ok, rtt_ms=result.avg_rtt_ms, loss_pct=result.packet_loss_pct,
            )
    return any_link_ok


async def _collect_traceroute(router: RouterConfig, client: MikrotikClient, metrics: list[Metric]) -> None:
    """Roda /tool/traceroute por link, num intervalo BEM maior que o ping
    (router.traceroute_interval_s) -- Fase 5 da proposta, "traceroute sob
    gatilho ou intervalo maior". MVP usa intervalo fixo (mais simples e
    robusto que decidir gatilho dinamico); intervalo tipico 15min evita
    sobrecarregar a CPU do roteador com hop-a-hop constante.

    Roda contra o primeiro target de cada link (normalmente a ancora
    publica 1.1.1.1) -- o objetivo aqui e comparar o CAMINHO entre links,
    nao repetir o teste de disponibilidade que o ping ja cobre.
    """
    last_run = _last_traceroute_run.get(router.unit, 0.0)
    if time.monotonic() - last_run < router.traceroute_interval_s:
        return
    _last_traceroute_run[router.unit] = time.monotonic()

    for link in router.links:
        if not link.targets:
            continue
        target = link.targets[0]
        hops = await asyncio.to_thread(client.traceroute_link, link, target, 3, TRACEROUTE_MAX_HOPS)
        for h in hops:
            metrics.append((f"mikrotik.traceroute.hop_address[{link.name},{h.hop}]", h.address or ""))
            if h.avg_rtt_ms is not None:
                metrics.append((f"mikrotik.traceroute.hop_rtt_ms[{link.name},{h.hop}]", h.avg_rtt_ms))
            if h.loss_pct is not None:
                metrics.append((f"mikrotik.traceroute.hop_loss_pct[{link.name},{h.hop}]", h.loss_pct))
        log.info(
            "traceroute_collected", unit=router.unit, link=link.name, target=target,
            hop_count=len(hops), last_hop=hops[-1].address if hops else None,
        )


async def _collect_health(router: RouterConfig, health: RouterHealthClient, metrics: list[Metric]) -> None:
    resource = await asyncio.to_thread(health.get_system_resource)
    if resource is not None:
        metrics.append(("mikrotik.system.cpu_load_pct", resource.cpu_load_pct))
        metrics.append(("mikrotik.system.free_memory_bytes", resource.free_memory_bytes))
        metrics.append(("mikrotik.system.total_memory_bytes", resource.total_memory_bytes))
        if resource.uptime_seconds is not None:
            metrics.append(("mikrotik.system.uptime_seconds", resource.uptime_seconds))
        log.info(
            "system_resource_collected", unit=router.unit,
            cpu_load_pct=resource.cpu_load_pct, free_memory_bytes=resource.free_memory_bytes,
        )
    else:
        log.warning("system_resource_skipped", unit=router.unit)

    if router.monitored_interfaces:
        traffic = await asyncio.to_thread(health.get_interface_traffic, router.monitored_interfaces)
        for t in traffic:
            metrics.append((f"mikrotik.interface.rx_bps[{t.name}]", t.rx_bps))
            metrics.append((f"mikrotik.interface.tx_bps[{t.name}]", t.tx_bps))
        log.info("interface_traffic_collected", unit=router.unit, count=len(traffic))

    tunnels = await asyncio.to_thread(health.get_vpn_tunnels)
    for tun in tunnels:
        metrics.append((f"mikrotik.vpn.tunnel_up[{tun.name}]", 1 if tun.up else 0))
    if tunnels:
        log.info(
            "vpn_tunnels_collected", unit=router.unit, count=len(tunnels),
            down=[t.name for t in tunnels if not t.up],
        )

    since_id = _last_log_id.get(router.unit)
    entries, new_since_id = await asyncio.to_thread(health.get_new_logs, since_id)
    _last_log_id[router.unit] = new_since_id
    for entry in entries:
        # item tipo Log no Zabbix -- valor e o texto, timestamp e "agora"
        # (o clock exato do roteador nao chega ao zabbix_sender sem usar o
        # protocolo trapper com -T, fora do escopo do ZabbixSink atual;
        # aceitavel, a ordem relativa entre entradas se mantem).
        metrics.append((f"mikrotik.log.entry", f"[{entry.topics}] {entry.message}"))
    if entries:
        log.info("log_entries_collected", unit=router.unit, count=len(entries))


async def _run_router(router: RouterConfig, args: argparse.Namespace) -> None:
    sink = ZabbixSink(args.zabbix_server, args.zabbix_port, router.zabbix_host)
    client = MikrotikClient(router)
    health = RouterHealthClient(router)
    metrics: list[Metric] = []

    any_link_ok = await _collect_links(router, client, metrics)
    await _collect_traceroute(router, client, metrics)
    await _collect_health(router, health, metrics)

    # Heartbeat sempre enviado, mesmo se tudo mais falhar -- distingue
    # "link/servico caido" (dado chegou, valor ruim) de "coletor quebrado"
    # (dado nao chega mais), mesmo padrao ja usado no template Downdetector.
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
