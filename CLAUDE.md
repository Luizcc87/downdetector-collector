# downdetector-collector — Contexto do projeto para Claude

> Ambiente de trabalho atual: **Docker Compose local** (Docker Desktop, Windows),
> não mais a VM remota `srv-zabbix` descrita em DOCS.md/INSTALL.md (essa
> continua sendo a referência de deploy bare-metal/produção). Última atualização
> **2026-09-01**.

## O que o projeto faz

Daemon Python que raspa páginas de status do Downdetector via **FlareSolverr**
(Docker), parseia HTML do Downdetector (Next.js, 2025+) e envia métricas a um
**Zabbix Server 7.0** via `zabbix_sender`. Um dashboard **Grafana** lê do
Zabbix pelo plugin `alexanderzobnin-zabbix-app` e mostra todos os serviços
monitorados.

Arquitetura, convenções e armadilhas técnicas detalhadas: **[AGENTS.md](AGENTS.md)**.
Deploy manual bare-metal (systemd/produção): **[INSTALL.md](INSTALL.md)** e
**[DOCS.md](DOCS.md)**.

## Ambiente local (Docker Compose)

Todo o stack roda em containers Docker Desktop, definidos em `docker-compose.yml`:

| Container | Serviço | Porta host | Papel |
|---|---|---|---|
| `dd-collector` | `collector` | — | Daemon Python (build a partir do `Dockerfile` local) |
| `dd-flaresolverr` | `flaresolverr` | `8191` | Bypass Cloudflare |
| `dd-zabbix-server` | `zabbix-server` | `10052→10051` | Zabbix Server 7.0 (trapper) |
| `dd-zabbix-web` | `zabbix-web` | `8888→8080` | UI Zabbix (`Admin`/`zabbix`) |
| `dd-postgres` | `postgres` | — | DB do Zabbix |
| `dd-grafana` | `grafana` | `3030→3000` | Dashboard (`admin`/`admin`) |

**Bind mounts do Grafana** (edições no repo refletem direto, sem rebuild):
- `./grafana/provisioning` → `/etc/grafana/provisioning`
- `./grafana` → `/var/lib/grafana/dashboards/downdetector` (inclui `dashboard_downdetector.json`)
- `./grafana/logos` → `/usr/share/grafana/public/img/downdetector`

**`dd-collector` NÃO tem bind mount de código** — só monta
`config/services.example.yaml`. Qualquer mudança em `collector/*.py` exige
**rebuild da imagem**, não só restart do container:

```bash
docker compose build collector
docker compose up -d collector
```

> Esquecer o rebuild é o bug mais fácil de reintroduzir aqui — já aconteceu
> nesta sessão (ver "Histórico de bugs resolvidos" abaixo): o container ficou
> rodando uma imagem sem o `LatencyChecker` por dias sem nenhum erro logado.

## Comandos úteis (ambiente Docker local)

```bash
# Status geral
docker ps --format "table {{.Names}}\t{{.Status}}"

# Logs do daemon (JSON estruturado via structlog)
docker logs dd-collector --since 1h -f

# Rebuild + redeploy do collector (após mudar collector/*.py)
docker compose build collector && docker compose up -d collector

# Regenerar dashboard a partir do services.yaml e aplicar
python3 bin/build_dashboard.py    # lê config/services.example.yaml (fallback local),
                                   # escreve grafana/dashboard_downdetector.json
# Grafana recarrega sozinho via provisioning (updateIntervalSeconds: 30) —
# só reiniciar o container se precisar forçar refresh imediato:
docker restart dd-grafana

# API Zabbix local (Admin/zabbix)
curl -s -X POST -H "Content-Type: application/json-rpc" \
  -d '{"jsonrpc":"2.0","method":"user.login","params":{"username":"Admin","password":"zabbix"},"id":1}' \
  http://localhost:8888/api_jsonrpc.php

# API Grafana local (admin/admin)
curl -s -u admin:admin http://localhost:3030/api/dashboards/uid/downdetector-main
```

⚠️ **Nota de ambiente Windows/Git Bash**: `curl`/`wget` neste shell podem ser
interceptados por uma ferramenta MCP de proxy de contexto — se `curl` falhar
com erro de redirecionamento, use `mcp__plugin_context-mode_context-mode__ctx_execute`
(`language: "javascript"`, `fetch()`) para chamadas HTTP a `localhost`. Cada
chamada roda em sandbox isolado — não há filesystem compartilhado entre
chamadas; combine steps dependentes num único `ctx_execute`.

## ⚠️ Cuidado ao reiniciar o Grafana

`docker restart dd-grafana` mata WebSockets/queries em voo (`SIGTERM` limpo,
não crash). Isso já foi confundido com "bug de dados sumindo" nesta sessão:
o usuário abriu DevTools durante uma janela de restarts manuais consecutivos
(vários fixes seguidos, cada um terminando em restart) e viu
`ERR_EMPTY_RESPONSE` / WebSocket falhando — não era problema de dado ou query,
era o container reiniciando no meio do carregamento da página.

**Regra**: o provisioning do Grafana (`updateIntervalSeconds: 30`) já detecta
mudanças no `dashboard_downdetector.json` e recarrega sozinho, sem downtime.
Só use `docker restart dd-grafana` quando estritamente necessário (mudança em
`grafana.ini`, plugin, ou datasource), e nunca em sequência rápida de vários
restarts — espere o anterior estabilizar (`docker ps` mostrando `Up` estável
por >1min) antes do próximo.

## Estado do dashboard (v24, `bin/build_dashboard.py`)

- **160 painéis**, categorizados por tipo de serviço.
- Cards por serviço: logo (`text`) + status (`stat`, cores por threshold) +
  sparkline de reports (`timeseries`) + card de latência (`stat` com
  `graphMode:"area"`, ver "Histórico de bugs" abaixo).
- Filtro de item Zabbix por **nome de exibição** (`item.filter: /^Nome: sufixo$/`),
  nunca por `key_` — o plugin `alexanderzobnin-zabbix-datasource` rejeita
  filtro por key silenciosamente (ver `AGENTS.md`).
- Cores de série alinhadas à paleta validada da skill `dataviz`
  (six-checks CVD): reports `#2a78d6`, latência `#eb6834` (slots categóricos
  1 e 2), status mantém paleta própria fixa (verde/amarelo/vermelho/roxo).
- `time.from`/`time.to` do dashboard: `now-6h` (não `now-1h`) — necessário
  porque o scrape interval real (~15-20min) só gera 3-5 pontos/hora; uma
  janela de 1h é frágil a qualquer drift de clock/timezone entre servidor e
  navegador e pode esvaziar o gráfico de reports mesmo com dado presente no
  Zabbix (o card de latência, por ser `stat`/`lastNotNull`, não sofre esse
  problema — só o painel `timeseries` de reports é sensível a isso).

## Histórico de bugs resolvidos nesta sessão (2026-09-01)

1. **Filtro Zabbix por `key_` em vez de `name`** — todos os `zbx_target()` em
   `build_dashboard.py` corrigidos pra regex de nome de exibição. Commit `6ff7666`.
2. **Card de latência sem gráfico / ilegível** — causa raiz real: `dd-collector`
   rodava imagem Docker **desatualizada**, sem o módulo `collector/latency.py`
   integrado a `_on_scrape` (nunca enviava `downdetector.latency_ms[*]` ao
   Zabbix, sem nenhum erro logado). Fix: `docker compose build collector &&
   docker compose up -d collector`. Depois disso, ajuste de layout: card
   trocado de `timeseries` (h=2, sem eixo) pra `stat` com sparkline `area`
   (h=3), seguindo o contrato "stat tile" da skill `dataviz`. Commit `d03d429`.
3. **Cores fora da paleta validada** — hex arbitrários (`#3498DB`, `#F39C12`)
   trocados por slots categóricos validados no six-checks CVD. Mesmo commit `d03d429`.
4. **Gráfico "Histórico Downdetector" (reports) com "No data"** — dado real
   presente no Zabbix, query da API confirmada OK; causa era range `now-1h`
   sendo insuficiente pros poucos pontos por hora do scrape. Fix: range
   default `now-6h`. Commit `2f870ba`.
5. **"Vários cards com No data" logo depois do fix acima** — falso alarme:
   era o próprio processo de debug (múltiplos `docker restart dd-grafana`
   consecutivos) derrubando WebSocket/queries em voo no navegador do usuário
   no momento exato da inspeção. Confirmado via `docker events` (kill/restart
   com `exitCode=0`, ou seja, shutdown limpo por `SIGTERM`, não crash). Sem
   fix de código — nenhum restart adicional necessário, só aguardar
   estabilizar.

## Convenções e armadilhas gerais

Ver **[AGENTS.md](AGENTS.md)** — cobre parser Next.js, schema Zabbix 7.0,
rate-limit do Downdetector, e por que FlareSolverr é obrigatório (Cloudflare
PAT). Não duplicado aqui pra evitar desatualização cruzada.
