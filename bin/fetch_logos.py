"""Baixa logos reais de cada serviço.

Ordem:
  1) simple-icons via unpkg (SVG monocromático, MIT)
  2) Google favicon API (PNG 128x128, embrulhado em SVG via base64)
  3) Se ambos falham, mantém placeholder existente.
"""
from __future__ import annotations

import asyncio
import base64
from pathlib import Path

import httpx
import yaml

LOGO_DIR = Path("/usr/share/grafana/public/img/downdetector")

SI_MAP = {
    "google": "google",
    "cloudflare": "cloudflare",
    "whatsapp": "whatsapp",
    "app-store": "appstore",
    "facebook": "facebook",
    "facebook-messenger": "messenger",
    "fortnite": "epicgames",
    "globo": "globo",
    "gmail": "gmail",
    "google-play": "googleplay",
    "ifood": "ifood",
    "instagram": "instagram",
    "league-of-legends": "leagueoflegends",
    "mercadopago": "mercadopago",
    "netflix": "netflix",
    "nubank": "nubank",
    "playstation-network": "playstation",
    "snapchat": "snapchat",
    "spotify": "spotify",
    "twitch": "twitch",
    "twitter": "x",
    "zoom": "zoom",
    "dropbox": "dropbox",
    "telegram": "telegram",
    "github": "github",
    "tinder": "tinder",
    "uber": "uber",
    "discord": "discord",
    "ebay": "ebay",
    "youtube": "youtube",
    "waze": "waze",
    "google-drive": "googledrive",
}

DOMAIN_MAP = {
    "amazon-prime-instant-video": "primevideo.com",
    "aws-amazon-web-services": "aws.amazon.com",
    "banco-do-brasil": "bb.com.br",
    "banco-inter": "bancointer.com.br",
    "banco-itau": "itau.com.br",
    "bradesco": "bradesco.com.br",
    "sicredi": "sicredi.com.br",
    "banrisul": "banrisul.com.br",
    "free-fire": "ff.garena.com",
    "globo": "globo.com",
    "globoplay": "globoplay.globo.com",
    "linkedin": "linkedin.com",
    "mercado-livre": "mercadolivre.com.br",
    "nota-fiscal-eletronica": "nfe.fazenda.gov.br",
    "bcb": "bcb.gov.br",
    "sicoob": "sicoob.com.br",
    "skype": "skype.com",
    "correios": "correios.com.br",
    "dataprev": "dataprev.gov.br",
    "enem": "gov.br",
    "policia-federal": "gov.br",
    "receita-federal": "gov.br",
    "sefaz": "fazenda.sp.gov.br",
    "terra": "terra.com.br",
    "locaweb": "locaweb.com.br",
    "caixa": "caixa.gov.br",
    "microsoft-365": "microsoft.com",
    "xbox-live": "xbox.com",
}


def png_to_svg(png_bytes: bytes) -> bytes:
    b64 = base64.b64encode(png_bytes).decode()
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128">'
        f'<image href="data:image/png;base64,{b64}" '
        'width="128" height="128" preserveAspectRatio="xMidYMid meet"/>'
        '</svg>'
    ).encode()


async def try_simple_icons(client, slug, si_name):
    try:
        r = await client.get(
            f"https://unpkg.com/simple-icons@latest/icons/{si_name}.svg",
            timeout=15, follow_redirects=True,
        )
        if r.status_code == 200 and r.content.lstrip().startswith(b"<svg"):
            (LOGO_DIR / f"{slug}.svg").write_bytes(r.content)
            return True
    except Exception as e:
        print(f"  [SI fail] {slug} ({si_name}): {e}", flush=True)
    return False


async def try_google_favicon(client, slug, domain):
    try:
        r = await client.get(
            f"https://www.google.com/s2/favicons?domain={domain}&sz=128",
            timeout=15, follow_redirects=True,
        )
        # Google returns 200 even for missing favicons (sends a default 16x16 globe).
        # Reject tiny files that are obviously fallbacks.
        if r.status_code == 200 and len(r.content) > 500:
            (LOGO_DIR / f"{slug}.svg").write_bytes(png_to_svg(r.content))
            return True
    except Exception as e:
        print(f"  [GF fail] {slug} ({domain}): {e}", flush=True)
    return False


async def fetch_one(client, slug):
    si_name = SI_MAP.get(slug)
    if si_name and await try_simple_icons(client, slug, si_name):
        return "simple-icons"
    domain = DOMAIN_MAP.get(slug)
    if domain and await try_google_favicon(client, slug, domain):
        return "google-favicon"
    # last-resort: try google favicon with slug as domain guess
    if await try_google_favicon(client, slug, f"{slug.replace('-', '')}.com"):
        return "google-favicon-guess"
    return None


async def main():
    global LOGO_DIR
    if not LOGO_DIR.exists():
        LOGO_DIR = Path(__file__).parents[1] / "grafana" / "logos"
        LOGO_DIR.mkdir(parents=True, exist_ok=True)

    services_yaml = Path("/etc/downdetector-collector/services.yaml")
    if not services_yaml.exists():
        services_yaml = Path(__file__).parents[1] / "config" / "services.example.yaml"

    cfg = yaml.safe_load(services_yaml.read_text(encoding="utf-8"))
    slugs = [s["slug"] for s in cfg["services"]]
    print(f"Fetching logos for {len(slugs)} services to {LOGO_DIR}...")
    async with httpx.AsyncClient(http2=False, headers={"User-Agent": "downdetector-collector/1.0"}) as client:
        sem = asyncio.Semaphore(6)

        async def gated(slug):
            async with sem:
                return slug, await fetch_one(client, slug)

        results = await asyncio.gather(*(gated(s) for s in slugs))

    by_src = {}
    for slug, src in results:
        by_src.setdefault(src or "fallback", []).append(slug)
    print()
    for src, ss in sorted(by_src.items()):
        print(f"{src}: {len(ss)}")
    if "fallback" in by_src:
        print(f"  kept placeholder: {', '.join(by_src['fallback'])}")


if __name__ == "__main__":
    asyncio.run(main())
