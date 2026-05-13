# downdetector-collector

> Daemon Python que coleta status de serviços do [Downdetector](https://downdetector.com.br) e envia métricas para o **Zabbix**, com dashboard pronto no **Grafana**.

Bypass de Cloudflare via [FlareSolverr](https://github.com/FlareSolverr/FlareSolverr), parser tolerante a mudanças de schema (Next.js + fallback CSS), detecção automática de rate-limit (HTTP 429) com backoff exponencial, e dashboard regenerado a partir de um único arquivo YAML.

---

## ✨ Funcionalidades

- 🔍 **Scraping resiliente** via FlareSolverr (Chromium real em container Docker)
- 📊 **Integração nativa Zabbix** — usa `zabbix_sender` + LLD (Low-Level Discovery)
- 🎨 **Dashboard Grafana gerado** — define os serviços em YAML, regenera o painel automaticamente
- 🔁 **Rotação de User-Agent**, jitter humano (2-5s) e detecção de 429 com backoff
- 🩺 **Métricas de saúde** do próprio scraper (uptime, ciclo, blocks/5min)
- 🌎 **Multi-país** — funciona com `downdetector.com.br`, `.com`, `.com.mx`, etc.
- 📈 **6 métricas por serviço**: status (Ok/Atenção/Problema/N/D), número de relatos, último check, nome, company_id, logo

## 🖼️ Preview

Card individual de cada serviço:

```
┌────────────────┐
│   [LOGO]       │  ← logo + nome do serviço
│   Instagram    │
├────────────────┤
│   Atenção      │  ← status colorido (Ok=verde, Atenção=laranja, Problema=vermelho)
├────────────────┤
│   47 R         │  ← número de relatos na última hora
└────────────────┘
```

Topo do dashboard:

```
┌─────┬─────┬─────┬─────┬──────┬─────────┬──────────┬─────────┐
│Total│ Ok  │ Atn │Prob │Uptime│ Ciclo s │ CF/5min  │Restarts │
└─────┴─────┴─────┴─────┴──────┴─────────┴──────────┴─────────┘
                          Painel Downdetector
[card 1][card 2][card 3][card 4][card 5][card 6][card 7][card 8]
[card 9][card 10][card 11]...
```

---

## 🏗️ Arquitetura

```
┌─────────────────────┐
│ downdetector.com.br │
│ (atrás de Cloudflare)│
└──────────▲──────────┘
           │ HTTPS
           │
┌──────────┴────────────┐
│ FlareSolverr (Docker) │  ← resolve challenge JS do Cloudflare
│ :8191                 │
└──────────▲────────────┘
           │ HTTP local
           │
┌──────────┴─────────────────┐
│ downdetector-collector     │
│ (daemon Python systemd)    │
│                            │
│ ├ scheduler async (heap)   │  ← agenda scrapes por serviço
│ ├ parser (regex Next.js)   │  ← extrai status/reports/etc do HTML
│ ├ backoff exponencial      │  ← reage a 429/CF/timeout
│ └ health metrics           │
└──────────┬─────────────────┘
           │ zabbix_sender
           │
┌──────────▼──────────┐    ┌──────────────────┐
│ Zabbix Server       │◄───┤ Grafana          │
│ (host "Downdetector"│    │ (dashboard JSON  │
│  com LLD)           │    │  provisionado)   │
└─────────────────────┘    └──────────────────┘
```

---

## 📋 Requisitos

- **Linux** (testado em Ubuntu 22.04+ e Debian 12+; outras distros com adaptações)
- **Python 3.11+**
- **Docker** (apenas para o FlareSolverr; ~500MB de imagem)
- **Zabbix Server 6.0+** (testado em 7.0)
- **Grafana 10+** com plugin `alexanderzobnin-zabbix-app` (testado em 11.6 e 13.0)
- Acesso de admin no Zabbix (pra importar template) e no Grafana (pra criar datasource e dashboard)
- Saída pra internet (rate-limit do Downdetector pode exigir IP "fresco" — ver [Lidando com rate limiting](#-lidando-com-rate-limiting))

---

## 🚀 Instalação rápida (script)

```bash
git clone https://github.com/<user>/downdetector-collector.git
cd downdetector-collector
sudo ./scripts/install-all.sh --zabbix-url http://zabbix/zabbix --zabbix-password <senha>
```

O script executa:

1. Pacotes do sistema (Python, Docker, zabbix-sender, jq, curl)
2. Container FlareSolverr
3. Usuário do sistema `downdetector`, venv em `/opt/downdetector-collector`, instalação editable
4. Unit systemd e diretórios em `/etc`, `/var/log`
5. Cópia do `services.example.yaml` pra `/etc/downdetector-collector/services.yaml`
6. **Próximos passos manuais** (Zabbix e Grafana): seções 4-5 abaixo

Flags úteis:

```bash
sudo ./scripts/install.sh --skip-flaresolverr   # se já tem rodando em outro host
sudo ./scripts/install.sh --no-start            # instala mas não inicia o daemon
sudo ./scripts/install.sh --help                # lista todas as opções
```

Setup do Zabbix e Grafana é feito por scripts separados (não precisam de root, mas precisam de credenciais):

```bash
./scripts/setup-zabbix.sh   --url http://zabbix/zabbix --user Admin --password zabbix
./scripts/setup-grafana.sh  --url http://grafana:3000  --user admin --password admin
```

---

## 🛠️ Instalação manual

Quem prefere fazer passo a passo:

### 1. Dependências do sistema

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip docker.io \
                    zabbix-sender jq curl wget
sudo systemctl enable --now docker
```

### 2. FlareSolverr (Docker)

```bash
sudo docker run -d --restart unless-stopped --name flaresolverr \
  -p 127.0.0.1:8191:8191 \
  -e LOG_LEVEL=info \
  -e TZ=America/Sao_Paulo \
  ghcr.io/flaresolverr/flaresolverr:latest
```

Confirmar:

```bash
curl http://127.0.0.1:8191/
# deve retornar JSON com "FlareSolverr is ready!"
```

### 3. Daemon

```bash
# Usuário do sistema
sudo useradd -r -s /bin/false downdetector

# Diretórios
sudo mkdir -p /opt/downdetector-collector \
              /etc/downdetector-collector \
              /var/log/downdetector-collector
sudo chown -R downdetector:downdetector /opt/downdetector-collector \
                                        /var/log/downdetector-collector

# Clone + venv editable
sudo git clone https://github.com/<user>/downdetector-collector.git \
               /opt/downdetector-collector/src
sudo python3 -m venv /opt/downdetector-collector/.venv
sudo /opt/downdetector-collector/.venv/bin/pip install \
     -e /opt/downdetector-collector/src

# Config inicial
sudo cp /opt/downdetector-collector/src/config/services.example.yaml \
        /etc/downdetector-collector/services.yaml

# Systemd
sudo cp /opt/downdetector-collector/src/systemd/downdetector-collector.service \
        /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now downdetector-collector
```

### 4. Zabbix — template + host

Pelo **UI** do Zabbix:

1. Configuration → Templates → **Import** → escolher `zabbix/tmpl_downdetector.yaml`
2. Configuration → Hosts → **Import** → escolher `zabbix/host_downdetector.yaml`
   (ou criar manualmente um host chamado `Downdetector`, com interface Agent em `127.0.0.1:10050`, e linkar ao template `Template Downdetector`)
3. Copiar o external script:
   ```bash
   sudo cp zabbix/externalscripts/downdetector_discovery.py \
           /usr/lib/zabbix/externalscripts/
   sudo chown zabbix:zabbix /usr/lib/zabbix/externalscripts/downdetector_discovery.py
   sudo chmod 755 /usr/lib/zabbix/externalscripts/downdetector_discovery.py
   ```

Ou rodar o script automatizado:

```bash
./scripts/setup-zabbix.sh \
  --url http://zabbix.example.com/zabbix \
  --user Admin \
  --password zabbix
```

### 5. Grafana — plugin, datasource, dashboard

```bash
# Plugin Zabbix
sudo grafana-cli plugins install alexanderzobnin-zabbix-app
sudo systemctl restart grafana-server
```

Datasource (Configuration → Data sources → Add → Zabbix):
- URL: `http://localhost/zabbix/api_jsonrpc.php`
- Auth: usuário + senha do Zabbix
- **Name** do datasource: `Downdetector-Zabbix`
- **UID** do datasource: `downdetector-zabbix` (referenciado no gerador do dashboard)

Provisionamento do dashboard:

```bash
sudo mkdir -p /var/lib/grafana/dashboards/downdetector
sudo chown -R grafana:grafana /var/lib/grafana/dashboards

sudo tee /etc/grafana/provisioning/dashboards/downdetector.yaml > /dev/null <<'EOF'
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

# Gera o dashboard inicial a partir do services.yaml
cd /opt/downdetector-collector/src
sudo /opt/downdetector-collector/.venv/bin/python bin/build_dashboard.py

# Baixa os logos dos serviços (simple-icons + Google favicon fallback)
sudo /opt/downdetector-collector/.venv/bin/python bin/fetch_logos.py

sudo systemctl restart grafana-server
```

> ⚠️ **Grafana 13**: o file provisioner às vezes para de detectar mudanças. Após regerar o dashboard, faça `systemctl restart grafana-server` (não basta SIGHUP).

---

## ⚙️ Configuração — `services.yaml`

Arquivo principal: `/etc/downdetector-collector/services.yaml`

```yaml
defaults:
  poll_interval: 300    # intervalo em segundos (default global)
  country: br           # afeta URL: downdetector.com.<country>/status/<slug>/

services:
  - name: Instagram                              # nome exibido nos dashboards
    slug: instagram                              # último componente da URL Downdetector
    id: 33204                                    # company_id (opcional, cosmético)
    logo: /public/img/downdetector/instagram.svg # path servido pelo Grafana

  - name: Banco do Brasil
    slug: banco-do-brasil
    id: 0
    logo: /public/img/downdetector/banco-do-brasil.svg
    poll_interval: 60                            # override por serviço

  - name: Cloudflare
    slug: cloudflare
    id: 32542
    logo: /public/img/downdetector/cloudflare.svg
    country: com                                 # força .com em vez de .br
```

### Campos

| Campo | Obrig. | Default | Descrição |
|---|---|---|---|
| `name` | ✅ | — | Nome legível. Usado como prefixo no Zabbix (`Instagram: status`) e label no dashboard. |
| `slug` | ✅ | — | Identificador no Downdetector. URL fica `https://downdetector.com.<country>/status/<slug>/`. |
| `id` | ✅ | `0` | `company_id`. Cosmético (só aparece na descoberta LLD). O real é coletado a cada scrape. |
| `logo` | ✅ | — | Path absoluto pra o SVG, servido pelo Grafana em `/public/img/downdetector/<slug>.svg`. |
| `poll_interval` | ❌ | `defaults.poll_interval` | Intervalo de scrape em segundos. Mínimo prático: 60s. |
| `country` | ❌ | `defaults.country` | Código de país do Downdetector (`br`, `com`, `mx`, `de`, etc). |

### Como saber o `slug` certo

1. Acessar `https://downdetector.com.br/status/<chute>/` no navegador
2. Se a página carregar com gráfico e contadores, o slug existe
3. Se redirecionar pra homepage ou der "página não encontrada", testar variantes (substituindo espaços por `-`, removendo acentos, etc.)

Alguns slugs comuns: `instagram`, `whatsapp`, `nubank`, `banco-do-brasil`, `banco-itau`, `bradesco`, `google`, `youtube`, `netflix`, `spotify`, `ifood`, `mercado-livre`, `mercadopago`.

### Como saber o `company_id` (opcional)

Use o script `bin/discover.py`:

```bash
/opt/downdetector-collector/.venv/bin/python bin/discover.py \
  --candidates instagram,whatsapp,banco-itau \
  --country br
```

Sai YAML pronto pra colar no `services.yaml`. Mas se você não se importa com o ID exibido, deixa `id: 0` — não afeta o funcionamento.

---

## ➕ Adicionando serviços

1. Editar `/etc/downdetector-collector/services.yaml` com o novo entry
2. Recarregar a config (sem reiniciar o daemon):
   ```bash
   sudo systemctl reload downdetector-collector
   sudo tail -3 /var/log/downdetector-collector/collector.log
   # deve mostrar: "config_loaded count=N"
   ```
3. Aguardar ~5min — o LLD do Zabbix descobre o novo slug e cria automaticamente as 6 métricas
4. Regenerar o dashboard:
   ```bash
   cd /opt/downdetector-collector/src
   sudo /opt/downdetector-collector/.venv/bin/python bin/build_dashboard.py
   sudo /opt/downdetector-collector/.venv/bin/python bin/fetch_logos.py  # baixa o logo novo
   sudo systemctl restart grafana-server
   ```
5. Hard-refresh no browser (Ctrl+Shift+R)

## ➖ Removendo serviços

1. Editar YAML, remover o entry
2. `sudo systemctl reload downdetector-collector`
3. Limpar items órfãos no Zabbix (o LLD desabilita mas não deleta automaticamente):
   ```bash
   ./scripts/cleanup-zabbix-orphans.sh
   ```
4. Regenerar dashboard + restart Grafana

---

## ⏱️ Ajustando intervalos (e cuidado com rate-limit)

O Downdetector usa Cloudflare com proteção anti-bot agressiva. A regra é:

| Faixa | Comportamento esperado |
|---|---|
| `< 5 req/min` | Seguro pra qualquer IP, inclusive datacenter |
| `5-15 req/min` | OK pra IP residencial, instável em datacenter |
| `> 15 req/min` | Vai tomar 429 cedo ou tarde |

Fórmula da demanda:

```
demanda (req/min) = sum(60 / svc.poll_interval) para todos os serviços
```

Exemplos:

| Cenário | Cálculo | req/min |
|---|---|---|
| 10 serviços a 60s | 10 × (60/60) | 10.0 |
| 19 serviços a 300s | 19 × (60/300) | 3.8 |
| 50 serviços a 600s | 50 × (60/600) | 5.0 |
| 100 serviços a 1800s | 100 × (60/1800) | 3.3 |

### O que acontece quando bate 429

O parser detecta a página `(╯°□°)╯︵ ┻━┻` (literal — é a página de bloqueio do Downdetector). O scheduler aplica **backoff exponencial** (300s → 600s → 1200s → ... → 7200s) por serviço, **sem sobrescrever o último valor bom no Zabbix**. Quando o rate-limit expira (~1-4h tipicamente), o serviço volta a coletar normalmente.

---

## 🎨 Dashboard

Gerado por `bin/build_dashboard.py` a partir do `services.yaml`. Modificando constantes no topo do arquivo dá pra ajustar o layout:

```python
CARDS_PER_ROW = 8        # serviços por linha (24 cols / 8 = w=3 cada)
LOGO_H = 4               # altura do header logo+nome (linhas do grid)
STATUS_H = 2             # altura do badge Ok/Atenção/Problema
REPORTS_H = 2            # altura do número de relatos
TOP_H = 3                # altura dos cards de topo (contadores + saúde)
```

Threshold das cores no número de relatos:

```python
{"color": "#3498DB", "value": None},   # azul até 30
{"color": "#F9B115", "value": 30},     # laranja 30-99
{"color": "#E55353", "value": 100},    # vermelho 100+
```

Como esses thresholds são **genéricos** (não calibrados por serviço), serviços de alto volume (WhatsApp, Instagram) tendem a ficar permanentemente laranja/vermelho, enquanto serviços de baixo volume (banco regional) ficam quase sempre azul. A leitura útil é a cor do **status** (badge do meio), que vem da classificação do próprio Downdetector via campo `companyCurrentStatus`.

### Regenerar dashboard

```bash
cd /opt/downdetector-collector/src
sudo /opt/downdetector-collector/.venv/bin/python bin/build_dashboard.py
sudo systemctl restart grafana-server
```

---

## 🖥️ Operação

```bash
# Status + start/stop/reload
sudo systemctl status   downdetector-collector
sudo systemctl start    downdetector-collector
sudo systemctl stop     downdetector-collector
sudo systemctl reload   downdetector-collector   # SIGHUP, só re-lê services.yaml
sudo systemctl restart  downdetector-collector   # restart completo (necessário p/ mudanças no código)

# Logs estruturados (JSON via structlog)
sudo tail -F /var/log/downdetector-collector/collector.log | jq -c .

# Filtrar só eventos não-rotineiros
sudo tail -F /var/log/downdetector-collector/collector.log \
  | grep -vE 'zabbix_sender_ok.*"count":5'

# Force re-scrape de serviços que tão em N/D
cd /opt/downdetector-collector/src
sudo /opt/downdetector-collector/.venv/bin/python bin/refresh_nd.py

# FlareSolverr: status + restart se Chromium travar
sudo docker ps | grep flaresolverr
sudo docker restart flaresolverr
```

### Eventos no log

| Evento | Significado |
|---|---|
| `config_loaded count=N` | Reload OK, N serviços ativos |
| `zabbix_sender_ok count=3` | Scrape OK (status + last_check + reports) |
| `zabbix_sender_ok count=5` | Push de saúde do scraper (a cada 60s) |
| `zabbix_sender_ok count=6` | Scrape OK + meta-push (name + company_id + logo, periódico) |
| `scrape_blocked` | Cloudflare 403 ou challenge — backoff automático |
| `scrape_rate_limited` | Downdetector cuspiu página 429 — backoff longo |
| `flaresolverr_http_error status=500` | Chromium do FS travou — geralmente recupera sozinho |

### Métricas no Zabbix

Para cada serviço (LLD-discovered):

| Item key | Tipo | Descrição |
|---|---|---|
| `downdetector.status[<slug>]` | Unsigned | 0=Ok, 1=Atenção, 2=Problema, 3=N/D |
| `downdetector.reports[<slug>]` | Unsigned | Relatos na última hora |
| `downdetector.last_check[<slug>]` | Unsigned | Unix timestamp do último scrape OK |
| `downdetector.name[<slug>]` | Char | Nome do serviço |
| `downdetector.company_id[<slug>]` | Unsigned | company_id descoberto |
| `downdetector.logo[<slug>]` | Char | Path do logo |

Health global:

- `downdetector.scraper.uptime` — segundos
- `downdetector.scraper.cycle_seconds` — duração do último scrape
- `downdetector.scraper.blocks_5m` — CF + 429 nos últimos 5min
- `downdetector.scraper.healthy` — 1 se OK, 0 se degradado

Triggers do template:

- `[Atenção] <NAME> reportando problemas leves` — status=1
- `[Problema] <NAME> reportando falha grave` — status=2
- `[Stale] <NAME> sem coleta há mais de 10min` — last_check antigo

---

## 🔧 Troubleshooting

### Tudo aparece como N/D

```bash
# 1. Daemon ativo?
sudo systemctl is-active downdetector-collector

# 2. FlareSolverr ready?
curl http://127.0.0.1:8191/

# 3. Saída de internet OK?
curl -s --max-time 5 https://api.ipify.org

# 4. Tomando 429?
sudo tail -200 /var/log/downdetector-collector/collector.log | grep rate_limited
```

Se 429 persistente: parar o daemon, aguardar 1-4h, ver seção [Lidando com rate limiting](#-lidando-com-rate-limiting).

### Dashboard mostra valores antigos

Grafana 13 tem bug no file provisioner. Workaround:

```bash
cd /opt/downdetector-collector/src
sudo /opt/downdetector-collector/.venv/bin/python bin/build_dashboard.py
sudo systemctl restart grafana-server
# Hard-refresh no browser (Ctrl+Shift+R)
```

### FlareSolverr cuspindo HTTP 500

Chromium interno crashou. Quase sempre recupera no próximo scrape. Se persistente:

```bash
sudo docker restart flaresolverr
sleep 5
curl http://127.0.0.1:8191/   # confirmar ready
```

### Slug fica em N/D mesmo com FlareSolverr OK

Provavelmente slug inválido. Testar manualmente:

```bash
SLUG=meu-slug-aqui
curl -sX POST -H "Content-Type: application/json" http://127.0.0.1:8191/v1 \
  -d "{\"cmd\":\"request.get\",\"url\":\"https://downdetector.com.br/status/${SLUG}/\",\"maxTimeout\":30000}" \
  | jq -r '.solution.response' \
  | grep -o 'companyCurrentStatus[^,]*' | head -1
```

Se não retornar nada, o slug não existe nesse país. Tentar outros (`country: com`, variantes do slug, etc.) ou remover.

### Item órfão no Zabbix depois de remover slug

LLD desabilita mas não deleta automaticamente. Usar o script:

```bash
./scripts/cleanup-zabbix-orphans.sh
```

Ou pela UI: Configuration → Hosts → Downdetector → Items → filtrar por "disabled" → Mass Update → Delete.

---

## 🌐 Lidando com rate limiting

O Downdetector usa Cloudflare com proteção anti-bot ativa e tem um **rate-limit próprio no app** (HTTP 200 com página de tabela-virada `(╯°□°)╯︵ ┻━┻`).

**Sintomas de IP queimado:**

- HTTP 403 sustentado em tudo (Cloudflare bloqueou)
- Página 429 (tabela-virada) consistente em vários slugs
- FlareSolverr não consegue resolver o challenge

**Soluções, em ordem de complexidade:**

1. **Diminuir frequência**: subir `poll_interval` pra 600s ou 900s. Tipicamente resolve em algumas horas.
2. **Parar o daemon por 1-4h**: `systemctl stop downdetector-collector`. CF/Downdetector esquecem reputação ruim com o tempo.
3. **Trocar o IP de saída**:
   - Usar uma segunda WAN (Starlink, 4G, etc) via Policy-Based Routing no roteador
   - Proxy/VPN comercial
   - Mover o servidor pra outra rede
4. **Distribuir entre múltiplos containers FlareSolverr** em IPs diferentes (não implementado nativamente; precisa custom).

Em testes, IPs **residenciais** e **Starlink** passam sem 429 mesmo com volume razoável. IPs de **datacenter** tendem a queimar rápido.

---

## 📁 Estrutura do projeto

```
downdetector-collector/
├── collector/                      # daemon Python
│   ├── __main__.py                 # entrypoint, SIGHUP reload
│   ├── scraper.py                  # backend FlareSolverr async (httpx)
│   ├── parser.py                   # regex Next.js + detect 429/CF
│   ├── config.py                   # YAML loader
│   ├── scheduler.py                # heap async com backoff exponencial
│   ├── health.py                   # métricas internas
│   └── zabbix_sink.py              # wrapper sobre zabbix_sender
├── bin/
│   ├── build_dashboard.py          # gera dashboard JSON a partir do services.yaml
│   ├── fetch_logos.py              # baixa logos (simple-icons + Google favicon)
│   ├── refresh_nd.py               # re-scrape one-off de serviços em N/D
│   ├── discover.py                 # descobre slug → company_id
│   └── snapshot.py                 # captura HTML pra fixtures de teste
├── scripts/
│   ├── install.sh                  # instalador end-to-end
│   ├── setup-zabbix.sh             # importa template + host via API
│   ├── setup-grafana.sh            # provisiona datasource + dashboard
│   └── cleanup-zabbix-orphans.sh   # remove items de slugs deletados
├── zabbix/
│   ├── tmpl_downdetector.yaml      # template Zabbix 7.0 (LLD + valuemaps)
│   ├── host_downdetector.yaml      # host de referência
│   └── externalscripts/
│       └── downdetector_discovery.py  # external script p/ LLD
├── grafana/
│   └── dashboard_downdetector.json # dashboard template (regerado pelo build_dashboard.py)
├── config/
│   └── services.example.yaml       # template do services.yaml
├── systemd/
│   └── downdetector-collector.service
├── tests/                          # pytest, 5 suítes
│   ├── test_parser.py
│   ├── test_config.py
│   ├── test_scheduler.py
│   ├── test_health.py
│   └── test_zabbix_sink.py
├── pyproject.toml
└── README.md
```

---

## 🧪 Desenvolvimento

```bash
git clone https://github.com/<user>/downdetector-collector.git
cd downdetector-collector
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

# Rodar testes
.venv/bin/pytest tests/ -v

# Lint
.venv/bin/ruff check .

# Type check
.venv/bin/mypy collector/
```

### Adicionando suporte a outro país do Downdetector

1. Verificar que a URL `https://downdetector.com.<country>/status/<slug>/` existe e usa Next.js (procurar `companyCurrentStatus` no HTML)
2. Adicionar entries no `services.yaml` com `country: <code>`
3. Não precisa mudar código — o parser é agnóstico de país

### Adicionando uma métrica nova ao Zabbix

1. Adicionar `item_prototype` em `zabbix/tmpl_downdetector.yaml`
2. Mexer em `collector/__main__.py::_on_scrape` pra enviar a métrica nova
3. Re-importar template no Zabbix (UI ou API)

---

## 🤝 Contribuindo

PRs bem-vindos. Antes de abrir:

1. Rode `pytest tests/` (precisa passar)
2. Rode `ruff check . && mypy collector/`
3. Atualize esta documentação se mudar comportamento visível
4. Adicione testes para novas funcionalidades

---

## 📄 Licença

MIT — veja `LICENSE`.

## 🙏 Agradecimentos

- [FlareSolverr](https://github.com/FlareSolverr/FlareSolverr) — bypass de Cloudflare
- [AlanMartines/monitoramento-downdetector-zabbix-grafana](https://github.com/AlanMartines/monitoramento-downdetector-zabbix-grafana) — inspiração do dashboard e lista de serviços BR
- [alexanderzobnin-zabbix-app](https://github.com/grafana/grafana-zabbix) — plugin Grafana
- [simple-icons](https://simpleicons.org/) — logos
