"""Conexao API reaproveitada durante um ciclo de coleta.

Antes cada operacao (ping de cada alvo, resolucao de gateway, traceroute,
cada consulta de saude) abria e fechava a sua conexao. A RB registra um
login/logout por conexao: na Filial eram dezenas por minuto no log (topico
account), enchendo o buffer de memoria e escondendo os eventos reais
(observado em 2026-10-20). Com sessao(), o ciclo inteiro usa UMA conexao.

A conexao continua descartavel (roteador pode cair): fechada no fim do
ciclo e descartada se um comando indicar que ela morreu -- a proxima
operacao reconecta, como antes. Fora de sessao(), o comportamento e o
antigo (uma conexao por operacao). Nao e thread-safe: as operacoes de um
roteador rodam em sequencia (mikrotik/__main__.py).
"""

from __future__ import annotations

from contextlib import contextmanager

from librouteros.exceptions import ConnectionClosed, FatalError

# Erros depois dos quais a conexao nao serve mais. ProtocolError NAO entra: TrapError
# (comando recusado, ex.: "no such command") herda dele e a conexao continua boa.
_CONEXAO_PERDIDA = (ConnectionClosed, FatalError)


class ConexaoDoCiclo:
    """Base para os clientes: exige `_connect()` na subclasse."""

    _em_sessao: bool = False
    _compartilhada = None

    @contextmanager
    def sessao(self):
        self._em_sessao = True
        try:
            yield self
        finally:
            self._em_sessao = False
            self._descartar()

    def _abrir(self):
        if not self._em_sessao:
            return self._connect()
        if self._compartilhada is None:
            self._compartilhada = self._connect()
        return self._compartilhada

    def _liberar(self, api) -> None:
        if api is self._compartilhada:
            return
        try:
            api.close()
        except Exception:
            pass

    def _descartar(self) -> None:
        api, self._compartilhada = self._compartilhada, None
        if api is not None:
            try:
                api.close()
            except Exception:
                pass

    def _descartar_se_perdida(self, exc: BaseException) -> None:
        if isinstance(exc, _CONEXAO_PERDIDA):
            self._descartar()
