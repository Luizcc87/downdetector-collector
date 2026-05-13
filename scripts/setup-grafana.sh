#!/usr/bin/env bash
# setup-grafana.sh — provisiona Grafana com o datasource Zabbix + dashboard.
#
# Roda como root (escreve em /etc/grafana e /var/lib/grafana).
#
# Uso:
#   sudo ./scripts/setup-grafana.sh
#   sudo ./scripts/setup-grafana.sh --no-restart
#   sudo ./scripts/setup-grafana.sh --skip-plugin

set -euo pipefail

# ── Config ──────────────────────────────────────────────────────────────────
GRAFANA_CONFIG_DIR="${GRAFANA_CONFIG_DIR:-/etc/grafana}"
GRAFANA_DATA_DIR="${GRAFANA_DATA_DIR:-/var/lib/grafana}"
GRAFANA_DASH_DIR="$GRAFANA_DATA_DIR/dashboards/downdetector"
GRAFANA_LOGOS_DIR="${GRAFANA_LOGOS_DIR:-/usr/share/grafana/public/img/downdetector}"

ZABBIX_API_URL="${ZABBIX_API_URL:-http://localhost/zabbix/api_jsonrpc.php}"
ZABBIX_API_USER="${ZABBIX_API_USER:-Admin}"
ZABBIX_API_PASSWORD="${ZABBIX_API_PASSWORD:-}"

SERVICES_YAML="${SERVICES_YAML:-/etc/downdetector-collector/services.yaml}"
DAEMON_VENV="${DAEMON_VENV:-/opt/downdetector-collector/.venv}"

SKIP_PLUGIN=0
NO_RESTART=0

# ── Helpers ─────────────────────────────────────────────────────────────────
log()  { printf "\033[1;34m[*]\033[0m %s\n" "$*"; }
ok()   { printf "\033[1;32m[✓]\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m[!]\033[0m %s\n" "$*" >&2; }
die()  { printf "\033[1;31m[✗]\033[0m %s\n" "$*" >&2; exit 1; }

usage() {
    cat <<EOF
Uso: sudo $0 [opções]

Opções:
  --zabbix-url URL       URL da API do Zabbix (default: http://localhost/zabbix/api_jsonrpc.php)
  --zabbix-user USER     Usuário Zabbix (default: Admin)
  --zabbix-password PASS Senha do usuário Zabbix (NECESSÁRIA pra criar datasource)
  --skip-plugin          Não instalar plugin alexanderzobnin-zabbix-app
  --no-restart           Não reiniciar grafana-server ao final
  --help

EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --zabbix-url)      ZABBIX_API_URL="$2"; shift 2 ;;
        --zabbix-user)     ZABBIX_API_USER="$2"; shift 2 ;;
        --zabbix-password) ZABBIX_API_PASSWORD="$2"; shift 2 ;;
        --skip-plugin)     SKIP_PLUGIN=1; shift ;;
        --no-restart)      NO_RESTART=1; shift ;;
        --help|-h)         usage; exit 0 ;;
        *) die "Opção desconhecida: $1" ;;
    esac
done

# ── Pre-flight ──────────────────────────────────────────────────────────────
[[ $EUID -eq 0 ]] || die "Precisa rodar como root."
command -v grafana-cli >/dev/null || die "grafana-cli não encontrado. Instale o Grafana antes."
[[ -d "$GRAFANA_CONFIG_DIR" ]] || die "Grafana config dir não existe: $GRAFANA_CONFIG_DIR"

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"

# ── 1. Plugin Zabbix (binário + habilitação no org) ─────────────────────────
if [[ $SKIP_PLUGIN -eq 0 ]]; then
    if grafana-cli plugins ls 2>/dev/null | grep -q alexanderzobnin-zabbix-app; then
        ok "Plugin alexanderzobnin-zabbix-app já instalado"
    else
        log "Instalando plugin alexanderzobnin-zabbix-app..."
        grafana-cli plugins install alexanderzobnin-zabbix-app >/dev/null
        ok "Plugin instalado"
    fi

    # Habilita o app no org 1. Sem isso, o datasource type
    # "alexanderzobnin-zabbix-datasource" não fica registrado
    # e o provisioner do datasource falha com "data source not found".
    APP_FILE="$GRAFANA_CONFIG_DIR/provisioning/plugins/downdetector-zabbix-app.yaml"
    log "Habilitando app Zabbix em $APP_FILE..."
    mkdir -p "$(dirname "$APP_FILE")"
    cat > "$APP_FILE" <<EOF
apiVersion: 1
apps:
  - type: alexanderzobnin-zabbix-app
    org_id: 1
    disabled: false
EOF
    chmod 640 "$APP_FILE"
    chown root:grafana "$APP_FILE" 2>/dev/null || true
    ok "App Zabbix habilitado no org 1"
else
    log "Pulando plugin + app provisioning (--skip-plugin)"
fi

# ── 2. Datasource provisioning ──────────────────────────────────────────────
DS_FILE="$GRAFANA_CONFIG_DIR/provisioning/datasources/downdetector.yaml"

if [[ -z "$ZABBIX_API_PASSWORD" ]]; then
    warn "ZABBIX_API_PASSWORD não fornecida — pulando provisioning de datasource."
    warn "Crie manualmente pela UI: Configuration → Data sources → Add → Zabbix"
    warn "  URL: $ZABBIX_API_URL"
    warn "  User/Pass: credenciais admin do Zabbix"
    warn "  Salve com Name 'Downdetector-Zabbix' e UID 'downdetector-zabbix'"
else
    log "Provisionando datasource em $DS_FILE..."
    mkdir -p "$(dirname "$DS_FILE")"
    cat > "$DS_FILE" <<EOF
apiVersion: 1
datasources:
  - name: Downdetector-Zabbix
    type: alexanderzobnin-zabbix-datasource
    uid: downdetector-zabbix
    access: proxy
    url: $ZABBIX_API_URL
    isDefault: false
    editable: true
    jsonData:
      username: $ZABBIX_API_USER
      trends: true
      trendsFrom: "7d"
      trendsRange: "4d"
      cacheTTL: "1h"
      alerting: false
    secureJsonData:
      password: $ZABBIX_API_PASSWORD
EOF
    chmod 640 "$DS_FILE"
    chown root:grafana "$DS_FILE" 2>/dev/null || true
    ok "Datasource provisionado (Name: Downdetector-Zabbix, UID: downdetector-zabbix)"
fi

# ── 3. Dashboard provisioning ───────────────────────────────────────────────
DASH_PROVISIONER="$GRAFANA_CONFIG_DIR/provisioning/dashboards/downdetector.yaml"
mkdir -p "$(dirname "$DASH_PROVISIONER")" "$GRAFANA_DASH_DIR"

if [[ ! -f "$DASH_PROVISIONER" ]]; then
    log "Provisionando dashboard loader em $DASH_PROVISIONER..."
    cat > "$DASH_PROVISIONER" <<EOF
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
      path: $GRAFANA_DASH_DIR
EOF
    chmod 644 "$DASH_PROVISIONER"
    ok "Dashboard loader provisionado (path: $GRAFANA_DASH_DIR)"
else
    ok "Dashboard loader já existe — preservado"
fi

chown -R grafana:grafana "$GRAFANA_DATA_DIR/dashboards" 2>/dev/null || true

# ── 4. Gerar dashboard JSON inicial ─────────────────────────────────────────
if [[ -x "$DAEMON_VENV/bin/python" && -f "$REPO_DIR/bin/build_dashboard.py" ]]; then
    if [[ -f "$SERVICES_YAML" ]]; then
        log "Gerando dashboard JSON a partir de $SERVICES_YAML..."
        # build_dashboard.py escreve em /var/lib/grafana/dashboards/downdetector/dashboard_downdetector.json
        "$DAEMON_VENV/bin/python" "$REPO_DIR/bin/build_dashboard.py" \
            || warn "build_dashboard.py falhou — gere manualmente depois"
    else
        warn "$SERVICES_YAML não existe. Crie o services.yaml e rode:"
        warn "  $DAEMON_VENV/bin/python $REPO_DIR/bin/build_dashboard.py"
    fi
else
    warn "venv ou build_dashboard.py não encontrados — pule a geração e regere depois"
fi

# ── 5. Logos dos serviços ───────────────────────────────────────────────────
mkdir -p "$GRAFANA_LOGOS_DIR"
chown -R grafana:grafana "$GRAFANA_LOGOS_DIR" 2>/dev/null || true

if [[ -x "$DAEMON_VENV/bin/python" && -f "$REPO_DIR/bin/fetch_logos.py" && -f "$SERVICES_YAML" ]]; then
    log "Baixando logos dos serviços (simple-icons + Google favicon)..."
    "$DAEMON_VENV/bin/python" "$REPO_DIR/bin/fetch_logos.py" \
        || warn "fetch_logos.py falhou — alguns logos podem aparecer como placeholder"
    chown -R grafana:grafana "$GRAFANA_LOGOS_DIR" 2>/dev/null || true
    ok "Logos baixados em $GRAFANA_LOGOS_DIR"
else
    warn "Pulando download de logos — rode depois:"
    warn "  $DAEMON_VENV/bin/python $REPO_DIR/bin/fetch_logos.py"
fi

# ── 6. Restart Grafana ──────────────────────────────────────────────────────
if [[ $NO_RESTART -eq 0 ]]; then
    log "Reiniciando grafana-server pra aplicar provisioning..."
    systemctl restart grafana-server
    # Esperar a API responder
    for i in {1..30}; do
        if curl -fsS -o /dev/null http://localhost:3000/api/health 2>/dev/null; then
            ok "Grafana ready"
            break
        fi
        sleep 1
        [[ $i -eq 30 ]] && warn "Grafana não respondeu em 30s — confira systemctl status grafana-server"
    done
else
    log "Não reiniciei o Grafana (--no-restart) — restart manualmente pra aplicar"
fi

# ── Conclusão ───────────────────────────────────────────────────────────────
cat <<EOF

═══════════════════════════════════════════════════════════════════════════
 GRAFANA CONFIGURADO
═══════════════════════════════════════════════════════════════════════════
 Plugin:    alexanderzobnin-zabbix-app
 Datasource: Name 'Downdetector-Zabbix' (UID downdetector-zabbix)
             $DS_FILE
 Dashboard:  $GRAFANA_DASH_DIR/dashboard_downdetector.json
 Logos:      $GRAFANA_LOGOS_DIR

 Acesse: http://<seu-host>:3000/d/downdetector-main/
         Login: admin / admin (mude na primeira visita!)

 Pra regerar o dashboard depois de editar services.yaml:
   sudo $DAEMON_VENV/bin/python $REPO_DIR/bin/build_dashboard.py
   sudo systemctl restart grafana-server   # workaround bug Grafana 13

EOF
