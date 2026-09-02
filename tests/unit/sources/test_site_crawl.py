from datetime import datetime, timezone

import httpx

from lead_enrichment.infrastructure.http import HttpClient
from lead_enrichment.models import (
    CompanyInput,
    EntityType,
    HttpClientSettings,
    PipelineContext,
    SiteCrawlSettings,
    SourceOutcome,
)
from lead_enrichment.sources.site_crawl import SiteCrawlPlugin

PUBLIC_RESOLVER = lambda _hostname: ["93.184.216.34"]


def _company(website: str | None) -> CompanyInput:
    return CompanyInput(
        input_row_id="Контрагенты:2",
        legal_name='ООО "Тест"',
        inn="1234567894",
        entity_type=EntityType.LEGAL_ENTITY,
        website=website,
    )


def _context(website: str | None) -> PipelineContext:
    return PipelineContext(
        run_id="test-run",
        company=_company(website),
        collected_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
    )


def _client(handler) -> HttpClient:
    return HttpClient(
        HttpClientSettings(
            max_attempts=1,
            retry_min_seconds=0,
            retry_max_seconds=0,
            per_host_delay_seconds=0,
        ),
        transport=httpx.MockTransport(handler),
        resolver=PUBLIC_RESOLVER,
    )


def test_site_crawl_finds_contact_page_and_ignores_inn_as_phone() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        if request.url.path == "/":
            return httpx.Response(
                200,
                headers={"Content-Type": "text/html; charset=utf-8"},
                text='''
                <html><body>
                  <a href="/contacts">Контакты</a>
                  <a href="https://t.me/test_company">Telegram</a>
                  test@example.ru
                </body></html>
                ''',
            )
        if request.url.path == "/contacts":
            return httpx.Response(
                200,
                headers={"Content-Type": "text/html"},
                text='''
                <html><body>
                  ИНН 1234567894
                  <a href="mailto:hello@brand.ru">Email</a>
                  <a href="tel:+7 (999) 111-22-33">Телефон</a>
                </body></html>
                ''',
            )
        return httpx.Response(404)

    with _client(handler) as client:
        result = SiteCrawlPlugin(client).execute(_context("https://example.com/"))

    values = {channel.value for channel in result.company_channels}
    assert result.outcome == SourceOutcome.FOUND
    assert result.reason_code == "SITE_DIRECT_CONTACTS_FOUND"
    assert values == {"hello@brand.ru", "+79991112233", "https://t.me/test_company"}
    assert "+71234567894" not in values
    assert result.metrics.request_count == 3
    assert result.metrics.checked_page_count == 2


def test_site_crawl_respects_robots_disallow() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/robots.txt"
        return httpx.Response(200, text="User-agent: *\nDisallow: /")

    with _client(handler) as client:
        result = SiteCrawlPlugin(client).execute(_context("https://example.com/"))

    assert result.outcome == SourceOutcome.SKIPPED
    assert result.reason_code == "ROBOTS_DISALLOWED"
    assert result.metrics.request_count == 1


def test_site_crawl_skips_company_without_website_without_requests() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("network must not be called")

    with _client(handler) as client:
        result = SiteCrawlPlugin(client).execute(_context(None))

    assert result.outcome == SourceOutcome.SKIPPED
    assert result.reason_code == "WEBSITE_UNKNOWN"
    assert client.request_count == 0


def test_site_crawl_returns_partial_for_social_links_only() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html"},
            text='<html><body><a href="https://vk.com/test_company">VK</a></body></html>',
        )

    with _client(handler) as client:
        result = SiteCrawlPlugin(
            client,
            SiteCrawlSettings(max_pages=1),
        ).execute(_context("https://example.com/"))

    assert result.outcome == SourceOutcome.PARTIAL
    assert result.reason_code == "SITE_SOCIALS_FOUND"
