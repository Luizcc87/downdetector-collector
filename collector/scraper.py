"""Scraper que usa FlareSolverr para contornar Cloudflare."""
from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass
from typing import Optional

import httpx
import structlog

from collector.config import ServiceConfig
from collector.parser import ParseResult, Status, parse_status_page

log = structlog.get_logger(__name__)

JITTER_MIN_SECONDS = 0.2
JITTER_MAX_SECONDS = 0.8
DEFAULT_FLARESOLVERR_URL = "http://localhost:8191/v1"
DEFAULT_TIMEOUT_MS = 60_000


@dataclass
class ScrapeResult:
    slug: str
    parse: ParseResult
    http_status: Optional[int]
    duration_seconds: float
    cloudflare_blocked: bool


class Scraper:
    def __init__(
        self,
        flaresolverr_url: str = DEFAULT_FLARESOLVERR_URL,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ) -> None:
        self._url = flaresolverr_url
        self._timeout_ms = timeout_ms
        self._client: Optional[httpx.AsyncClient] = None
        self.browser_restarts = 0
        self.cloudflare_blocks_5m: list[float] = []

    async def start(self) -> None:
        # httpx timeout = (FlareSolverr timeout) + 10s buffer
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout((self._timeout_ms / 1000) + 10)
        )

    async def stop(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _record_block(self) -> None:
        now = time.time()
        self.cloudflare_blocks_5m.append(now)
        cutoff = now - 300
        self.cloudflare_blocks_5m = [t for t in self.cloudflare_blocks_5m if t >= cutoff]

    async def scrape(self, service: ServiceConfig) -> ScrapeResult:
        assert self._client is not None, "call start() first"
        await asyncio.sleep(random.uniform(JITTER_MIN_SECONDS, JITTER_MAX_SECONDS))
        started = time.monotonic()
        http_status: Optional[int] = None
        html = ""
        try:
            resp = await self._client.post(
                self._url,
                json={
                    "cmd": "request.get",
                    "url": service.url(),
                    "maxTimeout": self._timeout_ms,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            solution = data.get("solution") or {}
            html = solution.get("response", "") or ""
            http_status = solution.get("status")
        except httpx.TimeoutException:
            log.warning("scrape_timeout", slug=service.slug)
        except httpx.HTTPStatusError as exc:
            log.warning(
                "flaresolverr_http_error",
                slug=service.slug,
                status=exc.response.status_code,
            )
        except Exception as exc:
            log.exception("scrape_unexpected_error", slug=service.slug, error=str(exc))
        duration = time.monotonic() - started

        parse = parse_status_page(html) if html else ParseResult(
            status=Status.UNKNOWN, error="empty_html"
        )
        cloudflare_blocked = parse.error == "cloudflare_block" or (
            http_status is not None and http_status == 403
        )
        if cloudflare_blocked:
            self._record_block()
            log.warning("scrape_blocked", slug=service.slug, http_status=http_status)

        return ScrapeResult(
            slug=service.slug,
            parse=parse,
            http_status=http_status,
            duration_seconds=duration,
            cloudflare_blocked=cloudflare_blocked,
        )
