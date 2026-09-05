#!/usr/bin/env python3
"""Provisiona no Zabbix os items necessarios para o modulo mikrotik/ de uma
unidade -- grupo de host, host, e todos os items (link, sistema, trafego,
VPN, log). Idempotente: nao recria o que ja existe.

Consolida em ferramenta reutilizavel os scripts descartaveis usados
manualmente durante a implantacao real da Filial em 2026-09-04/05
(setup_zabbix_mikrotik.py, fix_zabbix_gateway_items.py,
setup_zabbix_health_items.py) -- ver
09-Operacao-Infraestrutura/guias/geral_guia-mikrotik-zabbix-monitoramento.md
no repo Analise-TI-CCZaleski para o passo a passo completo de onboarding.

Uso (dentro da rede do Swarm, ou com ZABBIX_API_URL apontando pro Zabbix):

    ZBX_TOKEN=<token da API do Zabbix> \\
        python bin/provision-zabbix-mikrotik.py --config config/routers.yaml --unit filial

Os tuneis VPN sao descobertos AO VIVO no roteador (via RouterHealthClient),
nao precisam estar listados em routers.yaml.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mikrotik.config import GATEWAY_SENTINEL, load_routers_from_path
from mikrotik.health import RouterHealthClient

ZABBIX_API_URL = os.environ.get("ZABBIX_API_URL", "http://zabbix-web:8080/api_jsonrpc.php")
GROUP_NAME = "Rede/Mikrotik"
# Mesmo valor de mikrotik/__main__.py:TRACEROUTE_MAX_HOPS -- se um mudar, o
# outro tem que acompanhar (nao importado direto pra nao acoplar o script
# de provisionamento ao runtime do coletor).
TRACEROUTE_MAX_HOPS = 15


def call(token: str, method: str, params: dict):
    body = json.dumps({"jsonrpc": "2.0", "method": method, "params": params, "id": 1}).encode()
    req = urllib.request.Request(
        ZABBIX_API_URL, data=body,
        headers={"Content-Type": "application/json-rpc", "Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        result = json.loads(resp.read())
    if "error" in result:
        raise RuntimeError(f"{method} failed: {result['error']}")
    return result["result"]


def ensure_group(token: str) -> str:
    existing = call(token, "hostgroup.get", {"filter": {"name": [GROUP_NAME]}})
    if existing:
        return existing[0]["groupid"]
    return call(token, "hostgroup.create", {"name": GROUP_NAME})["groupids"][0]


def ensure_host(token: str, group_id: str, host_name: str) -> str:
    existing = call(token, "host.get", {"filter": {"host": [host_name]}})
    if existing:
        return existing[0]["hostid"]
    created = call(token, "host.create", {
        "host": host_name, "name": host_name,
        "groups": [{"groupid": group_id}], "interfaces": [], "status": 0,
    })
    return created["hostids"][0]


def ensure_item(token: str, host_id: str, key: str, name: str, value_type: int, units: str | None = None) -> None:
    existing = call(token, "item.get", {"hostids": [host_id], "filter": {"key_": key}})
    if existing:
        print(f"  ja existe: {key}")
        return
    params = {
        "hostid": host_id, "name": name, "key_": key,
        "type": 2,  # Zabbix trapper
        "value_type": value_type, "history": "31d",
    }
    if units:
        params["units"] = units
    if value_type in (0, 3):
        params["trends"] = "365d"
    call(token, "item.create", params)
    print(f"  criado: {key}")


def link_suffix(link_name: str, target: str) -> str:
    label = "gateway" if target == GATEWAY_SENTINEL else target
    return f"{link_name}.{label.replace(':', '_')}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--unit", required=True, help="unit do routers.yaml a provisionar (ex.: filial)")
    args = ap.parse_args()

    token = os.environ.get("ZBX_TOKEN")
    if not token:
        print("ZBX_TOKEN nao definido -- gere um token de API no Zabbix (Users > API tokens)", file=sys.stderr)
        return 1

    routers = {r.unit: r for r in load_routers_from_path(args.config)}
    if args.unit not in routers:
        print(f"unidade {args.unit!r} nao encontrada em {args.config} (disponiveis: {list(routers)})", file=sys.stderr)
        return 1
    router = routers[args.unit]

    group_id = ensure_group(token)
    print(f"Grupo '{GROUP_NAME}': {group_id}")
    host_id = ensure_host(token, group_id, router.zabbix_host)
    print(f"Host '{router.zabbix_host}': {host_id}")

    print("\n-- Items de link --")
    for link in router.links:
        for target in link.targets:
            s = link_suffix(link.name, target)
            label = "gateway" if target == GATEWAY_SENTINEL else target
            ensure_item(token, host_id, f"mikrotik.link.available[{s}]", f"Link {link.name} disponivel ({label})", 3)
            ensure_item(token, host_id, f"mikrotik.link.loss_pct[{s}]", f"Link {link.name} perda % ({label})", 0)
            ensure_item(token, host_id, f"mikrotik.link.rtt_ms[{s}]", f"Link {link.name} RTT ms ({label})", 0)

    print("\n-- Items de sistema --")
    ensure_item(token, host_id, "mikrotik.collector_heartbeat", "Heartbeat do coletor mikrotik/", 3)
    ensure_item(token, host_id, "mikrotik.system.cpu_load_pct", "CPU load (%)", 3, "%")
    ensure_item(token, host_id, "mikrotik.system.free_memory_bytes", "Memoria livre (bytes)", 3, "B")
    ensure_item(token, host_id, "mikrotik.system.total_memory_bytes", "Memoria total (bytes)", 3, "B")
    ensure_item(token, host_id, "mikrotik.system.uptime_seconds", "Uptime (segundos)", 3, "uptime")
    # value_type=1 (Text), NAO 2 (Log) -- o plugin Zabbix do Grafana nao
    # retorna historico de items tipo Log via query "Metrics" (confirmado
    # em campo em 2026-09-05, ver mikrotik/README.md).
    ensure_item(token, host_id, "mikrotik.log.entry", "Log de eventos do roteador", 1)

    if router.monitored_interfaces:
        print("\n-- Items de trafego por porta --")
        for iface in router.monitored_interfaces:
            ensure_item(token, host_id, f"mikrotik.interface.rx_bps[{iface}]", f"Trafego RX {iface} (bps)", 3, "bps")
            ensure_item(token, host_id, f"mikrotik.interface.tx_bps[{iface}]", f"Trafego TX {iface} (bps)", 3, "bps")

    print("\n-- Items de traceroute (comparacao de rota por link) --")
    for link in router.links:
        for hop in range(1, TRACEROUTE_MAX_HOPS + 1):
            ensure_item(token, host_id, f"mikrotik.traceroute.hop_address[{link.name},{hop}]", f"Traceroute {link.name} hop {hop} -- endereco", 1)
            ensure_item(token, host_id, f"mikrotik.traceroute.hop_rtt_ms[{link.name},{hop}]", f"Traceroute {link.name} hop {hop} -- RTT (ms)", 0, "ms")
            ensure_item(token, host_id, f"mikrotik.traceroute.hop_loss_pct[{link.name},{hop}]", f"Traceroute {link.name} hop {hop} -- perda (%)", 0, "%")

    print("\n-- Items de VPN (descoberta ao vivo no roteador) --")
    health = RouterHealthClient(router)
    tunnels = health.get_vpn_tunnels()
    if not tunnels:
        print("  nenhum tunel encontrado (ou roteador inacessivel neste momento -- rodar de novo depois)")
    for tun in tunnels:
        ensure_item(token, host_id, f"mikrotik.vpn.tunnel_up[{tun.name}]", f"Tunel VPN ativo: {tun.name}", 3)

    print("\nOK -- provisionamento concluido.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
