# downdetector-collector — Documentação completa

Sistema de monitoramento dos serviços do Downdetector com coleta automatizada,
armazenamento no Zabbix e visualização no Grafana. Atualizado em **2026-05-13**.

---

## 1. Arquitetura

```
                      ┌─────────────────────────────┐
                      │   downdetector.com.br       │
                      │   (atrás de Cloudflare)     │
                      └─────────────────────────────┘
                                    ▲
                                    │ HTTPS
                                    │
                ┌───────────────────┴───────────────────┐
                │                                       │
   ┌──────────────────────┐              ┌────────────────────────────┐
   │  Starlink (eth1)     │              │  NewLife PPPoE (pppoe0)    │
   │  IP: 153.67.103.190  │              │  IP: 177.72.82.28          │
   └──────────────────────┘              └────────────────────────────┘
                │                                       │
                └───────────────────┬───────────────────┘
                                    │
                       ┌────────────▼────────────┐
                       │  EdgeRouter Lite        │
                       │  10.0.0.1               │
                       │  PBR: 10.0.0.42 → eth1  │
                       └────────────┬────────────┘
                                    │ LAN
                                    │
   ┌────────────────────────────────▼────────────────────────────────┐
   │  srv-zabbix (10.0.0.42)                                         │
   │                                                                 │
   │  ┌────────────────────┐   ┌─────────────────────────────────┐   │
   │  │ FlareSolverr       │◄──┤ downdetector-collector (daemon) │   │
   │  │ Docker, :8191      │   │ /opt/downdetector-collector     │   │
   │  └────────────────────┘   │ systemd unit                    │   │
   │                           └───────┬─────────────────────────┘   │
   │                                   │ zabbix_sender              │
   │                                   ▼                            │
   │  ┌────────────────────┐   ┌─────────────────────────────────┐   │
   │  │ Zabbix Server 7.0  │◄──┤ Host "Downdetector" (id 10676)  │   │
   │  │ :10051             │   │ 19 services × 6 items + 5 health│   │
   │  └────────┬───────────┘   └─────────────────────────────────┘   │
   │           │ datasource API                                     │
   │           ▼                                                    │
   │  ┌────────────────────┐                                        │
   │  │ Grafana 13         │  Dashboard "DASHBOARD DOWNDETECTOR"    │
   │  │ :3000              │  UID: downdetector-main                │
   │  └────────────────────┘                                        │
   └─────────────────────────────────────────────────────────────────┘
```

**Fluxo de dados:**

1. Daemon `downdetector-collector` lê `services.yaml`, agenda scrapes por serviço.
2. Cada scrape: chama FlareSolverr via HTTP local; FS abre Chromium real, resolve Cloudflare, retorna HTML.
3. Parser extrai `companyCurrentStatus`, `reportsValue`, `companyName`, `companyId`.
4. Daemon envia métricas via `zabbix_sender` ao Zabbix.
5. Grafana lê do Zabbix pelo plugin `alexanderzobnin-zabbix-datasource` e renderiza o dashboard.

---

## 2. Componentes e versões

| Componente | Versão | Localização | Função |
|---|---|---|---|
| **Ubuntu Server** | 24.04.3 LTS | `srv-zabbix` (10.0.0.42) | Host base |
| **Zabbix Server** | 7.0.19 | `127.0.0.1:10051` | Trapper + storage |
| **Grafana** | 13.0.1+security-01 | `:3000` | Dashboard UI |
| **FlareSolverr** | latest (Docker) | `127.0.0.1:8191` | Bypass Cloudflare |
| **Python** | 3.12 | `/opt/downdetector-collector/.venv` | Runtime do daemon |
| **EdgeRouter Lite** | EdgeOS v3.0.1 | `10.0.0.1` | Gateway + PBR |
| **Starlink** | — | `eth1` (100.125.39.148) | WAN secundária (egress do srv-zabbix) |

Plugin Grafana obrigatório: `alexanderzobnin-zabbix-app` (v5.0.4+).

---

## 3. Instalação do zero

### 3.1 Pacotes do sistema

```bash
apt update
apt install -y python3.12 python3.12-venv python3-pip git \
  zabbix-server-mysql zabbix-frontend-php zabbix-sql-scripts \
  zabbix-agent2 traceroute mtr sshpass docker.io
systemctl enable --now docker
```

### 3.2 Zabbix Server

Instala via repo oficial Zabbix 7.0 e cria o banco. Detalhes em
[zabbix.com/documentation](https://www.zabbix.com/documentation/7.0/manual/installation).

Após subir o serviço, criar via API (ou UI):

- **Template group**: `Templates/Web`
- **Template**: `Template Downdetector` (carregar `zabbix/tmpl_downdetector.yaml`)
- **Host**: `Downdetector` (carregar `zabbix/host_downdetector.yaml`); vincular ao template
- **External script**: copiar `zabbix/externalscripts/downdetector_discovery.py` pra `/usr/lib/zabbix/externalscripts/` e dar `chmod 755 + chown zabbix:zabbix`

Tudo isso já está aplicado neste servidor — host `Downdetector` tem `hostid=10676`.

**Credenciais default no servidor atual:** `Admin / zabbix` (senha do Zabbix UI Admin).

### 3.3 Grafana 13

```bash
# Add repo oficial
mkdir -p /etc/apt/keyrings
wget -O - https://apt.grafana.com/gpg.key | gpg --dearmor -o /etc/apt/keyrings/grafana.gpg
echo "deb [signed-by=/etc/apt/keyrings/grafana.gpg] https://apt.grafana.com stable main" \
  > /etc/apt/sources.list.d/grafana.list
apt update
apt install -y grafana
systemctl enable --now grafana-server

# Plugin Zabbix
grafana-cli plugins install alexanderzobnin-zabbix-app
systemctl restart grafana-server
```

### 3.4 FlareSolverr (Docker)

```bash
docker run -d --restart unless-stopped --name flaresolverr \
  -p 127.0.0.1:8191:8191 \
  -e LOG_LEVEL=info \
  -e TZ=America/Sao_Paulo \
  ghcr.io/flaresolverr/flaresolverr:latest
```

Verificar: `curl http://127.0.0.1:8191/` deve responder com JSON `"FlareSolverr is ready!"`.

### 3.5 Daemon downdetector-collector

```bash
# Source em /home/cristiano (dev), instala editable em /opt (deploy)
cd /home/cristiano
git clone <repo> downdetector-collector
cd downdetector-collector

# venv de DESENVOLVIMENTO em /home (pra testar/regenerar dashboard etc)
python3.12 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/pip install pytest

# venv de PRODUÇÃO em /opt (o systemd unit usa esse)
useradd -r -s /bin/false downdetector
mkdir -p /opt/downdetector-collector /etc/downdetector-collector /var/log/downdetector-collector
python3.12 -m venv /opt/downdetector-collector/.venv
/opt/downdetector-collector/.venv/bin/pip install -e /home/cristiano/downdetector-collector
chown -R downdetector:downdetector /opt/downdetector-collector /var/log/downdetector-collector

# Config inicial (copia template e edita conforme seção 4)
cp /home/cristiano/downdetector-collector/config/services.example.yaml \
   /etc/downdetector-collector/services.yaml
chown root:root /etc/downdetector-collector/services.yaml
chmod 644 /etc/downdetector-collector/services.yaml

# Systemd unit
cp /home/cristiano/downdetector-collector/systemd/downdetector-collector.service \
   /etc/systemd/system/
systemctl daemon-reload
systemctl enable downdetector-collector
```

**Importante**: o `pip install -e` aponta o pacote `collector` do venv de produção
direto pra `/home/cristiano/downdetector-collector/collector/`. Isso significa que
editar o código em `/home/cristiano/...` afeta o daemon ao reiniciar — não precisa
re-instalar a cada mudança.

### 3.6 Plugin Zabbix no Grafana — configuração

UI: `http://srv-zabbix:3000` → Connections → Add data source → Zabbix:

- URL: `http://localhost/zabbix/api_jsonrpc.php`
- Auth: `Admin / zabbix`
- Trends: enabled
- Save & test

UID da datasource: `zabbix` (referenciada no `bin/build_dashboard.py`).

### 3.7 Provisionamento Grafana

```bash
# Cria arquivo de provisioning de dashboard
mkdir -p /var/lib/grafana/dashboards/downdetector
chown -R grafana:grafana /var/lib/grafana/dashboards

cat > /etc/grafana/provisioning/dashboards/downdetector.yaml <<'EOF'
apiVersion: 1
providers:
  - name: downdetector
    orgId: 1
    folder: ''
    type: file
    disableDeletion: false
    updateIntervalSeconds: 30
    allowUiUpdates: true
    options:
      path: /var/lib/grafana/dashboards/downdetector
EOF

# Gera o dashboard inicial
cd /home/cristiano/downdetector-collector
.venv/bin/python bin/build_dashboard.py

# Logos: gerar placeholders + baixar reais
.venv/bin/python bin/fetch_logos.py

systemctl restart grafana-server
```

> ⚠️ **Bug do Grafana 13**: o file provisioner às vezes para de detectar mudanças em arquivos novos. Pra forçar reimportação após regerar o dashboard, faça `systemctl restart grafana-server` (não basta SIGHUP nem polling automático).

### 3.8 Policy-Based Routing no EdgeRouter (Starlink)

Pra o `srv-zabbix` (10.0.0.42) sair pela Starlink (eth1) em vez do PPPoE NewLife:

```bash
# Via SSH no router (sshpass instalado no host pra script):
ssh -p 2050 claude@10.0.0.1 'sudo tee /config/scripts/post-config.d/zz-pbr-srv-zabbix.sh > /dev/null' <<'EOF'
#!/bin/bash
# PBR: srv-zabbix sai via Starlink
set -e
for i in 1 2 3 4 5 6 7 8 9 10; do
    if ip -4 addr show eth1 | grep -q 'inet '; then break; fi
    sleep 3
done
ip route replace default via 100.64.0.1 dev eth1 table 200
ip rule del from 10.0.0.42 lookup 200 priority 100 2>/dev/null || true
ip rule add from 10.0.0.42 lookup 200 priority 100
ip route flush cache
EOF
ssh -p 2050 claude@10.0.0.1 'sudo chmod 755 /config/scripts/post-config.d/zz-pbr-srv-zabbix.sh && sudo /config/scripts/post-config.d/zz-pbr-srv-zabbix.sh'
```

Validar: do `srv-zabbix`, `curl https://api.ipify.org` deve retornar `153.67.103.190` (IP Starlink).

**Por que `dev eth1` explícito**: o gateway `100.64.0.1` aparece em duas interfaces (CGNAT compartilhado). Sem `dev eth1`, o kernel resolveria pela tabela main que aponta pra `pppoe0`, e os pacotes voltariam pelo NewLife.

NAT masquerade no `eth1` já existe na config do EdgeRouter (rule 5001) — basta ter PBR.

### 3.9 Timezone

```bash
timedatectl set-timezone America/Sao_Paulo
systemctl restart zabbix-server   # pra logs do Zabbix em BRT
# Grafana já lê do dashboard JSON, que tem "timezone": "America/Sao_Paulo"
```

---

## 4. Configuração

### 4.1 `services.yaml` — lista de serviços

Arquivo: `/etc/downdetector-collector/services.yaml`

```yaml
defaults:
  poll_interval: 300    # segundos entre scrapes (default global)
  country: br           # afeta URL: downdetector.com.<country>/status/<slug>/

services:
  - name: Instagram                                    # nome exibido
    slug: instagram                                    # parte da URL Downdetector
    id: 33204                                          # company_id (opcional, só LLD cosmético)
    logo: /public/img/downdetector/instagram.svg       # path pro Grafana servir
    poll_interval: 60                                  # override (opcional)
    country: com                                       # override (opcional)
```

**Campos:**

- `name` *(obrigatório)*: nome legível. Usado no Zabbix como prefixo (`Instagram: status`) e no dashboard como label.
- `slug` *(obrigatório)*: identificador no Downdetector. URL fica `https://downdetector.com.br/status/<slug>/`. Deve existir no Downdetector (alguns BR não existem, ex: skype, receita-federal).
- `id` *(obrigatório, pode ser 0)*: company_id. Cosmético no LLD do Zabbix; o real é coletado a cada scrape e enviado em `downdetector.company_id[<slug>]`.
- `logo` *(obrigatório)*: path absoluto servido pelo Grafana. Convenção: `/public/img/downdetector/<slug>.svg`.
- `poll_interval` *(opcional)*: intervalo em segundos. Default 300 (5min). Mínimo prático 60s.
- `country` *(opcional)*: country code. Default `br`. Usar `com` pra forçar `.com` (sem `.br`).

### 4.2 Recarregar config sem restart

```bash
systemctl reload downdetector-collector   # envia SIGHUP
# Verificar no log:
tail -3 /var/log/downdetector-collector/collector.log | grep config_loaded
```

`reload` apenas re-lê o YAML e reconstrói o scheduler. Mudanças no **código Python** exigem `restart`.

### 4.3 Adicionar um serviço

1. Editar `/etc/downdetector-collector/services.yaml` com o novo entry.
2. `systemctl reload downdetector-collector`.
3. Aguardar ~5min — Zabbix LLD descobre o novo slug e cria os 6 items dele automaticamente.
4. Regenerar dashboard: `cd /home/cristiano/downdetector-collector && .venv/bin/python bin/build_dashboard.py`.
5. `systemctl restart grafana-server` (pelo bug do provisioner).
6. Hard-refresh no browser.

### 4.4 Remover um serviço

1. Editar YAML, remover o entry.
2. `systemctl reload downdetector-collector`.
3. **Limpar items órfãos no Zabbix** (LLD não apaga automaticamente — itens viram "Disabled" mas permanecem):
   ```bash
   AUTH=$(curl -s -X POST -H "Content-Type: application/json-rpc" \
     -d '{"jsonrpc":"2.0","method":"user.login","params":{"username":"Admin","password":"zabbix"},"id":1}' \
     http://localhost/zabbix/api_jsonrpc.php | python3 -c "import json,sys; print(json.load(sys.stdin)['result'])")
   # Listar items do slug:
   curl -s -X POST -H "Content-Type: application/json-rpc" \
     -d "{\"jsonrpc\":\"2.0\",\"method\":\"item.get\",\"params\":{\"hostids\":\"10676\",\"output\":[\"itemid\"],\"search\":{\"key_\":\"[SLUG_AQUI]\"}},\"auth\":\"$AUTH\",\"id\":2}" \
     http://localhost/zabbix/api_jsonrpc.php
   # Deletar com item.delete passando os itemids
   ```
4. Regenerar dashboard + restart Grafana.

### 4.5 Mudar `poll_interval` global

Editar `defaults.poll_interval` em `/etc/downdetector-collector/services.yaml`. Cuidado com rate limit: a regra prática é **manter demanda < 10 req/min** pra IP residencial; abaixo de 5 req/min é seguro pra qualquer IP. Cálculo:

```
demanda (req/min) = sum(60 / svc.poll_interval for svc in services)
```

Para 19 serviços a 300s: `19 * (60/300) = 3.8 req/min`. OK.

### 4.6 Layout do dashboard

Gerado por `bin/build_dashboard.py`. Constantes principais no topo do arquivo:

```python
CARDS_PER_ROW = 8      # serviços por linha (24 cols / 8 = w=3 cada)
LOGO_H = 4             # altura do header logo+nome
STATUS_H = 2           # altura do badge Ok/Atenção/Problema
REPORTS_H = 2          # altura do número de relatos
TOP_H = 3              # altura da linha de cima (contadores + saúde)
```

Thresholds dos relatos (cores genéricas, não calibradas por serviço):

```python
{"color": "#3498DB", "value": None},   # azul até 30
{"color": COLOR_ATTN, "value": 30},    # laranja 30-99
{"color": COLOR_PROB, "value": 100},   # vermelho 100+
```

Para regerar:

```bash
cd /home/cristiano/downdetector-collector
.venv/bin/python bin/build_dashboard.py
systemctl restart grafana-server   # workaround Grafana 13 provisioner
```

---

## 5. Operação dia-a-dia

### 5.1 Comandos rápidos

```bash
# Status do daemon
systemctl status downdetector-collector
systemctl is-active downdetector-collector

# Ligar/desligar (recolher tráfego pro Downdetector)
systemctl start downdetector-collector
systemctl stop downdetector-collector

# Recarregar config (SIGHUP, sem reiniciar processo)
systemctl reload downdetector-collector

# Logs estruturados (JSON, structlog)
tail -F /var/log/downdetector-collector/collector.log | jq -c .
# Filtrar só não-rotineiros:
tail -F /var/log/downdetector-collector/collector.log | grep -vE 'zabbix_sender_ok.*count..5'

# FlareSolverr
docker ps | grep flaresolverr
docker restart flaresolverr        # se Chromium travar (HTTP 500 freq)
docker logs --tail 50 flaresolverr

# Zabbix Server
systemctl status zabbix-server
tail -F /var/log/zabbix/zabbix_server.log

# Grafana
systemctl status grafana-server
tail -F /var/log/grafana/grafana.log
```

### 5.2 Eventos comuns no log do daemon

| Evento | Significado | Ação |
|---|---|---|
| `config_loaded count=N` | Reload OK, N serviços ativos | — |
| `sighup_received_reloading_config` | SIGHUP recebido | — |
| `term_received_stopping` | SIGTERM/SIGINT recebido | — |
| `zabbix_sender_ok count=5` | Push de health metrics (a cada 60s) | — |
| `zabbix_sender_ok count=3` | Scrape OK (status+last_check+reports) | — |
| `zabbix_sender_ok count=6` | Scrape OK + meta push (name/company_id/logo, cada N scrapes) | — |
| `scrape_blocked` | Cloudflare 403 ou challenge "Just a moment..." | Backoff exponencial automático |
| `scrape_rate_limited` | Página 429 `(╯°□°)╯︵ ┻━┻` do Downdetector | Backoff exponencial automático |
| `flaresolverr_http_error status=500` | Chromium do FS travou | Retry no próximo ciclo; se persistente, `docker restart flaresolverr` |
| `scrape_timeout` | Timeout no FS (>60s) | Idem |
| `zabbix_sender_failed` | Zabbix Server não aceitou — item inexistente ou daemon zabbix-server caído | `systemctl restart zabbix-server` |

### 5.3 Métricas no Zabbix (host "Downdetector")

Por serviço (LLD descobre via `services.yaml`):

| Key | Tipo | Descrição |
|---|---|---|
| `downdetector.status[<slug>]` | UNSIGNED | 0=Ok, 1=Atenção, 2=Problema, 3=N/D |
| `downdetector.reports[<slug>]` | UNSIGNED | Relatos na última hora (mais recente do chartData) |
| `downdetector.last_check[<slug>]` | UNSIGNED | Unix timestamp do último scrape OK |
| `downdetector.name[<slug>]` | CHAR | Nome do serviço (cosmético, raramente muda) |
| `downdetector.company_id[<slug>]` | UNSIGNED | company_id descoberto (idem) |
| `downdetector.logo[<slug>]` | CHAR | Path do logo SVG (idem) |

Globais (saúde do scraper):

| Key | Descrição |
|---|---|
| `downdetector.scraper.uptime` | Uptime do processo em segundos |
| `downdetector.scraper.cycle_seconds` | Duração do último scrape |
| `downdetector.scraper.blocks_5m` | Bloqueios CF + 429 nos últimos 5min |
| `downdetector.scraper.restarts` | Reinícios do browser (não usado com FlareSolverr) |
| `downdetector.scraper.healthy` | 1 = blocks_5m ≤ 10, 0 = degradado |

Triggers do template (em `zabbix/tmpl_downdetector.yaml`):

- `[Atenção] {#NAME} reportando problemas leves` — status=1
- `[Problema] {#NAME} reportando falha grave` — status=2
- `[Stale] {#NAME} sem coleta há mais de 10min` — last_check antigo

### 5.4 Re-scrapeio manual de serviços travados

Quando um serviço fica em N/D por tempo demais e quer forçar refresh:

```bash
cd /home/cristiano/downdetector-collector
.venv/bin/python bin/refresh_nd.py
```

Esse script:
1. Lê do Zabbix quais slugs estão com `status=3` (N/D)
2. Re-scrapeia cada um via FlareSolverr (mesmo backend do daemon)
3. Faz push do valor novo via `zabbix_sender` se o parse der certo

---

## 6. Troubleshooting

### 6.1 "Tudo travou em N/D"

1. Daemon ativo? `systemctl is-active downdetector-collector`
2. FlareSolverr OK? `curl -s http://127.0.0.1:8191/` → `"FlareSolverr is ready!"`
3. Egress OK? `curl -s --max-time 5 https://api.ipify.org` → tem que dar 153.67.103.190 (Starlink)
4. Está pegando 429? `tail -200 /var/log/downdetector-collector/collector.log | grep rate_limited`
5. Se 429 persistente: `systemctl stop downdetector-collector` e aguardar 1-4h para o IP esfriar. Considerar trocar o egress (Starlink → NewLife) temporariamente.

### 6.2 "Dashboard mostra valores antigos / não atualiza"

Grafana 13 tem bug no file provisioner — não detecta mudanças no JSON.

```bash
.venv/bin/python bin/build_dashboard.py  # regera
systemctl restart grafana-server         # força reimportação
# Hard-refresh no browser (Ctrl+Shift+R)
```

Confirmar versão no unified storage:

```bash
sqlite3 /var/lib/grafana/grafana.db \
  "SELECT value FROM resource WHERE name='downdetector-main';" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print('panels:', len(d['spec'].get('panels',[])))"
```

### 6.3 "Senha do Grafana admin esquecida"

```bash
grafana-cli admin reset-admin-password '<NovaSenha>'
```

⚠️ **Risco**: se a senha custom era importante, salvar `password+salt` do SQLite ANTES de resetar:

```bash
sqlite3 /var/lib/grafana/grafana.db \
  "SELECT login, password, salt FROM user WHERE login='admin';"
# Após uso, restaurar:
sqlite3 /var/lib/grafana/grafana.db \
  "UPDATE user SET password='<orig_password>', salt='<orig_salt>' WHERE login='admin';"
```

### 6.4 "FlareSolverr retorna 500 em rajada"

Chromium interno crashou. Quase sempre se recupera sozinho no próximo scrape. Se persistente:

```bash
docker restart flaresolverr
sleep 5
curl -s http://127.0.0.1:8191/   # confirmar ready
```

### 6.5 "Item órfão no Zabbix após mudar slug"

LLD não deleta items quando o slug some do YAML. Procedimento de limpeza está na seção 4.4.

### 6.6 "Dashboard mostra serviço errado em N/D mas site mostra Ok"

Dois cenários:
1. **Scrape pegou um pico antigo** — daemon coleta o último bucket do chartData (uma hora cheia, não pontos isolados). Aguardar próximo ciclo (default 5min).
2. **Slug não existe no Downdetector** — testar manualmente:
   ```bash
   curl -sX POST -H "Content-Type: application/json" http://localhost:8191/v1 \
     -d '{"cmd":"request.get","url":"https://downdetector.com.br/status/<SLUG>/","maxTimeout":30000}' \
     | python3 -c "import json,sys,re; html=json.load(sys.stdin)['solution']['response']; m=re.search(r'companyCurrentStatus\\\\+\":\s*\\\\+\"([a-z]+)', html); print('status:', m.group(1) if m else 'NOT FOUND (slug inválido?)')"
   ```
   Se voltar "NOT FOUND" o slug é inválido — remover ou corrigir no YAML.

### 6.7 "Servidor saindo pelo NewLife em vez de Starlink"

```bash
# No srv-zabbix:
curl -s https://api.ipify.org    # deve ser 153.67.103.190 (Starlink)
# Se for 177.72.82.28 (NewLife), PBR caiu. Reaplicar:
ssh -p 2050 claude@10.0.0.1 'sudo /config/scripts/post-config.d/zz-pbr-srv-zabbix.sh'
```

Em caso de reboot do EdgeRouter, o script `/config/scripts/post-config.d/zz-pbr-srv-zabbix.sh` é executado automaticamente. Se não estiver: re-criar conforme seção 3.8.

### 6.8 "Disco apertado"

```bash
df -h /
journalctl --vacuum-size=200M
docker system prune -af               # libera images/containers parados
# Cache do Playwright (não usado em runtime mas instalado):
rm -rf /root/.cache/ms-playwright     # ~1GB
```

---

## 7. Layout de arquivos (referência)

### 7.1 No servidor (`srv-zabbix`)

```
/home/cristiano/downdetector-collector/              # repo dev (git)
├── collector/                                       # daemon Python (importado pelo /opt via -e)
│   ├── __main__.py                                  # entrypoint, SIGHUP reload
│   ├── scraper.py                                   # FlareSolverr async via httpx
│   ├── parser.py                                    # markers Next.js + detect 429/CF
│   ├── config.py                                    # YAML loader
│   ├── scheduler.py                                 # heap async com backoff exponencial
│   ├── health.py                                    # métricas internas
│   ├── zabbix_sink.py                               # wrapper zabbix_sender
│   └── stealth.py                                   # (legado, não usado)
├── bin/
│   ├── build_dashboard.py                           # gera dashboard JSON do yaml
│   ├── fetch_logos.py                               # baixa SVGs (simple-icons + google favicon)
│   ├── refresh_nd.py                                # re-scrape one-off de N/D
│   ├── discover.py                                  # descobre slug → company_id
│   ├── bulk_discover.py                             # idem em batch
│   └── snapshot.py                                  # captura HTML fixture
├── tests/                                           # pytest, 5 suítes
├── zabbix/                                          # template + externalscript + host yaml
├── grafana/                                         # dashboard JSON template + logos
├── config/services.example.yaml                     # template do services.yaml
├── pyproject.toml                                   # deps + install editable
├── DOCS.md                                          # este arquivo
├── CLAUDE.md                                        # contexto p/ sessões Claude
├── INSTALL.md                                       # guia legacy (substituído por DOCS.md)
├── README.md                                        # placeholder
└── workflow.md                                      # workflow de orquestração inicial

/opt/downdetector-collector/                         # deploy de produção
└── .venv/                                           # venv Python 3.12 (editable install)

/etc/downdetector-collector/services.yaml            # CONFIG DE PRODUÇÃO
/etc/systemd/system/downdetector-collector.service   # systemd unit
/var/log/downdetector-collector/collector.log        # logs JSON (structlog)
/usr/lib/zabbix/externalscripts/downdetector_discovery.py  # LLD external

/etc/grafana/grafana.ini                             # config principal Grafana
/etc/grafana/provisioning/datasources/downdetector.yaml
/etc/grafana/provisioning/dashboards/downdetector.yaml
/var/lib/grafana/dashboards/downdetector/dashboard_downdetector.json
/var/lib/grafana/grafana.db                          # SQLite (dashboards, users, secrets)
/usr/share/grafana/public/img/downdetector/*.svg     # logos servidos em /public/img/downdetector/<slug>.svg
```

### 7.2 No EdgeRouter (`10.0.0.1`)

```
/config/config.boot                                  # config principal (Vyatta YAML)
/config/config.boot.pre-pbr-srv-zabbix               # backup pré-PBR
/config/scripts/post-config.d/zz-pbr-srv-zabbix.sh   # script de persistência PBR
```

---

## 8. Decisões arquiteturais — por que assim

### 8.1 Por que FlareSolverr e não Playwright/Selenium direto

Cloudflare exige **Private Access Token (PAT)** desde 2025 pra acessar a maioria dos sites protegidos. PAT requer atestação de hardware (Apple Secure Enclave ou similar). Playwright/Selenium em servidor headless **sempre** retorna 401 em `challenges.cloudflare.com/.../pat/...`.

FlareSolverr resolve isso usando Chromium próprio com bypass especializado (Chrome DevTools Protocol em modo undetected). É o único que funciona consistentemente no ambiente atual.

Testei também `cloudscraper` (lib Python): falha 100% no Cloudflare v3+ do Downdetector. **Não é usada** apesar de estar instalada no venv (legado de tentativa).

Testei também **Scrapling** (lib Python v0.4.8, biblioteca moderna com StealthyFetcher): também falha em 403 no IP do servidor. **Instalada mas não usada**. Pode ser revisitada com IP fresco.

### 8.2 Por que PBR via Starlink

O IP do datacenter onde o servidor está hospedado (NewLife PPPoE, 177.72.82.28) ficou marcado pelo Cloudflare do Downdetector após dias de testes de scraping. Mesmo backoff e baixa frequência mantinham 429s intermitentes.

A Starlink (rede residencial CGNAT compartilhada) dá ao servidor um IP que rotaciona dentro de um pool gigante (`153.x.x.x` no momento). **Reputação fresca** = scrapes 100% sucesso na primeira tentativa.

PBR (não default route) preserva o NewLife como saída pros demais hosts da rede 10.0.0.0/24, evitando degradar o resto da rede com latência satelital extra.

### 8.3 Por que markers Next.js no parser

O Downdetector migrou para Next.js em 2025. O HTML antigo (Bootstrap 4 com classes `color-success/warning/danger` nos `<span>`) não existe mais nas páginas atuais — apenas em fallback de homepage/rate-limit.

Markers atuais (capturados em `collector/parser.py`):

- Status: regex `"companyCurrentStatus":"(success|warning|danger)"` no JSON SSR
- Reports: último valor de `"reportsValue":N` no chartData (série temporal de 96 pontos)
- Name: `"companyName":"X"`
- company_id: `"companyId":"N"`

Fallback CSS pra `border-[var(--color-dd-...)]` cobre o caso de mudança de schema JSON sem mudança visual.

Detecção de 429 do Downdetector: 3 marcadores na página de "tabela virada", precisa de 2+ pra ativar (reduz falso-positivo):
- `"(╯°□°)╯︵ ┻━┻"` (h1)
- `"429 Rate Limited"`
- `"blocked from accessing"`

### 8.4 Por que `pip install -e` (editable) em vez de instalar como pacote

Permite editar `/home/cristiano/downdetector-collector/collector/*.py` e o daemon (rodando do venv em `/opt`) pega a mudança no próximo restart, sem precisar empacotar e reinstalar. Reduz fricção de iterar.

Trade-off: o código de produção depende fisicamente de `/home/cristiano/...`. Se aquele diretório for renomeado/movido, o daemon quebra. Mover é raro o suficiente pra não compensar overhead de reempacotar.

### 8.5 Por que dashboard regenerado por script vs editado na UI

O Grafana 13 tem `allowUiUpdates: true` no provisioner — edições UI persistem **até o próximo provisioning**, quando são sobrescritas. Isso significa: ajustes finos pontuais (mudar uma cor, mexer num threshold) podem ser feitos na UI, mas mudanças **estruturais** (adicionar serviço, mudar layout) devem ser feitas em `bin/build_dashboard.py` pra serem reproduzíveis.

Layout atual gerado é v19 = 19 serviços × 3 panels (logo + status + reports) + linha de topo unificada (contadores + saúde) + título = 66 panels totais. Card de cada serviço: `w=3, h=8` em grid 24 colunas (8 por linha).

---

## 9. Testes

```bash
cd /home/cristiano/downdetector-collector
.venv/bin/pytest tests/ -v
```

Suítes:

- `test_parser.py` — 5 testes contra fixtures HTML reais
- `test_config.py` — loader YAML, defaults, validação
- `test_scheduler.py` — heap, backoff exponencial, async timing
- `test_health.py` — bucket de 5min, métricas
- `test_zabbix_sink.py` — payload sanitization, subprocess mock

Sem fixtures pesadas → roda em <1s. Idealmente rodar antes de qualquer commit em `collector/`.

---

## 10. Limites conhecidos

- **Backend único** (FlareSolverr): se o Chromium do container travar e não recuperar, todos os scrapes param. Detectado por `flaresolverr_http_error 500` no log. Mitigation: `docker restart flaresolverr`.
- **Sem proxy rotation**: scraps saem todos pelo IP da Starlink. Se queimar de novo, próxima opção é proxy comercial (não implementado).
- **Reports sem baseline per-serviço**: a cor do número de relatos no dashboard usa thresholds genéricos (30/100). Para serviços com baseline baixo (banco regional), 30 já é muito; para alto volume (WhatsApp), 30 é normal. Aceitar imprecisão visual ou hardcodar threshold por serviço no `services.yaml` (não suportado hoje).
- **LLD não apaga items órfãos**: quando um slug some do YAML, os items existem mas viram "Disabled". Limpeza manual conforme 4.4.
- **Grafana 13 file provisioner não polleia confiavelmente**: regerar dashboard exige `systemctl restart grafana-server`. Bug do upstream.
- **Sem alerta nativo**: triggers do Zabbix funcionam mas não há integração com Slack/email/etc neste setup. Configurar pelos canais nativos do Zabbix se precisar.

---

## 11. Comandos úteis (cheat sheet)

```bash
# Daemon
systemctl {status,start,stop,reload,restart} downdetector-collector
journalctl -u downdetector-collector --since "10 min ago" --no-pager

# Logs daemon
tail -F /var/log/downdetector-collector/collector.log | jq -c .

# Regerar dashboard (após mudar services.yaml)
cd /home/cristiano/downdetector-collector
.venv/bin/python bin/build_dashboard.py && systemctl restart grafana-server

# Re-scrape forçado de N/D
.venv/bin/python bin/refresh_nd.py

# Baixar logos faltantes
.venv/bin/python bin/fetch_logos.py

# Testar parse de uma página manualmente
curl -sX POST -H "Content-Type: application/json" http://127.0.0.1:8191/v1 \
  -d '{"cmd":"request.get","url":"https://downdetector.com.br/status/instagram/","maxTimeout":30000}' \
  | python3 -c "
import json, sys, re
html = json.load(sys.stdin)['solution']['response']
m = re.search(r'\"companyCurrentStatus\\\\+\":\s*\\\\+\"([a-z]+)', html)
v = re.findall(r'reportsValue\\\\+\":\s*(\d+)', html)
print(f'status={m.group(1) if m else \"?\"} reports={v[-1] if v else \"?\"}')"

# Confirmar IP de saída
curl -s --max-time 5 https://api.ipify.org

# Login Zabbix API
AUTH=$(curl -s -X POST -H "Content-Type: application/json-rpc" \
  -d '{"jsonrpc":"2.0","method":"user.login","params":{"username":"Admin","password":"zabbix"},"id":1}' \
  http://localhost/zabbix/api_jsonrpc.php | python3 -c "import json,sys; print(json.load(sys.stdin)['result'])")

# Estado dos items
curl -s -X POST -H "Content-Type: application/json-rpc" \
  -d "{\"jsonrpc\":\"2.0\",\"method\":\"item.get\",\"params\":{\"hostids\":\"10676\",\"output\":[\"key_\",\"lastvalue\",\"lastclock\"],\"search\":{\"key_\":\"downdetector.status[\"}},\"auth\":\"$AUTH\",\"id\":2}" \
  http://localhost/zabbix/api_jsonrpc.php | python3 -m json.tool

# EdgeRouter SSH (Starlink PBR)
ssh -p 2050 claude@10.0.0.1
# Verificar PBR ativa
ssh -p 2050 claude@10.0.0.1 'ip rule show && ip route show table 200'
```

---

## 12. Histórico de mudanças relevantes

| Data | Mudança |
|---|---|
| 2026-05-12 | Implementação inicial: 3 services (Google, Cloudflare, WhatsApp), poll 3600s, Grafana 11.6 |
| 2026-05-12 | Upgrade Grafana 11.6 → 13.0.1 |
| 2026-05-12 | Expansão pra 58 services (lista AlanMartines), dashboard v17 com grid 8/linha |
| 2026-05-12 | Logos reais via simple-icons + Google favicon |
| 2026-05-13 | Bug Grafana 13 filterByValue: trocou reducer `lastNotNull` → `last` |
| 2026-05-13 | Dashboard v19: top row unificado (counters + health em h=3), card h=8 com logo h=4 |
| 2026-05-13 | Adicionado UA rotation, jitter 2-5s, parser detecta 429 |
| 2026-05-13 | Adicionado cloudscraper e scrapling (não funcionam no IP — instalados como legado) |
| 2026-05-13 | Trim pra 19 services (redes sociais + YouTube + bancos) |
| 2026-05-13 | PBR no EdgeRouter: srv-zabbix → Starlink |
| 2026-05-13 | Timezone do servidor + dashboard → America/Sao_Paulo |
