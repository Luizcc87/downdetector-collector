# downdetector-collector — Project Context for Claude

> This file is loaded automatically at session start. It captures the state
> at session pause on **2026-05-12** so the next session can continue without
> re-discovering everything.

## What this project does

Daemon Python (systemd) que raspa páginas de status do Downdetector via
**FlareSolverr** (Docker), parseia HTML do Downdetector (Next.js, 2025+) e
envia métricas a um **Zabbix Server 7.0** via `zabbix_sender`. Um dashboard
**Grafana 13** lê do Zabbix pelo plugin `alexanderzobnin-zabbix-app` e mostra
todos os serviços monitorados.

- **Spec:** `/home/cristiano/docs/superpowers/specs/2026-05-12-dashboard-downdetector-design.md`
- **Plan de implementação original:** `/home/cristiano/docs/superpowers/plans/2026-05-12-dashboard-downdetector.md`
- **Dashboard de referência (inspiração):** github.com/AlanMartines/monitoramento-downdetector-zabbix-grafana (`/tmp/alanmartines/` se ainda existir)

## Estado atual (snapshot 2026-05-12 ~18:00)

| Componente | Estado |
|---|---|
| **Grafana** | 13.0.1+security-01 instalado e rodando (upgrade de 11.6.0 concluído) |
| **Daemon `downdetector-collector`** | `active`, `enabled`, deployado em `/opt/downdetector-collector` |
| **FlareSolverr container** | `flaresolverr` (Docker), porta `127.0.0.1:8191` |
| **Zabbix Server** | 7.0.19 local, host "Downdetector" (hostid=10676), 24 items |
| **Scrape interval** | `3600s` (1h) em `/etc/downdetector-collector/services.yaml` |
| **Serviços monitorados** | 3 (Google, Cloudflare, WhatsApp) — placeholder pra expandir até 48 |
| **Dashboard JSON** | v14 em DB do Grafana; commit `c9852b8` no repo |
| **Testes Python** | 23 passing (em `/home/cristiano/downdetector-collector/.venv`) |
| **Disco** | ~622 M livres em `/` (15G total, ~96% usado) — apertado |
| **Backup pré-upgrade** | `/var/backups/grafana/pre-13-upgrade-20260512-174834/` |

## Por onde paramos

Pausamos no meio de:

1. **Upgrade Grafana 11.6 → 13.0.1 concluído** (apesar de dpkg ter erradoo durante install por falta de disco — o upgrade finalizou em outro momento; `/api/health` confirma versão 13.0.1).
2. **Usuário vai aumentar o disco da VM** (`/dev/mapper/ubuntu--vg-ubuntu--lv`) — está 96% cheio, precisa de mais espaço pra instalar plugins, cache, etc.
3. **Layout do dashboard precisa ser revalidado em Grafana 13** porque o problema anterior era:
   - Grafana 11 com `dashboardScene=true` (renderizador Scenes) **empilhava** verticalmente painéis `text` e `stat` no mesmo `y` em vez de respeitar `gridPos.x/w`.
   - Workaround aplicado: `[feature_toggles] dashboardScene = false` em `/etc/grafana/grafana.ini`.
   - **Em Grafana 13** esse toggle pode não existir mais (Scenes virou padrão único). Precisa testar se o workaround ainda funciona OU redesenhar o layout sem mistura `text`+`stat` no mesmo y.

## Próximos passos quando voltar

1. **Confirmar disco aumentou.** Rodar `df -h /` — deve ter pelo menos 2-3GB livres.
2. **Reiniciar Grafana** (`systemctl restart grafana-server`) e checar:
   - `curl -s http://localhost:3000/api/health` → version 13.0.1
   - Login com a senha do usuário (que NÃO foi alterada nos upgrades)
   - Abrir o dashboard `http://srv-zabbix:3000/d/downdetector-main/`
3. **Verificar se o layout funciona em Grafana 13** sem o workaround `dashboardScene=false`:
   - Remover as 3 linhas `dashboardScene*=false` do `grafana.ini` se Grafana 13 ignorá-las
   - Se layout quebrar (empilhar), **redesenhar** sem text panels — substituir o card de serviço por um stat panel com value mapping HTML, ou usar plugin React moderno (`volkovlabs-table-panel`)
4. **Limpar partial-install artifacts** se houver:
   - `dpkg --audit` — deve estar limpo
   - `ls /usr/share/grafana/public/build/*.dpkg-new` — não deve haver
5. **Atualizar memórias** com lições do Grafana 13 (Scenes ainda existe? Toggle removido? text+stat mix funciona?).

## Decisões arquiteturais críticas

### Por que FlareSolverr e não Playwright direto
- Cloudflare exige **Private Access Token (PAT)** desde 2025
- PAT requer atestação de hardware (Apple Secure Enclave ou equivalente)
- Playwright/Firefox/Chrome em servidor headless **sempre** retornam 401 em `challenges.cloudflare.com/.../pat/...`
- FlareSolverr usa seu próprio Chromium interno com bypass; só ele funciona
- Em `collector/scraper.py`: `Scraper(flaresolverr_url, timeout_ms)` chama via `httpx.AsyncClient`
- Mais detalhes: ver memória `flaresolverr-required`

### Por que o site mudou todos os markers
- Downdetector migrou para Next.js em 2025
- Markers antigos do plan (`status-success`, `<title>X | Downdetector</title>`) **não existem mais**
- Novos markers (em `collector/parser.py`):
  - Status: `"companyCurrentStatus":"(success|warning|danger)"` no JSON SSR
  - Reports: `reportsValue` no `chartData`
  - Name: `"companyName":"..."` no JSON SSR
  - company_id: `"companyId":"(\d+)"` no JSON SSR
  - CF block: `<title>Just a moment...</title>`
- Mais detalhes: memória `downdetector-nextjs-markers`

### Por que Zabbix template foi reescrito
- Plan original usava schema Zabbix 6.0
- Servidor é Zabbix 7.0 que mudou várias coisas:
  - `template_groups` agora é obrigatório no topo (separado de `host_groups`)
  - Valuemaps são **embedded** no template (não mais standalone)
  - UUIDs precisam ser UUIDv4 reais (não placeholders hex)
  - Rule names misturam camelCase + snake_case
  - `type: AGENT` em host yaml **não é mais aceito** — criar host via API com `type:1`
- Mais detalhes: memória `zabbix-70-yaml-quirks`

### Por que coluna Logo no dashboard é difícil
- Plugin `alexanderzobnin-zabbix-datasource v5.0.4` **rejeita queries de items text/CHAR** no backend Go: `"non-metrics queries are not supported"`
- Afeta items `downdetector.logo[*]` e `downdetector.name[*]` (value_type=CHAR)
- Workaround atual: daemon envia o `logo` como CHAR, mas o dashboard NÃO consegue ler — então o caminho do SVG é construído via HTML hardcoded em `text` panels (que NÃO usam o plugin)
- Detalhes: memória `zabbix-plugin-text-items`

### Por que o layout v14 usa stat+text mix
- Inspirado em AlanMartines (referência da spec)
- Cada serviço = 3 painéis no mesmo y: `text` (logo+nome+id) + 2 `stat` (status, relatos)
- Bug Grafana 11.6: `dashboardScene=true` empilha esses verticalmente
- Workaround Grafana 11.6: desabilitar `dashboardScene*` em `[feature_toggles]`
- Grafana 13: **a verificar** — se Scenes for o único renderer e o bug persistir, redesenhar
- Detalhes: memória `grafana-pattern-native-grid`

## Layout de arquivos importantes

```
/home/cristiano/downdetector-collector/      # repo dev (git)
├── collector/                                # daemon Python
│   ├── __main__.py                           # entrypoint, SIGHUP reload
│   ├── scraper.py                            # FlareSolverr via httpx
│   ├── parser.py                             # HTML markers Next.js
│   ├── config.py, scheduler.py, zabbix_sink.py, health.py
├── bin/
│   ├── build_dashboard.py                    # gera dashboard JSON a partir de services.yaml
│   ├── snapshot.py, discover.py
├── tests/                                    # 23 tests, pytest
├── zabbix/                                   # template + external script + host yaml
├── grafana/                                  # dashboard + provisioning + logos
├── systemd/, config/, INSTALL.md, README.md, pyproject.toml

/opt/downdetector-collector/                  # production deploy
├── .venv/                                    # Python 3.12, deps + httpx + structlog + anyio + playwright (não usado em runtime — só dev)

/etc/downdetector-collector/services.yaml    # config produção (poll_interval=3600)
/usr/lib/zabbix/externalscripts/downdetector_discovery.py
/etc/systemd/system/downdetector-collector.service
/var/log/downdetector-collector/collector.log

/etc/grafana/grafana.ini                       # tem [feature_toggles] desabilitando dashboardScene*
/etc/grafana/provisioning/datasources/downdetector.yaml
/etc/grafana/provisioning/dashboards/downdetector.yaml
/var/lib/grafana/dashboards/downdetector/dashboard_downdetector.json
/var/lib/grafana/grafana.db                    # SQLite, contém dashboards + users + secrets
/usr/share/grafana/public/img/downdetector/*.svg  # logos servidos em /public/img/downdetector/<slug>.svg
```

## Comandos úteis pra retomar

```bash
# Estado geral
systemctl status downdetector-collector grafana-server zabbix-server
docker ps | grep flaresolverr

# Daemon logs (JSON)
tail -50 /var/log/downdetector-collector/collector.log | jq

# Testes
cd /home/cristiano/downdetector-collector
.venv/bin/pytest tests/ -v

# Regenerar dashboard a partir de services.yaml
python3 bin/build_dashboard.py    # escreve em /var/lib/grafana/dashboards/downdetector/

# Disco
df -h /

# Backup config Grafana mais recente
ls -dt /var/backups/grafana/* | head

# Login API Zabbix (Admin/zabbix — default, ver memória local-server-credentials)
curl -s -X POST -H "Content-Type: application/json-rpc" \
  -d '{"jsonrpc":"2.0","method":"user.login","params":{"username":"Admin","password":"zabbix"},"id":1}' \
  http://localhost/zabbix/api_jsonrpc.php
```

## ⚠️ Cuidados

- **Senha Grafana**: o usuário tem senha custom; **não tentar brute force** (ativa rate-limit). Pra testar API durante debug, usar técnica reversível: salvar `password+salt` originais do user `admin`, rodar `grafana-cli admin reset-admin-password '...'`, fazer o que precisa, depois `UPDATE user SET password=..., salt=... WHERE login='admin'` pra restaurar.
- **wpp-server em /opt**: serviço de WhatsApp em produção do usuário. **NÃO TOCAR** em `/root/.cache/puppeteer` (usado por ele).
- **Disco apertado**: antes de baixar Docker images, plugins, ou caches grandes, sempre `df -h /` e considerar `journalctl --vacuum-size=100M`. `/root/.cache/ms-playwright` é OK de deletar (~900M).
- **Não usar `git push`** sem permissão explícita — repo ainda só local.
