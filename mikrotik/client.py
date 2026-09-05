"""Cliente sobre a API binaria do RouterOS (8728/8729) via librouteros.

IMPORTANTE -- pendencia de validacao em campo (ver Ponto em Aberto 6.2 e
secao 4.6 da proposta): o parsing do reply de `/ping` abaixo foi escrito
contra a documentacao publica do RouterOS/librouteros, sem um roteador real
acessivel via API no momento em que este modulo foi escrito (SSH/API ainda
desabilitados nas 3 unidades -- Ponto em Aberto 6.6). Testar
`ping_link()` contra o Frigorifico (v7, ja tem PBR em producao) assim que o
servico api-ssl for habilitado, antes de dar como pronto.
"""
from __future__ import annotations

import ipaddress
import re
import ssl
from dataclasses import dataclass

import structlog
from librouteros import connect
from librouteros.exceptions import LibRouterosError

from mikrotik.config import RouterConfig, LinkConfig

log = structlog.get_logger(__name__)

_RTT_RE = re.compile(r"(?:(\d+)ms)?(?:(\d+)us)?")


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def _to_float(value) -> float | None:
    """Converte campos do reply de /tool/traceroute (int, str tipo '21.1',
    ou vazio/None) em float. Nunca lanca -- retorna None se irreconhecivel."""
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_rtt_ms(time_str: str) -> float | None:
    """Converte o campo `time` do reply de /ping (ex.: '1ms200us', '3ms') em ms.

    Retorna None se o formato for irreconhecivel -- nao assume, so falha
    explicito (melhor um item UNSUPPORTED no Zabbix do que um numero errado).
    """
    match = _RTT_RE.fullmatch(time_str.strip())
    if not match or not any(match.groups()):
        return None
    ms = int(match.group(1)) if match.group(1) else 0
    us = int(match.group(2)) if match.group(2) else 0
    return ms + us / 1000


@dataclass(frozen=True)
class TracerouteHop:
    hop: int  # posicao dentro da secao, nao um campo real do RouterOS
    address: str | None  # None = hop nao respondeu (timeout)
    avg_rtt_ms: float | None
    loss_pct: float | None
    ok: bool  # True se o hop respondeu (tem endereco)


@dataclass(frozen=True)
class LinkPingResult:
    unit: str
    link_name: str
    target: str
    sent: int
    received: int
    packet_loss_pct: float
    avg_rtt_ms: float | None
    ok: bool
    error: str | None = None


class MikrotikClient:
    """Uma conexao API por roteador. Nao e thread-safe -- um MikrotikClient
    por RouterConfig, reaberta a cada ciclo (roteadores caem, a conexao TCP
    tem que ser descartavel)."""

    def __init__(self, router: RouterConfig, ping_count: int = 5, timeout_s: int = 10) -> None:
        self._router = router
        self._ping_count = ping_count
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
        ctx.verify_mode = ssl.CERT_NONE  # certificado autoassinado -- sem CA interna (ver secao 6 da proposta de NOC)
        return connect(
            username=self._router.username,
            password=self._router.password,
            host=self._router.host,
            port=self._router.api_port,
            ssl_wrapper=ctx.wrap_socket,
            timeout=self._timeout_s,
        )

    def resolve_gateway(self, link: LinkConfig) -> str | None:
        """Resolve o IP do gateway ATUAL do link, consultando a rota real em
        vez de confiar num IP fixo no routers.yaml.

        Necessario para links PPPoE/dinamicos (ex.: GloboInfo na Filial:
        gateway na faixa CGNAT 100.64.0.0/10, atribuido pelo provedor a cada
        negociacao PPPoE -- pode mudar). Dois casos, vistos na Filial real:

        1. `gateway` da rota ja e um IP (ex.: Brphonia, P2P fixo) -> usa direto.
        2. `gateway` da rota e um NOME DE INTERFACE (ex.: "pppoe-globoinfo",
           rota point-to-point) -> consulta `/interface/pppoe-client/monitor`
           dessa interface e pega o campo `remote-address` (o peer atual).

        Retorna None se nao conseguir resolver -- quem chama decide o que
        fazer (normalmente: pular esse alvo neste ciclo, nao travar o resto).
        """
        try:
            api = self._connect()
        except (LibRouterosError, OSError) as exc:
            log.warning(
                "mikrotik_gateway_resolve_connect_failed",
                unit=self._router.unit,
                link=link.name,
                error=str(exc),
            )
            return None

        try:
            # Busca tudo e filtra em Python -- mais robusto que depender da
            # sintaxe exata de filtro de campo da API (`?campo=valor` deu
            # "unknown parameter" em teste real contra RouterOS 6.49.10;
            # tabela de rotas e pequena, custo de trazer tudo e desprezivel.
            routes = [
                r for r in api("/ip/route/print")
                if r.get("routing-mark") == link.routing_table
                and r.get("dst-address") == "0.0.0.0/0"
            ]
            if not routes:
                log.warning(
                    "mikrotik_gateway_no_route",
                    unit=self._router.unit,
                    link=link.name,
                    routing_table=link.routing_table,
                )
                return None

            gateway = routes[0].get("gateway")
            if not gateway:
                return None
            if _is_ip(gateway):
                return gateway

            # gateway e nome de interface (PPPoE ou similar) -- resolver peer real
            monitor = list(
                api("/interface/pppoe-client/monitor", **{".id": gateway, "once": ""})
            )
            if not monitor:
                log.warning(
                    "mikrotik_gateway_monitor_empty",
                    unit=self._router.unit,
                    link=link.name,
                    interface=gateway,
                )
                return None
            remote = monitor[0].get("remote-address")
            if not remote or not _is_ip(remote):
                log.warning(
                    "mikrotik_gateway_monitor_no_remote_address",
                    unit=self._router.unit,
                    link=link.name,
                    interface=gateway,
                    monitor=monitor[0],
                )
                return None
            return remote
        except LibRouterosError as exc:
            log.warning(
                "mikrotik_gateway_resolve_failed",
                unit=self._router.unit,
                link=link.name,
                error=str(exc),
            )
            return None
        finally:
            try:
                api.close()
            except Exception:
                pass

    def ping_link(self, link: LinkConfig, target: str) -> LinkPingResult:
        """Roda /ping contra `target`, forcando a rota da tabela/mark do link.

        A API do RouterOS nao devolve um sumario pronto (isso so o REST v7
        faz) -- agrega-se aqui a partir das sentencas de reply individuais.
        """
        routing_param = self._router.routing_param()
        try:
            api = self._connect()
        except (LibRouterosError, OSError) as exc:
            log.warning(
                "mikrotik_connect_failed",
                unit=self._router.unit,
                link=link.name,
                error=str(exc),
            )
            return LinkPingResult(
                unit=self._router.unit,
                link_name=link.name,
                target=target,
                sent=0,
                received=0,
                packet_loss_pct=100.0,
                avg_rtt_ms=None,
                ok=False,
                error="connect_failed",
            )

        try:
            replies = list(
                api(
                    "/ping",
                    address=target,
                    count=str(self._ping_count),
                    **{routing_param: link.routing_table},
                )
            )
        except LibRouterosError as exc:
            log.warning(
                "mikrotik_ping_failed",
                unit=self._router.unit,
                link=link.name,
                target=target,
                error=str(exc),
            )
            return LinkPingResult(
                unit=self._router.unit,
                link_name=link.name,
                target=target,
                sent=self._ping_count,
                received=0,
                packet_loss_pct=100.0,
                avg_rtt_ms=None,
                ok=False,
                error="ping_command_failed",
            )
        finally:
            try:
                api.close()
            except Exception:
                pass

        rtts: list[float] = []
        for reply in replies:
            time_field = reply.get("time")
            if not time_field:
                continue
            rtt = _parse_rtt_ms(str(time_field))
            if rtt is not None:
                rtts.append(rtt)

        received = len(rtts)
        sent = self._ping_count
        loss_pct = round((sent - received) / sent * 100, 1) if sent else 100.0
        avg_rtt = round(sum(rtts) / len(rtts), 1) if rtts else None

        return LinkPingResult(
            unit=self._router.unit,
            link_name=link.name,
            target=target,
            sent=sent,
            received=received,
            packet_loss_pct=loss_pct,
            avg_rtt_ms=avg_rtt,
            ok=received > 0,
        )

    def traceroute_link(
        self, link: LinkConfig, target: str, count: int = 3, max_hops: int = 15
    ) -> list[TracerouteHop]:
        """Roda /tool/traceroute contra `target`, forcando a rota do link
        (mesmo mecanismo de ping_link -- routing_param).

        RouterOS agrupa replies por `.section` (uma rodada completa de
        hops por repeticao de `count`); dentro de uma secao, a ORDEM das
        linhas E o numero do hop (nao ha campo "hop" explicito). Usa-se a
        ULTIMA secao (rodada mais recente/completa) como fonte da tabela
        de hops. Confirmado contra a Filial real em 2026-09-04.
        """
        routing_param = self._router.routing_param()
        try:
            api = self._connect()
        except (LibRouterosError, OSError) as exc:
            log.warning(
                "mikrotik_traceroute_connect_failed",
                unit=self._router.unit, link=link.name, error=str(exc),
            )
            return []

        try:
            replies = list(
                api(
                    "/tool/traceroute",
                    address=target,
                    count=str(count),
                    **{routing_param: link.routing_table},
                )
            )
        except LibRouterosError as exc:
            log.warning(
                "mikrotik_traceroute_failed",
                unit=self._router.unit, link=link.name, target=target, error=str(exc),
            )
            return []
        finally:
            try:
                api.close()
            except Exception:
                pass

        if not replies:
            return []

        last_section = max((r.get(".section", 0) for r in replies), default=0)
        rows = [r for r in replies if r.get(".section") == last_section]

        hops: list[TracerouteHop] = []
        for i, row in enumerate(rows[:max_hops], start=1):
            address = row.get("address") or None
            hops.append(TracerouteHop(
                hop=i,
                address=address,
                avg_rtt_ms=_to_float(row.get("avg")),
                loss_pct=_to_float(row.get("loss")),
                ok=address is not None,
            ))
        return hops
