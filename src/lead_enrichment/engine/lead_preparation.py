from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID, uuid5

from lead_enrichment.models import (
    AssessmentContact,
    ChannelScope,
    ChannelType,
    CompanyInput,
    ContactChannel,
    ContactCoverage,
    ContactRole,
    CoverageResolutionStatus,
    EntityType,
    MergedLead,
    PersonContact,
    SourceReference,
    SourceResult,
)

ASSESSMENT_CONTACT_NAMESPACE = UUID("5f90bc07-9eb0-4dd2-acf7-9b5ec7baec67")
DEFAULT_TARGET_ROLES = (ContactRole.MARKETING, ContactRole.SALES)
DIRECT_CHANNEL_TYPES = {ChannelType.EMAIL, ChannelType.PHONE}


def prepare_pipeline_company(lead: MergedLead) -> CompanyInput:
    assessment = lead.assessment
    if assessment is None:
        if lead.kontur_company is None or not lead.kontur_company.inn:
            raise ValueError("INN-first pipeline requires a Kontur company with INN")
        return lead.kontur_company
    assessment_people = [
        _assessment_person(lead.company_key, contact) for contact in assessment.contacts
    ]
    if lead.kontur_company is None:
        return CompanyInput(
            company_key=lead.company_key,
            input_row_id=assessment.input_row_id,
            legal_name=None,
            brand_name=assessment.brand_name,
            inn=None,
            entity_type=EntityType.UNKNOWN,
            address=assessment.address,
            region=assessment.region,
            website=assessment.website,
            source_label="Клиентский assessment",
            company_channels=list(assessment.company_channels),
            initial_people=_merge_people(assessment_people),
            source_refs=list(assessment.source_refs),
        )

    kontur = lead.kontur_company
    return kontur.model_copy(
        update={
            "company_key": lead.company_key,
            "brand_name": assessment.brand_name,
            "website": assessment.website or kontur.website,
            "region": kontur.region or assessment.region,
            "address": kontur.address or assessment.address,
            "company_channels": _merge_channels(
                [*kontur.company_channels, *assessment.company_channels]
            ),
            "initial_people": _merge_people(
                [*kontur.initial_people, *assessment_people]
            ),
            "source_refs": _merge_source_refs(
                [*kontur.source_refs, *assessment.source_refs]
            ),
        }
    )


def evaluate_contact_coverage(
    company: CompanyInput,
    *,
    target_roles: Iterable[ContactRole] = DEFAULT_TARGET_ROLES,
    minimum_confidence: int = 70,
) -> ContactCoverage:
    targets = _unique_roles(target_roles)
    found_roles = _unique_roles(
        person.normalized_role
        for person in company.initial_people
        if person.normalized_role != ContactRole.UNKNOWN
    )
    qualified_people = [
        person
        for person in company.initial_people
        if person.normalized_role in targets and person.confidence_score >= minimum_confidence
    ]
    qualified_roles = {person.normalized_role for person in qualified_people}
    personal_direct = any(
        channel.channel_type in DIRECT_CHANNEL_TYPES
        and channel.scope == ChannelScope.PERSONAL
        for person in qualified_people
        for channel in person.channels
    )
    company_direct = any(
        channel.channel_type in DIRECT_CHANNEL_TYPES
        for channel in company.company_channels
    )

    if qualified_people and personal_direct:
        status = CoverageResolutionStatus.RESOLVED
        reason_code = "TARGET_PERSONAL_CONTACT_FOUND"
        reason_message = "Найден целевой ЛПР с подтверждённым персональным каналом"
    elif qualified_people:
        status = CoverageResolutionStatus.PARTIAL
        reason_code = "TARGET_PERSON_WITHOUT_PERSONAL_CHANNEL"
        reason_message = "Целевой ЛПР найден, но персональный email или телефон отсутствует"
    elif company_direct:
        status = CoverageResolutionStatus.PARTIAL
        reason_code = "COMPANY_CHANNEL_ONLY"
        reason_message = "Есть канал компании, но целевой ЛПР с достаточной уверенностью не найден"
    else:
        status = CoverageResolutionStatus.MANUAL_REQUIRED
        reason_code = "NO_ACTIONABLE_CONTACT"
        reason_message = "Не найден ни целевой ЛПР, ни прямой канал компании"

    return ContactCoverage(
        status=status,
        reason_code=reason_code,
        reason_message=reason_message,
        target_roles=targets,
        found_roles=found_roles,
        missing_roles=[role for role in targets if role not in qualified_roles],
        has_qualified_target_person=bool(qualified_people),
        has_personal_direct_channel=personal_direct,
        has_company_direct_channel=company_direct,
    )


def apply_source_result(company: CompanyInput, result: SourceResult) -> CompanyInput:
    return company.model_copy(
        update={
            "company_channels": _merge_channels(
                [*company.company_channels, *result.company_channels]
            ),
            "initial_people": _merge_people(
                [*company.initial_people, *result.person_contacts]
            ),
        }
    )


def _assessment_person(company_key: str, contact: AssessmentContact) -> PersonContact:
    identity = (
        f"assessment:{company_key}:{contact.full_name.casefold()}:"
        f"{contact.normalized_role.value}:{int(contact.is_primary)}"
    )
    return PersonContact(
        contact_id=uuid5(ASSESSMENT_CONTACT_NAMESPACE, identity),
        full_name=contact.full_name,
        job_title=contact.job_title,
        normalized_role=contact.normalized_role,
        confidence_score=_assessment_confidence(contact),
        source_refs=contact.source_refs,
    )


def _assessment_confidence(contact: AssessmentContact) -> int:
    status = (contact.verification_status or "").casefold()
    if "конфликт" in status:
        score = 30
    elif "актуально" in status or "verified" in status:
        score = 78
    elif "замена" in status:
        score = 68
    else:
        score = 55
    if contact.evidence_urls:
        score += 5
    return min(score, 100)


def _merge_people(people: Iterable[PersonContact]) -> list[PersonContact]:
    result: dict[tuple[str, ContactRole], PersonContact] = {}
    for person in people:
        key = (_normalized_name(person.full_name), person.normalized_role)
        existing = result.get(key)
        if existing is None:
            result[key] = person
            continue
        result[key] = existing.model_copy(
            update={
                "job_title": existing.job_title or person.job_title,
                "confidence_score": max(existing.confidence_score, person.confidence_score),
                "channels": _merge_channels([*existing.channels, *person.channels]),
                "source_refs": _merge_source_refs(
                    [*existing.source_refs, *person.source_refs]
                ),
            }
        )
    return list(result.values())


def _merge_channels(channels: Iterable[ContactChannel]) -> list[ContactChannel]:
    result: dict[tuple[ChannelType, str], ContactChannel] = {}
    for channel in channels:
        key = (channel.channel_type, channel.value.casefold())
        existing = result.get(key)
        if existing is None:
            result[key] = channel
            continue
        result[key] = existing.model_copy(
            update={
                "source_refs": _merge_source_refs(
                    [*existing.source_refs, *channel.source_refs]
                )
            }
        )
    return list(result.values())


def _merge_source_refs(refs: Iterable[SourceReference]) -> list[SourceReference]:
    result: dict[tuple[str, str, str | None], SourceReference] = {}
    for ref in refs:
        result.setdefault((ref.source_id, ref.locator, ref.url), ref)
    return list(result.values())


def _unique_roles(roles: Iterable[ContactRole]) -> list[ContactRole]:
    return list(dict.fromkeys(roles))


def _normalized_name(value: str) -> str:
    return "".join(char for char in value.casefold().replace("ё", "е") if char.isalnum())
