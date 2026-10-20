"""Metricas de saude do proprio roteador -- CPU, memoria, uptime, trafego
por porta, status de tuneis VPN e logs de evento.

Modulo separado de client.py (que so cuida do teste de link por rota):
responsabilidades diferentes, cada uma pode falhar sem derrubar a outra --
mesmo principio de isolamento ja usado entre mikrotik/ e collector/.

Todos os campos abaixo foram confirmados ao vivo contra a Filial
(192.168.42.2, RouterOS 6.49.10) em 2026-09-05, nao inferidos de doc.
"""
from __future__ import annotations

import re
import ssl
from dataclasses import dataclass

import structlog
from librouteros import connect
from librouteros.exceptions import LibRouterosError

from mikrotik.sessao import ConexaoDoCiclo
from mikrotik.config import RouterConfig

log = structlog.get_logger(__name__)

# Tipos de interface que representam tunel VPN site-to-site -- confirmado
# ao vivo: l2tp-in (4x na Filial), eoip (1x). l2tp-out/pptp/sstp incluidos
# por analogia (mesma familia de recurso RouterOS), nao testados ainda.
_VPN_TYPES = {"l2tp-in", "l2tp-out", "eoip", "pptp-in", "pptp-out", "sstp-in", "sstp-out"}

_UPTIME_RE = re.compile(r"(\d+)(w|d|h|m|s)")
_UPTIME_UNITS = {"w": 604800, "d": 86400, "h": 3600, "m": 60, "s": 1}


def _uptime_to_seconds(uptime: str) -> int | None:
    """Converte o formato de uptime do RouterOS ('11w4d4h59m11s') em segundos."""
    matches = _UPTIME_RE.findall(uptime)
    if not matches:
        return None
    return sum(int(n) * _UPTIME_UNITS[u] for n, u in matches)


@dataclass(frozen=True)
class SystemResource:
    cpu_load_pct: int
    free_memory_bytes: int
    total_memory_bytes: int
    uptime_seconds: int | None


@dataclass(frozen=True)
class InterfaceTraffic:
    name: str
    rx_bps: int
    tx_bps: int


@dataclass(frozen=True)
class VpnTunnel:
    name: str
    type: str
    up: bool


@dataclass(frozen=True)
class LogEntry:
    id: str
    topics: str
    message: str


class RouterHealthClient(ConexaoDoCiclo):
    """Mesma disciplina de mikrotik/client.py: dentro de sessao(), uma conexao
    para o ciclo inteiro; fora dela, uma por chamada. Nunca mantida aberta
    entre ciclos (roteador pode cair a qualquer momento)."""

    def __init__(self, router: RouterConfig, timeout_s: int = 10) -> None:
        self._router = router
        self._timeout_s = timeout_s

    def _connect(self):
        if not self._router.use_ssl:
            return connect(
                username=self._router.username,
                password=self._router.password,
                host=self._router.host,
                port=self._router.api_port,
                timeout=self._timeout_s,
            )
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return connect(
            username=self._router.username,
            password=self._router.password,
            host=self._router.host,
            port=self._router.api_port,
            ssl_wrapper=ctx.wrap_socket,
            timeout=self._timeout_s,
        )

    def get_system_resource(self) -> SystemResource | None:
        try:
            api = self._abrir()
        except (LibRouterosError, OSError) as exc:
            log.warning("mikrotik_health_connect_failed", unit=self._router.unit, error=str(exc))
            return None
        try:
            rows = list(api("/system/resource/print"))
            if not rows:
                return None
            r = rows[0]
            return SystemResource(
                cpu_load_pct=int(r.get("cpu-load", 0)),
                free_memory_bytes=int(r.get("free-memory", 0)),
                total_memory_bytes=int(r.get("total-memory", 0)),
                uptime_seconds=_uptime_to_seconds(str(r.get("uptime", ""))),
            )
        except LibRouterosError as exc:
            self._descartar_se_perdida(exc)
            log.warning("mikrotik_system_resource_failed", unit=self._router.unit, error=str(exc))
            return None
        finally:
            self._liberar(api)

    def get_interface_traffic(self, interfaces: list[str]) -> list[InterfaceTraffic]:
        if not interfaces:
            return []
        try:
            api = self._abrir()
        except (LibRouterosError, OSError) as exc:
            log.warning("mikrotik_health_connect_failed", unit=self._router.unit, error=str(exc))
            return []
        results: list[InterfaceTraffic] = []
        try:
            for iface in interfaces:
                try:
                    rows = list(api("/interface/monitor-traffic", **{"interface": iface, "once": ""}))
                except LibRouterosError as exc:
                    self._descartar_se_perdida(exc)
                    log.warning(
                        "mikrotik_interface_traffic_failed",
                        unit=self._router.unit, interface=iface, error=str(exc),
                    )
                    continue
                if not rows:
                    continue
                r = rows[0]
                results.append(InterfaceTraffic(
                    name=iface,
                    rx_bps=int(r.get("rx-bits-per-second", 0)),
                    tx_bps=int(r.get("tx-bits-per-second", 0)),
                ))
        finally:
            self._liberar(api)
        return results

    def get_vpn_tunnels(self) -> list[VpnTunnel]:
        try:
            api = self._abrir()
        except (LibRouterosError, OSError) as exc:
            log.warning("mikrotik_health_connect_failed", unit=self._router.unit, error=str(exc))
            return []
        try:
            rows = list(api("/interface/print"))
        except LibRouterosError as exc:
            self._descartar_se_perdida(exc)
            log.warning("mikrotik_vpn_tunnels_failed", unit=self._router.unit, error=str(exc))
            return []
        finally:
            self._liberar(api)

        tunnels = []
        for r in rows:
            if r.get("type") not in _VPN_TYPES:
                continue
            if r.get("disabled"):
                continue  # desativado de proposito -- nao e "tunel caido"
            name = r.get("name", "")
            tunnels.append(VpnTunnel(name=name.strip("<>"), type=r["type"], up=bool(r.get("running"))))
        return tunnels

    def get_new_logs(self, since_id: str | None, limit: int = 50) -> tuple[list[LogEntry], str | None]:
        """Retorna entradas novas desde `since_id` (exclusive) + o novo
        since_id (ultimo `.id` visto) para a proxima chamada.

        Primeira chamada (since_id=None) so marca a posicao atual como
        baseline -- nao inunda o Zabbix com o buffer de log inteiro do
        roteador na primeira execucao.
        """
        try:
            api = self._abrir()
        except (LibRouterosError, OSError) as exc:
            log.warning("mikrotik_health_connect_failed", unit=self._router.unit, error=str(exc))
            return [], since_id
        try:
            rows = list(api("/log/print"))
        except LibRouterosError as exc:
            self._descartar_se_perdida(exc)
            log.warning("mikrotik_log_print_failed", unit=self._router.unit, error=str(exc))
            return [], since_id
        finally:
            self._liberar(api)

        if not rows:
            return [], since_id

        if since_id is None:
            return [], rows[-1].get(".id")

        ids = [r.get(".id") for r in rows]
        try:
            idx = ids.index(since_id)
            new_rows = rows[idx + 1:]
        except ValueError:
            # since_id saiu do buffer (rotacionado desde o ultimo ciclo) --
            # nao da pra saber quanto foi perdido; pega so as ultimas
            # `limit` pra nao inundar o Zabbix de uma vez.
            new_rows = rows[-limit:]

        entries = [
            LogEntry(id=r.get(".id", ""), topics=r.get("topics", ""), message=r.get("message", ""))
            for r in new_rows
        ]
        return entries, rows[-1].get(".id")
