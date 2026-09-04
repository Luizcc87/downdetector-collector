"""Parsing de routers.yaml. Fonte unica de verdade para roteadores/links monitorados.

Modulo irmao de collector/config.py -- mesma forma (dataclass congelado +
loader puro), schema diferente. Nao reaproveita ServiceConfig porque o
dominio e outro (roteador -> N links, nao 1 servico -> 1 URL).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

# RouterOS v6 usa `routing-mark=` no /ping e /tool traceroute; v7 usa
# `routing-table=` (tabela nomeada). Mesmo conceito, parametro de API diferente
# -- ver 07-Propostas-Melhoria/2026-09-04_geral_monitoramento_links-wan-pbr-rotas-mikrotik.md
# secao 2.2 no repo Analise-TI-CCZaleski.
ROUTING_PARAM_BY_BRANCH = {
    "v6": "routing-mark",
    "v7": "routing-table",
}


@dataclass(frozen=True)
class LinkConfig:
    name: str  # ex.: "brphonia", "globoinfo", "starlink"
    routing_table: str  # nome da tabela/mark no Mikrotik, ex.: "to_brphonia"
    targets: list[str]  # ancoras publicas + gateway do ISP (secao 3.1 da proposta)


@dataclass(frozen=True)
class RouterConfig:
    unit: str  # ex.: "filial", "matriz", "frigorifico"
    host: str
    api_port: int
    use_ssl: bool
    username: str
    password: str
    branch: str  # "v6" ou "v7" -- decide o nome do parametro de rota
    zabbix_host: str  # host Zabbix que recebe as metricas desta unidade
    poll_interval: int
    links: list[LinkConfig] = field(default_factory=list)

    def routing_param(self) -> str:
        try:
            return ROUTING_PARAM_BY_BRANCH[self.branch]
        except KeyError as exc:
            raise ValueError(
                f"branch desconhecido: {self.branch!r} (esperado 'v6' ou 'v7')"
            ) from exc


_REQUIRED_ROUTER_FIELDS = ("unit", "host", "username", "password", "branch", "zabbix_host")
_REQUIRED_LINK_FIELDS = ("name", "routing_table", "targets")


def _merge_defaults(item: dict, defaults: dict) -> dict:
    merged = dict(defaults)
    merged.update(item)
    return merged


def _validate_router(item: dict) -> None:
    missing = [f for f in _REQUIRED_ROUTER_FIELDS if f not in item or item[f] in (None, "")]
    if missing:
        raise ValueError(f"router missing required fields: {missing}; got: {item}")
    if item["branch"] not in ROUTING_PARAM_BY_BRANCH:
        raise ValueError(f"router {item.get('unit')!r}: branch invalido {item['branch']!r}")


def _validate_link(item: dict, unit: str) -> None:
    missing = [f for f in _REQUIRED_LINK_FIELDS if f not in item or item[f] in (None, "")]
    if missing:
        raise ValueError(f"link missing required fields: {missing}; got: {item} (unit={unit})")
    if not isinstance(item["targets"], list) or not item["targets"]:
        raise ValueError(f"router {unit!r} link {item.get('name')!r}: 'targets' deve ser lista nao-vazia")


def _load_links(raw_links: list, unit: str) -> list[LinkConfig]:
    links: list[LinkConfig] = []
    seen_names: set[str] = set()
    for item in raw_links:
        if not isinstance(item, dict):
            raise ValueError(f"link entry deve ser mapping; got {type(item).__name__} (unit={unit})")
        _validate_link(item, unit)
        name = item["name"]
        if name in seen_names:
            raise ValueError(f"router {unit!r}: link duplicado {name!r}")
        seen_names.add(name)
        links.append(
            LinkConfig(
                name=name,
                routing_table=item["routing_table"],
                targets=list(item["targets"]),
            )
        )
    return links


def load_routers_from_path(path: Path) -> list[RouterConfig]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: root deve ser um mapping")
    defaults = raw.get("defaults", {}) or {}
    routers_raw = raw.get("routers", []) or []
    if not isinstance(routers_raw, list):
        raise ValueError(f"{path}: 'routers' deve ser uma lista")

    seen_units: set[str] = set()
    result: list[RouterConfig] = []
    for item in routers_raw:
        if not isinstance(item, dict):
            raise ValueError(f"router entry deve ser mapping; got {type(item).__name__}")
        merged = _merge_defaults(item, defaults)
        _validate_router(merged)
        unit = merged["unit"]
        if unit in seen_units:
            raise ValueError(f"duplicate unit: {unit}")
        seen_units.add(unit)
        links = _load_links(merged.get("links", []) or [], unit)
        result.append(
            RouterConfig(
                unit=unit,
                host=merged["host"],
                api_port=int(merged.get("api_port", 8729)),
                use_ssl=bool(merged.get("use_ssl", True)),
                username=merged["username"],
                password=merged["password"],
                branch=merged["branch"],
                zabbix_host=merged["zabbix_host"],
                poll_interval=int(merged.get("poll_interval", 90)),
                links=links,
            )
        )
    return result
