"""DASHBOARD DOWNDETECTOR v12 — AlanMartines-inspired layout (NO Angular, NO plugins).

Reference: https://github.com/AlanMartines/monitoramento-downdetector-zabbix-grafana
That dashboard uses ONLY native `stat` and `text` panels arranged in a grid —
no table panel, no boomtable, no transformations. Works on any Grafana version
including Grafana 12/13 (no Angular deprecation issues).

Layout per service (1 row = 1 service):
  ┌─────────┬───────────┬──────────────┬────────────┐
  │ Serviço │  Logo     │   Status     │  Relatos   │
  │ Name(id)│ <img/>    │ ESTÁVEL/etc  │ <number>   │
  └─────────┴───────────┴──────────────┴────────────┘
   text       text(html)  stat (mapped)  stat

Top row: 4 count cards (Total/OK/Atenção/Problema) + Downdetector wordmark
Bottom row: 4 scraper-health stats

Panels are generated from /etc/downdetector-collector/services.yaml so adding
a service to the config rebuilds the dashboard automatically.
"""
import json
from pathlib import Path
import yaml

ZBX_DS = {"type": "alexanderzobnin-zabbix-datasource", "uid": "zabbix"}
HOST_GROUP = "Downdetector"
HOST = "Downdetector"

COLOR_GRAY = "#808080"
COLOR_OK = "#2EB85C"
COLOR_ATTN = "#F9B115"
COLOR_PROB = "#E55353"
COLOR_UNK = "#9B59B6"

# Map status code -> mapping config (mimicking AlanMartines's range style)
STATUS_MAPPINGS = [
    {
        "type": "value",
        "options": {
            "0": {"text": "🟢 Ok", "color": COLOR_OK, "index": 0},
            "1": {"text": "🟠 Atenção", "color": COLOR_ATTN, "index": 1},
            "2": {"text": "🔴 Problema", "color": COLOR_PROB, "index": 2},
            "3": {"text": "⚪ Desconhecido", "color": COLOR_UNK, "index": 3},
        },
    }
]

STATUS_THRESHOLDS = {
    "mode": "absolute",
    "steps": [
        {"color": COLOR_OK, "value": None},
        {"color": COLOR_ATTN, "value": 1},
        {"color": COLOR_PROB, "value": 2},
        {"color": COLOR_UNK, "value": 3},
    ],
}


def zbx_target(name_filter, ref="A"):
    return {
        "refId": ref,
        "queryType": "0",
        "resultFormat": "time_series",
        "datasource": ZBX_DS,
        "group": {"filter": HOST_GROUP},
        "host": {"filter": HOST},
        "application": {"filter": ""},
        "item": {"filter": name_filter},
        "functions": [],
    }


# ── TOP ROW ─────────────────────────────────────────────────────────────────

def status_count_panel(panel_id, title, status_value, color, grid_x):
    return {
        "id": panel_id, "type": "stat", "title": title,
        "gridPos": {"h": 6, "w": 5, "x": grid_x, "y": 0},
        "datasource": ZBX_DS,
        "targets": [zbx_target("/.*: status$/")],
        "transformations": [
            {"id": "reduce", "options": {
                "reducers": ["lastNotNull"], "mode": "seriesToRows",
                "includeTimeField": False,
            }},
            {"id": "filterByValue", "options": {
                "filters": [{"fieldName": "Last *", "config": {
                    "id": "equal", "options": {"value": float(status_value)},
                }}],
                "type": "include", "match": "any",
            }},
        ],
        "options": {
            "reduceOptions": {"calcs": ["count"], "fields": "/^Last \\*$/", "values": False},
            "colorMode": "background", "graphMode": "none", "textMode": "value",
            "justifyMode": "center",
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


def total_panel():
    return {
        "id": 1, "type": "stat", "title": "Total de Serviços",
        "gridPos": {"h": 6, "w": 5, "x": 0, "y": 0},
        "datasource": ZBX_DS,
        "targets": [zbx_target("/.*: status$/")],
        "transformations": [
            {"id": "reduce", "options": {
                "reducers": ["lastNotNull"], "mode": "seriesToRows",
                "includeTimeField": False,
            }},
        ],
        "options": {
            "reduceOptions": {"calcs": ["count"], "fields": "/^Last \\*$/", "values": False},
            "colorMode": "background", "graphMode": "none", "textMode": "value",
            "justifyMode": "center",
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


def logo_panel():
    return {
        "id": 6, "type": "text", "title": "",
        "gridPos": {"h": 6, "w": 4, "x": 20, "y": 0},
        "options": {
            "mode": "html",
            "content": (
                '<div style="display:flex;align-items:center;justify-content:center;'
                'height:100%;flex-direction:column;text-align:center;">'
                '<div style="font-size:26px;font-weight:700;letter-spacing:-1px;">'
                '<span style="color:#E74C3C;">Down</span>'
                '<span style="color:#8a8a8a;">detector</span>'
                '<span style="color:#E74C3C;font-size:18px;vertical-align:top;">●</span>'
                '</div>'
                '<div style="font-size:11px;color:#888;letter-spacing:2px;margin-top:4px;">'
                'by Ookla®</div>'
                '</div>'
            ),
        },
        "transparent": True,
    }


# ── PER-SERVICE PANELS (the "table" rows) ────────────────────────────────────

# Each service row is 24 cols wide x 5 high, split as:
#   Serviço (name+id):  w=6   x=0
#   Logo (img):         w=6   x=6
#   Status (stat):      w=6   x=12
#   Relatos (stat):     w=6   x=18
ROW_H = 6
# 3-column layout (24 grid cols / 3 = 8 cols each)
COL_SERVICO_W = 8
COL_STATUS_W = 8
COL_RELATOS_W = 8


def service_card_cell(panel_id, service_name, company_id, logo_url, x, y):
    """Single text panel combining logo (top) + name + (id) below."""
    id_html = (
        f'<div style="color:#888;font-size:12px;margin-top:2px;">'
        f'({company_id})</div>'
        if company_id else ""
    )
    return {
        "id": panel_id, "type": "text", "title": "",
        "gridPos": {"h": ROW_H, "w": COL_SERVICO_W, "x": x, "y": y},
        "options": {
            "mode": "html",
            "content": (
                '<div style="display:flex;flex-direction:column;'
                'align-items:center;justify-content:center;height:100%;'
                'gap:8px;padding:6px;">'
                f'<img src="{logo_url}" style="max-height:48px;max-width:140px;'
                'object-fit:contain;" alt="" onerror="this.style.visibility=\'hidden\'" />'
                f'<div style="font-size:15px;font-weight:600;">{service_name}</div>'
                f'{id_html}'
                '</div>'
            ),
        },
        "transparent": False,
    }


def service_status_cell(panel_id, service_name, x, y):
    """Stat panel querying '<service>: status' item with text+color mappings."""
    return {
        "id": panel_id, "type": "stat", "title": "",
        "gridPos": {"h": ROW_H, "w": COL_STATUS_W, "x": x, "y": y},
        "datasource": ZBX_DS,
        "targets": [zbx_target(f"{service_name}: status")],
        "options": {
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "colorMode": "background", "graphMode": "none", "textMode": "value",
            "justifyMode": "center",
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


def service_reports_cell(panel_id, service_name, x, y):
    """Stat panel for reports count of one service."""
    return {
        "id": panel_id, "type": "stat", "title": "",
        "gridPos": {"h": ROW_H, "w": COL_RELATOS_W, "x": x, "y": y},
        "datasource": ZBX_DS,
        "targets": [zbx_target(f"{service_name}: reports last hour")],
        "options": {
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "colorMode": "value", "graphMode": "area", "textMode": "value",
            "justifyMode": "center",
        },
        "fieldConfig": {
            "defaults": {
                "color": {"mode": "thresholds"},
                "thresholds": {
                    "mode": "absolute",
                    "steps": [
                        {"color": COLOR_OK, "value": None},
                        {"color": COLOR_ATTN, "value": 50},
                        {"color": COLOR_PROB, "value": 100},
                    ],
                },
                "unit": "short", "decimals": 0,
            },
            "overrides": [],
        },
    }


def section_header(panel_id, y):
    """Header row aligned with the 3-column service grid below (8+8+8 = 24)."""
    return {
        "id": panel_id, "type": "text", "title": "",
        "gridPos": {"h": 2, "w": 24, "x": 0, "y": y},
        "options": {
            "mode": "html",
            "content": (
                '<div style="display:grid;grid-template-columns:1fr 1fr 1fr;'
                'font-weight:700;font-size:14px;color:#aaa;text-align:center;'
                'border-bottom:2px solid #444;padding:10px 0;">'
                '<div>Serviço</div><div>Status</div><div>Relatos</div>'
                '</div>'
            ),
        },
        "transparent": True,
    }


def section_title(panel_id, y):
    return {
        "id": panel_id, "type": "text", "title": "",
        "gridPos": {"h": 3, "w": 24, "x": 0, "y": y},
        "options": {
            "mode": "html",
            "content": (
                '<div style="display:flex;align-items:center;justify-content:flex-start;'
                'height:100%;padding-left:8px;">'
                '<h2 style="margin:0;font-size:22px;font-weight:700;letter-spacing:0.5px;">'
                'Painel Downdetector</h2></div>'
            ),
        },
        "transparent": True,
    }


def build_service_rows(services, start_y, start_panel_id):
    """Return a list of panels (3 per service)."""
    panels = []
    pid = start_panel_id
    y = start_y
    for svc in services:
        panels.append(service_card_cell(
            pid, svc["name"], svc.get("id"), svc["logo"], x=0, y=y))
        pid += 1
        panels.append(service_status_cell(pid, svc["name"], x=COL_SERVICO_W, y=y))
        pid += 1
        panels.append(service_reports_cell(
            pid, svc["name"], x=COL_SERVICO_W + COL_STATUS_W, y=y))
        pid += 1
        y += ROW_H
    return panels, y, pid


# ── BOTTOM ROW: scraper health ───────────────────────────────────────────────

def health_stat(panel_id, title, item_name, unit, color, grid_x, grid_y, thresholds=None):
    return {
        "id": panel_id, "type": "stat", "title": title,
        "gridPos": {"h": 5, "w": 6, "x": grid_x, "y": grid_y},
        "datasource": ZBX_DS,
        "targets": [zbx_target(item_name, ref="A")],
        "options": {
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "colorMode": "value", "graphMode": "area", "textMode": "auto",
            "justifyMode": "auto",
        },
        "fieldConfig": {
            "defaults": {
                "color": {"mode": "thresholds" if thresholds else "fixed", "fixedColor": color},
                "unit": unit,
                "thresholds": {
                    "mode": "absolute",
                    "steps": thresholds or [{"color": color, "value": None}],
                },
            },
            "overrides": [],
        },
    }


def scraper_health_row(y):
    return [
        health_stat(900, "Uptime", "Scraper uptime", "s", "blue", 0, y),
        health_stat(901, "Duração do ciclo", "Last cycle duration", "s", "blue", 6, y,
                    thresholds=[
                        {"color": "green", "value": None},
                        {"color": COLOR_ATTN, "value": 30},
                        {"color": COLOR_PROB, "value": 120},
                    ]),
        health_stat(902, "Bloqueios CF (5m)", "Cloudflare blocks (5m)", "short", "green", 12, y,
                    thresholds=[
                        {"color": "green", "value": None},
                        {"color": COLOR_ATTN, "value": 1},
                        {"color": COLOR_PROB, "value": 10},
                    ]),
        health_stat(903, "Reinícios do browser", "Browser restarts", "short", "blue", 18, y),
    ]


# ── BUILD ────────────────────────────────────────────────────────────────────

# Read services from production yaml
services_path = Path("/etc/downdetector-collector/services.yaml")
raw = yaml.safe_load(services_path.read_text())
defaults = raw.get("defaults", {}) or {}
services = []
for s in raw.get("services", []):
    merged = {**defaults, **s}
    services.append(merged)
print(f"Read {len(services)} services from {services_path}")

panels = [
    total_panel(),
    status_count_panel(2, "Serviços Ok", 0, COLOR_OK, 5),
    status_count_panel(3, "Serviços em Atenção", 1, COLOR_ATTN, 10),
    status_count_panel(4, "Serviços com Problema", 2, COLOR_PROB, 15),
    logo_panel(),
]

# Title row at y=6 (h=3, taller for readability)
panels.append(section_title(500, y=6))
# Header row at y=9 (right after title)
panels.append(section_header(501, y=9))

# Service rows starting at y=11
service_panels, next_y, _ = build_service_rows(services, start_y=11, start_panel_id=100)
panels.extend(service_panels)

# Scraper health row after the services
panels.extend(scraper_health_row(y=next_y + 1))

dashboard = {
    "title": "DASHBOARD DOWNDETECTOR",
    "uid": "downdetector-main",
    "schemaVersion": 41,
    "version": 13,
    "editable": True,
    "refresh": "1h",
    "time": {"from": "now-1h", "to": "now"},
    "timezone": "browser",
    "tags": ["downdetector"],
    "annotations": {"list": []},
    "templating": {"list": []},
    "panels": panels,
}

out = Path("/var/lib/grafana/dashboards/downdetector/dashboard_downdetector.json")
out.write_text(json.dumps(dashboard, indent=2, ensure_ascii=False))
print(f"wrote dashboard v{dashboard['version']} with {len(dashboard['panels'])} panels")
