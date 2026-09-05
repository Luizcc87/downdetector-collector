from unittest.mock import MagicMock, patch

import pytest
from librouteros.exceptions import LibRouterosError

from mikrotik.client import MikrotikClient, _parse_rtt_ms, _to_float
from mikrotik.config import LinkConfig, RouterConfig


def _router(branch: str = "v7") -> RouterConfig:
    return RouterConfig(
        unit="frigorifico",
        host="192.168.0.1",
        api_port=8729,
        use_ssl=True,
        username="zabbix-probe",
        password="secret",
        branch=branch,
        zabbix_host="Mikrotik-Frigorifico",
        poll_interval=90,
        links=[],
    )


def _link() -> LinkConfig:
    return LinkConfig(name="brphonia", routing_table="to_brphonia", targets=["1.1.1.1"])


class TestParseRtt:
    def test_ms_only(self):
        assert _parse_rtt_ms("3ms") == 3

    def test_ms_and_us(self):
        assert _parse_rtt_ms("1ms200us") == pytest.approx(1.2)

    def test_unrecognized_returns_none(self):
        assert _parse_rtt_ms("timeout") is None


class TestPingLink:
    def _fake_api(self, replies: list[dict]):
        api = MagicMock()
        api.return_value = iter(replies)
        api.close = MagicMock()
        return api

    def test_all_replies_ok_computes_avg_and_zero_loss(self):
        router = _router(branch="v7")
        replies = [{"time": "1ms"}, {"time": "3ms"}, {"time": "2ms"}]
        api = self._fake_api(replies)
        client = MikrotikClient(router, ping_count=3)
        with patch.object(MikrotikClient, "_connect", return_value=api):
            result = client.ping_link(_link(), "1.1.1.1")

        assert result.ok is True
        assert result.received == 3
        assert result.sent == 3
        assert result.packet_loss_pct == 0.0
        assert result.avg_rtt_ms == pytest.approx(2.0)

    def test_partial_loss_computes_percentage(self):
        router = _router(branch="v7")
        # count=5 pedido, so 3 respostas com time valido chegaram
        replies = [{"time": "1ms"}, {"time": "1ms"}, {"time": "1ms"}]
        api = self._fake_api(replies)
        client = MikrotikClient(router, ping_count=5)
        with patch.object(MikrotikClient, "_connect", return_value=api):
            result = client.ping_link(_link(), "1.1.1.1")

        assert result.sent == 5
        assert result.received == 3
        assert result.packet_loss_pct == 40.0
        assert result.ok is True

    def test_total_loss_marks_not_ok(self):
        router = _router(branch="v7")
        api = self._fake_api([])
        client = MikrotikClient(router, ping_count=5)
        with patch.object(MikrotikClient, "_connect", return_value=api):
            result = client.ping_link(_link(), "1.1.1.1")

        assert result.ok is False
        assert result.packet_loss_pct == 100.0
        assert result.avg_rtt_ms is None

    def test_connect_failure_returns_not_ok_without_raising(self):
        router = _router(branch="v7")
        client = MikrotikClient(router, ping_count=5)
        with patch.object(MikrotikClient, "_connect", side_effect=OSError("no route")):
            result = client.ping_link(_link(), "1.1.1.1")

        assert result.ok is False
        assert result.error == "connect_failed"

    def test_uses_routing_table_param_for_v7(self):
        router = _router(branch="v7")
        api = self._fake_api([{"time": "1ms"}])
        client = MikrotikClient(router, ping_count=1)
        with patch.object(MikrotikClient, "_connect", return_value=api):
            client.ping_link(_link(), "1.1.1.1")

        _, kwargs = api.call_args
        assert kwargs["routing-table"] == "to_brphonia"
        assert "routing-mark" not in kwargs

    def test_uses_routing_table_param_for_v6_too(self):
        # Confirmado em campo em 2026-09-04 contra a Filial (v6.49.10, real):
        # /ping usa routing-table= tanto em v6 quanto em v7 -- routing-mark=
        # nao existe como parametro da ferramenta ("unknown parameter").
        router = _router(branch="v6")
        api = self._fake_api([{"time": "1ms"}])
        client = MikrotikClient(router, ping_count=1)
        with patch.object(MikrotikClient, "_connect", return_value=api):
            client.ping_link(_link(), "1.1.1.1")

        _, kwargs = api.call_args
        assert kwargs["routing-table"] == "to_brphonia"
        assert "routing-mark" not in kwargs

    def test_ping_command_error_does_not_raise(self):
        router = _router(branch="v7")
        api = MagicMock()
        api.side_effect = LibRouterosError("bad command")
        api.close = MagicMock()
        client = MikrotikClient(router, ping_count=5)
        with patch.object(MikrotikClient, "_connect", return_value=api):
            result = client.ping_link(_link(), "1.1.1.1")

        assert result.ok is False
        assert result.error == "ping_command_failed"


def _dispatch_api(responses: dict):
    """Mock que despacha por nome de comando (ignora kwargs de filtro --
    suficiente pra testar os dois ramos de resolve_gateway)."""
    api = MagicMock()
    api.side_effect = lambda cmd, **kw: iter(responses.get(cmd, []))
    api.close = MagicMock()
    return api


class TestResolveGateway:
    def test_gateway_already_ip_returns_directly(self):
        # Caso Brphonia real: gateway da rota ja e um IP fixo (P2P).
        router = _router(branch="v6")
        api = _dispatch_api({
            "/ip/route/print": [
                {"dst-address": "0.0.0.0/0", "gateway": "177.74.144.109", "routing-mark": "to_brphonia"},
            ],
        })
        client = MikrotikClient(router)
        with patch.object(MikrotikClient, "_connect", return_value=api):
            result = client.resolve_gateway(LinkConfig(name="brphonia", routing_table="to_brphonia", targets=["1.1.1.1"]))
        assert result == "177.74.144.109"

    def test_gateway_is_interface_name_resolves_via_pppoe_monitor(self):
        # Caso GloboInfo real: gateway da rota e o NOME da interface PPPoE,
        # resolvido via /interface/pppoe-client/monitor -> remote-address.
        router = _router(branch="v6")
        api = _dispatch_api({
            "/ip/route/print": [
                {"dst-address": "0.0.0.0/0", "gateway": "pppoe-globoinfo", "routing-mark": "to_globoinfo"},
            ],
            "/interface/pppoe-client/monitor": [
                {"status": "connected", "remote-address": "100.65.0.1", "local-address": "138.94.183.96"},
            ],
        })
        client = MikrotikClient(router)
        with patch.object(MikrotikClient, "_connect", return_value=api):
            result = client.resolve_gateway(LinkConfig(name="globoinfo", routing_table="to_globoinfo", targets=["1.1.1.1"]))
        assert result == "100.65.0.1"

    def test_no_route_found_returns_none(self):
        router = _router(branch="v6")
        api = _dispatch_api({"/ip/route/print": []})
        client = MikrotikClient(router)
        with patch.object(MikrotikClient, "_connect", return_value=api):
            result = client.resolve_gateway(LinkConfig(name="globoinfo", routing_table="to_globoinfo", targets=["1.1.1.1"]))
        assert result is None

    def test_pppoe_monitor_without_remote_address_returns_none(self):
        router = _router(branch="v6")
        api = _dispatch_api({
            "/ip/route/print": [
                {"dst-address": "0.0.0.0/0", "gateway": "pppoe-globoinfo", "routing-mark": "to_globoinfo"},
            ],
            "/interface/pppoe-client/monitor": [{"status": "disconnected"}],
        })
        client = MikrotikClient(router)
        with patch.object(MikrotikClient, "_connect", return_value=api):
            result = client.resolve_gateway(LinkConfig(name="globoinfo", routing_table="to_globoinfo", targets=["1.1.1.1"]))
        assert result is None

    def test_connect_failure_returns_none_without_raising(self):
        router = _router(branch="v6")
        client = MikrotikClient(router)
        with patch.object(MikrotikClient, "_connect", side_effect=OSError("no route")):
            result = client.resolve_gateway(LinkConfig(name="globoinfo", routing_table="to_globoinfo", targets=["1.1.1.1"]))
        assert result is None


class TestToFloat:
    def test_string_decimal(self):
        assert _to_float("21.1") == 21.1

    def test_int(self):
        assert _to_float(2) == 2.0

    def test_none_returns_none(self):
        assert _to_float(None) is None

    def test_empty_string_returns_none(self):
        assert _to_float("") is None

    def test_unparseable_returns_none(self):
        assert _to_float("timeout") is None


class TestTracerouteLink:
    def test_uses_last_section_and_numbers_hops_by_position(self):
        # Replica o formato real observado contra a Filial em 2026-09-04:
        # multiplas secoes (uma por repeticao de count), usa a ultima.
        router = _router(branch="v7")
        api = _dispatch_api({
            "/tool/traceroute": [
                {"address": "", "loss": 100, ".section": 0},
                {"address": "172.30.30.106", "avg": "21.1", "loss": 0, ".section": 0},
                {"address": "", "loss": 100, ".section": 1},
                {"address": "172.30.30.106", "avg": "2.1", "loss": 0, ".section": 1},
                {"address": "1.1.1.1", "avg": 14, "loss": 0, ".section": 1},
            ],
        })
        client = MikrotikClient(router)
        with patch.object(MikrotikClient, "_connect", return_value=api):
            hops = client.traceroute_link(
                LinkConfig(name="brphonia", routing_table="to_brphonia", targets=["1.1.1.1"]),
                "1.1.1.1",
            )

        assert len(hops) == 3
        assert hops[0].hop == 1
        assert hops[0].address is None  # hop 1 nao respondeu (timeout)
        assert hops[0].ok is False
        assert hops[1].hop == 2
        assert hops[1].address == "172.30.30.106"
        assert hops[1].avg_rtt_ms == 2.1
        assert hops[2].hop == 3
        assert hops[2].address == "1.1.1.1"
        assert hops[2].avg_rtt_ms == 14.0

    def test_respects_max_hops(self):
        router = _router(branch="v7")
        rows = [{"address": f"10.0.0.{i}", "avg": "1", "loss": 0, ".section": 0} for i in range(20)]
        api = _dispatch_api({"/tool/traceroute": rows})
        client = MikrotikClient(router)
        with patch.object(MikrotikClient, "_connect", return_value=api):
            hops = client.traceroute_link(
                LinkConfig(name="globoinfo", routing_table="to_globoinfo", targets=["1.1.1.1"]),
                "1.1.1.1",
                max_hops=5,
            )
        assert len(hops) == 5

    def test_empty_response_returns_empty_list(self):
        router = _router(branch="v7")
        api = _dispatch_api({"/tool/traceroute": []})
        client = MikrotikClient(router)
        with patch.object(MikrotikClient, "_connect", return_value=api):
            hops = client.traceroute_link(
                LinkConfig(name="globoinfo", routing_table="to_globoinfo", targets=["1.1.1.1"]),
                "1.1.1.1",
            )
        assert hops == []

    def test_connect_failure_returns_empty_list(self):
        router = _router(branch="v7")
        client = MikrotikClient(router)
        with patch.object(MikrotikClient, "_connect", side_effect=OSError("no route")):
            hops = client.traceroute_link(
                LinkConfig(name="globoinfo", routing_table="to_globoinfo", targets=["1.1.1.1"]),
                "1.1.1.1",
            )
        assert hops == []

    def test_command_error_returns_empty_list(self):
        router = _router(branch="v7")
        api = MagicMock()
        api.side_effect = LibRouterosError("bad command")
        api.close = MagicMock()
        client = MikrotikClient(router)
        with patch.object(MikrotikClient, "_connect", return_value=api):
            hops = client.traceroute_link(
                LinkConfig(name="globoinfo", routing_table="to_globoinfo", targets=["1.1.1.1"]),
                "1.1.1.1",
            )
        assert hops == []
