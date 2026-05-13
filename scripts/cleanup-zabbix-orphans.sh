#!/usr/bin/env bash
# cleanup-zabbix-orphans.sh — deleta items do host Downdetector cujo slug
# não está mais no services.yaml.
#
# O LLD do Zabbix apenas DESABILITA items quando o slug some — não deleta.
# Esse script remove de vez.
#
# Uso:
#   ./scripts/cleanup-zabbix-orphans.sh --url http://zabbix/zabbix \
#                                        --user Admin --password zabbix
#   ./scripts/cleanup-zabbix-orphans.sh --dry-run     # só lista, não deleta

set -euo pipefail

ZABBIX_URL="${ZABBIX_URL:-}"
ZABBIX_USER="${ZABBIX_USER:-Admin}"
ZABBIX_PASSWORD="${ZABBIX_PASSWORD:-}"
ZABBIX_HOST_NAME="${ZABBIX_HOST_NAME:-Downdetector}"
SERVICES_YAML="${SERVICES_YAML:-/etc/downdetector-collector/services.yaml}"
DRY_RUN=0

log()  { printf "\033[1;34m[*]\033[0m %s\n" "$*"; }
ok()   { printf "\033[1;32m[✓]\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m[!]\033[0m %s\n" "$*" >&2; }
die()  { printf "\033[1;31m[✗]\033[0m %s\n" "$*" >&2; exit 1; }

usage() {
    cat <<EOF
Uso: $0 --url <URL> --user <USER> --password <PASS> [opções]

Obrigatórios:
  --url URL              URL base do Zabbix (ex: http://zabbix/zabbix)
  --user USER            Default: Admin
  --password PASS

Opcionais:
  --host NAME            Nome do host Zabbix (default: Downdetector)
  --services-yaml FILE   Path do services.yaml (default: /etc/downdetector-collector/services.yaml)
  --dry-run              Só lista órfãos, não deleta
  --help

EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --url)            ZABBIX_URL="$2"; shift 2 ;;
        --user)           ZABBIX_USER="$2"; shift 2 ;;
        --password)       ZABBIX_PASSWORD="$2"; shift 2 ;;
        --host)           ZABBIX_HOST_NAME="$2"; shift 2 ;;
        --services-yaml)  SERVICES_YAML="$2"; shift 2 ;;
        --dry-run)        DRY_RUN=1; shift ;;
        --help|-h)        usage; exit 0 ;;
        *) die "Opção desconhecida: $1" ;;
    esac
done

[[ -n "$ZABBIX_URL"      ]] || die "Faltou --url"
[[ -n "$ZABBIX_PASSWORD" ]] || die "Faltou --password"
[[ -f "$SERVICES_YAML"   ]] || die "services.yaml não encontrado: $SERVICES_YAML"
command -v curl    >/dev/null || die "curl não encontrado"
command -v jq      >/dev/null || die "jq não encontrado"
command -v python3 >/dev/null || die "python3 não encontrado"

API_URL="${ZABBIX_URL%/}/api_jsonrpc.php"

api_call() {
    local method="$1" params="$2" auth="${3:-}"
    local body
    if [[ -n "$auth" ]]; then
        body=$(jq -nc --arg m "$method" --argjson p "$params" --arg a "$auth" \
            '{jsonrpc:"2.0",method:$m,params:$p,auth:$a,id:1}')
    else
        body=$(jq -nc --arg m "$method" --argjson p "$params" \
            '{jsonrpc:"2.0",method:$m,params:$p,id:1}')
    fi
    curl -sS -X POST -H "Content-Type: application/json-rpc" \
         --data "$body" "$API_URL"
}

# ── 1. Login ────────────────────────────────────────────────────────────────
log "Login no Zabbix..."
LOGIN_RES=$(api_call "user.login" \
    "$(jq -nc --arg u "$ZABBIX_USER" --arg p "$ZABBIX_PASSWORD" \
        '{username:$u,password:$p}')")
AUTH=$(echo "$LOGIN_RES" | jq -r '.result // empty')
[[ -n "$AUTH" ]] || die "Login falhou: $(echo "$LOGIN_RES" | jq -r '.error.data // .error.message')"

# ── 2. Resolve hostid ───────────────────────────────────────────────────────
HOST_RES=$(api_call "host.get" \
    "$(jq -nc --arg n "$ZABBIX_HOST_NAME" '{filter:{host:[$n]},output:["hostid"]}')" "$AUTH")
HOST_ID=$(echo "$HOST_RES" | jq -r '.result[0].hostid // empty')
[[ -n "$HOST_ID" ]] || die "Host '$ZABBIX_HOST_NAME' não encontrado"
ok "Host '$ZABBIX_HOST_NAME' encontrado (id=$HOST_ID)"

# ── 3. Slugs ativos do YAML ─────────────────────────────────────────────────
ACTIVE_SLUGS=$(python3 -c "
import yaml, sys
cfg = yaml.safe_load(open('$SERVICES_YAML'))
for s in cfg.get('services', []):
    print(s['slug'])
")
ACTIVE_COUNT=$(echo "$ACTIVE_SLUGS" | wc -l)
log "Slugs ativos no yaml: $ACTIVE_COUNT"

# ── 4. Items do host ────────────────────────────────────────────────────────
ITEMS_RES=$(api_call "item.get" \
    "$(jq -nc --arg hid "$HOST_ID" \
        '{hostids:[$hid], output:["itemid","key_"], search:{key_:"downdetector."}}')" \
    "$AUTH")

# ── 5. Identifica órfãos ────────────────────────────────────────────────────
ORPHAN_IDS=()
ORPHAN_SLUGS=()
while IFS=$'\t' read -r itemid key; do
    [[ "$key" =~ \[(.+)\]$ ]] || continue
    slug="${BASH_REMATCH[1]}"
    if ! echo "$ACTIVE_SLUGS" | grep -qx "$slug"; then
        ORPHAN_IDS+=("$itemid")
        ORPHAN_SLUGS+=("$slug")
    fi
done < <(echo "$ITEMS_RES" | jq -r '.result[] | "\(.itemid)\t\(.key_)"')

if [[ ${#ORPHAN_IDS[@]} -eq 0 ]]; then
    ok "Sem órfãos — Zabbix sincronizado com o YAML."
    exit 0
fi

# Slugs órfãos únicos (cada slug tem ~6 items)
UNIQUE_ORPHAN_SLUGS=$(printf '%s\n' "${ORPHAN_SLUGS[@]}" | sort -u)
UNIQUE_COUNT=$(echo "$UNIQUE_ORPHAN_SLUGS" | wc -l)

echo
warn "Encontrados ${#ORPHAN_IDS[@]} items órfãos ($UNIQUE_COUNT slugs únicos):"
echo "$UNIQUE_ORPHAN_SLUGS" | sed 's/^/    /'
echo

# ── 6. Delete (ou dry-run) ──────────────────────────────────────────────────
if [[ $DRY_RUN -eq 1 ]]; then
    log "Dry-run: nada deletado. Re-rode sem --dry-run pra apagar."
    exit 0
fi

log "Deletando ${#ORPHAN_IDS[@]} items..."
# Batches de 50 pra não estourar payload
batch_size=50
total_deleted=0
for ((i=0; i<${#ORPHAN_IDS[@]}; i+=batch_size)); do
    batch=("${ORPHAN_IDS[@]:i:batch_size}")
    payload=$(printf '"%s",' "${batch[@]}")
    payload="[${payload%,}]"
    res=$(api_call "item.delete" "$payload" "$AUTH")
    deleted_in_batch=$(echo "$res" | jq -r '.result.itemids | length // 0')
    total_deleted=$((total_deleted + deleted_in_batch))
done

ok "Total deletado: $total_deleted items"
