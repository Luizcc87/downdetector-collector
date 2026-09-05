# mikrotik/ — teste de link WAN por rota + saúde do roteador (PBR)

Módulo irmão de `collector/` (Downdetector) neste mesmo repositório. Processo
separado, próprio `__main__`, próprio scheduler — não compartilha o ciclo de
vida nem o backoff do daemon do Downdetector (motivo: ver docstring de
`mikrotik/scheduler.py`).

Desenho completo (PBR nos Mikrotik, destinos de teste, ganhos/requisitos da
API): `07-Propostas-Melhoria/2026-09-04_geral_monitoramento_links-wan-pbr-rotas-mikrotik.md`
no repositório `Analise-TI-CCZaleski`. **Guia operacional passo a passo**
(como configurar uma unidade nova do zero): `09-Operacao-Infraestrutura/guias/geral_guia-mikrotik-zabbix-monitoramento.md`
no mesmo repositório.

**Status:** validado em produção contra a Filial (`192.168.42.2`, RouterOS
6.49.10) desde 2026-09-04/05 — não é mais protótipo.

## O que faz

Para cada roteador em `routers.yaml`, a cada `poll_interval` segundos:

1. **Teste de link por rota:** conecta via API do RouterOS (`librouteros`,
   `api-ssl`), roda `/ping` contra os destinos de cada link **forçando a
   rota daquele link** (`routing-table=` — confirmado em campo que vale
   para v6 **e** v7, `routing-mark=` não existe como parâmetro do `/ping`),
   agrega RTT médio e perda.
2. **Saúde do roteador** (`mikrotik/health.py`): CPU, memória, uptime,
   tráfego por porta (`monitored_interfaces` em `routers.yaml`), status dos
   túneis VPN (descoberto automaticamente por tipo de interface, não
   precisa listar), e novas entradas de log (`/log print`, paginado por
   `.id`).

Tudo enviado ao Zabbix via `zabbix_sender` (reaproveitando
`collector/zabbix_sink.py`) num host próprio por unidade (`Mikrotik-Filial`,
`Mikrotik-Matriz`, `Mikrotik-Frigorifico`).

## Pré-requisitos

Ver o guia operacional (link acima) para o passo a passo completo. Resumo:

1. `api-ssl` habilitado no roteador, restrito por ACL ao IP do host que
   roda o coletor.
2. Usuário dedicado com policy `api,read,test` (sem `write`/`policy`/`sensitive`).
3. Esquema de PBR já aplicado (mark-connection/mark-routing + tabela/mark
   nomeada por link) — sem isso, `routing-table=` não tem o que apontar.
4. Links PPPoE usam `"__gateway__"` como target em vez de IP fixo — o
   gateway fica em faixa CGNAT, atribuído a cada negociação, pode mudar
   (`mikrotik/client.py:resolve_gateway`). Links com IP fixo por contrato
   (P2P) usam o IP literal.

## Uso local

```bash
cp config/routers.example.yaml config/routers.yaml   # preencher host/senha reais
pip install -e ".[mikrotik]"
python -m mikrotik --config config/routers.yaml --zabbix-server localhost --zabbix-port 10052
```

## Provisionar items no Zabbix (nova unidade)

```bash
ZBX_TOKEN=<token de API do Zabbix> \
    python bin/provision-zabbix-mikrotik.py --config config/routers.yaml --unit <unidade>
```

Idempotente — cria só o que ainda não existe. Descobre os túneis VPN ao
vivo no roteador (não precisa listá-los em `routers.yaml`).

## Testes

```bash
pip install -e ".[dev,mikrotik]"
pytest tests/test_mikrotik_config.py tests/test_mikrotik_client.py tests/test_mikrotik_scheduler.py tests/test_mikrotik_health.py -v
```

Todos os testes usam mocks (`unittest.mock`) — não dependem de um roteador
real acessível.

## Métricas enviadas (por host Zabbix `Mikrotik-<Unidade>`)

| Chave | Tipo | Descrição |
|---|---|---|
| `mikrotik.link.available[<link>.<target>]` | 0/1 | Link alcançou o destino nesta rodada |
| `mikrotik.link.loss_pct[<link>.<target>]` | float | % de perda de pacotes |
| `mikrotik.link.rtt_ms[<link>.<target>]` | float | RTT médio (ms), ausente se perda=100% |
| `mikrotik.collector_heartbeat` | timestamp (segundos) | Enviado sempre — distingue "link caído" de "coletor quebrado" |
| `mikrotik.system.cpu_load_pct` | int | CPU load (%) |
| `mikrotik.system.free_memory_bytes` / `total_memory_bytes` | int | Memória (bytes) |
| `mikrotik.system.uptime_seconds` | int | Uptime, convertido do formato RouterOS |
| `mikrotik.interface.rx_bps[<iface>]` / `tx_bps[<iface>]` | int | Tráfego instantâneo por porta (bps), só para interfaces em `monitored_interfaces` |
| `mikrotik.vpn.tunnel_up[<tunel>]` | 0/1 | Status do túnel (descoberto automaticamente, ignora túneis desabilitados de propósito) |
| `mikrotik.log.entry` | texto | Última linha de log nova — ver limitação abaixo |
| `mikrotik.traceroute.hop_address[<link>,<hop>]` | texto | Endereço do hop N (posição no caminho, não IP fixo) |
| `mikrotik.traceroute.hop_rtt_ms[<link>,<hop>]` | float | RTT médio do hop N — ausente se o hop não respondeu |
| `mikrotik.traceroute.hop_loss_pct[<link>,<hop>]` | float | Perda no hop N |

Traceroute roda num intervalo **bem maior** que o ping (`traceroute_interval_s`,
padrão 900s/15min) — hop-a-hop constante sobrecarrega a CPU de um RB750Gr3.
Roda contra o primeiro target de cada link (a âncora pública, ex.: `1.1.1.1`),
objetivo é comparar o **caminho** entre links, não repetir o teste de
disponibilidade que o ping já cobre. `TRACEROUTE_MAX_HOPS` (15) limita
quantos items existem por link — caminhos mais longos são truncados.

## Limitações conhecidas

- **`mikrotik.log.entry` não aparece em painel Grafana via o plugin Zabbix
  usado neste projeto.** Confirmado em campo (2026-09-05): o dado chega e
  fica armazenado certinho no Zabbix (`history.get` da API do Zabbix
  confirma), mas o plugin `alexanderzobnin-zabbix-datasource` não retorna
  histórico de items tipo Log (`value_type=2`) — nem items tipo Texto
  (`value_type=1`) — via `queryType=Metrics`, mesmo com item novo e limpo
  testado do zero. Não é cache, não é erro de configuração. Enquanto não
  se descobre um modo de query suportado, ver os logs direto no Zabbix:
  **Monitoring → Latest data → host → "Log de eventos do roteador"**.
- **Variável de unidade no dashboard Grafana é lista fixa (`Custom`), não
  dinâmica.** Tentativa de variável tipo `Query` (Host, filtrado por grupo)
  não resolveu de forma confiável nesse plugin (`non-metrics queries are
  not supported` no backend, resultado vazio no navegador). Ao provisionar
  uma unidade nova, adicionar manualmente a opção na variável do dashboard
  (Settings → Variables → `unidade`).
- **Cache do datasource Zabbix no Grafana (`cacheTTL`, hoje 5 min):** items
  recém-criados podem levar alguns minutos para aparecer nos painéis. Não
  é bug se um painel novo mostrar "No data" por pouco tempo depois de
  provisionar.

## Próximos passos (fora do escopo deste módulo)

- Estender para Matriz e Frigorífico (código já é genérico por unidade —
  só falta aplicar o guia operacional a cada uma).
- Traceroute hoje usa intervalo fixo (Fase 5 da proposta previa "intervalo
  maior OU sob gatilho") — disparar sob gatilho quando o ping detectar
  degradação é uma evolução futura, não implementada ainda.
