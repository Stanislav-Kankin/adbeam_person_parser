from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

from lead_enrichment.models.company import EntityType

EMAIL_RE = re.compile(r"(?i)(?<![\w.+-])[\w.+-]+@[a-z0-9.-]+\.[a-z]{2,}(?![\w.+-])")
PHONE_RE = re.compile(r"(?<!\d)(?:\+?7|8)[\s\-().]*(?:\d[\s\-().]*){10}(?!\d)")


def normalize_identifier(value: object, valid_lengths: set[int]) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, float):
        if not value.is_integer():
            return None
        raw = str(int(value))
    elif isinstance(value, int):
        raw = str(value)
    else:
        raw = str(value).strip()
        if raw.endswith(".0") and raw[:-2].isdigit():
            raw = raw[:-2]

    compact = re.sub(r"[\s\-]", "", raw)
    if not compact.isdigit() or len(compact) not in valid_lengths:
        return None
    return compact


def normalize_inn(value: object) -> str | None:
    inn = normalize_identifier(value, {10, 12})
    if inn is None or not is_valid_inn(inn):
        return None
    return inn


def is_valid_inn(value: str) -> bool:
    if not value.isdigit():
        return False
    digits = [int(char) for char in value]
    if len(digits) == 10:
        weights = (2, 4, 10, 3, 5, 9, 4, 6, 8)
        checksum = sum(weight * digit for weight, digit in zip(weights, digits[:9], strict=True)) % 11 % 10
        return digits[9] == checksum
    if len(digits) == 12:
        weights_11 = (7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
        weights_12 = (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
        checksum_11 = sum(
            weight * digit for weight, digit in zip(weights_11, digits[:10], strict=True)
        ) % 11 % 10
        checksum_12 = sum(
            weight * digit for weight, digit in zip(weights_12, digits[:11], strict=True)
        ) % 11 % 10
        return digits[10] == checksum_11 and digits[11] == checksum_12
    return False


def infer_entity_type(inn: str) -> EntityType:
    if len(inn) == 10:
        return EntityType.LEGAL_ENTITY
    if len(inn) == 12:
        return EntityType.INDIVIDUAL_ENTREPRENEUR
    return EntityType.UNKNOWN


def split_emails(value: object) -> list[str]:
    if value is None:
        return []
    return _unique(match.casefold() for match in EMAIL_RE.findall(str(value)))


def split_phones(value: object) -> list[str]:
    if value is None:
        return []
    normalized: list[str] = []
    for candidate in PHONE_RE.findall(str(value)):
        phone = normalize_phone_candidate(candidate)
        if phone:
            normalized.append(phone)
    return _unique(normalized)


def normalize_phone_candidate(value: object) -> str | None:
    if value is None:
        return None
    digits = re.sub(r"\D", "", str(value))
    if len(digits) == 10:
        digits = f"7{digits}"
    elif len(digits) == 11 and digits.startswith("8"):
        digits = f"7{digits[1:]}"
    if len(digits) == 11 and digits.startswith("7"):
        return f"+{digits}"
    return None


def normalize_http_url(value: object) -> str | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    has_http_scheme = raw.casefold().startswith(("http://", "https://"))
    if re.match(r"^[a-z][a-z0-9+.-]*:", raw, flags=re.IGNORECASE) and not has_http_scheme:
        return None
    if not has_http_scheme:
        raw = f"https://{raw}"
    parsed = urlsplit(raw)
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
        return None
    if parsed.username or parsed.password:
        return None
    return urlunsplit((parsed.scheme.casefold(), parsed.netloc, parsed.path, parsed.query, ""))


def normalize_person_name(value: object) -> str | None:
    if value is None:
        return None
    compact = re.sub(r"\s+", " ", str(value)).strip(" \t\r\n\"'«»")
    return compact or None


def extract_ip_owner_name(legal_name: str) -> str | None:
    value = re.sub(
        r"^\s*(?:ИП|индивидуальный\s+предприниматель)\s+",
        "",
        legal_name,
        flags=re.IGNORECASE,
    )
    return normalize_person_name(value) if value != legal_name else None


def split_lines(value: object) -> list[str]:
    if value is None:
        return []
    parts = re.split(r"[\r\n]+", str(value))
    return _unique(part.strip() for part in parts if part.strip())


def _unique(values) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value:
            continue
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result
