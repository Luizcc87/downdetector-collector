"""Script em Python para importar template, criar Host 'Downdetector' e pré-criar itens no Zabbix."""
import json
import urllib.request
from pathlib import Path

ZABBIX_URL = "http://localhost:8888/api_jsonrpc.php"
ZABBIX_USER = "Admin"
ZABBIX_PASS = "zabbix"
HOST_NAME = "Downdetector"
TEMPLATE_NAME = "Template Downdetector"
GROUP_NAME = "Downdetector"


def api_call(method: str, params: dict, auth: str | None = None) -> dict:
    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
        "id": 1,
    }
    if auth:
        payload["auth"] = auth
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(ZABBIX_URL, data=data, headers={"Content-Type": "application/json-rpc"})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    print(f"1. Autenticando em {ZABBIX_URL}...")
    res = api_call("user.login", {"username": ZABBIX_USER, "password": ZABBIX_PASS})
    if "error" in res:
        print("Erro de login:", res["error"])
        return
    auth = res["result"]
    print("[OK] Autenticado com sucesso!")

    # 2. Host Group
    print(f"2. Verificando grupo de hosts '{GROUP_NAME}'...")
    res = api_call("hostgroup.get", {"filter": {"name": [GROUP_NAME]}, "output": ["groupid"]}, auth)
    groups = res.get("result", [])
    if groups:
        group_id = groups[0]["groupid"]
        print(f"[OK] Grupo já existe (id={group_id})")
    else:
        res = api_call("hostgroup.create", {"name": GROUP_NAME}, auth)
        group_id = res["result"]["groupids"][0]
        print(f"[OK] Grupo criado (id={group_id})")

    # 3. Importar Template
    print(f"3. Importando {TEMPLATE_NAME}...")
    tmpl_path = Path(__file__).parents[1] / "zabbix" / "tmpl_downdetector.yaml"
    tmpl_content = tmpl_path.read_text(encoding="utf-8")
    import_params = {
        "format": "yaml",
        "rules": {
            "template_groups": {"createMissing": True, "updateExisting": True},
            "host_groups": {"createMissing": True, "updateExisting": True},
            "templates": {"createMissing": True, "updateExisting": True},
            "items": {"createMissing": True, "updateExisting": True, "deleteMissing": False},
            "triggers": {"createMissing": True, "updateExisting": True, "deleteMissing": False},
            "discoveryRules": {"createMissing": True, "updateExisting": True, "deleteMissing": False},
            "valueMaps": {"createMissing": True, "updateExisting": True, "deleteMissing": False},
            "graphs": {"createMissing": True, "updateExisting": True, "deleteMissing": False},
        },
        "source": tmpl_content,
    }
    res = api_call("configuration.import", import_params, auth)
    if "error" in res:
        print("Aviso ao importar template:", res["error"])
    else:
        print("[OK] Template importado com sucesso!")

    # Resolver templateid
    res = api_call("template.get", {"filter": {"host": [TEMPLATE_NAME]}, "output": ["templateid"]}, auth)
    template_id = res["result"][0]["templateid"]

    # 4. Host
    print(f"4. Verificando Host '{HOST_NAME}'...")
    res = api_call("host.get", {"filter": {"host": [HOST_NAME]}, "output": ["hostid"]}, auth)
    hosts = res.get("result", [])
    if hosts:
        host_id = hosts[0]["hostid"]
        api_call("host.update", {"hostid": host_id, "templates": [{"templateid": template_id}]}, auth)
        print(f"[OK] Host '{HOST_NAME}' já existia (id={host_id}), template vinculado.")
    else:
        host_params = {
            "host": HOST_NAME,
            "name": HOST_NAME,
            "interfaces": [{"type": 1, "main": 1, "useip": 1, "ip": "127.0.0.1", "dns": "", "port": "10050"}],
            "groups": [{"groupid": group_id}],
            "templates": [{"templateid": template_id}],
        }
        res = api_call("host.create", host_params, auth)
        host_id = res["result"]["hostids"][0]
        print(f"[OK] Host '{HOST_NAME}' criado com sucesso (id={host_id})!")

    # 5. Criar itens diretos para os serviços do YAML (para recepção imediata sem esperar o LLD cron)
    yaml_path = Path(__file__).parents[1] / "config" / "services.example.yaml"
    import yaml
    services_data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    services = services_data.get("services", [])

    print(f"5. Garantindo criação de itens para {len(services)} serviços...")
    for s in services:
        slug = s["slug"]
        name = s["name"]
        item_keys = [
            (f"downdetector.status[{slug}]", f"{name}: status", 3, 0),  # int, numeric unsigned
            (f"downdetector.reports[{slug}]", f"{name}: reports last hour", 3, 0),
            (f"downdetector.latency_ms[{slug}]", f"{name}: latency to official service", 0, 0),
            (f"downdetector.last_check[{slug}]", f"{name}: last successful check", 3, 0),
            (f"downdetector.name[{slug}]", f"{name}: service name", 1, 0),  # text/char
            (f"downdetector.company_id[{slug}]", f"{name}: company id", 3, 0),
            (f"downdetector.logo[{slug}]", f"{name}: logo", 1, 0),
        ]
        for key, item_name, value_type, _ in item_keys:
            res_item = api_call("item.get", {"hostids": [host_id], "filter": {"key_": [key]}}, auth)
            if not res_item.get("result"):
                api_call("item.create", {
                    "hostid": host_id,
                    "name": item_name,
                    "key_": key,
                    "type": 2,  # Zabbix Trapper
                    "value_type": value_type,
                }, auth)

    print("[OK] Configuração do Zabbix finalizada com sucesso!")


if __name__ == "__main__":
    main()
