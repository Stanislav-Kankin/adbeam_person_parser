from __future__ import annotations

from datetime import datetime
from urllib.parse import urljoin, urlsplit, urlunsplit

from selectolax.parser import HTMLParser

from lead_enrichment.engine.normalization import (
    normalize_phone_candidate,
    split_emails,
    split_phones,
)
from lead_enrichment.models import (
    ChannelScope,
    ChannelType,
    ContactChannel,
    SourceKind,
    SourceReference,
)

SOCIAL_HOSTS = {
    "t.me",
    "telegram.me",
    "vk.com",
    "ok.ru",
    "youtube.com",
    "www.youtube.com",
    "rutube.ru",
    "dzen.ru",
    "instagram.com",
    "www.instagram.com",
    "facebook.com",
    "www.facebook.com",
    "linkedin.com",
    "www.linkedin.com",
}
PLACEHOLDER_LOCAL_PARTS = {
    "email",
    "example",
    "test",
    "your-email",
    "name",
    "noreply",
    "no-reply",
}


def extract_site_channels(
    html: str,
    *,
    page_url: str,
    collected_at: datetime,
) -> list[ContactChannel]:
    parser = HTMLParser(html)
    body_text = parser.body.text(separator=" ", strip=True) if parser.body else ""
    emails = split_emails(body_text)
    phones = split_phones(body_text)
    socials: list[str] = []

    for node in parser.css("a[href]"):
        href = (node.attributes.get("href") or "").strip()
        lowered = href.casefold()
        if lowered.startswith("mailto:"):
            emails.extend(split_emails(href[7:].split("?", 1)[0]))
        elif lowered.startswith("tel:"):
            phone = normalize_phone_candidate(href[4:].split("?", 1)[0])
            if phone:
                phones.append(phone)
        else:
            social_url = _normalize_social_url(page_url, href)
            if social_url:
                socials.append(social_url)

    emails = [email for email in _unique(emails) if _email_is_usable(email)]
    phones = _unique(phones)
    socials = _unique(socials)
    source_ref = SourceReference(
        source_id="site_crawl",
        source_kind=SourceKind.COMPANY_SITE,
        source_name="Официальный сайт компании",
        locator=page_url,
        collected_at=collected_at,
        url=page_url,
        reliability=85,
    )
    channels = [
        ContactChannel(
            channel_type=ChannelType.EMAIL,
            value=email,
            scope=ChannelScope.COMPANY,
            source_refs=[source_ref],
        )
        for email in emails
    ]
    channels.extend(
        ContactChannel(
            channel_type=ChannelType.PHONE,
            value=phone,
            scope=ChannelScope.COMPANY,
            source_refs=[source_ref],
        )
        for phone in phones
    )
    channels.extend(
        ContactChannel(
            channel_type=ChannelType.SOCIAL,
            value=social,
            scope=ChannelScope.COMPANY,
            source_refs=[source_ref],
        )
        for social in socials
    )
    return channels


def _email_is_usable(email: str) -> bool:
    local, _, domain = email.partition("@")
    if local.casefold() in PLACEHOLDER_LOCAL_PARTS:
        return False
    lowered_domain = domain.casefold()
    if lowered_domain.startswith("example.") or lowered_domain.endswith(".example"):
        return False
    if "ingest.sentry.io" in lowered_domain:
        return False
    return True


def _normalize_social_url(page_url: str, href: str) -> str | None:
    absolute = urljoin(page_url, href)
    parsed = urlsplit(absolute)
    if parsed.scheme.casefold() not in {"http", "https"}:
        return None
    hostname = (parsed.hostname or "").casefold()
    if hostname not in SOCIAL_HOSTS:
        return None
    path = parsed.path.rstrip("/") or "/"
    lowered_path = path.casefold()
    if any(marker in lowered_path for marker in ("/share", "/sharer", "/intent/")):
        return None
    return urlunsplit(("https", parsed.netloc.casefold(), path, parsed.query, ""))


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result
