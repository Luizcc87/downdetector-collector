"""DASHBOARD DOWNDETECTOR v20 — Layout NOC Profissional com Categorias e Incidentes.

Recursos:
- Banner de Métricas Globais (Total, OK, Atenção, Problema) + Métricas do Scraper.
- Painel em Destaque: Incidentes e Instabilidades Ativas no Momento.
- Linhas Retráteis por Categoria:
    * 📱 Redes Sociais & Comunicação
    * 📺 Streaming & Vídeo
    * 🏦 Bancos & Fintechs
    * 🏛️ Governo & Serviços Fiscais
- Gráfico de Tendência: Histórico de Reclamações (últimas 24h).
"""
import json
from html import escape
from pathlib import Path

import yaml

ZBX_DS = {"type": "alexanderzobnin-zabbix-datasource", "uid": "downdetector-zabbix"}
HOST_GROUP = "Downdetector"
HOST = "Downdetector"

COLOR_GRAY = "#808080"
COLOR_OK = "#2EB85C"
COLOR_ATTN = "#F9B115"
COLOR_PROB = "#E55353"
COLOR_UNK = "#9B59B6"

STATUS_MAPPINGS = [{
    "type": "value",
    "options": {
        "0": {"text": "Ok", "color": COLOR_OK, "index": 0},
        "1": {"text": "Atenção", "color": COLOR_ATTN, "index": 1},
        "2": {"text": "Problema", "color": COLOR_PROB, "index": 2},
        "3": {"text": "N/D", "color": COLOR_UNK, "index": 3},
    },
}]
STATUS_THRESHOLDS = {
    "mode": "absolute",
    "steps": [
        {"color": COLOR_OK, "value": None},
        {"color": COLOR_ATTN, "value": 1},
        {"color": COLOR_PROB, "value": 2},
        {"color": COLOR_UNK, "value": 3},
    ],
}

CARDS_PER_ROW = 4
CARD_W = 24 // CARDS_PER_ROW  # = 6
LOGO_H = 5
STATUS_H = 1
REPORTS_H = 3
LATENCY_H = 3
CARD_H = LOGO_H + STATUS_H + REPORTS_H + LATENCY_H  # = 12

TOP_H = 3


def zbx_target(name_filter, ref="A"):
    return {
        "refId": ref, "queryType": "0", "resultFormat": "time_series",
        "datasource": ZBX_DS,
        "group": {"filter": HOST_GROUP}, "host": {"filter": HOST},
        "application": {"filter": ""}, "item": {"filter": name_filter},
        "functions": [],
    }


def downdetector_service_url(service):
    country = service.get("country", "br")
    slug = service["slug"]
    if country == "com":
        return f"https://downdetector.com/status/{slug}/"
    return f"https://downdetector.com.{country}/status/{slug}/"


def panel_link(url):
    return [{"title": "Abrir no Downdetector", "url": url, "targetBlank": True}]


def total_panel():
    return {
        "id": 1, "type": "stat", "title": "Total",
        "gridPos": {"h": TOP_H, "w": 2, "x": 0, "y": 0},
        "datasource": ZBX_DS,
        "targets": [zbx_target("/.*: status$/")],
        "transformations": [
            {"id": "reduce", "options": {"reducers": ["last"], "mode": "seriesToRows", "includeTimeField": False}},
        ],
        "options": {
            "reduceOptions": {"calcs": ["count"], "fields": "/^Last/", "values": False},
            "colorMode": "background", "graphMode": "none", "textMode": "value", "justifyMode": "center",
        },
        "fieldConfig": {
            "defaults": {
                "color": {"mode": "fixed", "fixedColor": COLOR_GRAY},
                "thresholds": {"mode": "absolute", "steps": [{"color": COLOR_GRAY, "value": None}]},
                "unit": "none", "min": 0,
            },
            "overrides": [],
        },
    }


def status_count_panel(pid, title, status_value, color, gx, gw):
    return {
        "id": pid, "type": "stat", "title": title,
        "gridPos": {"h": TOP_H, "w": gw, "x": gx, "y": 0},
        "datasource": ZBX_DS,
        "targets": [zbx_target("/.*: status$/")],
        "transformations": [
            {"id": "reduce", "options": {"reducers": ["last"], "mode": "seriesToRows", "includeTimeField": False}},
            {"id": "filterByValue", "options": {
                "filters": [{"fieldName": "Last", "config": {"id": "equal", "options": {"value": float(status_value)}}}],
                "type": "include", "match": "any",
            }},
        ],
        "options": {
            "reduceOptions": {"calcs": ["count"], "fields": "/^Last/", "values": False},
            "colorMode": "background", "graphMode": "none", "textMode": "value", "justifyMode": "center",
        },
        "fieldConfig": {
            "defaults": {
                "color": {"mode": "fixed", "fixedColor": color},
                "thresholds": {"mode": "absolute", "steps": [{"color": color, "value": None}]},
                "unit": "none", "min": 0,
            },
            "overrides": [],
        },
    }


def health_stat(pid, title, item, unit, color, gx, gw, thresholds=None):
    return {
        "id": pid, "type": "stat", "title": title,
        "gridPos": {"h": TOP_H, "w": gw, "x": gx, "y": 0},
        "datasource": ZBX_DS,
        "targets": [zbx_target(item, ref="A")],
        "options": {
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "colorMode": "value", "graphMode": "area", "textMode": "auto", "justifyMode": "auto",
        },
        "fieldConfig": {
            "defaults": {
                "color": {"mode": "thresholds" if thresholds else "fixed", "fixedColor": color},
                "unit": unit,
                "thresholds": {"mode": "absolute", "steps": thresholds or [{"color": color, "value": None}]},
            },
            "overrides": [],
        },
    }


def active_incidents_panel(pid, y):
    """Painel no topo destacando serviços com instabilidade ou falha."""
    return {
        "id": pid, "type": "stat", "title": "🚨 Serviços em Estado de Alerta / Falha",
        "gridPos": {"h": 4, "w": 24, "x": 0, "y": y},
        "datasource": ZBX_DS,
        "targets": [zbx_target("/.*: status$/")],
        "transformations": [
            {"id": "reduce", "options": {"reducers": ["last"], "mode": "seriesToRows", "includeTimeField": False}},
            {"id": "filterByValue", "options": {
                "filters": [{"fieldName": "Last", "config": {"id": "greater", "options": {"value": 0}}}],
                "type": "include", "match": "any",
            }},
        ],
        "options": {
            "reduceOptions": {"calcs": ["last"], "fields": "", "values": False},
            "colorMode": "background", "graphMode": "none", "textMode": "value_and_name", "justifyMode": "center",
        },
        "fieldConfig": {
            "defaults": {
                "color": {"mode": "thresholds"},
                "mappings": STATUS_MAPPINGS,
                "thresholds": STATUS_THRESHOLDS,
                "noValue": "Nenhum incidente ativo no momento 🟢",
            },
            "overrides": [],
        },
    }


def row_header(pid, title, y):
    return {
        "id": pid, "type": "row", "title": title,
        "collapsed": False,
        "gridPos": {"h": 1, "w": 24, "x": 0, "y": y},
        "panels": [],
    }


def card_logo(pid, name, logo_url, service_url, x, y):
    safe_name = escape(name)
    safe_logo_url = escape(logo_url, quote=True)
    safe_service_url = escape(service_url, quote=True)
    return {
        "id": pid, "type": "text", "title": "",
        "gridPos": {"h": LOGO_H, "w": CARD_W, "x": x, "y": y},
        "links": panel_link(service_url),
        "options": {
            "mode": "html",
            "content": (
                f'<a href="{safe_service_url}" target="_blank" rel="noopener noreferrer" '
                'style="display:flex;flex-direction:column;align-items:center;'
                'justify-content:center;height:100%;padding:14px 16px 6px;gap:10px;'
                'background:#ffffff;border-radius:6px 6px 0 0;text-decoration:none;'
                'box-sizing:border-box;border:1px solid #d7dbe0;border-bottom:0;">'
                '<div style="font-size:15px;font-weight:500;align-self:flex-start;'
                'line-height:1.2;color:#20242a;max-width:100%;overflow:hidden;'
                'text-overflow:ellipsis;white-space:nowrap;">'
                f'{safe_name}</div>'
                '<div style="display:flex;align-items:center;justify-content:center;'
                'width:100%;height:100%;">'
                f'<img src="{safe_logo_url}" style="max-height:78px;max-width:86%;'
                'object-fit:contain;" />'
                '</div>'
                '<div style="font-size:11px;color:#68717d;align-self:flex-end;">'
                'Abrir</div>'
                '</a>'
            ),
        },
        "transparent": True,
    }


def card_status(pid, name, service_url, x, y):
    return {
        "id": pid, "type": "stat", "title": "",
        "gridPos": {"h": STATUS_H, "w": CARD_W, "x": x, "y": y},
        "datasource": ZBX_DS,
        "links": panel_link(service_url),
        "targets": [zbx_target(f"{name}: status")],
        "options": {
            "reduceOptions": {"calcs": ["last"], "fields": "", "values": False},
            "colorMode": "background", "graphMode": "none", "textMode": "value", "justifyMode": "center",
        },
        "fieldConfig": {
            "defaults": {
                "color": {"mode": "thresholds"},
                "mappings": STATUS_MAPPINGS,
                "thresholds": STATUS_THRESHOLDS,
                "unit": "none",
            },
            "overrides": [],
        },
    }


def card_reports(pid, name, service_url, x, y):
    return {
        "id": pid, "type": "timeseries", "title": "Historico Downdetector",
        "gridPos": {"h": REPORTS_H, "w": CARD_W, "x": x, "y": y},
        "datasource": ZBX_DS,
        "links": panel_link(service_url),
        "targets": [zbx_target(f"{name}: reports last hour")],
        "options": {
            "tooltip": {"mode": "single", "sort": "none"},
            "legend": {"displayMode": "hidden", "placement": "bottom", "calcs": []},
        },
        "fieldConfig": {
            "defaults": {
                "color": {"mode": "fixed", "fixedColor": "#15AABF"},
                "custom": {
                    "drawStyle": "line",
                    "lineInterpolation": "smooth",
                    "lineWidth": 2,
                    "fillOpacity": 0,
                    "showPoints": "never",
                    "axisPlacement": "hidden",
                    "hideFrom": {"tooltip": False, "viz": False, "legend": False},
                },
                "thresholds": {
                    "mode": "absolute",
                    "steps": [
                        {"color": "#15AABF", "value": None},
                        {"color": COLOR_ATTN, "value": 30},
                        {"color": COLOR_PROB, "value": 100},
                    ],
                },
                "unit": "short",
                "decimals": 0,
                "min": 0,
            },
            "overrides": [],
        },
        "transparent": True,
    }


def card_latency(pid, name, service_url, x, y):
    return {
        "id": pid, "type": "timeseries", "title": "Latencia ate o servico oficial",
        "gridPos": {"h": LATENCY_H, "w": CARD_W, "x": x, "y": y},
        "datasource": ZBX_DS,
        "links": panel_link(service_url),
        "targets": [zbx_target(f"{name}: latency to official service")],
        "options": {
            "tooltip": {"mode": "single", "sort": "none"},
            "legend": {"displayMode": "hidden", "placement": "bottom", "calcs": []},
        },
        "fieldConfig": {
            "defaults": {
                "color": {"mode": "fixed", "fixedColor": "#7C3AED"},
                "custom": {
                    "drawStyle": "line",
                    "lineInterpolation": "smooth",
                    "lineWidth": 2,
                    "fillOpacity": 0,
                    "showPoints": "never",
                    "axisPlacement": "hidden",
                    "hideFrom": {"tooltip": False, "viz": False, "legend": False},
                },
                "thresholds": {
                    "mode": "absolute",
                    "steps": [
                        {"color": "#2EB85C", "value": None},
                        {"color": COLOR_ATTN, "value": 500},
                        {"color": COLOR_PROB, "value": 1500},
                    ],
                },
                "unit": "ms",
                "decimals": 0,
                "min": 0,
            },
            "overrides": [],
        },
        "transparent": True,
    }


def build_service_grid(services, start_y, start_pid):
    panels = []
    pid = start_pid
    y = start_y
    col = 0
    for svc in services:
        x = col * CARD_W
        service_url = downdetector_service_url(svc)
        panels.append(card_logo(pid, svc["name"], svc["logo"], service_url, x=x, y=y))
        pid += 1
        panels.append(card_status(pid, svc["name"], service_url, x=x, y=y + LOGO_H))
        pid += 1
        panels.append(card_reports(pid, svc["name"], service_url, x=x, y=y + LOGO_H + STATUS_H))
        pid += 1
        panels.append(card_latency(
            pid,
            svc["name"],
            service_url,
            x=x,
            y=y + LOGO_H + STATUS_H + REPORTS_H,
        ))
        pid += 1
        col += 1
        if col >= CARDS_PER_ROW:
            col = 0
            y += CARD_H
    if col > 0:
        y += CARD_H
    return panels, y, pid


def reports_timeline_panel(pid, y):
    """Gráfico de tendência de relatos das últimas 24h."""
    return {
        "id": pid, "type": "timeseries", "title": "📊 Histórico de Relatos de Problemas (Últimas 24h)",
        "gridPos": {"h": 8, "w": 24, "x": 0, "y": y},
        "datasource": ZBX_DS,
        "targets": [zbx_target("/.*: reports last hour$/")],
        "options": {
            "tooltip": {"mode": "multi", "sort": "desc"},
            "legend": {"displayMode": "table", "placement": "right", "calcs": ["max", "last"]},
        },
        "fieldConfig": {
            "defaults": {
                "custom": {
                    "drawStyle": "line",
                    "lineInterpolation": "smooth",
                    "fillOpacity": 10,
                },
                "unit": "short",
                "min": 0,
            },
            "overrides": [],
        },
    }


def categorize_services(services):
    categories = {
        "📱 Redes Sociais & Comunicação": [],
        "📺 Streaming & Vídeo": [],
        "🏦 Bancos & Fintechs": [],
        "🏛️ Governo & Serviços Fiscais": [],
        "🌐 Outros Serviços": [],
    }

    social_slugs = {"instagram", "whatsapp", "facebook", "twitter", "telegram", "discord", "facebook-messenger", "linkedin", "snapchat"}
    video_slugs = {"youtube", "netflix", "spotify"}
    bank_slugs = {"banco-do-brasil", "banco-inter", "banco-itau", "bradesco", "nubank", "bcb", "sicoob", "sicredi", "banrisul", "caixa", "mercadopago"}
    gov_slugs = {"sefaz", "nota-fiscal-eletronica", "receita-federal", "gov-br"}

    for s in services:
        slug = s["slug"]
        if slug in social_slugs:
            categories["📱 Redes Sociais & Comunicação"].append(s)
        elif slug in video_slugs:
            categories["📺 Streaming & Vídeo"].append(s)
        elif slug in bank_slugs:
            categories["🏦 Bancos & Fintechs"].append(s)
        elif slug in gov_slugs:
            categories["🏛️ Governo & Serviços Fiscais"].append(s)
        else:
            categories["🌐 Outros Serviços"].append(s)

    return {k: v for k, v in categories.items() if v}


def main():
    services_yaml = Path("/etc/downdetector-collector/services.yaml")
    if not services_yaml.exists():
        services_yaml = Path(__file__).parents[1] / "config" / "services.example.yaml"

    cfg = yaml.safe_load(services_yaml.read_text(encoding="utf-8"))
    defaults = cfg.get("defaults", {}) or {}
    services = [{**defaults, **s} for s in cfg.get("services", [])]

    panels = [
        # Linha do topo (h=3): Métricas globais + Scraper Health
        total_panel(),                                              # x=0  w=2
        status_count_panel(2, "Ok", 0, COLOR_OK, gx=2, gw=2),         # x=2  w=2
        status_count_panel(3, "Atenção", 1, COLOR_ATTN, gx=4, gw=2),  # x=4  w=2
        status_count_panel(4, "Problema", 2, COLOR_PROB, gx=6, gw=3), # x=6  w=3
        health_stat(900, "Uptime", "Scraper uptime", "s", "blue", gx=9, gw=3),
        health_stat(901, "Duração do ciclo", "Last cycle duration", "s", "blue", gx=12, gw=4,
                    thresholds=[{"color": "green", "value": None},
                                {"color": COLOR_ATTN, "value": 30},
                                {"color": COLOR_PROB, "value": 120}]),
        health_stat(902, "Bloqueios CF (5m)", "Cloudflare blocks (5m)", "short", "green", gx=16, gw=4,
                    thresholds=[{"color": "green", "value": None},
                                {"color": COLOR_ATTN, "value": 1},
                                {"color": COLOR_PROB, "value": 10}]),
        health_stat(903, "Restarts browser", "Browser restarts", "short", "blue", gx=20, gw=4),
    ]

    current_y = 3
    current_pid = 10

    # Incidentes ativos no topo
    panels.append(active_incidents_panel(current_pid, current_y))
    current_pid += 1
    current_y += 4

    # Categorias
    categorized = categorize_services(services)
    for cat_name, cat_services in categorized.items():
        panels.append(row_header(current_pid, cat_name, current_y))
        current_pid += 1
        current_y += 1

        cat_panels, current_y, current_pid = build_service_grid(cat_services, start_y=current_y, start_pid=current_pid)
        panels.extend(cat_panels)

    # Gráfico de Tendências das últimas 24h
    panels.append(row_header(current_pid, "📈 Tendências & Histórico", current_y))
    current_pid += 1
    current_y += 1
    panels.append(reports_timeline_panel(current_pid, current_y))

    dashboard = {
        "title": "DASHBOARD DOWNDETECTOR",
        "uid": "downdetector-main",
        "schemaVersion": 41, "version": 21,
        "editable": True, "refresh": "1m",
        "time": {"from": "now-1h", "to": "now"},
        "timezone": "America/Sao_Paulo", "tags": ["downdetector"],
        "annotations": {"list": []}, "templating": {"list": []},
        "panels": panels,
    }

    out = Path("/var/lib/grafana/dashboards/downdetector/dashboard_downdetector.json")
    if not out.parent.exists():
        out = Path(__file__).parents[1] / "grafana" / "dashboard_downdetector.json"

    out.write_text(json.dumps(dashboard, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote v{dashboard['version']} with {len(panels)} panels to {out}")


if __name__ == "__main__":
    main()
