"""Parsing de services.yaml. Fonte única de verdade para a lista de serviços."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml


@dataclass(frozen=True)
class ServiceConfig:
    name: str
    slug: str
    id: int
    logo: str
    poll_interval: int
    country: str

    def url(self) -> str:
        return f"https://downdetector.com.{self.country}/status/{self.slug}/"


_REQUIRED_FIELDS = ("name", "slug", "id", "logo")


def _merge_defaults(item: dict, defaults: dict) -> dict:
    merged = dict(defaults)
    merged.update(item)
    return merged


def _validate(item: dict) -> None:
    missing = [f for f in _REQUIRED_FIELDS if f not in item or item[f] in (None, "")]
    if missing:
        raise ValueError(f"service missing required fields: {missing}; got: {item}")


def load_services_from_path(path: Path) -> list[ServiceConfig]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: root must be a mapping")
    defaults = raw.get("defaults", {}) or {}
    services_raw = raw.get("services", []) or []
    if not isinstance(services_raw, list):
        raise ValueError(f"{path}: 'services' must be a list")

    seen_slugs: set[str] = set()
    result: list[ServiceConfig] = []
    for item in services_raw:
        if not isinstance(item, dict):
            raise ValueError(f"service entry must be a mapping; got {type(item).__name__}")
        merged = _merge_defaults(item, defaults)
        _validate(merged)
        slug = merged["slug"]
        if slug in seen_slugs:
            raise ValueError(f"duplicate slug: {slug}")
        seen_slugs.add(slug)
        result.append(
            ServiceConfig(
                name=merged["name"],
                slug=slug,
                id=int(merged["id"]),
                logo=merged["logo"],
                poll_interval=int(merged.get("poll_interval", 60)),
                country=merged.get("country", "br"),
            )
        )
    return result


def services_to_dict(services: Iterable[ServiceConfig]) -> dict:
    """Useful for LLD JSON output."""
    return {
        "data": [
            {"{#SLUG}": s.slug, "{#NAME}": s.name, "{#ID}": str(s.id)}
            for s in services
        ]
    }
