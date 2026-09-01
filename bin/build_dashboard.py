"""DASHBOARD DOWNDETECTOR v24 — Layout NOC Completo com Filtros por Chaves de Item Zabbix.

Recursos:
- Banner de Métricas Globais (Total, OK, Atenção, Problema) + Métricas do Scraper.
- Painel em Destaque: Incidentes e Instabilidades Ativas no Momento.
- Cards Individuais por Serviço com Logo, Status, Histórico Sparkline e Latência.
- Linhas Retráteis por Categoria.
- Painel Histórico: State Timeline do Status dos Serviços (Últimas 24h).
- Painel Histórico: Histórico de Relatos de Problemas (Últimas 24h).
- Painel de Desempenho: Latência Direta de Resposta aos Serviços (ms).
"""
import json
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

CARDS_PER_ROW = 8
CARD_W = 24 // CARDS_PER_ROW  # = 3
LOGO_H = 3
STATUS_H = 2
SPARKLINE_H = 2
LATENCY_H = 2
CARD_H = LOGO_H + STATUS_H + SPARKLINE_H + LATENCY_H  # = 9

TOP_H = 3


def zbx_target(name_filter, ref="A"):
    return {
        "refId": ref, "queryType": "0", "resultFormat": "time_series",
        "datasource": ZBX_DS,
        "group": {"filter": HOST_GROUP}, "host": {"filter": HOST},
        "application": {"filter": ""}, "item": {"filter": name_filter},
        "functions": [],
    }


def downdetector_service_url(svc: dict) -> str:
    country = svc.get("country", "br")
    slug = svc["slug"]
    if country == "com":
        return f"https://downdetector.com/status/{slug}/"
    return f"https://downdetector.com.br/status/{slug}/"


def panel_links(svc: dict) -> list[dict]:
    return [{
        "title": svc["name"],
        "url": downdetector_service_url(svc),
        "targetBlank": True,
    }]


def total_panel():
    return {
        "id": 1, "type": "stat", "title": "Total",
        "gridPos": {"h": TOP_H, "w": 2, "x": 0, "y": 0},
        "datasource": ZBX_DS,
        "targets": [zbx_target("/downdetector\\.status\\[.*\\]/")],
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
        "targets": [zbx_target("/downdetector\\.status\\[.*\\]/")],
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
    return {
        "id": pid, "type": "stat", "title": "🚨 Serviços em Estado de Alerta / Falha",
        "gridPos": {"h": 4, "w": 24, "x": 0, "y": y},
        "datasource": ZBX_DS,
        "targets": [zbx_target("/downdetector\\.status\\[.*\\]/")],
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


def card_logo(pid, svc, logo_url, x, y):
    return {
        "id": pid, "type": "text", "title": "",
        "gridPos": {"h": LOGO_H, "w": CARD_W, "x": x, "y": y},
        "links": panel_links(svc),
        "options": {
            "mode": "html",
            "content": (
                '<div style="display:flex;flex-direction:column;align-items:center;'
                'justify-content:center;height:100%;padding:4px;gap:2px;'
                'background:#181b1f;border-radius:6px 6px 0 0;">'
                '<div style="background:#ffffff;padding:2px;border-radius:6px;'
                'display:flex;align-items:center;justify-content:center;'
                'width:36px;height:36px;box-shadow:0 2px 4px rgba(0,0,0,0.4);">'
                f'<img src="{logo_url}" style="max-height:30px;max-width:30px;'
                'object-fit:contain;" />'
                '</div>'
                '<div style="font-size:11px;font-weight:600;text-align:center;'
                'line-height:1.1;color:#ffffff;max-width:100%;overflow:hidden;'
                'text-overflow:ellipsis;white-space:nowrap;padding:0 2px;">'
                f'{svc["name"]}</div>'
                '</div>'
            ),
        },
        "transparent": True,
    }


def card_status(pid, svc, x, y):
    return {
        "id": pid, "type": "stat", "title": "",
        "gridPos": {"h": STATUS_H, "w": CARD_W, "x": x, "y": y},
        "links": panel_links(svc),
        "datasource": ZBX_DS,
        "targets": [zbx_target(f"/downdetector\\.status\\[{svc['slug']}\\]/")],
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


def card_sparkline_reports(pid, svc, x, y):
    return {
        "id": pid, "type": "timeseries", "title": "Historico Downdetector",
        "gridPos": {"h": SPARKLINE_H, "w": CARD_W, "x": x, "y": y},
        "links": panel_links(svc),
        "datasource": ZBX_DS,
        "targets": [zbx_target(f"/downdetector\\.reports\\[{svc['slug']}\\]/")],
        "options": {
            "legend": {"displayMode": "hidden"},
            "tooltip": {"mode": "single"},
        },
        "fieldConfig": {
            "defaults": {
                "custom": {
                    "drawStyle": "line",
                    "lineInterpolation": "smooth",
                    "fillOpacity": 20,
                    "axisPlacement": "none",
                    "showPoints": "never",
                },
                "color": {"mode": "fixed", "fixedColor": "#3498DB"},
                "unit": "short",
                "min": 0,
            },
            "overrides": [],
        },
    }


def card_sparkline_latency(pid, svc, x, y):
    return {
        "id": pid, "type": "timeseries", "title": "Latencia ate o servico oficial",
        "gridPos": {"h": LATENCY_H, "w": CARD_W, "x": x, "y": y},
        "links": panel_links(svc),
        "datasource": ZBX_DS,
        "targets": [zbx_target(f"/downdetector\\.latency_ms\\[{svc['slug']}\\]/")],
        "options": {
            "legend": {"displayMode": "hidden"},
            "tooltip": {"mode": "single"},
        },
        "fieldConfig": {
            "defaults": {
                "custom": {
                    "drawStyle": "line",
                    "lineInterpolation": "smooth",
                    "fillOpacity": 15,
                    "axisPlacement": "none",
                    "showPoints": "never",
                },
                "color": {"mode": "fixed", "fixedColor": "#F39C12"},
                "unit": "ms",
                "min": 0,
            },
            "overrides": [],
        },
    }


def build_service_grid(services, start_y, start_pid):
    panels = []
    pid = start_pid
    y = start_y
    col = 0
    for svc in services:
        x = col * CARD_W
        panels.append(card_logo(pid, svc, svc["logo"], x=x, y=y))
        pid += 1
        panels.append(card_status(pid, svc, x=x, y=y + LOGO_H))
        pid += 1
        panels.append(card_sparkline_reports(pid, svc, x=x, y=y + LOGO_H + STATUS_H))
        pid += 1
        panels.append(card_sparkline_latency(pid, svc, x=x, y=y + LOGO_H + STATUS_H + SPARKLINE_H))
        pid += 1
        col += 1
        if col >= CARDS_PER_ROW:
            col = 0
            y += CARD_H
    if col > 0:
        y += CARD_H
    return panels, y, pid


def status_history_panel(pid, y):
    return {
        "id": pid, "type": "state-timeline", "title": "⏱️ Histórico de Status dos Serviços (Últimas 24h)",
        "gridPos": {"h": 10, "w": 24, "x": 0, "y": y},
        "datasource": ZBX_DS,
        "targets": [zbx_target("/downdetector\\.status\\[.*\\]/")],
        "options": {
            "showValue": "never",
            "mergeValues": True,
            "rowHeight": 0.8,
            "alignValue": "center",
            "tooltip": {"mode": "single"},
        },
        "fieldConfig": {
            "defaults": {
                "color": {"mode": "thresholds"},
                "mappings": STATUS_MAPPINGS,
                "thresholds": STATUS_THRESHOLDS,
            },
            "overrides": [],
        },
    }


def reports_timeline_panel(pid, y):
    return {
        "id": pid, "type": "timeseries", "title": "📊 Histórico de Relatos de Problemas (Últimas 24h)",
        "gridPos": {"h": 8, "w": 24, "x": 0, "y": y},
        "datasource": ZBX_DS,
        "targets": [zbx_target("/downdetector\\.reports\\[.*\\]/")],
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


def latency_timeline_panel(pid, y):
    return {
        "id": pid, "type": "timeseries", "title": "⚡ Latência de Resposta Direta aos Serviços (ms)",
        "gridPos": {"h": 8, "w": 24, "x": 0, "y": y},
        "datasource": ZBX_DS,
        "targets": [zbx_target("/downdetector\\.latency_ms\\[.*\\]/")],
        "options": {
            "tooltip": {"mode": "multi", "sort": "desc"},
            "legend": {"displayMode": "table", "placement": "right", "calcs": ["mean", "max", "last"]},
        },
        "fieldConfig": {
            "defaults": {
                "custom": {
                    "drawStyle": "line",
                    "lineInterpolation": "smooth",
                    "fillOpacity": 10,
                },
                "unit": "ms",
                "min": 0,
                "thresholds": {
                    "mode": "absolute",
                    "steps": [
                        {"color": "green", "value": None},
                        {"color": COLOR_ATTN, "value": 500},
                        {"color": COLOR_PROB, "value": 2000},
                    ],
                },
            },
            "overrides": [],
        },
    }


def categorize_services(services):
    categories = {
        "📱 Redes Sociais & Comunicação": [],
        "📺 Streaming & Vídeo": [],
        "🏦 Bancos & Fintechs": [],
        "☁️ Cloud & Infraestrutura": [],
        "🤖 Inteligência Artificial": [],
        "🏛️ Governo & Serviços Fiscais": [],
        "🌐 Outros Serviços": [],
    }

    social_slugs = {"instagram", "whatsapp", "facebook", "twitter", "telegram", "discord", "facebook-messenger", "linkedin", "snapchat"}
    video_slugs = {"youtube", "netflix", "spotify"}
    bank_slugs = {"pix", "banco-do-brasil", "banco-inter", "banco-itau", "bradesco", "nubank", "bcb", "sicoob", "sicredi", "banrisul", "caixa", "mercadopago"}
    cloud_slugs = {"google", "google-cloud", "google-drive", "aws-amazon-web-services", "microsoft-365", "microsoft-account", "outlook", "hostgator"}
    ai_slugs = {"claude-ai", "openai", "googlegemini"}
    gov_slugs = {"sefaz", "nota-fiscal-eletronica", "receita-federal", "gov-br"}

    for s in services:
        slug = s["slug"]
        if slug in social_slugs:
            categories["📱 Redes Sociais & Comunicação"].append(s)
        elif slug in video_slugs:
            categories["📺 Streaming & Vídeo"].append(s)
        elif slug in bank_slugs:
            categories["🏦 Bancos & Fintechs"].append(s)
        elif slug in cloud_slugs:
            categories["☁️ Cloud & Infraestrutura"].append(s)
        elif slug in ai_slugs:
            categories["🤖 Inteligência Artificial"].append(s)
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

    # Seção de Desempenho & Latência
    panels.append(row_header(current_pid, "⚡ Desempenho & Latência de Rede", current_y))
    current_pid += 1
    current_y += 1
    panels.append(latency_timeline_panel(current_pid, current_y))
    current_pid += 1
    current_y += 8

    # Seção de Históricos & Tendências
    panels.append(row_header(current_pid, "📈 Histórico de Status & Relatos", current_y))
    current_pid += 1
    current_y += 1
    panels.append(status_history_panel(current_pid, current_y))
    current_pid += 1
    current_y += 10
    panels.append(reports_timeline_panel(current_pid, current_y))

    dashboard = {
        "title": "DASHBOARD DOWNDETECTOR",
        "uid": "downdetector-main",
        "schemaVersion": 41, "version": 24,
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
