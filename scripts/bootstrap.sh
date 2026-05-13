#!/usr/bin/env bash
# bootstrap.sh — clona o repo + roda o install-all.sh em um único comando.
#
# Uso (uma linha):
#   curl -fsSL https://raw.githubusercontent.com/clfigueiredo/downdetector-collector/master/scripts/bootstrap.sh \
#     | sudo bash -s -- --zabbix-password <senha>
#
# Repo privado: passa --token <ghp_xxx> nos args.
# Custom branch/repo: --repo <owner/name>, --branch <name>, --dest <dir>.

set -euo pipefail

REPO="${REPO:-clfigueiredo/downdetector-collector}"
BRANCH="${BRANCH:-master}"
DEST="${DEST:-/opt/downdetector-collector/src}"
TOKEN=""
INSTALL_ARGS=()

# Separa flags do bootstrap das flags do install-all
while [[ $# -gt 0 ]]; do
    case "$1" in
        --repo)   REPO="$2"; shift 2 ;;
        --branch) BRANCH="$2"; shift 2 ;;
        --dest)   DEST="$2"; shift 2 ;;
        --token)  TOKEN="$2"; shift 2 ;;
        *)        INSTALL_ARGS+=("$1"); shift ;;
    esac
done

log() { printf "\033[1;34m[bootstrap]\033[0m %s\n" "$*"; }
die() { printf "\033[1;31m[bootstrap]\033[0m %s\n" "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Rode com sudo."

# Instala git se faltar
if ! command -v git >/dev/null; then
    log "Instalando git..."
    apt-get update -qq && apt-get install -y --no-install-recommends git ca-certificates >/dev/null
fi

# Monta URL do clone (com token se for privado)
if [[ -n "$TOKEN" ]]; then
    CLONE_URL="https://${TOKEN}@github.com/${REPO}.git"
else
    CLONE_URL="https://github.com/${REPO}.git"
fi

# Clone (ou pull se já existir)
if [[ -d "$DEST/.git" ]]; then
    log "Repo já existe em $DEST — fazendo pull..."
    git -C "$DEST" fetch origin "$BRANCH" --quiet
    git -C "$DEST" reset --hard "origin/$BRANCH" --quiet
else
    log "Clonando $REPO ($BRANCH) em $DEST..."
    mkdir -p "$(dirname "$DEST")"
    git clone --branch "$BRANCH" --depth 1 "$CLONE_URL" "$DEST" --quiet
fi

log "Rodando install-all.sh..."
exec "$DEST/scripts/install-all.sh" "${INSTALL_ARGS[@]}"
