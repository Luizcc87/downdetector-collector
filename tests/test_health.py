import time

from collector.health import HealthState


def test_uptime_increases():
    h = HealthState()
    time.sleep(0.05)
    assert h.uptime_seconds() >= 0.04


def test_record_cycle_keeps_last():
    h = HealthState()
    h.record_cycle_duration(3.5)
    h.record_cycle_duration(4.1)
    assert h.last_cycle_seconds == 4.1


def test_record_block_decays_after_5min():
    h = HealthState()
    h.record_block(timestamp=1000.0)
    h.record_block(timestamp=1100.0)
    assert h.blocks_in_last_5m(now=1200.0) == 2
    assert h.blocks_in_last_5m(now=1500.0) == 0  # ambos passaram dos 300s


def test_healthy_flag_combines_signals():
    h = HealthState()
    assert h.healthy() is True
    for _ in range(15):
        h.record_block(timestamp=time.time())
    assert h.healthy() is False
