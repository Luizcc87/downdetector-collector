#!/usr/bin/env bash
# install-all.sh — instala TUDO em um comando só: sistema + Zabbix + Grafana.
#
# Wrapper sobre install.sh + setup-zabbix.sh + setup-grafana.sh.
#
# Uso:
#   sudo ./scripts/install-all.sh \
#     --zabbix-url http://zabbix/zabbix \
#     --zabbix-user Admin \
#     --zabbix-password <senha>
#
# Variáveis de ambiente equivalentes às flags estão no --help dos scripts individuais.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ZABBIX_URL=""
ZABBIX_USER="Admin"
ZABBIX_PASSWORD=""
SKIP_ZABBIX=0
SKIP_GRAFANA=0
EXTRA_INSTALL_ARGS=()

log()  { printf "\n\033[1;34m═══ %s ═══\033[0m\n" "$*"; }
die()  { printf "\033[1;31m[✗]\033[0m %s\n" "$*" >&2; exit 1; }

usage() {
    cat <<EOF
Uso: sudo $0 [opções]

Faz o setup completo: pacotes + FlareSolverr + daemon + Zabbix + Grafana.

Opções Zabbix (necessárias se NÃO usar --skip-zabbix):
  --zabbix-url URL            URL base do Zabbix (ex: http://zabbix/zabbix)
  --zabbix-user USER          Usuário (default: Admin)
  --zabbix-password PASS      Senha

Skips:
  --skip-zabbix               Não configurar Zabbix automaticamente
  --skip-grafana              Não configurar Grafana automaticamente
  --skip-flaresolverr         Repassa pro install.sh
  --no-start                  Repassa pro install.sh

EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --zabbix-url)      ZABBIX_URL="$2"; shift 2 ;;
        --zabbix-user)     ZABBIX_USER="$2"; shift 2 ;;
        --zabbix-password) ZABBIX_PASSWORD="$2"; shift 2 ;;
        --skip-zabbix)     SKIP_ZABBIX=1; shift ;;
        --skip-grafana)    SKIP_GRAFANA=1; shift ;;
        --skip-flaresolverr|--no-start) EXTRA_INSTALL_ARGS+=("$1"); shift ;;
        --help|-h)         usage; exit 0 ;;
        *) die "Opção desconhecida: $1 (--help)" ;;
    esac
done

[[ $EUID -eq 0 ]] || die "Precisa rodar como root (sudo)."

if [[ $SKIP_ZABBIX -eq 0 ]]; then
    [[ -n "$ZABBIX_URL"      ]] || die "Faltou --zabbix-url (ou use --skip-zabbix)"
    [[ -n "$ZABBIX_PASSWORD" ]] || die "Faltou --zabbix-password (ou use --skip-zabbix)"
fi

# ── 1. Sistema + daemon ─────────────────────────────────────────────────────
log "PARTE 1/3 — Sistema + daemon"
"$SCRIPT_DIR/install.sh" "${EXTRA_INSTALL_ARGS[@]}"

# ── 2. Zabbix ───────────────────────────────────────────────────────────────
if [[ $SKIP_ZABBIX -eq 0 ]]; then
    log "PARTE 2/3 — Zabbix (template + host)"
    "$SCRIPT_DIR/setup-zabbix.sh" \
        --url "$ZABBIX_URL" \
        --user "$ZABBIX_USER" \
        --password "$ZABBIX_PASSWORD"
else
    log "PARTE 2/3 — Zabbix (PULADO via --skip-zabbix)"
fi

# ── 3. Grafana ──────────────────────────────────────────────────────────────
if [[ $SKIP_GRAFANA -eq 0 ]]; then
    log "PARTE 3/3 — Grafana (plugin + datasource + dashboard)"
    GRAFANA_ARGS=()
    if [[ $SKIP_ZABBIX -eq 0 ]]; then
        # Reaproveita as creds do Zabbix pra o datasource no Grafana
        GRAFANA_ARGS+=(--zabbix-url "${ZABBIX_URL%/}/api_jsonrpc.php"
                       --zabbix-user "$ZABBIX_USER"
                       --zabbix-password "$ZABBIX_PASSWORD")
    fi
    "$SCRIPT_DIR/setup-grafana.sh" "${GRAFANA_ARGS[@]}"
else
    log "PARTE 3/3 — Grafana (PULADO via --skip-grafana)"
fi

cat <<EOF

╔═══════════════════════════════════════════════════════════════════════════╗
║  INSTALAÇÃO COMPLETA                                                       ║
╠═══════════════════════════════════════════════════════════════════════════╣
║  Próximos passos:                                                          ║
║    1. Editar /etc/downdetector-collector/services.yaml com seus serviços  ║
║    2. sudo systemctl reload downdetector-collector                         ║
║    3. Acessar Grafana em http://<host>:3000 (dashboard "DASHBOARD          ║
║       DOWNDETECTOR")                                                       ║
║    4. Logs: sudo tail -F /var/log/downdetector-collector/collector.log    ║
╚═══════════════════════════════════════════════════════════════════════════╝
EOF
