"""Scraper único contra FlareSolverr (Chromium em Docker).

Antes tinha cloudscraper como primário, mas no nosso IP atual ele toma
403 do Cloudflare 100% das vezes — pura latência extra. Mantemos só o
FlareSolverr, que funciona com sessão warmada dentro do container.

Características:
- Rotação de User-Agent por request (pool de 7 navegadores modernos)
- Jitter de 2-5s entre scrapes pra imitar latência humana
- Detecta página 429 ("(╯°□°)╯︵ ┻━┻") e marca rate_limited
- httpx.AsyncClient persistente
"""
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

JITTER_MIN_SECONDS = 2.0
JITTER_MAX_SECONDS = 5.0
DEFAULT_FLARESOLVERR_URL = "http://localhost:8191/v1"
DEFAULT_TIMEOUT_MS = 60_000

USER_AGENTS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
)


@dataclass
class ScrapeResult:
    slug: str
    parse: ParseResult
    http_status: Optional[int]
    duration_seconds: float
    cloudflare_blocked: bool
    rate_limited: bool = False
    backend: str = "flaresolverr"


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
        self.rate_limits_5m: list[float] = []

    async def start(self) -> None:
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout((self._timeout_ms / 1000) + 10)
        )

    async def stop(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _record(self, bucket: list[float]) -> None:
        now = time.time()
        bucket.append(now)
        cutoff = now - 300
        bucket[:] = [t for t in bucket if t >= cutoff]

    async def scrape(self, service: ServiceConfig) -> ScrapeResult:
        assert self._client is not None, "call start() first"
        await asyncio.sleep(random.uniform(JITTER_MIN_SECONDS, JITTER_MAX_SECONDS))
        started = time.monotonic()
        ua = random.choice(USER_AGENTS)
        http_status: Optional[int] = None
        html = ""
        try:
            resp = await self._client.post(
                self._url,
                json={
                    "cmd": "request.get",
                    "url": service.url(),
                    "maxTimeout": self._timeout_ms,
                    "userAgent": ua,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            sol = data.get("solution") or {}
            html = sol.get("response", "") or ""
            http_status = sol.get("status")
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

        parse = (
            parse_status_page(html)
            if html
            else ParseResult(status=Status.UNKNOWN, error="empty_html")
        )
        cloudflare_blocked = parse.error == "cloudflare_block" or (
            http_status is not None and http_status == 403
        )
        rate_limited = parse.error == "rate_limited"
        if cloudflare_blocked:
            self._record(self.cloudflare_blocks_5m)
            log.warning("scrape_blocked", slug=service.slug, http_status=http_status)
        if rate_limited:
            self._record(self.rate_limits_5m)
            log.warning("scrape_rate_limited", slug=service.slug)

        return ScrapeResult(
            slug=service.slug,
            parse=parse,
            http_status=http_status,
            duration_seconds=duration,
            cloudflare_blocked=cloudflare_blocked,
            rate_limited=rate_limited,
            backend="flaresolverr",
        )
