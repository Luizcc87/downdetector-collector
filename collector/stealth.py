"""Patches anti-detecção para Playwright.

NOTA: Neste deploy o scraping é feito via FlareSolverr (collector/scraper.py),
que executa seu próprio Chromium interno otimizado para bypass Cloudflare.
Este módulo permanece como referência para o caso de futura troca de backend.
"""
from __future__ import annotations

CURRENT_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"
)
VIEWPORT = {"width": 1920, "height": 1080}


def context_kwargs() -> dict:
    return {
        "viewport": VIEWPORT,
        "user_agent": CURRENT_UA,
        "locale": "pt-BR",
        "timezone_id": "America/Sao_Paulo",
    }
