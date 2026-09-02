import httpx
import pytest

from lead_enrichment.infrastructure.http import (
    HttpClient,
    ResponseTooLargeError,
    UnsafeUrlError,
)
from lead_enrichment.models import HttpClientSettings

PUBLIC_RESOLVER = lambda _hostname: ["93.184.216.34"]


def _settings(**updates) -> HttpClientSettings:
    values = {
        "max_attempts": 1,
        "retry_min_seconds": 0,
        "retry_max_seconds": 0,
        "per_host_delay_seconds": 0,
    }
    values.update(updates)
    return HttpClientSettings(**values)


def test_fetch_returns_bounded_response_with_tls_url() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.scheme == "https"
        return httpx.Response(200, text="ok", headers={"Content-Type": "text/plain"})

    with HttpClient(
        _settings(),
        transport=httpx.MockTransport(handler),
        resolver=PUBLIC_RESOLVER,
    ) as client:
        response = client.fetch("https://example.com/")

    assert response.status_code == 200
    assert response.text == "ok"
    assert client.request_count == 1


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://[::1]/",
        "http://localhost/",
        "file:///etc/passwd",
        "https://example.com:8080/",
    ],
)
def test_fetch_blocks_unsafe_targets_before_transport(url: str) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, text="unexpected")

    with HttpClient(
        _settings(),
        transport=httpx.MockTransport(handler),
        resolver=PUBLIC_RESOLVER,
    ) as client:
        with pytest.raises(UnsafeUrlError):
            client.fetch(url)

    assert calls == 0


def test_redirect_target_is_revalidated_for_ssrf() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "http://127.0.0.1/private"})

    with HttpClient(
        _settings(),
        transport=httpx.MockTransport(handler),
        resolver=PUBLIC_RESOLVER,
    ) as client:
        with pytest.raises(UnsafeUrlError):
            client.fetch("https://example.com/")

    assert client.request_count == 1


def test_retryable_status_uses_retry_after_and_then_succeeds() -> None:
    calls = 0
    sleeps: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "1"})
        return httpx.Response(200, text="ok")

    with HttpClient(
        _settings(max_attempts=2, retry_max_seconds=2),
        transport=httpx.MockTransport(handler),
        resolver=PUBLIC_RESOLVER,
        sleep=sleeps.append,
    ) as client:
        response = client.fetch("https://example.com/")

    assert response.status_code == 200
    assert calls == 2
    assert sleeps == [1.0]


def test_response_size_is_limited() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 1025)

    with HttpClient(
        _settings(max_response_bytes=1024),
        transport=httpx.MockTransport(handler),
        resolver=PUBLIC_RESOLVER,
    ) as client:
        with pytest.raises(ResponseTooLargeError):
            client.fetch("https://example.com/")
