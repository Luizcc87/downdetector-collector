# AGENTS.md — Contexto do projeto para IAs

Documento para IAs (Claude Code, Cursor, Aider, Copilot, etc.) que vão editar este repositório. Resume arquitetura, convenções e armadilhas críticas que não dá pra inferir só do código.

> **Nota de ambiente**: os caminhos `/opt`, `/etc`, `systemd` abaixo descrevem o
> deploy **bare-metal de produção** (ver [INSTALL.md](INSTALL.md) / [DOCS.md](DOCS.md)).
> Rodando localmente via `docker compose up -d`, o equivalente é
> `docker exec dd-collector`, bind mounts do `docker-compose.yml`, e
> `docker restart <container>` no lugar de `systemctl`. Detalhes e armadilhas
> específicas do modo Docker: **[CLAUDE.md](CLAUDE.md)**.

## O que o projeto faz

Daemon Python (em `collector/`) que raspa páginas de status do `downdetector.com.br` via FlareSolverr (Chromium em Docker), parseia o HTML do Next.js do site, e envia métricas para Zabbix Server via `zabbix_sender`. Um dashboard Grafana auto-gerado a partir de `services.yaml` consome as métricas via plugin Zabbix.

**Stack:**
- Python 3.11+, asyncio, httpx, structlog, pyyaml
- FlareSolverr (Chromium em Docker) — única forma de passar pelo Cloudflare em 2025+
- Zabbix Server 7.0+ com LLD (Low-Level Discovery)
- Grafana 13+ com plugin `alexanderzobnin-zabbix-app`

## Arquitetura

```
downdetector.com.br (atrás de Cloudflare)
        ▲
        │ HTTPS
        │
FlareSolverr :8191 (Docker)
        ▲
        │ HTTP local
        │
collector/  (daemon Python, systemd)
  ├ scheduler.py     heap async com backoff exponencial
  ├ scraper.py       cliente httpx → FlareSolverr
  ├ parser.py        regex em JSON SSR do Next.js
  ├ config.py        loader de services.yaml
  ├ zabbix_sink.py   wrapper sobre zabbix_sender
  ├ health.py        métricas internas (uptime, ciclo, blocks)
  └ __main__.py      entrypoint + SIGHUP reload
        │
        │ zabbix_sender
        ▼
Zabbix Server (host "Downdetector", LLD → 6 items por serviço)
        │
        ▼
Grafana (datasource "Downdetector-Zabbix" / uid downdetector-zabbix)
```

## Layout do repo

```
collector/                      # daemon Python (core)
bin/
  build_dashboard.py            # gera dashboard JSON a partir de services.yaml
  fetch_logos.py                # baixa SVGs (simple-icons + Google favicon)
  refresh_nd.py                 # re-scrape one-off de serviços em N/D
  discover.py                   # descobre company_id de um slug
  snapshot.py                   # captura HTML pra fixtures de teste
scripts/
  bootstrap.sh                  # clone + install one-liner via curl
  install-all.sh                # wrapper sobre os 3 abaixo
  install.sh                    # pacotes + FlareSolverr + daemon
  setup-zabbix.sh               # importa template + cria host via API
  setup-grafana.sh              # plugin + app enable + datasource + dashboard
  cleanup-zabbix-orphans.sh     # remove items LLD desabilitados
zabbix/
  tmpl_downdetector.yaml        # template Zabbix 7.0 (LLD + valuemaps embedded)
  host_downdetector.yaml        # host de referência
  externalscripts/
    downdetector_discovery.py   # external script invocado pelo Zabbix p/ LLD
grafana/
  dashboard_downdetector.json   # snapshot do dashboard gerado
  provisioning/                 # templates de provisioning (não usado em runtime — referência)
  logos/                        # SVGs pré-baixados (opcional)
config/
  services.example.yaml         # starter pack (19 serviços BR)
systemd/
  downdetector-collector.service
tests/                          # pytest, 24 suites
pyproject.toml
README.md
DOCS.md                         # docs profundas (instalação manual, schema, troubleshooting)
INSTALL.md
AGENTS.md                       # este arquivo
```

## Caminhos críticos em runtime

```
/opt/downdetector-collector/.venv/                       venv produção
/opt/downdetector-collector/src/                         código clonado (deploy)
/etc/downdetector-collector/services.yaml                config produção
/etc/grafana/provisioning/
  ├ plugins/downdetector-zabbix-app.yaml                 habilita app Zabbix no org 1
  ├ datasources/downdetector.yaml                        datasource Downdetector-Zabbix
  └ dashboards/downdetector.yaml                         dashboard file provisioner
/var/lib/grafana/dashboards/downdetector/dashboard_downdetector.json   dashboard JSON gerado
/usr/share/grafana/public/img/downdetector/*.svg         logos servidos pelo Grafana
/usr/lib/zabbix/externalscripts/downdetector_discovery.py   script LLD chamado pelo Zabbix
/var/log/downdetector-collector/collector.log            logs JSON (structlog)
```

## Convenções

- **Idioma**: PT-BR em comentários, mensagens de log de usuário, docs; identificadores em inglês.
- **Sem emojis em código novo.** Existentes em README/DOCS podem permanecer.
- **Logs estruturados** via structlog → JSON. Eventos curtos em snake_case: `config_loaded`, `scrape_blocked`, `zabbix_sender_ok`, `scrape_rate_limited`, `flaresolverr_http_error`.
- **YAML**: 2-space indent. Comentários `# === Categoria ===` separam grupos em `services.yaml`.
- **Shell scripts**: `set -euo pipefail`. Helpers `log/ok/warn/die` com cores ANSI. `--help` em todos.
- **Idempotência**: scripts de install/setup nunca devem apagar config do aluno (outros dashboards, datasources, hosts). Só nossos próprios artefatos (prefixados com `downdetector` ou `Downdetector-`).

## Armadilhas críticas

### 1. Bypass de Cloudflare exige FlareSolverr
- Cloudflare exige **Private Access Token (PAT)** desde 2025, com atestação de hardware (Apple Secure Enclave ou equivalente)
- Playwright/Firefox/Chrome em servidor headless **sempre** retornam 401 no challenge
- Só o Chromium interno do FlareSolverr passa. **Não tente substituir.**
- Endpoint: `POST http://127.0.0.1:8191/v1` com `{"cmd":"request.get","url":...,"maxTimeout":30000}`

### 2. Site usa Next.js — markers no JSON SSR
`collector/parser.py` extrai por regex no HTML:

| Campo | Regex |
|---|---|
| Status | `"companyCurrentStatus":"(success\|warning\|danger)"` |
| Reports (última hora) | `"reportsValue":<int>` dentro de `chartData` |
| Nome | `"companyName":"..."` |
| company_id | `"companyId":"(\d+)"` |
| Cloudflare block | `<title>Just a moment...</title>` |
| Rate-limit | literal `(╯°□°)╯︵ ┻━┻` no body |

Os markers antigos da era pre-Next.js (`status-success` em CSS class, `<title>X \| Downdetector</title>`) **não existem mais**.

### 3. Zabbix 7.0 schema (não 6.0)
- `template_groups` no topo do YAML é **obrigatório** (separado de `host_groups`)
- Valuemaps são **embedded** no template (não standalone)
- UUIDs precisam ser **UUIDv4 reais** (não placeholders hex)
- Host YAML `type: AGENT` **não é mais aceito**; criar via API com `type: 1`

### 4. Grafana 13 — storage de dashboards mudou
- Dashboards **não estão mais** na tabela legada `dashboard`
- Estão em `resource` table com `group=dashboard.grafana.app`
- Log de confirmação: `bleve-backend ... resource=dashboards size=N`
- File provisioner às vezes para de detectar mudanças após reload → `systemctl restart grafana-server` resolve
- App plugins (como `alexanderzobnin-zabbix-app`) precisam ser **habilitados** via `/etc/grafana/provisioning/plugins/*.yaml` para seus datasource types ficarem registrados. Sem isso, o provisioning do datasource falha com `data source not found`.

### 5. Datasource: `Downdetector-Zabbix` / UID `downdetector-zabbix`
- **Não usar mais** `name: Zabbix` / `uid: zabbix` (colide com config externa de aluno)
- O UID está hardcoded como constante `ZBX_DS` em `bin/build_dashboard.py:23`
- Todo painel no dashboard referencia esse UID
- Se mudar o UID, atualizar:
  - `bin/build_dashboard.py` (constante `ZBX_DS`)
  - `scripts/setup-grafana.sh` (cat do datasource yaml)
  - `grafana/provisioning/datasources/zabbix.yaml` (template legado)
  - `grafana/dashboard_downdetector.json` (snapshot — opcional, é regenerado)

### 6. Rate-limit do Downdetector
- Acima de ~15 req/min em IP datacenter = 429 sustentado
- A página de bloqueio é HTTP 200 com body `(╯°□°)╯︵ ┻━┻` — não 429 de verdade
- `parser.py` detecta e o `scheduler.py` aplica backoff exponencial por serviço: 300 → 600 → 1200 → ... → 7200s
- **Importante**: backoff não sobrescreve o último valor bom no Zabbix
- IPs residenciais / Starlink raramente queimam; datacenter queima fácil

## Como adicionar um serviço (end-to-end)

1. Editar `/etc/downdetector-collector/services.yaml` (estrutura em [README.md](README.md))
2. SIGHUP reload — re-lê o YAML sem matar o processo:
   ```bash
   sudo systemctl reload downdetector-collector
   ```
3. Aguardar ~5 min — o LLD do Zabbix cria as 6 métricas para o novo slug automaticamente
4. Regerar dashboard:
   ```bash
   cd /opt/downdetector-collector/src
   sudo /opt/downdetector-collector/.venv/bin/python bin/build_dashboard.py
   sudo /opt/downdetector-collector/.venv/bin/python bin/fetch_logos.py
   sudo systemctl restart grafana-server
   ```

## Testes

```bash
cd /home/cristiano/downdetector-collector   # ou /opt/downdetector-collector/src
.venv/bin/pytest tests/ -v
```

24 testes cobrindo parser, config, scheduler, health, zabbix_sink. Não dependem de Zabbix/Grafana/FlareSolverr rodando — usam fixtures inline.

## Não fazer

- **Não substituir FlareSolverr** por Playwright direto (não passa pelo Cloudflare PAT)
- **Não consultar `dashboard` table** do Grafana 13 esperando achar dashboards lá (vazia — vai na `resource`)
- **Não provisionar datasource com `name: Zabbix`** — usar `Downdetector-Zabbix` (evita colisão com config do aluno)
- **Não esquecer de habilitar o app Zabbix** via `/etc/grafana/provisioning/plugins/*.yaml`. Sem isso, provisioning do datasource falha com `data source not found`.
- **Não baixar `poll_interval` abaixo de 60s** (rate-limit certo)
- **Não apagar arquivos de provisioning não-prefixados** com `downdetector-` ou `Downdetector-` — podem ser do aluno
- **Não usar `git push --force`** em main/master; sempre cria commits novos
