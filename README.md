# downdetector-collector

Daemon Python que raspa o [Downdetector](https://downdetector.com.br) e envia métricas pro **Zabbix**, com dashboard pronto no **Grafana**.

Bypass de Cloudflare via [FlareSolverr](https://github.com/FlareSolverr/FlareSolverr), detecção automática de rate-limit com backoff, e dashboard regenerado a partir de um único YAML.

```
Downdetector → FlareSolverr → daemon Python → zabbix_sender → Zabbix → Grafana
```

---

## Instalação

Ubuntu 22.04+ ou Debian 12+, com Zabbix Server 7.0+ e Grafana 13+ já instalados:

```bash
curl -fsSL https://raw.githubusercontent.com/clfigueiredo/downdetector-collector/master/scripts/bootstrap.sh \
  | sudo bash -s -- --zabbix-password <sua-senha-zabbix>
```

Isso clona o repo, instala pacotes, sobe FlareSolverr (Docker), cria o daemon systemd, importa template + host no Zabbix, e provisiona datasource + dashboard no Grafana.

Passo-a-passo manual e troubleshooting profundo em **[DOCS.md](DOCS.md)**.

---

## Como configurar os serviços

Arquivo: `/etc/downdetector-collector/services.yaml`

### Estrutura

```yaml
defaults:
  poll_interval: 300    # segundos entre scrapes — padrão global
  country: br           # br, com, mx, de, ...

services:
  - name: Instagram                              # nome exibido nos dashboards
    slug: instagram                              # parte da URL: .../status/<slug>/
    id: 33204                                    # company_id (cosmético, pode ser 0)
    logo: /public/img/downdetector/instagram.svg # path do logo no Grafana
    target_url: https://www.instagram.com/       # URL oficial usada para medir latência HTTP

  - name: Banco Itaú
    slug: banco-itau
    id: 0
    logo: /public/img/downdetector/banco-itau.svg
    target_url: https://www.itau.com.br/
    poll_interval: 600                           # override por serviço (opcional)

  - name: Cloudflare
    slug: cloudflare
    id: 32542
    logo: /public/img/downdetector/cloudflare.svg
    country: com                                 # força .com em vez do default .br
    target_url: https://www.cloudflare.com/
```

### Campos

| Campo | Obrig. | Default | O que é |
|---|---|---|---|
| `name` | sim | — | Nome legível (prefixo no Zabbix e label no dashboard) |
| `slug` | sim | — | Identificador na URL do Downdetector |
| `id` | sim | `0` | `company_id` — cosmético, pode deixar `0` |
| `logo` | sim | — | Path absoluto do SVG servido pelo Grafana |
| `poll_interval` | não | `defaults.poll_interval` | Segundos entre scrapes |
| `country` | não | `defaults.country` | Código de país do Downdetector |
| `target_url` | não | — | URL oficial medida diretamente para latência HTTP |

No dashboard, o gráfico **Histórico Downdetector** mostra relatos extraídos do Downdetector. O gráfico **Latência até o serviço oficial** mede HTTP direto contra `target_url` e é enviado como métrica separada ao Zabbix.

### poll_interval — recomendação

O Downdetector tem rate-limit duro via Cloudflare. A regra:

| Demanda total | Faixa segura |
|---|---|
| `< 5 req/min` | Qualquer IP, inclusive datacenter |
| `5–15 req/min` | OK em IP residencial, instável em datacenter |
| `> 15 req/min` | 429 garantido |

Fórmula: `demanda = sum(60 / poll_interval)` para todos os serviços.

| Exemplo | req/min |
|---|---|
| 10 serviços × 60s | 10.0 |
| 19 serviços × 300s (default) | 3.8 |
| 50 serviços × 600s | 5.0 |

Para a maioria dos casos, **300s (5 min)** é o sweet spot.

### Como descobrir um slug

Acessa `https://downdetector.com.br/status/<chute>/` no navegador. Se carregar com gráfico, o slug existe.

Comuns: `instagram`, `whatsapp`, `nubank`, `banco-do-brasil`, `banco-itau`, `bradesco`, `google`, `youtube`, `netflix`, `spotify`, `ifood`, `mercado-livre`, `mercadopago`.

---

## Adicionar / remover um serviço

```bash
# 1. Editar o YAML
sudo nano /etc/downdetector-collector/services.yaml

# 2. Reload (sem reiniciar o daemon — SIGHUP)
sudo systemctl reload downdetector-collector
sudo tail -3 /var/log/downdetector-collector/collector.log
# deve mostrar: "config_loaded count=N"

# 3. Aguardar ~5 min — o LLD do Zabbix cria/desabilita os items automaticamente

# 4. Regerar dashboard + logos
cd /opt/downdetector-collector/src
sudo /opt/downdetector-collector/.venv/bin/python bin/build_dashboard.py
sudo /opt/downdetector-collector/.venv/bin/python bin/fetch_logos.py
sudo systemctl restart grafana-server
```

Para limpar items órfãos no Zabbix após remover slugs:

```bash
/opt/downdetector-collector/src/scripts/cleanup-zabbix-orphans.sh
```

---

## Operação

```bash
# Status
sudo systemctl status downdetector-collector

# Logs estruturados em JSON
sudo tail -F /var/log/downdetector-collector/collector.log | jq -c .

# Reload (depois de editar services.yaml)
sudo systemctl reload downdetector-collector

# Restart completo (depois de mudar código)
sudo systemctl restart downdetector-collector

# Forçar re-scrape de serviços travados em N/D
sudo /opt/downdetector-collector/.venv/bin/python /opt/downdetector-collector/src/bin/refresh_nd.py
```

### Eventos no log

| Evento | Significado |
|---|---|
| `config_loaded count=N` | Reload OK, N serviços ativos |
| `zabbix_sender_ok count=4` | Scrape OK (status + last_check + reports + latency_ms, quando `target_url` existe) |
| `zabbix_sender_ok count=7` | Scrape OK + meta-push (name + id + logo, periódico) |
| `scrape_blocked` | Cloudflare 403 — backoff automático |
| `scrape_rate_limited` | Página `(╯°□°)╯︵ ┻━┻` — backoff longo |
| `flaresolverr_http_error` | Chromium do FS travou — geralmente recupera sozinho |

---

## Troubleshooting rápido

**Tudo em N/D:**
```bash
sudo systemctl is-active downdetector-collector   # daemon ativo?
curl http://127.0.0.1:8191/                       # FlareSolverr ready?
sudo tail -200 /var/log/downdetector-collector/collector.log | grep rate_limited
```

**429 sustentado:** pare o daemon por 1–4h, ou suba o `poll_interval` pra 600s+. Detalhes em [DOCS.md](DOCS.md).

**Dashboard com valores antigos no Grafana 13:**
```bash
sudo systemctl restart grafana-server
# Hard-refresh no browser: Ctrl+Shift+R
```

**FlareSolverr cuspindo 500:**
```bash
sudo docker restart flaresolverr
```

---

## Documentação

- **[DOCS.md](DOCS.md)** — instalação manual, schema do Zabbix, parser do Next.js, rate-limit em profundidade
- **[AGENTS.md](AGENTS.md)** — contexto pra IAs (Claude Code, Cursor, etc.) que vão editar o projeto
- **[INSTALL.md](INSTALL.md)** — checklist de instalação

---

## Licença

MIT — veja `LICENSE`.

## Agradecimentos

- [FlareSolverr](https://github.com/FlareSolverr/FlareSolverr) — bypass de Cloudflare
- [AlanMartines/monitoramento-downdetector-zabbix-grafana](https://github.com/AlanMartines/monitoramento-downdetector-zabbix-grafana) — inspiração inicial
- [alexanderzobnin-zabbix-app](https://github.com/grafana/grafana-zabbix) — plugin Grafana
- [simple-icons](https://simpleicons.org/) — logos
