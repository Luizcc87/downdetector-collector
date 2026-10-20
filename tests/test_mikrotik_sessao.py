from unittest.mock import MagicMock, patch

from librouteros.exceptions import ConnectionClosed, TrapError

from mikrotik.client import MikrotikClient
from mikrotik.config import LinkConfig, RouterConfig
from mikrotik.health import RouterHealthClient


def _router() -> RouterConfig:
    return RouterConfig(
        unit="filial", host="10.0.0.1", api_port=8728, use_ssl=False,
        username="u", password="p", branch="v6", zabbix_host="h", poll_interval=60, links=[],
    )


def _link() -> LinkConfig:
    return LinkConfig(name="link1", routing_table="tbl", targets=["1.1.1.1"])


def _api(reply=None, erro=None):
    api = MagicMock(side_effect=erro) if erro else MagicMock(return_value=iter(reply or []))
    api.close = MagicMock()
    return api


class TestSessao:
    def test_fora_da_sessao_abre_e_fecha_por_operacao(self):
        conexoes = [_api([{"time": "10ms", "received": "1", "sent": "1"}]) for _ in range(2)]
        with patch.object(MikrotikClient, "_connect", side_effect=conexoes) as conn:
            c = MikrotikClient(_router(), ping_count=1)
            c.ping_link(_link(), "1.1.1.1")
            c.ping_link(_link(), "1.1.1.1")
        assert conn.call_count == 2
        assert all(a.close.called for a in conexoes)

    def test_sessao_reaproveita_uma_conexao_e_fecha_no_fim(self):
        api = MagicMock(side_effect=lambda *a, **k: iter([{"time": "10ms", "received": "1", "sent": "1"}]))
        api.close = MagicMock()
        with patch.object(MikrotikClient, "_connect", return_value=api) as conn:
            c = MikrotikClient(_router(), ping_count=1)
            with c.sessao():
                c.ping_link(_link(), "1.1.1.1")
                c.ping_link(_link(), "1.1.1.1")
                assert not api.close.called
        assert conn.call_count == 1
        assert api.close.call_count == 1

    def test_conexao_perdida_reconecta_na_proxima_operacao(self):
        morta = _api(erro=ConnectionClosed("fechada"))
        nova = _api([{"time": "10ms", "received": "1", "sent": "1"}])
        with patch.object(MikrotikClient, "_connect", side_effect=[morta, nova]) as conn:
            c = MikrotikClient(_router(), ping_count=1)
            with c.sessao():
                r1 = c.ping_link(_link(), "1.1.1.1")
                r2 = c.ping_link(_link(), "1.1.1.1")
        assert not r1.ok and r2.ok
        assert conn.call_count == 2
        assert morta.close.called and nova.close.called

    def test_erro_de_comando_nao_derruba_a_conexao(self):
        api = MagicMock(side_effect=TrapError("no such command"))
        api.close = MagicMock()
        with patch.object(RouterHealthClient, "_connect", return_value=api) as conn:
            h = RouterHealthClient(_router())
            with h.sessao():
                h.get_system_resource()
                h.get_vpn_tunnels()
        assert conn.call_count == 1
