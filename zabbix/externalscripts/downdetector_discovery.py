#!/usr/bin/env python3
"""External script for Zabbix LLD: emits services.yaml as Zabbix discovery JSON.

Called by Zabbix Server as: downdetector_discovery.py [config_path]
Defaults to /etc/downdetector-collector/services.yaml.
"""
import json
import sys
from pathlib import Path

import yaml

DEFAULT_CONFIG = Path("/etc/downdetector-collector/services.yaml")


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CONFIG
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    defaults = raw.get("defaults", {}) or {}
    data = []
    for item in raw.get("services", []) or []:
        merged = {**defaults, **item}
        data.append({
            "{#SLUG}": merged["slug"],
            "{#NAME}": merged["name"],
            "{#ID}": str(merged.get("id", 0)),
            "{#LOGO}": merged.get("logo", ""),
            "{#COUNTRY}": merged.get("country", "br"),
        })
    json.dump({"data": data}, sys.stdout, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
