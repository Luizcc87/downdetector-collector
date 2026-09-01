"""Mede latência HTTP direta até o endereço oficial de cada serviço."""
from __future__ import annotations

from dataclasses import dataclass
from time import monotonic

import httpx
import structlog

from collector.config import ServiceConfig

log = structlog.get_logger(__name__)

DEFAULT_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class LatencyResult:
    slug: str
    target_url: str | None
    latency_ms: int | None
    status_code: int | None
    available: bool
    error: str | None = None


class LatencyChecker:
    def __init__(self, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        self._timeout_seconds = timeout_seconds
        self._client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        self._client = httpx.AsyncClient(
            timeout=self._timeout_seconds,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
        )

    async def stop(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def check(self, service: ServiceConfig) -> LatencyResult:
        if not service.target_url:
            return LatencyResult(
                slug=service.slug,
                target_url=None,
                latency_ms=None,
                status_code=None,
                available=False,
                error="target_url_missing",
            )

        assert self._client is not None, "call start() first"

        started = monotonic()
        try:
            response = await self._client.head(service.target_url, follow_redirects=True)
            if response.status_code in (403, 405):
                response = await self._client.get(service.target_url, follow_redirects=True)
        except httpx.HTTPError as exc:
            log.warning(
                "service_latency_failed",
                slug=service.slug,
                target_url=service.target_url,
                error=str(exc),
            )
            return LatencyResult(
                slug=service.slug,
                target_url=service.target_url,
                latency_ms=None,
                status_code=None,
                available=False,
                error=exc.__class__.__name__,
            )

        elapsed_ms = max(1, round((monotonic() - started) * 1000))
        return LatencyResult(
            slug=service.slug,
            target_url=service.target_url,
            latency_ms=elapsed_ms,
            status_code=response.status_code,
            available=response.status_code < 500,
        )
