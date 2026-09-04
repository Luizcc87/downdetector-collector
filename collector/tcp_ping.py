"""Mede latencia TCP (connect ping) ate o host oficial de cada servico.

Usa asyncio.open_connection -- sem dependencias externas.
Complementa a latencia HTTP ao medir a camada de rede pura (sem TLS/HTTP overhead).
"""
from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from urllib.parse import urlparse
import asyncio

import structlog

from collector.config import ServiceConfig

log = structlog.get_logger(__name__)

DEFAULT_TIMEOUT_SECONDS = 5.0
DEFAULT_PORT = 443


@dataclass(frozen=True)
class TcpPingResult:
    slug: str
    host: str | None
    port: int
    tcp_ping_ms: int | None  # None = falha/timeout
    available: bool
    error: str | None = None


def _resolve_host_port(service: ServiceConfig) -> tuple[str | None, int]:
    """Extrai (host, port) da target_url ou usa ping_host configurado."""
    if service.ping_host:
        return service.ping_host, DEFAULT_PORT

    if not service.target_url:
        return None, DEFAULT_PORT

    parsed = urlparse(service.target_url)
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return host, port


class TcpPingChecker:
    """Realiza TCP connect ping assincrono para cada servico."""

    def __init__(self, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        self._timeout_seconds = timeout_seconds

    async def check(self, service: ServiceConfig) -> TcpPingResult:
        host, port = _resolve_host_port(service)

        if not host:
            return TcpPingResult(
                slug=service.slug,
                host=None,
                port=port,
                tcp_ping_ms=None,
                available=False,
                error="no_host",
            )

        started = monotonic()
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=self._timeout_seconds,
            )
            elapsed_ms = max(1, round((monotonic() - started) * 1000))
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            return TcpPingResult(
                slug=service.slug,
                host=host,
                port=port,
                tcp_ping_ms=elapsed_ms,
                available=True,
            )
        except asyncio.TimeoutError:
            log.warning(
                "tcp_ping_timeout",
                slug=service.slug,
                host=host,
                port=port,
                timeout=self._timeout_seconds,
            )
            return TcpPingResult(
                slug=service.slug,
                host=host,
                port=port,
                tcp_ping_ms=None,
                available=False,
                error="timeout",
            )
        except OSError as exc:
            log.warning(
                "tcp_ping_failed",
                slug=service.slug,
                host=host,
                port=port,
                error=str(exc),
            )
            return TcpPingResult(
                slug=service.slug,
                host=host,
                port=port,
                tcp_ping_ms=None,
                available=False,
                error=exc.__class__.__name__,
            )