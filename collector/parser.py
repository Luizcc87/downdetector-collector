"""Parser puro para páginas de status do Downdetector.

Sem I/O. Recebe HTML, devolve ParseResult.

Marcadores reais (Next.js, capturado em 2026-05):
- Status: companyCurrentStatus em JSON escapado ("success" | "warning" | "danger")
  Fallback: border-[var(--color-dd-blue|yellow|red)] no card-company-status
- Reports: reportsValue no chartData (último datapoint) ou "peak of N reports"
- Name: companyName em JSON escapado
- company_id: companyId em JSON escapado
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import IntEnum
from typing import Optional


class Status(IntEnum):
    OK = 0
    WARNING = 1
    DANGER = 2
    UNKNOWN = 3


@dataclass(frozen=True)
class ParseResult:
    status: Status
    reports: Optional[int] = None
    name: Optional[str] = None
    company_id: Optional[int] = None
    error: Optional[str] = None


# JSON escapado embutido pelo Next.js SSR: companyCurrentStatus\":\"success\"
_STATUS_JSON_RE = re.compile(r'companyCurrentStatus\\+":\s*\\+"([a-z]+)')

# Fallback: classe Tailwind na div card-company-status
_STATUS_CSS_RE = re.compile(
    r'card-company-status[^>]*class="[^"]*border-\[var\(--color-dd-([a-z]+)\)\]'
)

_CSS_COLOR_TO_STATUS: dict[str, Status] = {
    "blue": Status.OK,
    "yellow": Status.WARNING,
    "red": Status.DANGER,
}

_JSON_VALUE_TO_STATUS: dict[str, Status] = {
    "success": Status.OK,
    "warning": Status.WARNING,
    "danger": Status.DANGER,
}

# Último reportsValue no chartData (série temporal, último ponto = mais recente)
_REPORTS_VALUE_RE = re.compile(r'reportsValue\\+":\s*(\d+)')

# Fallback: peak no aria-label do chart
_REPORTS_PEAK_RE = re.compile(r'peak of (\d+) reports', re.IGNORECASE)

# companyName no JSON escapado
_NAME_RE = re.compile(r'companyName\\+":\s*\\+"([^\\]+)')

# companyId no JSON escapado (valor numérico entre aspas ou sem)
_COMPANY_ID_RE = re.compile(r'companyId\\+":\s*\\+"(\d+)')


def _is_cloudflare_block(html: str) -> bool:
    # Use title-specific markers to avoid false positives on real pages that
    # embed challenge-platform scripts as optional browser verification
    title_markers = ["<title>Just a moment...</title>"]
    body_markers = ["cf-mitigated"]
    return any(m in html for m in title_markers) or any(m in html for m in body_markers)


# Página de bloqueio anti-scraping do Downdetector: vem com HTTP 200 mas
# conteúdo é "(╯°□°)╯︵ ┻━┻" + "429 Rate Limited" + texto sobre scraping.
# Página inteira tem ~248KB e título genérico "Downdetector".
_RATE_LIMIT_MARKERS = (
    "(╯°□°)╯︵ ┻━┻",
    "429 Rate Limited",
    "blocked from accessing",
)


def _is_rate_limited(html: str) -> bool:
    if not html:
        return False
    hits = sum(1 for m in _RATE_LIMIT_MARKERS if m in html)
    return hits >= 2  # dois marcadores reduzem falso-positivo


def _extract_status(html: str) -> Optional[Status]:
    # Primary: JSON SSR
    m = _STATUS_JSON_RE.search(html)
    if m:
        return _JSON_VALUE_TO_STATUS.get(m.group(1).lower())
    # Fallback: CSS class on company-status card
    # The class appears before the data-testid in the HTML, so we search differently
    m2 = re.search(
        r'(?:id="company-status"|data-testid="card-company-status")[^>]*'
        r'border-\[var\(--color-dd-([a-z]+)\)\]',
        html,
    )
    if m2:
        return _CSS_COLOR_TO_STATUS.get(m2.group(1))
    # Second fallback: look for the border class anywhere near the card
    m3 = _STATUS_CSS_RE.search(html)
    if m3:
        return _CSS_COLOR_TO_STATUS.get(m3.group(1))
    return None


def _extract_reports(html: str) -> Optional[int]:
    # Use last reportsValue from chartData time series
    all_values = _REPORTS_VALUE_RE.findall(html)
    if all_values:
        try:
            return int(all_values[-1])
        except (ValueError, IndexError):
            pass
    # Fallback: peak of N reports in aria-label
    m = _REPORTS_PEAK_RE.search(html)
    if m:
        try:
            return int(m.group(1))
        except (ValueError, IndexError):
            pass
    return None


def _extract_name(html: str) -> Optional[str]:
    m = _NAME_RE.search(html)
    if m:
        return m.group(1).strip()
    # Fallback: <title> tag, first word(s) before "down", "problems", "status"
    m2 = re.search(r'<title>([^<]+)</title>', html, re.IGNORECASE)
    if m2:
        title = m2.group(1)
        name_m = re.match(
            r'^([A-Za-z0-9 ._+\-]+?)\s+(?:down|problems?|status|issues?)',
            title,
            re.IGNORECASE,
        )
        if name_m:
            return name_m.group(1).strip()
    return None


def _extract_company_id(html: str) -> Optional[int]:
    m = _COMPANY_ID_RE.search(html)
    if m is None:
        return None
    try:
        return int(m.group(1))
    except (ValueError, IndexError):
        return None


def parse_status_page(html: str) -> ParseResult:
    if _is_cloudflare_block(html):
        return ParseResult(status=Status.UNKNOWN, error="cloudflare_block")
    if _is_rate_limited(html):
        return ParseResult(status=Status.UNKNOWN, error="rate_limited")
    status = _extract_status(html)
    if status is None:
        return ParseResult(status=Status.UNKNOWN, error="status_not_found")
    return ParseResult(
        status=status,
        reports=_extract_reports(html),
        name=_extract_name(html),
        company_id=_extract_company_id(html),
    )
