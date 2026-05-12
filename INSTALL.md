# Instalação — downdetector-collector

## Pré-requisitos no servidor

- Debian/Ubuntu com systemd
- Zabbix Server 6.0+ rodando (porta trapper 10051 acessível em localhost)
- Grafana 10+ rodando
- Python 3.11+
- Docker 20+ (para rodar FlareSolverr)
- Plugin Grafana: `alexanderzobnin-zabbix-app` instalado
- `zabbix_sender` binário disponível (pacote `zabbix-sender` no apt)

## Passos

### 1. Criar usuário do sistema

```bash
sudo useradd --system --create-home --home-dir /var/lib/downdetector-collector \
    --shell /usr/sbin/nologin downdetector
sudo mkdir -p /var/log/downdetector-collector /etc/downdetector-collector \
    /var/lib/downdetector-collector
sudo chown -R downdetector:downdetector /var/log/downdetector-collector \
    /var/lib/downdetector-collector
sudo chmod 750 /etc/downdetector-collector
```

### 2. Instalar o código

```bash
sudo cp -r /home/cristiano/downdetector-collector /opt/
sudo chown -R downdetector:downdetector /opt/downdetector-collector
sudo -u downdetector python3.11 -m venv /opt/downdetector-collector/.venv
sudo -u downdetector /opt/downdetector-collector/.venv/bin/pip install -e /opt/downdetector-collector
```

### 2b. Subir FlareSolverr

```bash
# Instalar Docker (se ainda não instalado)
sudo apt update && sudo apt install -y docker.io
sudo systemctl enable --now docker

# Subir FlareSolverr container com restart automático
sudo docker run -d \
    --name flaresolverr \
    --restart unless-stopped \
    -p 127.0.0.1:8191:8191 \
    -e LOG_LEVEL=info \
    -e TZ=America/Sao_Paulo \
    ghcr.io/flaresolverr/flaresolverr:latest

# Verificar
curl -s http://localhost:8191/ | head -1
# Esperado: {"msg": "FlareSolverr is ready!", "version": "...", ...}
```

> **Nota:** o port-bind em `127.0.0.1:8191` garante que o FlareSolverr não seja exposto externamente — apenas o daemon local precisa acessá-lo.

### 3. Configurar serviços

```bash
sudo cp /opt/downdetector-collector/config/services.example.yaml \
    /etc/downdetector-collector/services.yaml
sudo chown downdetector:downdetector /etc/downdetector-collector/services.yaml
sudo chmod 640 /etc/downdetector-collector/services.yaml
sudo nano /etc/downdetector-collector/services.yaml  # editar com sua lista real
```

Para descobrir IDs faltantes:

```bash
sudo -u downdetector /opt/downdetector-collector/.venv/bin/python \
    /opt/downdetector-collector/bin/discover.py --slug nubank --country br
```

### 4. Instalar external script no Zabbix

```bash
sudo cp /opt/downdetector-collector/zabbix/externalscripts/downdetector_discovery.py \
    /usr/lib/zabbix/externalscripts/
sudo chmod +x /usr/lib/zabbix/externalscripts/downdetector_discovery.py
sudo chown zabbix:zabbix /usr/lib/zabbix/externalscripts/downdetector_discovery.py
```

### 5. Importar template e host no Zabbix

UI Zabbix → Data collection → Templates → Import → carregue:
- `/opt/downdetector-collector/zabbix/valuemap_downdetector.yaml`
- `/opt/downdetector-collector/zabbix/tmpl_downdetector.yaml`
- `/opt/downdetector-collector/zabbix/host_downdetector.yaml`

### 6. Provisionar Grafana

```bash
sudo cp /opt/downdetector-collector/grafana/provisioning/datasources/zabbix.yaml \
    /etc/grafana/provisioning/datasources/
sudo cp /opt/downdetector-collector/grafana/provisioning/dashboards/downdetector.yaml \
    /etc/grafana/provisioning/dashboards/
sudo mkdir -p /var/lib/grafana/dashboards/downdetector
sudo cp /opt/downdetector-collector/grafana/dashboard_downdetector.json \
    /var/lib/grafana/dashboards/downdetector/
sudo chown -R grafana:grafana /var/lib/grafana/dashboards
sudo nano /etc/grafana/provisioning/datasources/zabbix.yaml  # ajustar password
sudo systemctl restart grafana-server
```

### 7. Copiar logos

```bash
sudo mkdir -p /var/lib/grafana/plugins/static/downdetector/logos
sudo cp /opt/downdetector-collector/grafana/logos/*.svg \
    /var/lib/grafana/plugins/static/downdetector/logos/ 2>/dev/null || true
sudo chown -R grafana:grafana /var/lib/grafana/plugins/static/downdetector
```

### 8. Habilitar e iniciar o serviço

```bash
sudo cp /opt/downdetector-collector/systemd/downdetector-collector.service \
    /etc/systemd/system/
sudo cp /opt/downdetector-collector/systemd/downdetector-collector.logrotate \
    /etc/logrotate.d/downdetector-collector
sudo systemctl daemon-reload
sudo systemctl enable --now downdetector-collector
sudo journalctl -u downdetector-collector -f | jq
```

### 9. Verificações

- `docker ps | grep flaresolverr` → mostra container running
- `systemctl status downdetector-collector` → active (running)
- Em ~2 min, no Zabbix UI: `Hosts → Downdetector → Latest data` deve mostrar valores chegando
- Em ~5 min, LLD cria items por serviço (Discovery rules → Downdetector services)
- Em ~6 min, Grafana → Dashboards → "DASHBOARD DOWNDETECTOR" mostra valores

## Operação cotidiana

| Ação | Comando |
|---|---|
| Adicionar serviço | edite `/etc/downdetector-collector/services.yaml` e `sudo systemctl reload downdetector-collector` |
| Descobrir ID novo | `sudo -u downdetector /opt/downdetector-collector/.venv/bin/python /opt/downdetector-collector/bin/discover.py --slug X` |
| Ver erros | `sudo journalctl -u downdetector-collector -n 100 \| jq` |
| Restart limpo | `sudo systemctl restart downdetector-collector` |
| Atualizar FlareSolverr (mensal) | `sudo docker pull ghcr.io/flaresolverr/flaresolverr:latest && sudo docker restart flaresolverr` |

## Troubleshooting

### Daemon não envia métricas
1. `systemctl status downdetector-collector` — daemon ativo?
2. `docker ps | grep flaresolverr` — FlareSolverr ativo?
3. `curl -s http://localhost:8191/` — responde?
4. `which zabbix_sender` — binário instalado?
5. `sudo journalctl -u downdetector-collector -n 50 | jq` — eventos `sink_send_failed` ou `scrape_blocked`?

### CF blocks (5m) > 5 sustentado
- Reduzir cadência: editar `services.yaml`, aumentar `poll_interval` para 120s ou mais
- Atualizar FlareSolverr: `sudo docker pull ghcr.io/flaresolverr/flaresolverr:latest && sudo docker restart flaresolverr`
- Verificar conectividade do servidor: o IP do servidor pode ter sido flaggado pelo Cloudflare; tente outro servidor ou rota

### Itens não aparecem no Zabbix
- Aguarde 5 min para LLD (delay padrão)
- `Hosts → Downdetector → Discovery rules → Downdetector services → Latest data` mostra erro?
- External script: `sudo -u zabbix /usr/lib/zabbix/externalscripts/downdetector_discovery.py /etc/downdetector-collector/services.yaml` deve retornar JSON válido

### Painéis vazios no Grafana
- Datasource Zabbix retorna erro? `Configuration → Data sources → Zabbix → Save & Test`
- Plugin alexanderzobnin-zabbix-app instalado e ativado?
- `cat /etc/grafana/provisioning/datasources/zabbix.yaml` — `password` foi alterado?
