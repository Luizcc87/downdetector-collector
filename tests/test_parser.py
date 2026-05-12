from __future__ import annotations

from pathlib import Path

import pytest

from collector.parser import ParseResult, Status, parse_status_page

FIXTURES = Path(__file__).parent / "fixtures"


def _read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_success_status():
    html = _read_fixture("downdetector_ok.html")
    result = parse_status_page(html)
    assert isinstance(result, ParseResult)
    assert result.status == Status.OK


def test_parse_warning_status():
    html = _read_fixture("downdetector_warning.html")
    result = parse_status_page(html)
    assert result.status == Status.WARNING


def test_parse_cloudflare_block_returns_unknown():
    html = _read_fixture("downdetector_blocked.html")
    result = parse_status_page(html)
    assert result.status == Status.UNKNOWN
    assert result.error == "cloudflare_block"


def test_parse_extracts_reports_count():
    """Reports count must be extracted from the page when available."""
    html = _read_fixture("downdetector_warning.html")
    result = parse_status_page(html)
    # warning fixture has real dd-yellow status, so reports must be present
    if result.status != Status.OK:
        assert result.reports is not None
        assert result.reports >= 0


def test_parse_extracts_name_and_company_id():
    html = _read_fixture("downdetector_ok.html")
    result = parse_status_page(html)
    assert result.name is not None and len(result.name) > 0
    assert result.company_id is not None and result.company_id > 0
