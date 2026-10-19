#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script de Automação para Adição de Novos Serviços ao NOC CCZaleski
Automatiza:
1. Criação dos 9 itens e 4 triggers no Zabbix Server (Host Downdetector) via API
2. Adição do serviço no arquivo services.yaml do coletor
3. Atualização automática do dashboard Grafana (gerar-dashboard-grafana.py)
4. Reload do coletor no Docker Swarm
"""

import argparse
import json
import os
import ssl
import sys
import urllib.request
import re

ZBX_URL = "https://zabbix.cczaleski.com.br/api_jsonrpc.php"
HOST_ID = "10684" # Host 'Downdetector'

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

def zbx_call(method, params, auth=None):
    payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
    data = json.dumps(payload).encode('utf-8')
    headers = {"Content-Type": "application/json-rpc"}
    if auth: headers["Authorization"] = f"Bearer {auth}"
    req = urllib.request.Request(ZBX_URL, data=data, headers=headers)
    with urllib.request.urlopen(req, context=ctx, timeout=10) as r:
        resp = json.load(r)
    if "error" in resp:
        raise RuntimeError(f"Zabbix API Error: {resp['error']}")
    return resp["result"]

def provision_zabbix(name, slug, critico=False):
    print(f"\n[1/3] Conectando ao Zabbix Server para provisionar itens de '{name}' ({slug})...")
    # Token de API (Zabbix 7.0) do ambiente; nada de senha no código.
    token = os.environ.get("ZABBIX_API_TOKEN")
    if not token:
        print("❌ Defina ZABBIX_API_TOKEN (token de API do Zabbix) no ambiente.")
        sys.exit(1)

    # Obter itens existentes
    existing = zbx_call("item.get", {
        "hostids": [HOST_ID],
        "search": {"key_": f"[{slug}]"},
        "output": ["key_", "name"]
    }, auth=token)
    existing_keys = {it["key_"] for it in existing}

    items_to_create = [
        {"name": f"{name}: status", "key_": f"downdetector.status[{slug}]", "type": 2, "value_type": 3, "history": "90d", "trends": "365d"},
        {"name": f"{name}: reports last hour", "key_": f"downdetector.reports[{slug}]", "type": 2, "value_type": 3, "history": "90d", "trends": "365d"},
        {"name": f"{name}: latency to official service", "key_": f"downdetector.latency_ms[{slug}]", "type": 2, "value_type": 0, "units": "ms", "history": "30d", "trends": "365d"},
        {"name": f"{name}: TCP ping", "key_": f"downdetector.tcp_ping_ms[{slug}]", "type": 2, "value_type": 0, "units": "ms", "history": "30d", "trends": "365d"},
        {"name": f"{name}: TCP reachability", "key_": f"downdetector.tcp_ping_ok[{slug}]", "type": 2, "value_type": 3, "history": "7d", "trends": "90d"},
        {"name": f"{name}: last successful check", "key_": f"downdetector.last_check[{slug}]", "type": 2, "value_type": 3, "history": "7d", "trends": "90d"},
        {"name": f"{name}: service name", "key_": f"downdetector.name[{slug}]", "type": 2, "value_type": 1, "history": "365d", "trends": "0"},
        {"name": f"{name}: company id", "key_": f"downdetector.company_id[{slug}]", "type": 2, "value_type": 3, "history": "365d", "trends": "0"},
        {"name": f"{name}: logo", "key_": f"downdetector.logo[{slug}]", "type": 2, "value_type": 1, "history": "365d", "trends": "0"},
    ]

    created = 0
    for it in items_to_create:
        if it["key_"] not in existing_keys:
            it["hostid"] = HOST_ID
            zbx_call("item.create", it, auth=token)
            created += 1
    print(f"  ✅ {created} itens criados no Zabbix ({len(items_to_create) - created} já existiam).")

    # Criar triggers
    triggers_to_create = [
        {"description": f"[Atenção] {name} reportando problemas leves", "expression": f"last(/Downdetector/downdetector.status[{slug}])=1", "priority": 3 if critico else 2},
        {"description": f"[Problema] {name} reportando falha grave", "expression": f"last(/Downdetector/downdetector.status[{slug}])=2", "priority": 4},
        {"description": f"[Offline TCP] {name} inacessível via TCP", "expression": f"last(/Downdetector/downdetector.tcp_ping_ok[{slug}])=0", "priority": 4},
        {"description": f"[Stale] {name} sem coleta há mais de 10min", "expression": f"(now()-last(/Downdetector/downdetector.last_check[{slug}]))>600", "priority": 1},
    ]

    existing_trigs = zbx_call("trigger.get", {
        "hostids": [HOST_ID],
        "search": {"description": name},
        "output": ["description"]
    }, auth=token)
    existing_desc = {t["description"] for t in existing_trigs}

    trig_created = 0
    for tg in triggers_to_create:
        if tg["description"] not in existing_desc:
            zbx_call("trigger.create", tg, auth=token)
            trig_created += 1
    print(f"  ✅ {trig_created} triggers criadas no Zabbix ({len(triggers_to_create) - trig_created} já existiam).")

def main():
    parser = argparse.ArgumentParser(description="Adiciona um novo serviço monitorado à plataforma NOC")
    parser.add_argument("--name", required=True, help="Nome de exibição do serviço (ex: 'Asaas')")
    parser.add_argument("--slug", required=True, help="Slug no Downdetector (ex: 'asaas')")
    parser.add_argument("--id", required=True, type=int, help="ID da empresa no Downdetector (ex: 39500)")
    parser.add_argument("--url", required=True, help="URL oficial de acesso/login (ex: 'https://www.asaas.com/')")
    parser.add_argument("--ping-host", help="Host opcional para o Ping TCP (se diferente do domínio da URL)")
    parser.add_argument("--critico", action="store_true",
                        help="Serviço que para a loja: [Atenção] em Average, vai para o Telegram")
    parser.add_argument("--logo", help="Nome do arquivo de logo SVG em grafana/logos/ (default: <slug>.svg)")

    args = parser.parse_args()
    logo_file = args.logo or f"/public/img/downdetector/{args.slug}.svg"

    print("=" * 80)
    print(f" 🚀 CADASTRO DE NOVO SERVIÇO NOC: {args.name} ({args.slug})")
    print("=" * 80)

    # 1. Provisionar no Zabbix
    provision_zabbix(args.name, args.slug, critico=args.critico)

    print("\n[2/3] Instruções para persistência no Coletor:")
    print("  1. Cole este bloco no arquivo /home/zaleski/downdetector/services.yaml:")
    print("     --------------------------------------------------")
    print(f"     - name: {args.name}")
    print(f"       slug: {args.slug}")
    print(f"       id: {args.id}")
    print(f"       logo: {logo_file}")
    print(f"       target_url: {args.url}")
    if args.ping_host:
        print(f"       ping_host: {args.ping_host}")
    print("     --------------------------------------------------")
    print("  2. Certifique-se de salvar o ícone SVG em:")
    print(f"     /home/zaleski/downdetector-collector/grafana/logos/{args.slug}.svg")

    print("\n[3/3] Próximo passo para o Grafana:")
    print("  • Adicione o serviço em '09-Operacao-Infraestrutura/scripts/gerar-dashboard-grafana.py'")
    print("    na lista CATEGORIES correspondente e execute:")
    print("    python 09-Operacao-Infraestrutura/scripts/gerar-dashboard-grafana.py")
    print("\n✨ Processo de provisionamento Zabbix concluído com sucesso!")

if __name__ == "__main__":
    main()