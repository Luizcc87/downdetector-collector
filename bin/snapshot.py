"""Utility: baixa páginas do Downdetector e salva como fixture HTML.

Uso:
    python bin/snapshot.py cloudflare --country br --out tests/fixtures/downdetector_warning.html

Estratégia anti-Cloudflare (em ordem de precedência):
1. FlareSolverr (sidecar Docker, porta 8191) — estratégia principal e mais confiável.
   Inicia com: docker run -d --name=flaresolverr -p 8191:8191 ghcr.io/flaresolverr/flaresolverr:latest
2. Playwright headed via Xvfb — fallback se FlareSolverr não estiver disponível.
   Requer: apt install xvfb e rodar com xvfb-run -a python bin/snapshot.py ...

Notas:
- URL correta: country=br -> downdetector.com.br, country=com -> downdetector.com
- Validação: recusa salvar se parece Cloudflare challenge ou menor que 50KB
- Perfil Playwright em /tmp/dd-snapshot-profile (limpar para resetar cookies)
"""
import argparse
import asyncio
import os
import random
import sys
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError
import json as _json

from playwright.async_api import async_playwright
from playwright_stealth import Stealth

# UA compatível com Chromium 124 estável (alinhado com sec-ch-ua abaixo).
# Atualizar junto com CURRENT_SEC_CH_UA se trocar a versão maior.
CURRENT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
CURRENT_SEC_CH_UA = '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"'

FLARESOLVERR_URL = "http://localhost:8191/v1"

# Marcadores que indicam HTML real do Downdetector (site usa Next.js desde 2025)
REAL_CONTENT_MARKERS = [
    "company-status",      # id="company-status" (card de status atual)
    'id="company"',        # section pai do card
    "chartData",           # JSON embutido com dados do gráfico
    "data-testid=\"card-company-status\"",  # atributo do card Next.js
    "downdetector",        # domain name no conteúdo
]

# Marcadores que indicam Cloudflare challenge
CHALLENGE_MARKERS = [
    "Just a moment",
    "cf-mitigated",
    "challenges.cloudflare.com",
    "Ray ID",
]

MIN_REAL_SIZE = 50_000  # bytes


def _build_url(slug: str, country: str) -> str:
    """Constrói URL correta para o Downdetector.

    country=br  -> https://downdetector.com.br/status/{slug}/
    country=com -> https://downdetector.com/status/{slug}/
    """
    if country == "br":
        return f"https://downdetector.com.br/status/{slug}/"
    else:
        return f"https://downdetector.com/status/{slug}/"


def _is_cloudflare_challenge(html: str) -> bool:
    return any(marker in html for marker in CHALLENGE_MARKERS)


def _has_real_content(html: str) -> bool:
    return any(marker in html for marker in REAL_CONTENT_MARKERS)


def _flaresolverr_available() -> bool:
    """Verifica se FlareSolverr está respondendo na porta 8191."""
    try:
        req = Request(FLARESOLVERR_URL, method="GET")
        # FlareSolverr retorna 405 em GET /v1, mas isso confirma que está up
        urlopen(req, timeout=3)
    except URLError as e:
        # 405 Method Not Allowed ainda é "disponível"
        if hasattr(e, "code") and e.code == 405:
            return True
        return False
    except Exception:
        return False
    return True


def _snapshot_via_flaresolverr(url: str) -> str | None:
    """Usa FlareSolverr para obter o HTML final da página.

    Retorna o HTML como string, ou None em caso de falha.
    """
    payload = _json.dumps({
        "cmd": "request.get",
        "url": url,
        "maxTimeout": 60000,
    }).encode("utf-8")
    req = Request(
        FLARESOLVERR_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=90) as resp:
            data = _json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        print(f"FlareSolverr erro de rede: {exc}")
        return None

    if data.get("status") != "ok":
        print(f"FlareSolverr retornou status={data.get('status')}: {data.get('message', '')}")
        return None

    solution = data.get("solution", {})
    http_status = solution.get("status")
    html = solution.get("response", "")
    print(f"HTTP {http_status} via FlareSolverr ({len(html.encode('utf-8'))} bytes)")
    return html


async def _snapshot_via_playwright(url: str) -> str | None:
    """Usa Playwright headed (Xvfb) para obter o HTML da página.

    Requer DISPLAY disponível (use xvfb-run -a).
    Retorna o HTML como string, ou None em caso de falha.
    """
    profile_dir = Path("/tmp/dd-snapshot-profile")
    profile_dir.mkdir(exist_ok=True)

    display = os.environ.get("DISPLAY", "")
    headless = not bool(display)
    if headless:
        print(
            "AVISO: DISPLAY não encontrado — rodando headless. "
            "Para melhores resultados: xvfb-run -a python bin/snapshot.py ..."
        )
    else:
        print(f"Rodando headed (DISPLAY={display})")

    stealth = Stealth(
        chrome_runtime=True,
        navigator_platform_override="Win32",
        navigator_vendor_override="Google Inc.",
        navigator_user_agent_override=CURRENT_UA,
        sec_ch_ua_override=CURRENT_SEC_CH_UA,
        webgl_vendor_override="Google Inc. (Intel)",
        webgl_renderer_override="ANGLE (Intel, Intel(R) UHD Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)",
    )

    browser_args = [
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-infobars",
        "--disable-background-timer-throttling",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
        "--no-first-run",
        "--no-default-browser-check",
        "--lang=en-US",
    ]

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=headless,
            args=browser_args,
            viewport={"width": 1920, "height": 1080},
            user_agent=CURRENT_UA,
            locale="en-US",
            timezone_id="America/New_York",
            geolocation={"longitude": -74.006, "latitude": 40.7128},
            permissions=["geolocation"],
            color_scheme="light",
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9",
                "sec-ch-ua": CURRENT_SEC_CH_UA,
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
            },
        )
        try:
            page = await ctx.new_page()
            await stealth.apply_stealth_async(page)

            print(f"Playwright goto {url}...")
            response = await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            http_status = response.status if response else None
            print(f"HTTP {http_status}")

            jitter = random.uniform(3.0, 6.0)
            print(f"Aguardando {jitter:.1f}s...")
            await page.wait_for_timeout(int(jitter * 1000))

            try:
                await page.wait_for_load_state("networkidle", timeout=15_000)
            except Exception:
                pass  # timeout é normal no Cloudflare

            html = await page.content()
            size = len(html.encode("utf-8"))
            print(f"HTML capturado: {size} bytes")
            return html
        finally:
            await ctx.close()


def snapshot(slug: str, country: str, out_path: Path) -> bool:
    """Captura página do Downdetector e salva em out_path.

    Tenta FlareSolverr primeiro; cai para Playwright se não disponível.
    Retorna True se captura bem-sucedida e arquivo salvo.
    """
    url = _build_url(slug, country)
    print(f"URL alvo: {url}")

    html: str | None = None

    # Estratégia 1: FlareSolverr
    if _flaresolverr_available():
        print("FlareSolverr detectado — usando como estratégia primária.")
        html = _snapshot_via_flaresolverr(url)
    else:
        print("FlareSolverr não disponível (porta 8191). Usando Playwright.")
        print("Para ativar: docker run -d --name=flaresolverr -p 8191:8191 ghcr.io/flaresolverr/flaresolverr:latest")

    # Estratégia 2: Playwright headed (fallback)
    if html is None:
        html = asyncio.run(_snapshot_via_playwright(url))

    if html is None:
        print("FALHA: nenhuma estratégia retornou HTML.")
        return False

    size = len(html.encode("utf-8"))

    # Validação
    if _is_cloudflare_challenge(html):
        print(f"FALHA: HTML contém marcadores de Cloudflare challenge — NÃO salvo.")
        return False

    if not _has_real_content(html):
        print(f"FALHA: HTML não contém marcadores reais do Downdetector — NÃO salvo.")
        return False

    if size < MIN_REAL_SIZE:
        print(f"FALHA: Arquivo muito pequeno ({size} < {MIN_REAL_SIZE} bytes) — NÃO salvo.")
        return False

    out_path.write_text(html, encoding="utf-8")
    print(f"OK: Salvo {size} bytes em {out_path}")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Captura página do Downdetector como fixture HTML."
    )
    ap.add_argument("slug", help="Slug do serviço (ex: google, whatsapp, steam)")
    ap.add_argument("--country", default="br", choices=["br", "com"])
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    success = snapshot(args.slug, args.country, args.out)
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
