import importlib.util
from pathlib import Path


def load_dashboard_module():
    path = Path(__file__).parents[1] / "bin" / "build_dashboard.py"
    spec = importlib.util.spec_from_file_location("build_dashboard", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_downdetector_service_url_uses_country_and_slug():
    dashboard = load_dashboard_module()

    assert (
        dashboard.downdetector_service_url({"slug": "instagram", "country": "br"})
        == "https://downdetector.com.br/status/instagram/"
    )
    assert (
        dashboard.downdetector_service_url({"slug": "cloudflare", "country": "com"})
        == "https://downdetector.com/status/cloudflare/"
    )


def test_service_panels_link_to_downdetector_page():
    dashboard = load_dashboard_module()
    service = {
        "name": "Instagram",
        "slug": "instagram",
        "country": "br",
        "logo": "/public/img/downdetector/instagram.svg",
        "target_url": "https://www.instagram.com/",
    }

    panels, _, _ = dashboard.build_service_grid([service], start_y=1, start_pid=10)

    assert all(
        panel["links"][0]["url"] == "https://downdetector.com.br/status/instagram/"
        for panel in panels
    )
    assert all(panel["links"][0]["targetBlank"] is True for panel in panels)


def test_service_grid_renders_logo_status_and_sparkline():
    dashboard = load_dashboard_module()
    service = {
        "name": "Instagram",
        "slug": "instagram",
        "country": "br",
        "logo": "/public/img/downdetector/instagram.svg",
        "target_url": "https://www.instagram.com/",
    }

    panels, next_y, next_pid = dashboard.build_service_grid([service], start_y=1, start_pid=10)

    assert [panel["type"] for panel in panels] == ["text", "stat", "timeseries", "stat"]
    assert all(panel["gridPos"]["w"] == 4 for panel in panels)
    sparkline = panels[2]
    assert sparkline["title"] == "Historico Downdetector"
    assert sparkline["targets"][0]["item"]["filter"] == "/^Instagram: reports last hour$/"
    assert sparkline["options"]["legend"]["displayMode"] == "hidden"
    assert sparkline["fieldConfig"]["defaults"]["custom"]["drawStyle"] == "line"
    assert sparkline["fieldConfig"]["defaults"]["custom"]["lineWidth"] == 2
    assert sparkline["fieldConfig"]["defaults"]["custom"]["showPoints"] == "auto"
    latency = panels[3]
    assert latency["title"] == "Latencia ate o servico oficial"
    assert latency["targets"][0]["item"]["filter"] == "/^Instagram: latency to official service$/"
    assert latency["options"]["reduceOptions"]["calcs"] == ["lastNotNull"]
    assert latency["fieldConfig"]["defaults"]["unit"] == "ms"
    assert next_y == 1 + dashboard.CARD_H
    assert next_pid == 14
