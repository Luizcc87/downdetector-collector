from unittest.mock import MagicMock, patch

import pytest
from librouteros.exceptions import LibRouterosError

from mikrotik.client import MikrotikClient, _parse_rtt_ms
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
