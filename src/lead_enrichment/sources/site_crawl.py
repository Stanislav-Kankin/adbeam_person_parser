from __future__ import annotations

import time
from collections.abc import Iterable
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import httpx
from selectolax.parser import HTMLParser

from lead_enrichment.infrastructure.http import (
    HttpClient,
    ResponseTooLargeError,
    UnsafeUrlError,
)
from lead_enrichment.models import (
    ChannelType,
    ContactChannel,
    PipelineContext,
    SiteCrawlSettings,
    SourceApplicability,
    SourceMetadata,
    SourceMetrics,
    SourceOutcome,
    SourceResult,
)
from lead_enrichment.sources.parsing.contacts import extract_site_channels

CONTACT_LINK_TERMS = (
    "contact",
    "contacts",
    "kontakty",
    "контакт",
    "about",
    "o-kompanii",
    "company",
    "requisites",
    "rekvizity",
    "реквизит",
    "team",
    "management",
    "leadership",
    "руковод",
    "команд",
)
EXCLUDED_EXTENSIONS = (
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".svg",
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".zip",
    ".rar",
)


class SiteCrawlPlugin:
    def __init__(
        self,
        http_client: HttpClient,
        settings: SiteCrawlSettings | None = None,
    ) -> None:
        self._http = http_client
        self._settings = settings or SiteCrawlSettings()

    @property
    def metadata(self) -> SourceMetadata:
        return SourceMetadata(
            source_id="site_crawl",
            version="1.0.0",
            display_name="Обход официального сайта",
            network_access=True,
        )

    def is_applicable(self, context: PipelineContext) -> SourceApplicability:
        if not context.company.website:
            return SourceApplicability(
                applicable=False,
                reason_code="WEBSITE_UNKNOWN",
                reason_message="В карточке компании отсутствует сайт",
            )
        return SourceApplicability(
            applicable=True,
            reason_code="WEBSITE_AVAILABLE",
            reason_message="В карточке компании указан сайт",
        )

    def execute(self, context: PipelineContext) -> SourceResult:
        metadata = self.metadata
        applicability = self.is_applicable(context)
        if not applicability.applicable:
            return SourceResult(
                source_id=metadata.source_id,
                source_version=metadata.version,
                outcome=SourceOutcome.SKIPPED,
                reason_code=applicability.reason_code,
                reason_message=applicability.reason_message,
                continue_reason="Нужен следующий источник для поиска сайта",
            )

        start = time.perf_counter()
        requests_before = self._http.request_count
        website = context.company.website
        assert website is not None
        checked_urls: list[str] = []
        warnings: list[str] = []

        robots = self._load_robots_policy(website, warnings)
        if robots is not None and not robots.can_fetch(self._http.settings.user_agent, website):
            return self._result(
                metadata=metadata,
                outcome=SourceOutcome.SKIPPED,
                reason_code="ROBOTS_DISALLOWED",
                reason_message="robots.txt запрещает обход указанной страницы",
                continue_reason="Сайт пропущен; нужен следующий разрешённый источник",
                channels=[],
                checked_urls=[],
                warnings=warnings,
                start=start,
                requests_before=requests_before,
            )

        try:
            entry = self._http.fetch(website)
        except (httpx.HTTPError, UnsafeUrlError, ResponseTooLargeError):
            return self._result(
                metadata=metadata,
                outcome=SourceOutcome.FAILED,
                reason_code="WEBSITE_UNAVAILABLE",
                reason_message="Не удалось безопасно загрузить сайт",
                continue_reason="Нужен следующий источник, потому что сайт недоступен",
                channels=[],
                checked_urls=[],
                warnings=warnings,
                start=start,
                requests_before=requests_before,
            )

        checked_urls.append(entry.final_url)
        if entry.status_code >= 400:
            return self._result(
                metadata=metadata,
                outcome=SourceOutcome.FAILED,
                reason_code="WEBSITE_HTTP_ERROR",
                reason_message=f"Сайт вернул HTTP {entry.status_code}",
                continue_reason="Нужен следующий источник, потому что сайт не отдал страницу",
                channels=[],
                checked_urls=checked_urls,
                warnings=warnings,
                start=start,
                requests_before=requests_before,
            )
        if not _is_html(entry.headers):
            return self._result(
                metadata=metadata,
                outcome=SourceOutcome.NOT_FOUND,
                reason_code="WEBSITE_NOT_HTML",
                reason_message="Главная страница не содержит HTML",
                continue_reason="Нужен следующий источник для поиска контактов",
                channels=[],
                checked_urls=checked_urls,
                warnings=warnings,
                start=start,
                requests_before=requests_before,
            )

        channels = extract_site_channels(
            entry.text,
            page_url=entry.final_url,
            collected_at=context.collected_at,
        )
        candidates = _contact_page_candidates(
            entry.text,
            entry.final_url,
            limit=self._settings.max_link_candidates,
        )
        for candidate in candidates:
            if len(checked_urls) >= self._settings.max_pages:
                break
            if robots is not None and not robots.can_fetch(self._http.settings.user_agent, candidate):
                warnings.append("ROBOTS_DISALLOWED_CANDIDATE")
                continue
            try:
                page = self._http.fetch(candidate)
            except (httpx.HTTPError, UnsafeUrlError, ResponseTooLargeError):
                warnings.append("CONTACT_PAGE_UNAVAILABLE")
                continue
            checked_urls.append(page.final_url)
            if page.status_code >= 400 or not _is_html(page.headers):
                warnings.append("CONTACT_PAGE_NOT_ANALYZABLE")
                continue
            channels.extend(
                extract_site_channels(
                    page.text,
                    page_url=page.final_url,
                    collected_at=context.collected_at,
                )
            )

        channels = _merge_channels(channels)
        direct_channels = [
            channel
            for channel in channels
            if channel.channel_type in {ChannelType.EMAIL, ChannelType.PHONE}
        ]
        if direct_channels:
            outcome = SourceOutcome.FOUND
            reason_code = "SITE_DIRECT_CONTACTS_FOUND"
            reason_message = "На официальном сайте найдены email или телефоны"
            continue_reason = None
        elif channels:
            outcome = SourceOutcome.PARTIAL
            reason_code = "SITE_SOCIALS_FOUND"
            reason_message = "На официальном сайте найдены только публичные соцсети компании"
            continue_reason = "Нужен следующий источник для прямого контакта"
        else:
            outcome = SourceOutcome.NOT_FOUND
            reason_code = "SITE_NO_CONTACTS"
            reason_message = "Сайт доступен, но контакты не найдены"
            continue_reason = "Нужен следующий структурированный источник"

        return self._result(
            metadata=metadata,
            outcome=outcome,
            reason_code=reason_code,
            reason_message=reason_message,
            continue_reason=continue_reason,
            channels=channels,
            checked_urls=checked_urls,
            warnings=warnings,
            start=start,
            requests_before=requests_before,
        )

    def _load_robots_policy(
        self,
        website: str,
        warnings: list[str],
    ) -> RobotFileParser | None:
        if not self._settings.respect_robots_txt:
            return None
        parsed = urlsplit(website)
        robots_url = urlunsplit((parsed.scheme, parsed.netloc, "/robots.txt", "", ""))
        try:
            response = self._http.fetch(robots_url)
        except (httpx.HTTPError, UnsafeUrlError, ResponseTooLargeError):
            warnings.append("ROBOTS_UNAVAILABLE")
            return None
        if response.status_code in {401, 403}:
            parser = RobotFileParser()
            parser.set_url(robots_url)
            parser.parse(["User-agent: *", "Disallow: /"])
            return parser
        if response.status_code >= 400:
            return None
        parser = RobotFileParser()
        parser.set_url(robots_url)
        parser.parse(response.text.splitlines())
        return parser

    def _result(
        self,
        *,
        metadata: SourceMetadata,
        outcome: SourceOutcome,
        reason_code: str,
        reason_message: str,
        continue_reason: str | None,
        channels: list[ContactChannel],
        checked_urls: list[str],
        warnings: list[str],
        start: float,
        requests_before: int,
    ) -> SourceResult:
        return SourceResult(
            source_id=metadata.source_id,
            source_version=metadata.version,
            outcome=outcome,
            reason_code=reason_code,
            reason_message=reason_message,
            continue_reason=continue_reason,
            company_channels=channels,
            checked_urls=checked_urls,
            warnings=_unique(warnings),
            metrics=SourceMetrics(
                duration_ms=max(0, round((time.perf_counter() - start) * 1000)),
                request_count=max(0, self._http.request_count - requests_before),
                checked_page_count=len(checked_urls),
            ),
        )


def _contact_page_candidates(html: str, page_url: str, *, limit: int) -> list[str]:
    parser = HTMLParser(html)
    base_host = _canonical_host(page_url)
    scored: dict[str, int] = {}
    for node in parser.css("a[href]"):
        href = (node.attributes.get("href") or "").strip()
        candidate = _normalize_candidate(page_url, href, base_host)
        if not candidate:
            continue
        text = node.text(separator=" ", strip=True).casefold()
        haystack = f"{candidate.casefold()} {text}"
        score = sum(1 for term in CONTACT_LINK_TERMS if term in haystack)
        if score:
            scored[candidate] = max(score, scored.get(candidate, 0))
    return [
        url
        for url, _score in sorted(scored.items(), key=lambda item: (-item[1], len(item[0])))
    ][:limit]


def _normalize_candidate(base_url: str, href: str, base_host: str) -> str | None:
    if not href or href.casefold().startswith(("mailto:", "tel:", "javascript:", "#")):
        return None
    absolute = urljoin(base_url, href)
    parsed = urlsplit(absolute)
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
        return None
    if _canonical_host(absolute) != base_host:
        return None
    if parsed.path.casefold().endswith(EXCLUDED_EXTENSIONS):
        return None
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit((parsed.scheme.casefold(), parsed.netloc.casefold(), path, parsed.query, ""))


def _canonical_host(url: str) -> str:
    hostname = (urlsplit(url).hostname or "").casefold()
    return hostname[4:] if hostname.startswith("www.") else hostname


def _is_html(headers: dict[str, str]) -> bool:
    content_type = headers.get("content-type", "").casefold()
    return not content_type or "html" in content_type or "text/plain" in content_type


def _merge_channels(channels: Iterable[ContactChannel]) -> list[ContactChannel]:
    merged: dict[tuple[str, str], ContactChannel] = {}
    for channel in channels:
        key = (channel.channel_type.value, channel.value.casefold())
        existing = merged.get(key)
        if existing is None:
            merged[key] = channel
            continue
        refs = list(existing.source_refs)
        known = {(ref.source_id, ref.locator, ref.url) for ref in refs}
        for ref in channel.source_refs:
            ref_key = (ref.source_id, ref.locator, ref.url)
            if ref_key not in known:
                refs.append(ref)
                known.add(ref_key)
        merged[key] = existing.model_copy(update={"source_refs": refs})
    return list(merged.values())


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))
