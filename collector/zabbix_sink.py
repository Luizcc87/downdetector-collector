"""Wrapper sobre o binário `zabbix_sender` para envio batch de métricas."""
from __future__ import annotations

import shutil
import subprocess
from typing import Iterable, Sequence, Union

import structlog

log = structlog.get_logger(__name__)

ZabbixValue = Union[int, float, str]
Metric = tuple[str, ZabbixValue]  # (key, value)
MetricWithHost = tuple[str, str, str]  # (host, key, str_value)


def _escape_quotes(value: str) -> str:
    return value.replace('"', '\\"')


def build_input_lines(metrics: Sequence[MetricWithHost]) -> str:
    out = []
    for host, key, value in metrics:
        out.append(f'"{_escape_quotes(host)}" "{_escape_quotes(key)}" "{_escape_quotes(str(value))}"\n')
    return "".join(out)


class ZabbixSink:
    def __init__(self, zabbix_server: str, port: int, host_name: str) -> None:
        self._server = zabbix_server
        self._port = port
        self._host_name = host_name
        self._binary = shutil.which("zabbix_sender") or "/usr/bin/zabbix_sender"

    def send(self, metrics: Iterable[Metric]) -> None:
        with_host: list[MetricWithHost] = [
            (self._host_name, key, str(value)) for key, value in metrics
        ]
        if not with_host:
            return
        payload = build_input_lines(with_host)
        cmd = [self._binary, "-z", self._server, "-p", str(self._port), "-i", "-"]
        result = subprocess.run(
            cmd, input=payload, capture_output=True, text=True, timeout=30, check=False,
        )
        if result.returncode != 0:
            log.error(
                "zabbix_sender_failed",
                returncode=result.returncode,
                stderr=result.stderr.strip(),
            )
        else:
            log.debug("zabbix_sender_ok", count=len(with_host), stdout=result.stdout.strip())
