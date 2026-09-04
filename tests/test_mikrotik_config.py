from pathlib import Path

import pytest

from mikrotik.config import RouterConfig, load_routers_from_path


@pytest.fixture
def example_yaml(tmp_path: Path) -> Path:
    dst = tmp_path / "routers.yaml"
    dst.write_text(
        """
defaults:
  api_port: 8729
  use_ssl: true
  poll_interval: 90
routers:
  - unit: filial
    host: 192.168.42.2
    branch: v6
    username: zabbix-probe
    password: secret
    zabbix_host: "Mikrotik-Filial"
    links:
      - name: brphonia
        routing_table: to_brphonia
        targets: ["1.1.1.1", "8.8.8.8"]
  - unit: frigorifico
    host: 192.168.0.1
    branch: v7
    username: zabbix-probe
    password: secret
    poll_interval: 60
    zabbix_host: "Mikrotik-Frigorifico"
    links:
      - name: brphonia
        routing_table: to_brphonia
        targets: ["1.1.1.1"]
      - name: globoinfo
        routing_table: to_globo
        targets: ["8.8.8.8"]
""",
        encoding="utf-8",
    )
    return dst


def test_load_returns_list_of_router_configs(example_yaml):
    routers = load_routers_from_path(example_yaml)
    assert len(routers) == 2
    assert all(isinstance(r, RouterConfig) for r in routers)


def test_load_applies_defaults(example_yaml):
    routers = load_routers_from_path(example_yaml)
    filial = next(r for r in routers if r.unit == "filial")
    assert filial.api_port == 8729
    assert filial.use_ssl is True
    assert filial.poll_interval == 90


def test_load_keeps_per_router_override(example_yaml):
    routers = load_routers_from_path(example_yaml)
    frigo = next(r for r in routers if r.unit == "frigorifico")
    assert frigo.poll_interval == 60


def test_load_parses_links(example_yaml):
    routers = load_routers_from_path(example_yaml)
    frigo = next(r for r in routers if r.unit == "frigorifico")
    assert len(frigo.links) == 2
    brphonia = next(l for l in frigo.links if l.name == "brphonia")
    assert brphonia.routing_table == "to_brphonia"
    assert brphonia.targets == ["1.1.1.1"]


def test_routing_param_v6_uses_routing_mark(example_yaml):
    routers = load_routers_from_path(example_yaml)
    filial = next(r for r in routers if r.unit == "filial")
    assert filial.routing_param() == "routing-mark"


def test_routing_param_v7_uses_routing_table(example_yaml):
    routers = load_routers_from_path(example_yaml)
    frigo = next(r for r in routers if r.unit == "frigorifico")
    assert frigo.routing_param() == "routing-table"


def test_invalid_branch_raises_on_load(tmp_path):
    dst = tmp_path / "routers.yaml"
    dst.write_text(
        """
routers:
  - unit: x
    host: 1.2.3.4
    branch: v9
    username: u
    password: p
    zabbix_host: h
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="branch invalido"):
        load_routers_from_path(dst)


def test_duplicate_unit_raises(tmp_path):
    dst = tmp_path / "routers.yaml"
    dst.write_text(
        """
routers:
  - unit: filial
    host: 1.2.3.4
    branch: v6
    username: u
    password: p
    zabbix_host: h
  - unit: filial
    host: 5.6.7.8
    branch: v6
    username: u
    password: p
    zabbix_host: h
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate unit"):
        load_routers_from_path(dst)


def test_link_missing_targets_raises(tmp_path):
    dst = tmp_path / "routers.yaml"
    dst.write_text(
        """
routers:
  - unit: filial
    host: 1.2.3.4
    branch: v6
    username: u
    password: p
    zabbix_host: h
    links:
      - name: brphonia
        routing_table: to_brphonia
        targets: []
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="targets"):
        load_routers_from_path(dst)
