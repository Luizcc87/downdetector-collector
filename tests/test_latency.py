import pytest

from collector.config import ServiceConfig
from collector.latency import LatencyChecker


def make_service(target_url: str | None) -> ServiceConfig:
    return ServiceConfig(
        name="Example",
        slug="example",
        id=1,
        logo="example.svg",
        poll_interval=60,
        country="br",
        target_url=target_url,
    )


class FakeResponse:
    status_code = 204


@pytest.mark.asyncio
async def test_latency_checker_returns_elapsed_ms(monkeypatch):
    class FakeClient:
        async def head(self, url, follow_redirects):
            assert url == "https://example.com/"
            assert follow_redirects is True
            return FakeResponse()

    checker = LatencyChecker()
    checker._client = FakeClient()
    ticks = iter([10.0, 10.123])
    monkeypatch.setattr("collector.latency.monotonic", lambda: next(ticks))

    result = await checker.check(make_service("https://example.com/"))

    assert result.available is True
    assert result.status_code == 204
    assert result.latency_ms == 123


@pytest.mark.asyncio
async def test_latency_checker_skips_service_without_target_url():
    checker = LatencyChecker()

    result = await checker.check(make_service(None))

    assert result.available is False
    assert result.latency_ms is None
    assert result.error == "target_url_missing"


@pytest.mark.asyncio
async def test_latency_checker_falls_back_to_get_when_head_is_rejected(monkeypatch):
    class RejectedHead:
        status_code = 405

    class OkGet:
        status_code = 200

    class FakeClient:
        async def head(self, url, follow_redirects):
            return RejectedHead()

        async def get(self, url, follow_redirects):
            assert url == "https://example.com/"
            assert follow_redirects is True
            return OkGet()

    checker = LatencyChecker()
    checker._client = FakeClient()
    ticks = iter([1.0, 1.250])
    monkeypatch.setattr("collector.latency.monotonic", lambda: next(ticks))

    result = await checker.check(make_service("https://example.com/"))

    assert result.available is True
    assert result.status_code == 200
    assert result.latency_ms == 250
