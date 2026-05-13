"""DASHBOARD DOWNDETECTOR v19 — Layout do Cristiano.

Topo (h=3, linha única, 24 cols):
  Total(2) Ok(2) Atn(2) Prob(3) | Uptime(3) Cycle(4) CF(4) Restarts(4)

Título (h=2)

Cada card de serviço (w=3, h=8, 8 por linha):
  ┌────────────┐
  │   <logo>   │  ← text panel (h=4): logo + nome
  │   Nome     │
  ├────────────┤
  │  🟢 Ok     │  ← stat panel (h=2): status mapeado/colorido
  ├────────────┤
  │  35 R      │  ← stat panel (h=2): número de relatos
  └────────────┘
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

# Grid: 24 cols. 8 cards per row, each w=3.
CARDS_PER_ROW = 8
CARD_W = 24 // CARDS_PER_ROW  # = 3
LOGO_H = 4
STATUS_H = 2
REPORTS_H = 2
CARD_H = LOGO_H + STATUS_H + REPORTS_H  # = 8

# Topo: linha única de h=3 com contadores (esq) + saúde do scraper (dir)
TOP_H = 3
TITLE_Y = 3
TITLE_H = 2
SERVICES_Y = TITLE_Y + TITLE_H  # = 5


def zbx_target(name_filter, ref="A"):
    return {
        "refId": ref, "queryType": "0", "resultFormat": "time_series",
        "datasource": ZBX_DS,
        "group": {"filter": HOST_GROUP}, "host": {"filter": HOST},
        "application": {"filter": ""}, "item": {"filter": name_filter},
        "functions": [],
    }


# ── TOP ROW ─────────────────────────────────────────────────────────────────

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


def section_title(pid, y):
    return {
        "id": pid, "type": "text", "title": "",
        "gridPos": {"h": TITLE_H, "w": 24, "x": 0, "y": y},
        "options": {
            "mode": "html",
            "content": (
                '<div style="display:flex;align-items:center;justify-content:flex-start;'
                'height:100%;padding-left:8px;">'
                '<h2 style="margin:0;font-size:20px;font-weight:700;">'
                'Painel Downdetector</h2></div>'
            ),
        },
        "transparent": True,
    }


# ── SERVICE CARDS ───────────────────────────────────────────────────────────

def card_logo(pid, name, logo_url, x, y):
    """Topo do card: logo + nome do serviço."""
    return {
        "id": pid, "type": "text", "title": "",
        "gridPos": {"h": LOGO_H, "w": CARD_W, "x": x, "y": y},
        "options": {
            "mode": "html",
            "content": (
                '<div style="display:flex;flex-direction:column;align-items:center;'
                'justify-content:center;height:100%;padding:2px;gap:2px;'
                'background:#1f1f1f;border-radius:4px 4px 0 0;">'
                f'<img src="{logo_url}" style="max-height:32px;max-width:80%;'
                'object-fit:contain;" onerror="this.style.display=\'none\'" />'
                '<div style="font-size:10px;font-weight:600;text-align:center;'
                'line-height:1.1;color:#ddd;max-width:100%;overflow:hidden;'
                'text-overflow:ellipsis;white-space:nowrap;padding:0 4px;">'
                f'{name}</div>'
                '</div>'
            ),
        },
        "transparent": True,
    }


def card_status(pid, name, x, y):
    """Meio do card: stat com background colorido mostrando o status mapeado."""
    return {
        "id": pid, "type": "stat", "title": "",
        "gridPos": {"h": STATUS_H, "w": CARD_W, "x": x, "y": y},
        "datasource": ZBX_DS,
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


def card_reports(pid, name, x, y):
    """Fim do card: stat com o número de relatos da última hora."""
    return {
        "id": pid, "type": "stat", "title": "",
        "gridPos": {"h": REPORTS_H, "w": CARD_W, "x": x, "y": y},
        "datasource": ZBX_DS,
        "targets": [zbx_target(f"{name}: reports last hour")],
        "options": {
            "reduceOptions": {"calcs": ["last"], "fields": "", "values": False},
            "colorMode": "value", "graphMode": "none", "textMode": "value_and_name",
            "justifyMode": "center",
        },
        "fieldConfig": {
            "defaults": {
                "color": {"mode": "thresholds"},
                "thresholds": {
                    "mode": "absolute",
                    "steps": [
                        {"color": "#3498DB", "value": None},
                        {"color": COLOR_ATTN, "value": 30},
                        {"color": COLOR_PROB, "value": 100},
                    ],
                },
                "displayName": "R",
                "unit": "short",
                "decimals": 0,
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
        panels.append(card_logo(pid, svc["name"], svc["logo"], x=x, y=y))
        pid += 1
        panels.append(card_status(pid, svc["name"], x=x, y=y + LOGO_H))
        pid += 1
        panels.append(card_reports(pid, svc["name"], x=x, y=y + LOGO_H + STATUS_H))
        pid += 1
        col += 1
        if col >= CARDS_PER_ROW:
            col = 0
            y += CARD_H
    if col > 0:
        y += CARD_H
    return panels, y, pid


# ── HEALTH ROW ──────────────────────────────────────────────────────────────

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


# ── BUILD ───────────────────────────────────────────────────────────────────

cfg = yaml.safe_load(Path("/etc/downdetector-collector/services.yaml").read_text())
defaults = cfg.get("defaults", {}) or {}
services = [{**defaults, **s} for s in cfg.get("services", [])]
print(f"Read {len(services)} services from production yaml")

panels = [
    # Linha do topo (h=3), contadores à esquerda + saúde do scraper à direita
    total_panel(),                                              # x=0  w=2
    status_count_panel(2, "Ok", 0, COLOR_OK, gx=2, gw=2),         # x=2  w=2
    status_count_panel(3, "Atenção", 1, COLOR_ATTN, gx=4, gw=2),  # x=4  w=2
    status_count_panel(4, "Problema", 2, COLOR_PROB, gx=6, gw=3), # x=6  w=3
    health_stat(900, "Uptime", "Scraper uptime", "s", "blue", gx=9, gw=3),         # x=9  w=3
    health_stat(901, "Duração do ciclo", "Last cycle duration", "s", "blue", gx=12, gw=4,
                thresholds=[{"color": "green", "value": None},
                            {"color": COLOR_ATTN, "value": 30},
                            {"color": COLOR_PROB, "value": 120}]),                  # x=12 w=4
    health_stat(902, "Bloqueios CF (5m)", "Cloudflare blocks (5m)", "short", "green", gx=16, gw=4,
                thresholds=[{"color": "green", "value": None},
                            {"color": COLOR_ATTN, "value": 1},
                            {"color": COLOR_PROB, "value": 10}]),                   # x=16 w=4
    health_stat(903, "Restarts browser", "Browser restarts", "short", "blue", gx=20, gw=4), # x=20 w=4
    # Título
    section_title(500, y=TITLE_Y),
]

service_panels, next_y, _ = build_service_grid(services, start_y=SERVICES_Y, start_pid=100)
panels.extend(service_panels)

dashboard = {
    "title": "DASHBOARD DOWNDETECTOR",
    "uid": "downdetector-main",
    "schemaVersion": 41, "version": 19,
    "editable": True, "refresh": "1h",
    "time": {"from": "now-1h", "to": "now"},
    "timezone": "America/Sao_Paulo", "tags": ["downdetector"],
    "annotations": {"list": []}, "templating": {"list": []},
    "panels": panels,
}

out = Path("/var/lib/grafana/dashboards/downdetector/dashboard_downdetector.json")
out.write_text(json.dumps(dashboard, indent=2, ensure_ascii=False))
print(f"wrote v{dashboard['version']} with {len(panels)} panels (last_y={next_y})")
