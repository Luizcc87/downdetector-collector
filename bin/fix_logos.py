"""Script para baixar e gerar logos de alta definição e visibilidade para todos os serviços."""
import base64
import urllib.request
from pathlib import Path

LOGO_DIR = Path(__file__).parents[1] / "grafana" / "logos"
LOGO_DIR.mkdir(parents=True, exist_ok=True)

DOMAINS = {
    "instagram": "instagram.com",
    "whatsapp": "whatsapp.com",
    "facebook": "facebook.com",
    "twitter": "x.com",
    "telegram": "telegram.org",
    "discord": "discord.com",
    "facebook-messenger": "messenger.com",
    "linkedin": "linkedin.com",
    "snapchat": "snapchat.com",
    "youtube": "youtube.com",
    # Bancos & Fintechs
    "pix": "bcb.gov.br",
    "banco-do-brasil": "bb.com.br",
    "banco-inter": "bancointer.com.br",
    "banco-itau": "itau.com.br",
    "bradesco": "bradesco.com.br",
    "nubank": "nubank.com.br",
    "bcb": "bcb.gov.br",
    "sicoob": "sicoob.com.br",
    "sicredi": "sicredi.com.br",
    "banrisul": "banrisul.com.br",
    "caixa": "caixa.gov.br",
    "mercadopago": "mercadopago.com.br",
    # Cloud & Infraestrutura
    "google": "google.com",
    "google-cloud": "cloud.google.com",
    "google-drive": "drive.google.com",
    "aws-amazon-web-services": "aws.amazon.com",
    "microsoft-365": "microsoft.com",
    "microsoft-account": "account.microsoft.com",
    "outlook": "outlook.com",
    "hostgator": "hostgator.com.br",
    # Inteligência Artificial
    "claude-ai": "claude.ai",
    "openai": "openai.com",
    "googlegemini": "gemini.google.com",
    # Governo
    "sefaz": "fazenda.sp.gov.br",
    "nota-fiscal-eletronica": "nfe.fazenda.gov.br",
}


def png_to_svg(png_bytes: bytes) -> bytes:
    b64 = base64.b64encode(png_bytes).decode("utf-8")
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128">'
        f'<image href="data:image/png;base64,{b64}" width="128" height="128" preserveAspectRatio="xMidYMid meet"/>'
        '</svg>'
    )
    return svg.encode("utf-8")


def text_badge_svg(label: str, bg_color: str = "#2C3E50") -> bytes:
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128">'
        f'<rect width="128" height="128" rx="24" fill="{bg_color}"/>'
        f'<text x="64" y="74" font-size="42" font-weight="bold" fill="#FFFFFF" text-anchor="middle" font-family="sans-serif">{label}</text>'
        '</svg>'
    )
    return svg.encode("utf-8")


def main():
    print(f"Baixando logos para {len(DOMAINS)} serviços em {LOGO_DIR}...")
    for slug, domain in DOMAINS.items():
        dst = LOGO_DIR / f"{slug}.svg"
        fetched = False
        try:
            url = f"https://www.google.com/s2/favicons?domain={domain}&sz=128"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req) as resp:
                content = resp.read()
                if len(content) > 100:
                    dst.write_bytes(png_to_svg(content))
                    print(f"  [OK] {slug} ({domain}) -> {len(content)} bytes")
                    fetched = True
        except Exception:
            pass

        if not fetched:
            # Fallback para SVG text badge bonito
            label = slug.replace("-", " ").split()[0][:4].upper()
            dst.write_bytes(text_badge_svg(label))
            print(f"  [BADGE] {slug} -> criado badge SVG ({label})")

    print("Logos atualizados com sucesso!")


if __name__ == "__main__":
    main()
