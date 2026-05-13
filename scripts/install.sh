#!/usr/bin/env bash
# install.sh — instala o downdetector-collector no sistema.
#
# Roda como root. Idempotente — pode ser re-executado sem efeitos colaterais.
#
# Uso:
#   sudo ./scripts/install.sh                 # instalação padrão
#   sudo ./scripts/install.sh --skip-flaresolverr
#   sudo ./scripts/install.sh --no-start
#   sudo ./scripts/install.sh --prefix /opt/downdetector-collector
#   sudo ./scripts/install.sh --help

set -euo pipefail

# ── Config ──────────────────────────────────────────────────────────────────
PREFIX="${PREFIX:-/opt/downdetector-collector}"
CONFIG_DIR="${CONFIG_DIR:-/etc/downdetector-collector}"
LOG_DIR="${LOG_DIR:-/var/log/downdetector-collector}"
SERVICE_USER="${SERVICE_USER:-downdetector}"
FLARESOLVERR_NAME="${FLARESOLVERR_NAME:-flaresolverr}"
FLARESOLVERR_PORT="${FLARESOLVERR_PORT:-8191}"
FLARESOLVERR_TZ="${FLARESOLVERR_TZ:-America/Sao_Paulo}"

SKIP_FLARESOLVERR=0
NO_START=0
REPO_DIR=""

# ── Helpers ─────────────────────────────────────────────────────────────────
log()  { printf "\033[1;34m[*]\033[0m %s\n" "$*"; }
ok()   { printf "\033[1;32m[✓]\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m[!]\033[0m %s\n" "$*" >&2; }
die()  { printf "\033[1;31m[✗]\033[0m %s\n" "$*" >&2; exit 1; }

usage() {
    cat <<EOF
Uso: $0 [opções]

Opções:
  --skip-flaresolverr   Não instalar/iniciar o container FlareSolverr
  --no-start            Instalar mas não iniciar o systemd unit
  --prefix DIR          Diretório de instalação do venv (default: /opt/downdetector-collector)
  --user NAME           Usuário do sistema pro daemon (default: downdetector)
  --help                Mostra esta ajuda

Variáveis de ambiente equivalentes: PREFIX, SERVICE_USER, FLARESOLVERR_PORT,
FLARESOLVERR_TZ, CONFIG_DIR, LOG_DIR.
EOF
}

# ── Parse args ──────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-flaresolverr) SKIP_FLARESOLVERR=1; shift ;;
        --no-start)          NO_START=1; shift ;;
        --prefix)            PREFIX="$2"; shift 2 ;;
        --user)              SERVICE_USER="$2"; shift 2 ;;
        --help|-h)           usage; exit 0 ;;
        *) die "Opção desconhecida: $1 (--help pra ajuda)" ;;
    esac
done

# ── Pre-flight ──────────────────────────────────────────────────────────────
[[ $EUID -eq 0 ]] || die "Precisa rodar como root (sudo)."

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
[[ -f "$REPO_DIR/pyproject.toml" ]] || die "Não achei pyproject.toml em $REPO_DIR — rode o script do clone."

log "Repo: $REPO_DIR"
log "Prefix: $PREFIX"
log "Config: $CONFIG_DIR"
log "Log: $LOG_DIR"
log "User: $SERVICE_USER"

# ── 1. Pacotes do sistema ───────────────────────────────────────────────────
log "Instalando pacotes do sistema..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y --no-install-recommends \
    python3 python3-venv python3-pip \
    zabbix-sender \
    docker.io \
    jq curl wget ca-certificates >/dev/null

PY_VERSION=$(python3 -c 'import sys; print("{}.{}".format(sys.version_info.major, sys.version_info.minor))')
if [[ "$(printf '%s\n' "3.11" "$PY_VERSION" | sort -V | head -1)" != "3.11" ]]; then
    die "Python 3.11+ requerido, achei $PY_VERSION"
fi
ok "Pacotes OK (Python $PY_VERSION)"

systemctl enable --now docker >/dev/null 2>&1
ok "Docker habilitado"

# ── 2. FlareSolverr (Docker) ────────────────────────────────────────────────
if [[ $SKIP_FLARESOLVERR -eq 0 ]]; then
    if docker ps -a --format '{{.Names}}' | grep -qx "$FLARESOLVERR_NAME"; then
        log "Container FlareSolverr já existe — start (se parado)"
        docker start "$FLARESOLVERR_NAME" >/dev/null
    else
        log "Subindo container FlareSolverr..."
        docker run -d --restart unless-stopped --name "$FLARESOLVERR_NAME" \
            -p "127.0.0.1:${FLARESOLVERR_PORT}:8191" \
            -e LOG_LEVEL=info \
            -e TZ="$FLARESOLVERR_TZ" \
            ghcr.io/flaresolverr/flaresolverr:latest >/dev/null
    fi
    # Esperar ficar ready
    for i in {1..20}; do
        if curl -fsS "http://127.0.0.1:${FLARESOLVERR_PORT}/" 2>/dev/null | grep -q "is ready"; then
            ok "FlareSolverr ready em :${FLARESOLVERR_PORT}"
            break
        fi
        sleep 1
        [[ $i -eq 20 ]] && warn "FlareSolverr não respondeu em 20s — confira docker logs $FLARESOLVERR_NAME"
    done
else
    log "Pulando FlareSolverr (--skip-flaresolverr)"
fi

# ── 3. Usuário e diretórios ─────────────────────────────────────────────────
if ! id "$SERVICE_USER" &>/dev/null; then
    log "Criando usuário do sistema '$SERVICE_USER'..."
    useradd -r -s /bin/false "$SERVICE_USER"
fi
ok "Usuário '$SERVICE_USER' existe"

mkdir -p "$PREFIX" "$CONFIG_DIR" "$LOG_DIR" /var/lib/downdetector-collector
chown -R "$SERVICE_USER":"$SERVICE_USER" "$PREFIX" "$LOG_DIR" /var/lib/downdetector-collector
ok "Diretórios criados ($PREFIX, $CONFIG_DIR, $LOG_DIR)"

# ── 4. venv + instalação editable ───────────────────────────────────────────
if [[ ! -x "$PREFIX/.venv/bin/python" ]]; then
    log "Criando venv em $PREFIX/.venv..."
    python3 -m venv "$PREFIX/.venv"
fi
"$PREFIX/.venv/bin/pip" install --quiet --upgrade pip
"$PREFIX/.venv/bin/pip" install --quiet -e "$REPO_DIR"
chown -R "$SERVICE_USER":"$SERVICE_USER" "$PREFIX/.venv"
ok "venv pronto, pacote 'collector' instalado em editable mode"

# ── 5. Config inicial ───────────────────────────────────────────────────────
if [[ ! -f "$CONFIG_DIR/services.yaml" ]]; then
    cp "$REPO_DIR/config/services.example.yaml" "$CONFIG_DIR/services.yaml"
    chmod 644 "$CONFIG_DIR/services.yaml"
    ok "services.yaml copiado do template (edite $CONFIG_DIR/services.yaml)"
else
    log "services.yaml já existe — preservado"
fi

# ── 6. Systemd unit ─────────────────────────────────────────────────────────
UNIT_SRC="$REPO_DIR/systemd/downdetector-collector.service"
UNIT_DST="/etc/systemd/system/downdetector-collector.service"

# Substitui paths no unit pra refletir o PREFIX escolhido
sed -e "s|/opt/downdetector-collector|$PREFIX|g" \
    -e "s|/etc/downdetector-collector|$CONFIG_DIR|g" \
    -e "s|/var/log/downdetector-collector|$LOG_DIR|g" \
    -e "s|^User=.*|User=$SERVICE_USER|" \
    -e "s|^Group=.*|Group=$SERVICE_USER|" \
    "$UNIT_SRC" > "$UNIT_DST"
chmod 644 "$UNIT_DST"

systemctl daemon-reload
systemctl enable downdetector-collector >/dev/null 2>&1
ok "Systemd unit instalado e habilitado"

# ── 7. Start (opcional) ─────────────────────────────────────────────────────
if [[ $NO_START -eq 0 ]]; then
    log "Iniciando daemon..."
    systemctl restart downdetector-collector
    sleep 2
    if systemctl is-active --quiet downdetector-collector; then
        ok "Daemon ativo"
    else
        warn "Daemon falhou ao iniciar — veja: journalctl -u downdetector-collector --no-pager -n 30"
    fi
else
    log "Daemon instalado mas não iniciado (--no-start)"
fi

# ── Conclusão ───────────────────────────────────────────────────────────────
cat <<EOF

═══════════════════════════════════════════════════════════════════════════
 INSTALAÇÃO BÁSICA CONCLUÍDA
═══════════════════════════════════════════════════════════════════════════

 Próximos passos:

 1. Editar a lista de serviços:
    sudo \$EDITOR $CONFIG_DIR/services.yaml
    sudo systemctl reload downdetector-collector

 2. Importar o template Zabbix + criar host:
    ./scripts/setup-zabbix.sh --url http://<zabbix>/zabbix --user Admin --password <senha>
    (ou pela UI: Configuration → Templates/Hosts → Import)

 3. Configurar Grafana (datasource + provisioning + dashboard):
    sudo ./scripts/setup-grafana.sh

 4. Acompanhar logs:
    sudo tail -F $LOG_DIR/collector.log | jq -c .

 Documentação completa: README.md

EOF
