"""Bulk discovery: testa muitos slugs candidatos via FlareSolverr,
baixa logo PNG real (og:image) e gera services.yaml.

Uso:
  python3 bin/bulk_discover.py            # roda tudo
  python3 bin/bulk_discover.py --dry-run  # só testa, não baixa nem grava
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path

import httpx
import yaml

FLARESOLVERR_URL = "http://127.0.0.1:8191/v1"
LOGO_DIR = Path("/usr/share/grafana/public/img/downdetector")
SERVICES_YAML = Path("/etc/downdetector-collector/services.yaml")
CONCURRENCY = 3
TIMEOUT_MS = 60_000
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# (slug, country, friendly_name)
# country='com' ou 'com.br'. Vou tentar primeiro o que está aqui, e se UNKNOWN, tentar o outro.
CANDIDATES: list[tuple[str, str, str]] = [
    # já temos: google, cloudflare, whatsapp
    ("google", "com", "Google"),
    ("cloudflare", "com", "Cloudflare"),
    ("whatsapp", "com", "WhatsApp"),
    # Bancos / fintechs BR
    ("nubank", "com.br", "Nubank"),
    ("banco-do-brasil", "com.br", "Banco do Brasil"),
    ("bradesco", "com.br", "Bradesco"),
    ("itau", "com.br", "Itaú"),
    ("caixa", "com.br", "Caixa"),
    ("santander", "com.br", "Santander"),
    ("inter", "com.br", "Banco Inter"),
    ("c6-bank", "com.br", "C6 Bank"),
    ("banco-pan", "com.br", "Banco Pan"),
    ("banco-original", "com.br", "Banco Original"),
    ("banco-bv", "com.br", "Banco BV"),
    ("will-bank", "com.br", "Will Bank"),
    ("picpay", "com.br", "PicPay"),
    ("pagseguro", "com.br", "PagSeguro"),
    ("mercado-pago", "com.br", "Mercado Pago"),
    ("sicoob", "com.br", "Sicoob"),
    ("sicredi", "com.br", "Sicredi"),
    ("safra", "com.br", "Safra"),
    # Redes sociais
    ("facebook", "com", "Facebook"),
    ("instagram", "com", "Instagram"),
    ("twitter", "com", "Twitter (X)"),
    ("tiktok", "com", "TikTok"),
    ("linkedin", "com", "LinkedIn"),
    ("snapchat", "com", "Snapchat"),
    ("threads", "com", "Threads"),
    ("reddit", "com", "Reddit"),
    ("discord", "com", "Discord"),
    ("telegram", "com", "Telegram"),
    ("pinterest", "com", "Pinterest"),
    # Streaming
    ("youtube", "com", "YouTube"),
    ("netflix", "com", "Netflix"),
    ("spotify", "com", "Spotify"),
    ("amazon-prime-video", "com", "Prime Video"),
    ("disney-plus", "com", "Disney+"),
    ("hbo-max", "com", "HBO Max"),
    ("max", "com", "Max"),
    ("globoplay", "com.br", "Globoplay"),
    ("twitch", "com", "Twitch"),
    ("apple-music", "com", "Apple Music"),
    ("deezer", "com", "Deezer"),
    # Marketplace BR/global
    ("mercado-livre", "com.br", "Mercado Livre"),
    ("amazon", "com", "Amazon"),
    ("shopee", "com.br", "Shopee"),
    ("magazine-luiza", "com.br", "Magalu"),
    ("americanas", "com.br", "Americanas"),
    ("casas-bahia", "com.br", "Casas Bahia"),
    ("kabum", "com.br", "KaBuM!"),
    ("aliexpress", "com", "AliExpress"),
    # AI
    ("chatgpt", "com", "ChatGPT"),
    ("claude", "com", "Claude"),
    ("anthropic-claude", "com", "Claude"),
    ("microsoft-copilot", "com", "Copilot"),
    ("gemini", "com", "Gemini"),
    ("perplexity", "com", "Perplexity"),
    # Outros essenciais
    ("gmail", "com", "Gmail"),
    ("outlook", "com", "Outlook"),
    ("microsoft-365", "com", "Microsoft 365"),
    ("github", "com", "GitHub"),
    ("ifood", "com.br", "iFood"),
    ("uber", "com", "Uber"),
    ("99-app", "com.br", "99"),
    ("steam", "com", "Steam"),
    ("playstation-network", "com", "PlayStation Network"),
    ("xbox-live", "com", "Xbox Live"),
    # Telecom BR
    ("claro", "com.br", "Claro"),
    ("vivo", "com.br", "Vivo"),
    ("oi", "com.br", "Oi"),
    ("tim", "com.br", "Tim"),
]


def _url_for(slug: str, country: str) -> str:
    if country == "com":
        return f"https://downdetector.com/status/{slug}/"
    return f"https://downdetector.{country}/status/{slug}/"


# JSON vem escapado dentro do SSR: \"companyName\":\"X\"
_RE_NAME = re.compile(r'companyName\\+":\s*\\+"([^\\]+)')
_RE_ID = re.compile(r'companyId\\+":\s*\\+"(\d+)')
_RE_OG = re.compile(r'<meta\s+property="og:image"[^>]+content="([^"]+)"')
_RE_TITLE_BLOCK = re.compile(r"<title>([^<]+)</title>", re.IGNORECASE)


async def _flare_get(client: httpx.AsyncClient, url: str) -> str:
    r = await client.post(
        FLARESOLVERR_URL,
        json={"cmd": "request.get", "url": url, "maxTimeout": TIMEOUT_MS},
    )
    r.raise_for_status()
    sol = r.json().get("solution", {}) or {}
    return sol.get("response", "") or ""


async def _discover_one(
    client: httpx.AsyncClient, slug: str, country: str, friendly: str
) -> dict | None:
    url = _url_for(slug, country)
    try:
        html = await _flare_get(client, url)
    except Exception as exc:  # noqa: BLE001
        print(f"  [error] {slug}: {exc}", file=sys.stderr)
        return None
    title = (_RE_TITLE_BLOCK.search(html) or [None, ""])[1]
    if "Just a moment" in title:
        print(f"  [cf-block] {slug}", file=sys.stderr)
        return None
    name_m = _RE_NAME.search(html)
    id_m = _RE_ID.search(html)
    og_m = _RE_OG.search(html)
    if not name_m or not id_m:
        print(f"  [no-ssr] {slug} ({country})", file=sys.stderr)
        return None
    return {
        "name": friendly or name_m.group(1),
        "slug": slug,
        "id": int(id_m.group(1)),
        "country": country,
        "og_image": og_m.group(1) if og_m else None,
    }


async def _download_logo(
    client: httpx.AsyncClient, slug: str, url: str
) -> str | None:
    """Baixa PNG e salva em LOGO_DIR/{slug}.png; retorna caminho relativo servido."""
    try:
        r = await client.get(
            url,
            headers={
                "User-Agent": UA,
                "Referer": "https://downdetector.com/",
                "Accept": "image/avif,image/webp,*/*",
            },
            timeout=30,
        )
        r.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        print(f"  [logo-fail] {slug}: {exc}", file=sys.stderr)
        return None
    ct = r.headers.get("content-type", "")
    ext = ".png" if "png" in ct else (".jpg" if "jpeg" in ct or "jpg" in ct else ".png")
    fname = f"{slug}{ext}"
    out = LOGO_DIR / fname
    out.write_bytes(r.content)
    return f"/public/img/downdetector/{fname}"


async def _process(
    sem: asyncio.Semaphore,
    client: httpx.AsyncClient,
    slug: str,
    country: str,
    friendly: str,
    dry_run: bool,
) -> dict | None:
    async with sem:
        info = await _discover_one(client, slug, country, friendly)
        # Fallback: tenta outro country se falhou
        if info is None:
            alt = "com" if country != "com" else "com.br"
            info = await _discover_one(client, slug, alt, friendly)
        if info is None:
            return None
        logo_path = None
        if info.get("og_image") and not dry_run:
            logo_path = await _download_logo(client, slug, info["og_image"])
        info["logo"] = logo_path or f"/public/img/downdetector/{slug}.png"
        print(
            f"  [ok] {slug} ({info['country']}) id={info['id']} "
            f"name={info['name']!r} logo={info['logo']}"
        )
        return info


async def main(dry_run: bool) -> int:
    LOGO_DIR.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(CONCURRENCY)
    timeout = httpx.Timeout((TIMEOUT_MS / 1000) + 10)
    async with httpx.AsyncClient(timeout=timeout) as client:
        tasks = [
            _process(sem, client, slug, country, friendly, dry_run)
            for slug, country, friendly in CANDIDATES
        ]
        results = await asyncio.gather(*tasks)
    discovered = [r for r in results if r]
    print(
        f"\n=== {len(discovered)}/{len(CANDIDATES)} services discovered ===",
        file=sys.stderr,
    )
    if dry_run:
        return 0

    # gera services.yaml com defaults + lista
    yaml_doc: dict = {
        "defaults": {"poll_interval": 3600},
        "services": [
            {
                "name": r["name"],
                "slug": r["slug"],
                "id": r["id"],
                "logo": r["logo"],
                "country": r["country"],
            }
            for r in discovered
        ],
    }
    SERVICES_YAML.write_text(
        yaml.safe_dump(yaml_doc, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    print(f"wrote {SERVICES_YAML} with {len(discovered)} services")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    sys.exit(asyncio.run(main(args.dry_run)))
