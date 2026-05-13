from pathlib import Path

import pytest

from collector.config import ServiceConfig, load_services_from_path


@pytest.fixture
def example_yaml(tmp_path: Path) -> Path:
    dst = tmp_path / "services.yaml"
    dst.write_text("""
defaults:
  poll_interval: 60
  country: br
services:
  - name: Cloudflare
    slug: cloudflare
    id: 32542
    logo: /public/img/downdetector/cloudflare.svg
    poll_interval: 30
    country: com
  - name: Banco Itaú
    slug: banco-itau
    id: 33205
    logo: /public/img/downdetector/banco-itau.svg
  - name: Nubank
    slug: nubank
    id: 33205
    logo: /public/img/downdetector/nubank.svg
  - name: WhatsApp
    slug: whatsapp
    id: 10136
    logo: /public/img/downdetector/whatsapp.svg
""")
    return dst


def test_load_returns_list_of_service_configs(example_yaml):
    services = load_services_from_path(example_yaml)
    assert len(services) == 4
    assert all(isinstance(s, ServiceConfig) for s in services)


def test_load_applies_defaults_for_missing_fields(example_yaml):
    services = load_services_from_path(example_yaml)
    itau = next(s for s in services if s.slug == "banco-itau")
    assert itau.poll_interval == 60
    assert itau.country == "br"


def test_load_keeps_per_service_overrides(example_yaml):
    services = load_services_from_path(example_yaml)
    cloudflare = next(s for s in services if s.slug == "cloudflare")
    assert cloudflare.poll_interval == 30
    assert cloudflare.country == "com"


def test_example_yaml_is_valid():
    """Smoke test: o exemplo embalado no repo carrega sem erro."""
    example = Path(__file__).parents[1] / "config" / "services.example.yaml"
    services = load_services_from_path(example)
    assert len(services) > 0
    assert all(isinstance(s, ServiceConfig) for s in services)


def test_load_rejects_duplicate_slugs(tmp_path: Path):
    bad = tmp_path / "services.yaml"
    bad.write_text("""
defaults:
  poll_interval: 60
  country: br
services:
  - {name: A, slug: x, id: 1, logo: a.svg}
  - {name: B, slug: x, id: 2, logo: b.svg}
""")
    with pytest.raises(ValueError, match="duplicate slug"):
        load_services_from_path(bad)


def test_service_url_country_br():
    s = ServiceConfig(name="Test", slug="test", id=1, logo="t.svg", poll_interval=60, country="br")
    assert s.url() == "https://downdetector.com.br/status/test/"


def test_service_url_country_com():
    s = ServiceConfig(name="Test", slug="test", id=1, logo="t.svg", poll_interval=60, country="com")
    assert s.url() == "https://downdetector.com/status/test/"


def test_load_rejects_missing_required_fields(tmp_path: Path):
    bad = tmp_path / "services.yaml"
    bad.write_text("""
defaults: {poll_interval: 60, country: br}
services:
  - {name: A, slug: x}
""")
    with pytest.raises(ValueError, match="id"):
        load_services_from_path(bad)
