from unittest.mock import MagicMock, patch

import pytest

from mikrotik.config import RouterConfig
from mikrotik.health import RouterHealthClient, _uptime_to_seconds


def _router() -> RouterConfig:
    return RouterConfig(
        unit="filial",
        host="192.168.42.2",
        api_port=8729,
        use_ssl=True,
        username="zabbix-probe",
        password="secret",
        branch="v6",
        zabbix_host="Mikrotik-Filial",
        poll_interval=90,
        links=[],
        monitored_interfaces=["ether5-LAN"],
    )


def _dispatch_api(responses: dict):
    api = MagicMock()
    api.side_effect = lambda cmd, **kw: iter(responses.get(cmd, []))
    api.close = MagicMock()
    return api


class TestUptimeParsing:
    def test_full_format(self):
        assert _uptime_to_seconds("11w4d4h59m11s") == (
            11 * 604800 + 4 * 86400 + 4 * 3600 + 59 * 60 + 11
        )

    def test_seconds_only(self):
        assert _uptime_to_seconds("42s") == 42

    def test_unrecognized_returns_none(self):
        assert _uptime_to_seconds("") is None


class TestSystemResource:
    def test_parses_real_fields(self):
        router = _router()
        api = _dispatch_api({
            "/system/resource/print": [{
                "cpu-load": 2, "free-memory": 213626880, "total-memory": 268435456,
                "uptime": "11w4d4h59m11s",
            }],
        })
        client = RouterHealthClient(router)
        with patch.object(RouterHealthClient, "_connect", return_value=api):
            result = client.get_system_resource()

        assert result.cpu_load_pct == 2
        assert result.free_memory_bytes == 213626880
        assert result.total_memory_bytes == 268435456
        assert result.uptime_seconds == _uptime_to_seconds("11w4d4h59m11s")

    def test_connect_failure_returns_none(self):
        router = _router()
        client = RouterHealthClient(router)
        with patch.object(RouterHealthClient, "_connect", side_effect=OSError("no route")):
            assert client.get_system_resource() is None

    def test_empty_response_returns_none(self):
        router = _router()
        api = _dispatch_api({"/system/resource/print": []})
        client = RouterHealthClient(router)
        with patch.object(RouterHealthClient, "_connect", return_value=api):
            assert client.get_system_resource() is None


class TestInterfaceTraffic:
    def test_returns_rx_tx_per_interface(self):
        router = _router()
        api = _dispatch_api({
            "/interface/monitor-traffic": [{"rx-bits-per-second": 3703704, "tx-bits-per-second": 257000}],
        })
        client = RouterHealthClient(router)
        with patch.object(RouterHealthClient, "_connect", return_value=api):
            result = client.get_interface_traffic(["ether5-LAN"])

        assert len(result) == 1
        assert result[0].name == "ether5-LAN"
        assert result[0].rx_bps == 3703704
        assert result[0].tx_bps == 257000

    def test_empty_list_skips_connection(self):
        router = _router()
        client = RouterHealthClient(router)
        with patch.object(RouterHealthClient, "_connect") as mock_connect:
            result = client.get_interface_traffic([])
        assert result == []
        mock_connect.assert_not_called()


class TestVpnTunnels:
    def test_filters_by_type_and_disabled(self):
        router = _router()
        api = _dispatch_api({
            "/interface/print": [
                {"name": "<l2tp-globoinfo-l2tp>", "type": "l2tp-in", "running": True, "disabled": False},
                {"name": "eoip-tunnel-Brphonia-Matriz", "type": "eoip", "running": True, "disabled": False},
                {"name": "l2tp-schlosser", "type": "l2tp-out", "running": False, "disabled": True},
                {"name": "ether1-Globoinfo", "type": "ether", "running": True, "disabled": False},
            ],
        })
        client = RouterHealthClient(router)
        with patch.object(RouterHealthClient, "_connect", return_value=api):
            tunnels = client.get_vpn_tunnels()

        names = {t.name for t in tunnels}
        assert names == {"l2tp-globoinfo-l2tp", "eoip-tunnel-Brphonia-Matriz"}
        assert all(t.up for t in tunnels)

    def test_down_tunnel_reported(self):
        router = _router()
        api = _dispatch_api({
            "/interface/print": [
                {"name": "<l2tp-globoinfo-l2tp>", "type": "l2tp-in", "running": False, "disabled": False},
            ],
        })
        client = RouterHealthClient(router)
        with patch.object(RouterHealthClient, "_connect", return_value=api):
            tunnels = client.get_vpn_tunnels()
        assert tunnels[0].up is False


class TestNewLogs:
    def test_first_call_returns_no_entries_only_baseline(self):
        router = _router()
        api = _dispatch_api({
            "/log/print": [
                {".id": "*1", "topics": "system", "message": "a"},
                {".id": "*2", "topics": "system", "message": "b"},
            ],
        })
        client = RouterHealthClient(router)
        with patch.object(RouterHealthClient, "_connect", return_value=api):
            entries, since_id = client.get_new_logs(since_id=None)
        assert entries == []
        assert since_id == "*2"

    def test_returns_only_entries_after_since_id(self):
        router = _router()
        api = _dispatch_api({
            "/log/print": [
                {".id": "*1", "topics": "system", "message": "a"},
                {".id": "*2", "topics": "system", "message": "b"},
                {".id": "*3", "topics": "system", "message": "c"},
            ],
        })
        client = RouterHealthClient(router)
        with patch.object(RouterHealthClient, "_connect", return_value=api):
            entries, since_id = client.get_new_logs(since_id="*1")
        assert [e.id for e in entries] == ["*2", "*3"]
        assert since_id == "*3"

    def test_rotated_buffer_falls_back_to_recent_entries(self):
        router = _router()
        api = _dispatch_api({
            "/log/print": [
                {".id": "*10", "topics": "system", "message": "x"},
                {".id": "*11", "topics": "system", "message": "y"},
            ],
        })
        client = RouterHealthClient(router)
        with patch.object(RouterHealthClient, "_connect", return_value=api):
            entries, since_id = client.get_new_logs(since_id="*1", limit=1)
        assert [e.id for e in entries] == ["*11"]
        assert since_id == "*11"

    def test_connect_failure_preserves_since_id(self):
        router = _router()
        client = RouterHealthClient(router)
        with patch.object(RouterHealthClient, "_connect", side_effect=OSError("down")):
            entries, since_id = client.get_new_logs(since_id="*5")
        assert entries == []
        assert since_id == "*5"
