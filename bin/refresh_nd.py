"""One-off: re-scrape services currently em N/D no Zabbix e push valores frescos.

Útil quando FlareSolverr cuspiu HTTP 500 em alguns scrapes e os serviços
ficaram travados em status=3 (UNKNOWN/N/D) até o próximo ciclo natural.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
import urllib.request
from pathlib import Path

import yaml

from collector.config import ServiceConfig
from collector.parser import Status
from collector.scraper import Scraper
from collector.zabbix_sink import ZabbixSink

ZBX_URL = "http://localhost/zabbix/api_jsonrpc.php"
ZBX_USER = "Admin"
ZBX_PASS = "zabbix"
HOSTID = "10676"


def zbx_call(method, params, auth=None):
    body = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
    if auth:
        body["auth"] = auth
    req = urllib.request.Request(
        ZBX_URL, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json-rpc"},
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def list_nd_slugs():
    auth = zbx_call("user.login", {"username": ZBX_USER, "password": ZBX_PASS})["result"]
    items = zbx_call("item.get", {
        "hostids": HOSTID, "output": ["key_", "lastvalue"],
        "search": {"key_": "downdetector.status["},
    }, auth=auth)["result"]
    return sorted(i["key_"].split("[")[1].rstrip("]") for i in items if i.get("lastvalue") == "3")


async def main():
    cfg = yaml.safe_load(Path("/etc/downdetector-collector/services.yaml").read_text())
    defaults = cfg.get("defaults", {}) or {}
    by_slug = {}
    for s in cfg["services"]:
        merged = {**defaults, **s}
        by_slug[s["slug"]] = ServiceConfig(
            name=merged["name"], slug=merged["slug"], id=int(merged.get("id", 0) or 0),
            logo=merged.get("logo", ""),
            poll_interval=int(merged.get("poll_interval", 300)),
            country=merged.get("country", "br"),
        )

    nd_slugs = list_nd_slugs()
    print(f"Currently N/D ({len(nd_slugs)}): {nd_slugs}")
    if not nd_slugs:
        return

    scraper = Scraper()
    sink = ZabbixSink("127.0.0.1", 10051, "Downdetector")
    await scraper.start()
    fixed, still_nd, blocked = [], [], []
    try:
        for slug in nd_slugs:
            svc = by_slug.get(slug)
            if not svc:
                print(f"  {slug}: not in yaml (orphan?), skip")
                continue
            print(f"Scraping {slug:35s}", end=" ", flush=True)
            res = await scraper.scrape(svc)
            print(f"http={res.http_status} dur={res.duration_seconds:.1f}s "
                  f"status={int(res.parse.status)} "
                  f"blocked={res.cloudflare_blocked} err={res.parse.error}")
            if res.cloudflare_blocked:
                blocked.append(slug)
                continue
            status_int = int(res.parse.status)
            if status_int == 3:
                still_nd.append(slug)
                continue
            metrics = [
                (f"downdetector.status[{slug}]", status_int),
                (f"downdetector.last_check[{slug}]", int(time.time())),
            ]
            if res.parse.reports is not None:
                metrics.append((f"downdetector.reports[{slug}]", res.parse.reports))
            if res.parse.name:
                metrics.append((f"downdetector.name[{slug}]", res.parse.name))
            if res.parse.company_id:
                metrics.append((f"downdetector.company_id[{slug}]", res.parse.company_id))
            sink.send(metrics)
            fixed.append(slug)
    finally:
        await scraper.stop()

    print()
    print(f"FIXED ({len(fixed)}): {fixed}")
    print(f"STILL N/D ({len(still_nd)}): {still_nd}")
    print(f"CF BLOCKED ({len(blocked)}): {blocked}")
    return 0 if not still_nd and not blocked else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()) or 0)
