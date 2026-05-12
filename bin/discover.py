"""One-shot: descobre IDs e nomes do Downdetector dado um slug.

Uso:
  python bin/discover.py --slug nubank --country br
  python bin/discover.py --slugs-file slugs.txt
  python bin/discover.py --candidates banco-itau,bradesco,santander
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import structlog
import yaml

from collector.config import ServiceConfig
from collector.parser import Status
from collector.scraper import Scraper

structlog.configure(processors=[structlog.processors.KeyValueRenderer()])
log = structlog.get_logger("discover")


def _slug_to_logo(slug: str) -> str:
    return f"{slug.replace('-', '_')}.svg"


async def _discover_one(scraper: Scraper, slug: str, country: str) -> dict:
    fake_cfg = ServiceConfig(
        name=slug, slug=slug, id=0, logo=_slug_to_logo(slug),
        poll_interval=60, country=country,
    )
    result = await scraper.scrape(fake_cfg)
    if result.parse.status == Status.UNKNOWN:
        return {"slug": slug, "error": result.parse.error or "unknown"}
    return {
        "name": result.parse.name or slug,
        "slug": slug,
        "id": result.parse.company_id or 0,
        "logo": _slug_to_logo(slug),
        "country": country,
    }


async def _main_async(slugs: list[str], country: str) -> None:
    scraper = Scraper()
    await scraper.start()
    try:
        out_list = []
        for slug in slugs:
            log.info("discovering", slug=slug)
            entry = await _discover_one(scraper, slug, country)
            if "error" in entry:
                log.warning("discovery_failed", **entry)
                continue
            out_list.append(entry)
        yaml.safe_dump({"services": out_list}, sys.stdout, sort_keys=False, allow_unicode=True)
    finally:
        await scraper.stop()


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--slug", help="Single slug to discover")
    g.add_argument("--slugs-file", type=Path, help="File with one slug per line")
    g.add_argument("--candidates", help="Comma-separated slugs to probe")
    ap.add_argument("--country", default="br", choices=["br", "com"])
    args = ap.parse_args()

    if args.slug:
        slugs = [args.slug]
    elif args.slugs_file:
        slugs = [s.strip() for s in args.slugs_file.read_text().splitlines() if s.strip()]
    else:
        slugs = [s.strip() for s in args.candidates.split(",") if s.strip()]

    asyncio.run(_main_async(slugs, args.country))
    return 0


if __name__ == "__main__":
    sys.exit(main())
