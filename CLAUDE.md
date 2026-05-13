# downdetector-collector — Project Context for Claude

> This file is loaded automatically at session start. It captures the state
> at session pause on **2026-05-12 ~18:00** so the next session can continue
> without re-discovering everything. Última atualização: **2026-05-12 ~19:42**
> após retomada pós-crash: expansão de 3 → 58 serviços via SIGHUP reload.

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
| **Serviços monitorados** | **58** — 3 confirmados (Google id=10200, Cloudflare 32542, WhatsApp 10136) + 55 novos da lista AlanMartines com `id: 0` (placeholder) |
| **Dashboard JSON** | v14 em DB do Grafana; commit `c9852b8` no repo |
| **Testes Python** | 23 passing (em `/home/cristiano/downdetector-collector/.venv`) |
| **Disco** | 15G livres / 30G (48% usado) — usuário aumentou a VM ✓ |
| **Backup pré-upgrade** | `/var/backups/grafana/pre-13-upgrade-20260512-174834/` |
| **grafana.ini toggles** | Limpos — `dashboardScene*=false` removidos (Grafana 13 ignora) |

## Por onde paramos (após segunda retomada 2026-05-12 ~19:42)

Sessão anterior crashou no meio da edição do `services.yaml` — o arquivo ficou
zerado (`services: []`) enquanto o daemon ainda rodava com 3 serviços em memória
do reload anterior (18:38:58). Recuperação feita:

1. **Recuperei os 3 serviços** confirmando IDs via Zabbix items (`downdetector.company_id[*]`).
2. **Expandi pra 58 serviços** copiando a lista de 56 do AlanMartines (`/tmp/alanmartines/downdetectorlist.list`, 57 únicos), removendo overlap com cloudflare/whatsapp, corrigindo typo `receite-federal` → `receita-federal`.
3. **IDs dos 55 novos como `0`** (placeholder) — o `{#ID}` macro só aparece como cosmético no LLD (não é usado em key/trigger; verifiquei em `zabbix/tmpl_downdetector.yaml`). `company_id` real é coletado a cada scrape e enviado em `downdetector.company_id[<slug>]`. Pra popular IDs reais, rodar `python3 bin/discover.py --slugs-file <lista>`.
4. **SIGHUP** via `systemctl reload downdetector-collector` → log confirmou `count: 58, event: config_loaded`.
5. **LLD do Zabbix rodou sozinho** (delay 5min) e criou ~360 items (58 svcs × 6 metrics + 5 health + extras). Primeiros scrapes saíram count=6 (status+last_check+reports+name+company_id+logo) por causa do META_PUSH_EVERY_N_SCRAPES=20 (count==1 dispara meta).
6. Pace observado: ~15s/scrape via FlareSolverr (serial). Primeira passada completa: ~14min após reload.

Pendente (continuação do TODO da primeira retomada — não foi tocado):

### Por onde paramos (snapshot 2026-05-12 ~18:05)

Concluído nesta sessão:

1. **Upgrade Grafana 11.6 → 13.0.1 confirmado** — `/api/health` responde version 13.0.1+security-01.
2. **Disco aumentado** — `/` agora tem 30G total / 15G livres.
3. **grafana.ini limpo** — os 3 toggles `dashboardScene*=false` em `[feature_toggles]` foram removidos (substituídos por comentário). Logs do startup confirmam que em Grafana 13 esses toggles são **ignorados** (`FeatureToggles ... dashboardScene=true dashboardSceneSolo=true dashboardSceneForViewers=true`). Scenes virou padrão único.
4. **Backup do grafana.ini** em `/etc/grafana/grafana.ini.bak-20260512-175853` (caso queira reverter).
5. **Permissão regravada** — `Edit` tool zerou o group do `grafana.ini` pra `root:root`, restaurado pra `root:grafana 640`. **Cuidado**: editar `grafana.ini` por ferramentas que reescrevem o arquivo (Edit/Write/sed) podem repetir o bug. Sempre re-aplicar `chown root:grafana /etc/grafana/grafana.ini` e `systemctl restart grafana-server` depois.

Pendente:

- **Validação visual do layout v14 em Grafana 13.** Sem `grafana-image-renderer` plugin instalado, não foi possível screenshot programático. **Você precisa abrir `http://srv-zabbix:3000/d/downdetector-main/` e olhar**:
  - Se cada serviço aparece como **uma linha de 3 cards lado-a-lado** (logo+nome / status / relatos) → Grafana 13 corrigiu o bug do Scenes 1.0; está pronto.
  - Se os painéis text+stat aparecem **empilhados verticalmente** no mesmo y → bug persistiu em Scenes 13. Nesse caso, redesenhar substituindo `text` panels por `stat` com `mappings` HTML inline, ou usar `volkovlabs-table-panel`.

## Próximos passos quando voltar

1. **Olhar o dashboard** e me dizer qual dos dois cenários acima ocorreu (layout OK ou quebrado em Grafana 13 Scenes).
2. **Regenerar dashboard JSON** pra refletir os 58 serviços: `python3 bin/build_dashboard.py` → escreve em `/var/lib/grafana/dashboards/downdetector/dashboard_downdetector.json`. **Atenção**: dashboard atual ainda foi gerado pra 3 serviços; vai mostrar muito espaço vazio até regenerar.
3. **Gerar/baixar SVGs faltantes** dos 52 serviços novos em `/usr/share/grafana/public/img/downdetector/<slug>.svg`. Só temos 6 hoje (cloudflare/google/whatsapp + 3 placeholders itau/ms365/nubank). Sem SVG, dashboard mostra alt text/quadradinho quebrado mas coleta não é afetada.
4. **Popular IDs reais** dos 55 novos serviços rodando discover (opcional, só cosmético no `{#ID}`):
   ```
   cd /home/cristiano/downdetector-collector
   .venv/bin/python -c "from pathlib import Path; from collector.config import load_services_from_path; print('\n'.join(s.slug for s in load_services_from_path(Path('/etc/downdetector-collector/services.yaml')) if s.id == 0))" > /tmp/new_slugs.txt
   .venv/bin/python bin/discover.py --slugs-file /tmp/new_slugs.txt > /tmp/discovered.yaml
   ```
   Depois mesclar IDs descobertos manualmente no services.yaml.
5. **Trimming**: se 58 ficou demais, podar serviços irrelevantes pra ti (FIFA, Free Fire, Tinder, Snapchat etc) — basta deletar do yaml e dar SIGHUP novamente.
6. Se layout quebrado em Grafana 13 → redesign do dashboard (sem mistura text+stat no mesmo y).
7. **Limpar partial-install artifacts** se houver:
   - `dpkg --audit` — deve estar limpo
   - `ls /usr/share/grafana/public/build/*.dpkg-new` — não deve haver

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
