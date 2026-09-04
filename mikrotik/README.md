# mikrotik/ — teste de link WAN por rota (PBR)

Modulo irmao de `collector/` (Downdetector) neste mesmo repositorio. Processo
separado, proprio `__main__`, proprio scheduler — nao compartilha o ciclo de
vida nem o backoff do daemon do Downdetector (motivo: ver docstring de
`mikrotik/scheduler.py`).

Desenho completo (PBR nos Mikrotik, destinos de teste, ganhos/requisitos da
API): `07-Propostas-Melhoria/2026-09-04_geral_monitoramento_links-wan-pbr-rotas-mikrotik.md`
no repositorio `Analise-TI-CCZaleski`.

## O que faz

Para cada roteador em `routers.yaml`, a cada `poll_interval` segundos: conecta
via API do RouterOS (`librouteros`, `api-ssl`), roda `/ping` contra os
destinos de cada link **forcando a rota daquele link** (`routing-table=` em
v7, `routing-mark=` em v6), agrega RTT medio e perda, e envia ao Zabbix
(`zabbix_sender`, reaproveitando `collector/zabbix_sink.py`) num host proprio
por unidade (`Mikrotik-Filial`, `Mikrotik-Matriz`, `Mikrotik-Frigorifico`).

## Pre-requisitos (ainda pendentes em 2026-09-04)

1. Servico `api-ssl` habilitado nas 3 unidades, restrito por ACL ao IP do
   host que rodar este coletor.
2. Usuario dedicado no Mikrotik com policy `api` + `read` + `test` (sem
   `write`/`policy`/`sensitive`).
3. Esquema de PBR (mangle mark-connection/mark-routing + tabelas nomeadas)
   ja aplicado no roteador — sem isso, `routing-table=`/`routing-mark=`
   nao tem o que apontar.
4. ~~Confirmar em campo que `/ping` aceita `routing-table=`/`routing-mark=`~~
   — **feito em 2026-09-04** contra a Filial (v6.49.10, real): `/ping` usa
   `routing-table=` em v6 **e** v7 (`routing-mark=` não existe como parâmetro
   da ferramenta — "unknown parameter"). `mikrotik/config.py` já reflete isso
   (`PING_ROUTING_PARAM` constante, sem diferenciação por branch).

## Uso local

```bash
cp config/routers.example.yaml config/routers.yaml   # preencher host/senha reais
pip install -e ".[mikrotik]"
python -m mikrotik --config config/routers.yaml --zabbix-server localhost --zabbix-port 10052
```

## Testes

```bash
pip install -e ".[dev,mikrotik]"
pytest tests/test_mikrotik_config.py tests/test_mikrotik_client.py tests/test_mikrotik_scheduler.py -v
```

Todos os testes usam mocks (`unittest.mock`) — nao dependem de um roteador
real acessivel. A validacao contra hardware real (item 4 acima) e um passo
separado, manual, antes de considerar este modulo pronto para producao.

## Metricas enviadas (por host Zabbix `Mikrotik-<Unidade>`)

| Chave | Tipo | Descricao |
|---|---|---|
| `mikrotik.link.available[<link>.<target>]` | 0/1 | Link alcancou o destino nesta rodada |
| `mikrotik.link.loss_pct[<link>.<target>]` | float | % de perda de pacotes |
| `mikrotik.link.rtt_ms[<link>.<target>]` | float | RTT medio (ms), ausente se perda=100% |
| `mikrotik.collector_heartbeat` | timestamp | Enviado sempre, mesmo com todos os links fora — distingue "link caido" de "coletor quebrado" |

## Proximos passos (fora do escopo deste modulo)

- Criar os hosts/items/triggers correspondentes no Zabbix (via `zabbix-ops`
  no repo `Analise-TI-CCZaleski`).
- Wiring no stack Swarm de producao (`09-Operacao-Infraestrutura/stacks-docker/`
  no repo `Analise-TI-CCZaleski`) — ainda nao feito; este modulo por enquanto
  so existe como codigo + testes, nao esta implantado.
- Traceroute/MTR sob gatilho (Fase 5 da proposta) — nao implementado neste
  modulo ainda; hoje so cobre o teste de ping curto (Fase 4).
