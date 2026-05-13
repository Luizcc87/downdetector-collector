#!/usr/bin/env bash
# setup-zabbix.sh — importa o template + cria o host no Zabbix via API.
#
# Roda como qualquer usuário (precisa só de credenciais admin do Zabbix).
#
# Uso:
#   ./scripts/setup-zabbix.sh --url http://zabbix.example.com/zabbix \
#                              --user Admin \
#                              --password zabbix
#
# Variáveis equivalentes: ZABBIX_URL, ZABBIX_USER, ZABBIX_PASSWORD,
#                         ZABBIX_HOST_NAME, ZABBIX_HOST_IP.

set -euo pipefail

# ── Config / args ───────────────────────────────────────────────────────────
ZABBIX_URL="${ZABBIX_URL:-}"
ZABBIX_USER="${ZABBIX_USER:-Admin}"
ZABBIX_PASSWORD="${ZABBIX_PASSWORD:-}"
ZABBIX_HOST_NAME="${ZABBIX_HOST_NAME:-Downdetector}"
ZABBIX_HOST_IP="${ZABBIX_HOST_IP:-127.0.0.1}"
TEMPLATE_NAME="Template Downdetector"
HOST_GROUP_NAME="Downdetector"

log()  { printf "\033[1;34m[*]\033[0m %s\n" "$*"; }
ok()   { printf "\033[1;32m[✓]\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m[!]\033[0m %s\n" "$*" >&2; }
die()  { printf "\033[1;31m[✗]\033[0m %s\n" "$*" >&2; exit 1; }

usage() {
    cat <<EOF
Uso: $0 --url <ZABBIX_URL> --user <USER> --password <PASS> [opções]

Obrigatórios:
  --url URL              URL base do Zabbix (ex: http://zabbix/zabbix)
  --user USER            Usuário com permissão de admin (default: Admin)
  --password PASS        Senha

Opcionais:
  --host-name NAME       Nome do host a criar (default: Downdetector)
  --host-ip IP           IP da interface Agent do host (default: 127.0.0.1)
  --help

Variáveis equivalentes: ZABBIX_URL, ZABBIX_USER, ZABBIX_PASSWORD,
ZABBIX_HOST_NAME, ZABBIX_HOST_IP.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --url)        ZABBIX_URL="$2"; shift 2 ;;
        --user)       ZABBIX_USER="$2"; shift 2 ;;
        --password)   ZABBIX_PASSWORD="$2"; shift 2 ;;
        --host-name)  ZABBIX_HOST_NAME="$2"; shift 2 ;;
        --host-ip)    ZABBIX_HOST_IP="$2"; shift 2 ;;
        --help|-h)    usage; exit 0 ;;
        *) die "Opção desconhecida: $1" ;;
    esac
done

[[ -n "$ZABBIX_URL"      ]] || die "Faltou --url"
[[ -n "$ZABBIX_PASSWORD" ]] || die "Faltou --password"
command -v curl >/dev/null || die "curl não encontrado"
command -v jq   >/dev/null || die "jq não encontrado (apt install jq)"
command -v python3 >/dev/null || die "python3 não encontrado"

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TEMPLATE_FILE="$REPO_DIR/zabbix/tmpl_downdetector.yaml"
HOST_FILE="$REPO_DIR/zabbix/host_downdetector.yaml"
EXTSCRIPT="$REPO_DIR/zabbix/externalscripts/downdetector_discovery.py"
EXTSCRIPT_DST="/usr/lib/zabbix/externalscripts/downdetector_discovery.py"

[[ -f "$TEMPLATE_FILE" ]] || die "Não achei o template em $TEMPLATE_FILE"

API_URL="${ZABBIX_URL%/}/api_jsonrpc.php"

# ── Helpers de API ──────────────────────────────────────────────────────────
api_call() {
    # $1 = method, $2 = params JSON (string), $3 = auth (opcional)
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
log "Login no Zabbix em $API_URL..."
LOGIN_RES=$(api_call "user.login" \
    "$(jq -nc --arg u "$ZABBIX_USER" --arg p "$ZABBIX_PASSWORD" \
        '{username:$u,password:$p}')")
AUTH=$(echo "$LOGIN_RES" | jq -r '.result // empty')
[[ -n "$AUTH" ]] || die "Login falhou: $(echo "$LOGIN_RES" | jq -r '.error.data // .error.message // .')"
ok "Autenticado"

# ── 2. Host group ───────────────────────────────────────────────────────────
log "Garantindo host group '$HOST_GROUP_NAME'..."
GROUP_RES=$(api_call "hostgroup.get" \
    "$(jq -nc --arg n "$HOST_GROUP_NAME" '{filter:{name:[$n]},output:["groupid"]}')" "$AUTH")
GROUP_ID=$(echo "$GROUP_RES" | jq -r '.result[0].groupid // empty')

if [[ -z "$GROUP_ID" ]]; then
    GROUP_RES=$(api_call "hostgroup.create" \
        "$(jq -nc --arg n "$HOST_GROUP_NAME" '{name:$n}')" "$AUTH")
    GROUP_ID=$(echo "$GROUP_RES" | jq -r '.result.groupids[0]')
    ok "Host group criado (id=$GROUP_ID)"
else
    ok "Host group já existia (id=$GROUP_ID)"
fi

# ── 3. Importa template ─────────────────────────────────────────────────────
log "Importando template '$TEMPLATE_NAME'..."
TEMPLATE_YAML=$(cat "$TEMPLATE_FILE")
IMPORT_PARAMS=$(jq -nc --arg yaml "$TEMPLATE_YAML" \
    '{
        format: "yaml",
        rules: {
            template_groups: {createMissing: true, updateExisting: true},
            host_groups:     {createMissing: true, updateExisting: true},
            templates:       {createMissing: true, updateExisting: true},
            items:           {createMissing: true, updateExisting: true, deleteMissing: false},
            triggers:        {createMissing: true, updateExisting: true, deleteMissing: false},
            discoveryRules:  {createMissing: true, updateExisting: true, deleteMissing: false},
            valueMaps:       {createMissing: true, updateExisting: true, deleteMissing: false},
            graphs:          {createMissing: true, updateExisting: true, deleteMissing: false}
        },
        source: $yaml
    }')
IMPORT_RES=$(api_call "configuration.import" "$IMPORT_PARAMS" "$AUTH")
if echo "$IMPORT_RES" | jq -e '.error' >/dev/null; then
    warn "Import com erro: $(echo "$IMPORT_RES" | jq -r '.error.data // .error.message')"
else
    ok "Template importado"
fi

# Pega templateid
TPL_RES=$(api_call "template.get" \
    "$(jq -nc --arg n "$TEMPLATE_NAME" '{filter:{host:[$n]},output:["templateid"]}')" "$AUTH")
TEMPLATE_ID=$(echo "$TPL_RES" | jq -r '.result[0].templateid // empty')
[[ -n "$TEMPLATE_ID" ]] || die "Não consegui resolver templateid de '$TEMPLATE_NAME'"

# ── 4. Host ─────────────────────────────────────────────────────────────────
log "Garantindo host '$ZABBIX_HOST_NAME'..."
HOST_RES=$(api_call "host.get" \
    "$(jq -nc --arg n "$ZABBIX_HOST_NAME" '{filter:{host:[$n]},output:["hostid"]}')" "$AUTH")
HOST_ID=$(echo "$HOST_RES" | jq -r '.result[0].hostid // empty')

if [[ -z "$HOST_ID" ]]; then
    HOST_PARAMS=$(jq -nc \
        --arg n  "$ZABBIX_HOST_NAME" \
        --arg ip "$ZABBIX_HOST_IP" \
        --arg gid "$GROUP_ID" \
        --arg tid "$TEMPLATE_ID" \
        '{
            host: $n, name: $n,
            interfaces: [{type:1, main:1, useip:1, ip:$ip, dns:"", port:"10050"}],
            groups: [{groupid:$gid}],
            templates: [{templateid:$tid}]
        }')
    HOST_RES=$(api_call "host.create" "$HOST_PARAMS" "$AUTH")
    HOST_ID=$(echo "$HOST_RES" | jq -r '.result.hostids[0] // empty')
    [[ -n "$HOST_ID" ]] || die "Falha ao criar host: $(echo "$HOST_RES" | jq -r '.error.data // .error.message')"
    ok "Host criado (id=$HOST_ID)"
else
    # Já existe — apenas garante que o template está linkado
    api_call "host.update" \
        "$(jq -nc --arg hid "$HOST_ID" --arg tid "$TEMPLATE_ID" \
            '{hostid:$hid, templates:[{templateid:$tid}]}')" "$AUTH" >/dev/null
    ok "Host já existia (id=$HOST_ID), template re-linkado"
fi

# ── 5. External script ──────────────────────────────────────────────────────
if [[ -f "$EXTSCRIPT" ]]; then
    if [[ $EUID -eq 0 ]]; then
        log "Instalando external script em $EXTSCRIPT_DST..."
        install -m 755 -o zabbix -g zabbix "$EXTSCRIPT" "$EXTSCRIPT_DST" 2>/dev/null \
            || install -m 755 "$EXTSCRIPT" "$EXTSCRIPT_DST"
        ok "External script instalado"
    else
        warn "Não rodei como root — copie manualmente o external script:"
        warn "  sudo install -m 755 -o zabbix -g zabbix $EXTSCRIPT $EXTSCRIPT_DST"
    fi
else
    warn "External script não encontrado em $EXTSCRIPT — pulando"
fi

# ── Conclusão ───────────────────────────────────────────────────────────────
cat <<EOF

═══════════════════════════════════════════════════════════════════════════
 ZABBIX CONFIGURADO
═══════════════════════════════════════════════════════════════════════════
 Host:        $ZABBIX_HOST_NAME (id=$HOST_ID)
 Template:    $TEMPLATE_NAME (id=$TEMPLATE_ID)
 Group:       $HOST_GROUP_NAME (id=$GROUP_ID)
 LLD:         discovery rodará no próximo ciclo (~1h por padrão).
              Pode forçar pela UI: Configuration → Hosts → Downdetector →
              Discovery → "Downdetector services" → Execute now.

EOF
