"""Parsing de routers.yaml. Fonte unica de verdade para roteadores/links monitorados.

Modulo irmao de collector/config.py -- mesma forma (dataclass congelado +
loader puro), schema diferente. Nao reaproveita ServiceConfig porque o
dominio e outro (roteador -> N links, nao 1 servico -> 1 URL).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

# CORRIGIDO em 2026-09-04 apos teste de campo real contra a Filial
# (192.168.42.2, RouterOS 6.49.10): /ping usa `routing-table=` tanto em v6
# quanto em v7 -- `routing-mark=` nao existe como parametro da ferramenta
# /ping em nenhuma das duas branches testadas ("unknown parameter").
# O que muda entre v6/v7 e SO a sintaxe de criacao da tabela/mark em
# /ip route (fora do escopo deste modulo -- ver secao 2.2 da proposta), nao
# o parametro usado aqui. `branch` fica no schema por documentacao (qual
# receita de PBR aplicar no roteador), mas nao influencia mais o /ping.
PING_ROUTING_PARAM = "routing-table"


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
    branch: str  # "v6" ou "v7" -- so documentacao, ver PING_ROUTING_PARAM acima
    zabbix_host: str  # host Zabbix que recebe as metricas desta unidade
    poll_interval: int
    links: list[LinkConfig] = field(default_factory=list)

    def routing_param(self) -> str:
        return PING_ROUTING_PARAM


_REQUIRED_ROUTER_FIELDS = ("unit", "host", "username", "password", "branch", "zabbix_host")
_REQUIRED_LINK_FIELDS = ("name", "routing_table", "targets")
_VALID_BRANCHES = ("v6", "v7")


def _merge_defaults(item: dict, defaults: dict) -> dict:
    merged = dict(defaults)
    merged.update(item)
    return merged


def _validate_router(item: dict) -> None:
    missing = [f for f in _REQUIRED_ROUTER_FIELDS if f not in item or item[f] in (None, "")]
    if missing:
        raise ValueError(f"router missing required fields: {missing}; got: {item}")
    if item["branch"] not in _VALID_BRANCHES:
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
