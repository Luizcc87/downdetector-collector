from collector.zabbix_sink import ZabbixSink, build_input_lines


def test_build_input_lines_format():
    metrics = [
        ("Downdetector", "downdetector.status[cloudflare]", "1"),
        ("Downdetector", "downdetector.reports[cloudflare]", "127"),
    ]
    lines = build_input_lines(metrics)
    assert lines == (
        '"Downdetector" "downdetector.status[cloudflare]" "1"\n'
        '"Downdetector" "downdetector.reports[cloudflare]" "127"\n'
    )


def test_build_input_lines_escapes_quotes():
    metrics = [("Downdetector", "downdetector.name[x]", 'Foo "Bar"')]
    lines = build_input_lines(metrics)
    assert lines == '"Downdetector" "downdetector.name[x]" "Foo \\"Bar\\""\n'


def test_build_input_lines_strips_newlines_to_prevent_injection():
    metrics = [
        (
            "Downdetector",
            "downdetector.name[x]",
            'Foo\n"Downdetector" "downdetector.status[evil]" "2',
        )
    ]
    lines = build_input_lines(metrics)
    # Newlines collapsed to spaces and quotes escaped; result is exactly ONE line
    assert lines.count("\n") == 1
    assert "evil" in lines  # value preserved as text, just not as a new record


def test_sink_invokes_zabbix_sender(monkeypatch, tmp_path):
    called = {}

    def fake_run(cmd, input, capture_output, text, timeout, check):
        called["cmd"] = cmd
        called["input"] = input
        class R:
            returncode = 0
            stdout = "info from server: processed 2 sent 2"
            stderr = ""
        return R()

    monkeypatch.setattr("collector.zabbix_sink.subprocess.run", fake_run)
    sink = ZabbixSink(zabbix_server="127.0.0.1", port=10051, host_name="Downdetector")
    sink.send([("downdetector.status[cloudflare]", 1)])
    assert "zabbix_sender" in called["cmd"][0]
    assert "Downdetector" in called["input"]
    assert "downdetector.status[cloudflare]" in called["input"]
