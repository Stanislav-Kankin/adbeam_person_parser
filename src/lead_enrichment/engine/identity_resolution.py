from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from urllib.parse import urlsplit

from lead_enrichment.models import (
    AssessmentCompany,
    AssessmentImportResult,
    AssessmentKonturMergeResult,
    AssessmentKonturMergeSummary,
    CompanyInput,
    IdentityMatchMethod,
    IdentityResolution,
    IdentityResolutionStatus,
    KonturImportResult,
    MergedLead,
)

LEGAL_FORM_TOKENS = {
    "ао",
    "гк",
    "зао",
    "оао",
    "ооо",
    "пао",
    "сз",
}
LEGAL_FORM_PHRASES = (
    ("акционерное", "общество"),
    ("группа", "компаний"),
    ("общество", "с", "ограниченной", "ответственностью"),
    ("специализированный", "застройщик"),
)


def merge_assessment_with_kontur(
    assessment_result: AssessmentImportResult,
    kontur_result: KonturImportResult,
) -> AssessmentKonturMergeResult:
    domain_index: dict[str, list[CompanyInput]] = defaultdict(list)
    name_index: dict[str, list[CompanyInput]] = defaultdict(list)
    for company in kontur_result.companies:
        if not company.inn:
            continue
        domain = _domain(company.website)
        if domain:
            domain_index[domain].append(company)
        normalized_name = _normalized_company_name(company.legal_name or company.brand_name or "")
        if normalized_name:
            name_index[normalized_name].append(company)

    leads: list[MergedLead] = []
    status_counts: Counter[IdentityResolutionStatus] = Counter()
    method_counts: Counter[IdentityMatchMethod] = Counter()
    for assessment in assessment_result.companies:
        company, resolution = _resolve_company(assessment, domain_index, name_index)
        status_counts[resolution.status] += 1
        if resolution.status == IdentityResolutionStatus.MATCHED:
            method_counts[resolution.method] += 1
        leads.append(
            MergedLead(
                company_key=f"inn:{company.inn}" if company else assessment.company_key,
                assessment=assessment,
                kontur_company=company,
                identity=resolution,
            )
        )

    return AssessmentKonturMergeResult(
        summary=AssessmentKonturMergeSummary(
            assessment_rows=len(assessment_result.companies),
            kontur_rows=len(kontur_result.companies),
            matched_rows=status_counts[IdentityResolutionStatus.MATCHED],
            ambiguous_rows=status_counts[IdentityResolutionStatus.AMBIGUOUS],
            not_found_rows=status_counts[IdentityResolutionStatus.NOT_FOUND],
            matched_by_method={method.value: count for method, count in method_counts.items()},
        ),
        leads=leads,
    )


def create_inn_leads(kontur_result: KonturImportResult) -> list[MergedLead]:
    """Create pipeline inputs whose identity is anchored only by a verified INN."""
    leads: list[MergedLead] = []
    for company in kontur_result.companies:
        if not company.inn:
            raise ValueError("Контур pipeline принимает только компании с валидным ИНН")
        leads.append(
            MergedLead(
                company_key=f"inn:{company.inn}",
                kontur_company=company,
                identity=IdentityResolution(
                    status=IdentityResolutionStatus.MATCHED,
                    method=IdentityMatchMethod.INN,
                    confidence_score=100,
                    reason_code="VERIFIED_INPUT_INN",
                    reason_message="Компания идентифицирована по ИНН из выгрузки Контур",
                    matched_inn=company.inn,
                    candidate_inns=[company.inn],
                ),
            )
        )
    return leads


def _resolve_company(
    assessment: AssessmentCompany,
    domain_index: dict[str, list[CompanyInput]],
    name_index: dict[str, list[CompanyInput]],
) -> tuple[CompanyInput | None, IdentityResolution]:
    domain = _domain(assessment.website)
    domain_candidates = _unique_by_inn(domain_index.get(domain, [])) if domain else []
    if domain_candidates:
        if len(domain_candidates) == 1:
            return domain_candidates[0], _matched(
                domain_candidates[0],
                method=IdentityMatchMethod.DOMAIN,
                confidence=92,
                reason_code="UNIQUE_DOMAIN_MATCH",
                reason_message="Бренд и строка Контур имеют один и тот же уникальный домен",
            )
        name_candidates = _match_by_name(assessment.brand_name, domain_candidates)
        if len(name_candidates) == 1:
            return name_candidates[0], _matched(
                name_candidates[0],
                method=IdentityMatchMethod.DOMAIN_AND_NAME,
                confidence=98,
                reason_code="DOMAIN_AND_NAME_MATCH",
                reason_message="Общий домен и нормализованное название однозначно определили юрлицо",
            )
        return None, _ambiguous(
            domain_candidates,
            method=IdentityMatchMethod.DOMAIN,
            reason_code="AMBIGUOUS_DOMAIN_MATCH",
            reason_message="Один домен связан с несколькими юрлицами Контур; требуется ручной выбор",
        )

    normalized_name = _normalized_company_name(assessment.brand_name)
    name_candidates = (
        _unique_by_inn(name_index.get(normalized_name, [])) if normalized_name else []
    )
    if len(name_candidates) == 1:
        return name_candidates[0], _matched(
            name_candidates[0],
            method=IdentityMatchMethod.NORMALIZED_NAME,
            confidence=82,
            reason_code="UNIQUE_NORMALIZED_NAME_MATCH",
            reason_message="После удаления организационно-правовой формы название совпало однозначно",
        )
    if len(name_candidates) > 1:
        return None, _ambiguous(
            name_candidates,
            method=IdentityMatchMethod.NORMALIZED_NAME,
            reason_code="AMBIGUOUS_NAME_MATCH",
            reason_message="Нормализованное название соответствует нескольким юрлицам Контур",
        )
    return None, IdentityResolution(
        status=IdentityResolutionStatus.NOT_FOUND,
        method=IdentityMatchMethod.NONE,
        confidence_score=0,
        reason_code="KONTUR_COMPANY_NOT_FOUND",
        reason_message="В выгрузке Контур не найдено однозначное совпадение по домену или названию",
    )


def _match_by_name(brand_name: str, candidates: Iterable[CompanyInput]) -> list[CompanyInput]:
    normalized = _normalized_company_name(brand_name)
    if not normalized:
        return []
    return [
        candidate
        for candidate in candidates
        if _normalized_company_name(candidate.legal_name or candidate.brand_name or "") == normalized
    ]


def _matched(
    company: CompanyInput,
    *,
    method: IdentityMatchMethod,
    confidence: int,
    reason_code: str,
    reason_message: str,
) -> IdentityResolution:
    assert company.inn is not None
    return IdentityResolution(
        status=IdentityResolutionStatus.MATCHED,
        method=method,
        confidence_score=confidence,
        reason_code=reason_code,
        reason_message=reason_message,
        matched_inn=company.inn,
        candidate_inns=[company.inn],
    )


def _ambiguous(
    companies: Iterable[CompanyInput],
    *,
    method: IdentityMatchMethod,
    reason_code: str,
    reason_message: str,
) -> IdentityResolution:
    return IdentityResolution(
        status=IdentityResolutionStatus.AMBIGUOUS,
        method=method,
        confidence_score=0,
        reason_code=reason_code,
        reason_message=reason_message,
        candidate_inns=sorted({company.inn for company in companies}),
    )


def _unique_by_inn(companies: Iterable[CompanyInput]) -> list[CompanyInput]:
    result: dict[str, CompanyInput] = {}
    for company in companies:
        if company.inn:
            result.setdefault(company.inn, company)
    return list(result.values())


def _domain(value: str | None) -> str | None:
    if not value:
        return None
    hostname = (urlsplit(value).hostname or "").casefold().rstrip(".")
    if hostname.startswith("www."):
        hostname = hostname[4:]
    try:
        return hostname.encode("idna").decode("ascii") or None
    except UnicodeError:
        return None


def _normalized_company_name(value: str) -> str:
    tokens = re.findall(r"[0-9a-zа-яё]+", value.casefold().replace("ё", "е"))
    changed = True
    while tokens and changed:
        changed = False
        if tokens[0] in LEGAL_FORM_TOKENS:
            tokens.pop(0)
            changed = True
            continue
        for phrase in LEGAL_FORM_PHRASES:
            if tuple(tokens[: len(phrase)]) == phrase:
                del tokens[: len(phrase)]
                changed = True
                break
    return "".join(tokens)
