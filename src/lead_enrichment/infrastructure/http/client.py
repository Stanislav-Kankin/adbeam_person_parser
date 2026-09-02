from __future__ import annotations

import ipaddress
import random
import socket
import threading
import time
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field
from tenacity import RetryCallState, Retrying, retry_if_exception, stop_after_attempt

from lead_enrichment.models.settings import HttpClientSettings

HostResolver = Callable[[str], Iterable[str]]
Sleep = Callable[[float], None]
Clock = Callable[[], float]


class UnsafeUrlError(ValueError):
    """The URL can reach a local/special network or uses an unsafe scheme."""


class ResponseTooLargeError(ValueError):
    """The response exceeds the configured byte limit."""


class RetryableHttpStatusError(httpx.HTTPError):
    def __init__(self, status_code: int, retry_after_seconds: float | None = None) -> None:
        self.status_code = status_code
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"Retryable HTTP status: {status_code}")


class FetchedResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    requested_url: str
    final_url: str
    status_code: int = Field(ge=100, le=599)
    headers: dict[str, str] = Field(default_factory=dict)
    content: bytes
    encoding: str = "utf-8"

    @property
    def text(self) -> str:
        try:
            return self.content.decode(self.encoding, errors="replace")
        except LookupError:
            return self.content.decode("utf-8", errors="replace")


class HostRateLimiter:
    def __init__(
        self,
        delay_seconds: float,
        *,
        sleep: Sleep = time.sleep,
        clock: Clock = time.monotonic,
    ) -> None:
        self._delay_seconds = delay_seconds
        self._sleep = sleep
        self._clock = clock
        self._next_allowed: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, url: str) -> None:
        hostname = (urlsplit(url).hostname or "").casefold()
        if not hostname or self._delay_seconds <= 0:
            return
        with self._lock:
            now = self._clock()
            scheduled = max(now, self._next_allowed.get(hostname, now))
            self._next_allowed[hostname] = scheduled + self._delay_seconds
        delay = max(0.0, scheduled - now)
        if delay:
            self._sleep(delay)


class HttpClient:
    def __init__(
        self,
        settings: HttpClientSettings | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        resolver: HostResolver | None = None,
        sleep: Sleep = time.sleep,
        clock: Clock = time.monotonic,
    ) -> None:
        self.settings = settings or HttpClientSettings()
        self._resolver = resolver or _resolve_host
        self._sleep = sleep
        self._rate_limiter = HostRateLimiter(
            self.settings.per_host_delay_seconds,
            sleep=sleep,
            clock=clock,
        )
        self._request_count = 0
        self._client = httpx.Client(
            headers={
                "User-Agent": self.settings.user_agent,
                "Accept": "text/html,application/xhtml+xml,text/plain;q=0.8,*/*;q=0.1",
            },
            timeout=httpx.Timeout(
                connect=self.settings.connect_timeout_seconds,
                read=self.settings.read_timeout_seconds,
                write=self.settings.write_timeout_seconds,
                pool=self.settings.pool_timeout_seconds,
            ),
            limits=httpx.Limits(
                max_connections=self.settings.max_connections,
                max_keepalive_connections=self.settings.max_keepalive_connections,
            ),
            follow_redirects=False,
            max_redirects=self.settings.max_redirects,
            verify=True,
            transport=transport,
        )

    @property
    def request_count(self) -> int:
        return self._request_count

    def fetch(self, url: str) -> FetchedResponse:
        retrying = Retrying(
            stop=stop_after_attempt(self.settings.max_attempts),
            retry=retry_if_exception(_is_retryable_exception),
            wait=self._retry_wait,
            sleep=self._sleep,
            reraise=True,
        )
        for attempt in retrying:
            with attempt:
                return self._fetch_once(url)
        raise RuntimeError("Retry loop completed without a response")

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> HttpClient:
        return self

    def __exit__(self, *_args) -> None:
        self.close()

    def _fetch_once(self, requested_url: str) -> FetchedResponse:
        current_url = requested_url
        for redirect_index in range(self.settings.max_redirects + 1):
            _validate_public_http_url(current_url, self._resolver)
            self._rate_limiter.wait(current_url)
            self._request_count += 1

            with self._client.stream("GET", current_url) as response:
                if response.status_code in {408, 425, 429} or 500 <= response.status_code <= 599:
                    raise RetryableHttpStatusError(
                        response.status_code,
                        _parse_retry_after(response.headers.get("Retry-After")),
                    )

                if response.is_redirect:
                    location = response.headers.get("Location")
                    if not location:
                        return _read_response(requested_url, response, self.settings.max_response_bytes)
                    if redirect_index >= self.settings.max_redirects:
                        raise httpx.TooManyRedirects("Redirect limit exceeded", request=response.request)
                    current_url = urljoin(str(response.url), location)
                    continue

                return _read_response(requested_url, response, self.settings.max_response_bytes)

        raise httpx.TooManyRedirects("Redirect limit exceeded")

    def _retry_wait(self, retry_state: RetryCallState) -> float:
        exception = retry_state.outcome.exception() if retry_state.outcome else None
        if isinstance(exception, RetryableHttpStatusError):
            if exception.retry_after_seconds is not None:
                return min(exception.retry_after_seconds, self.settings.retry_max_seconds)
        exponent = max(retry_state.attempt_number - 1, 0)
        base = min(
            self.settings.retry_min_seconds * (2**exponent),
            self.settings.retry_max_seconds,
        )
        jitter = random.uniform(0.0, min(base * 0.2, self.settings.retry_max_seconds - base))
        return base + jitter


def _read_response(
    requested_url: str,
    response: httpx.Response,
    max_response_bytes: int,
) -> FetchedResponse:
    content_length = response.headers.get("Content-Length")
    if content_length and content_length.isdigit() and int(content_length) > max_response_bytes:
        raise ResponseTooLargeError("Response Content-Length exceeds configured limit")

    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_bytes():
        total += len(chunk)
        if total > max_response_bytes:
            raise ResponseTooLargeError("Response body exceeds configured limit")
        chunks.append(chunk)

    return FetchedResponse(
        requested_url=requested_url,
        final_url=str(response.url),
        status_code=response.status_code,
        headers={key.casefold(): value for key, value in response.headers.items()},
        content=b"".join(chunks),
        encoding=response.encoding or "utf-8",
    )


def _validate_public_http_url(url: str, resolver: HostResolver) -> None:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise UnsafeUrlError("URL is malformed") from exc

    if parsed.scheme.casefold() not in {"http", "https"}:
        raise UnsafeUrlError("Only http and https URLs are allowed")
    if not parsed.hostname or parsed.username or parsed.password:
        raise UnsafeUrlError("URL hostname is missing or contains credentials")
    if port not in {None, 80, 443}:
        raise UnsafeUrlError("Only standard HTTP ports are allowed")

    hostname = parsed.hostname.rstrip(".").casefold()
    if hostname == "localhost" or hostname.endswith(".localhost") or hostname.endswith(".local"):
        raise UnsafeUrlError("Local hostnames are not allowed")

    try:
        literal_ip = ipaddress.ip_address(hostname)
    except ValueError:
        literal_ip = None
    if literal_ip is not None:
        addresses = [hostname]
    else:
        try:
            addresses = list(resolver(hostname))
        except OSError as exc:
            raise httpx.ConnectError("Hostname resolution failed") from exc
    if not addresses:
        raise httpx.ConnectError("Hostname did not resolve")
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError as exc:
            raise UnsafeUrlError("Resolver returned an invalid IP address") from exc
        if not ip.is_global:
            raise UnsafeUrlError("URL resolves to a non-public IP address")


def _resolve_host(hostname: str) -> Iterable[str]:
    return {
        item[4][0]
        for item in socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    }


def _is_retryable_exception(exception: BaseException) -> bool:
    return isinstance(exception, (RetryableHttpStatusError, httpx.RequestError)) and not isinstance(
        exception,
        (httpx.InvalidURL, httpx.TooManyRedirects),
    )


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    stripped = value.strip()
    if stripped.isdigit():
        return max(0.0, float(stripped))
    try:
        parsed = parsedate_to_datetime(stripped)
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(0.0, (parsed - datetime.now(timezone.utc)).total_seconds())
