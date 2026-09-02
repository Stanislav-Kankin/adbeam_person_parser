from datetime import datetime, timezone
from uuid import uuid4

from lead_enrichment.engine.lead_preparation import (
    evaluate_contact_coverage,
    prepare_pipeline_company,
)
from lead_enrichment.models import (
    AssessmentCompany,
    AssessmentContact,
    ChannelScope,
    ChannelType,
    CompanyInput,
    ContactChannel,
    ContactRole,
    CoverageResolutionStatus,
    EntityType,
    IdentityMatchMethod,
    IdentityResolution,
    IdentityResolutionStatus,
    MergedLead,
    PersonContact,
    SourceKind,
    SourceReference,
)


def _source(source_id: str) -> SourceReference:
    return SourceReference(
        source_id=source_id,
        source_kind=SourceKind.CLIENT_ASSESSMENT,
        source_name=source_id,
        locator=f"sheet!{source_id}",
        collected_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
        reliability=70,
    )


def _assessment() -> AssessmentCompany:
    source = _source("assessment")
    return AssessmentCompany(
        company_key="assessment:erz:1",
        input_row_id="Ростовская область:2",
        assessment_row=2,
        brand_name="ГК Тест",
        region="Ростовская область",
        website="https://brand.ru",
        company_channels=[
            ContactChannel(
                channel_type=ChannelType.PHONE,
                value="+78631234567",
                scope=ChannelScope.COMPANY,
                source_refs=[source],
            )
        ],
        contacts=[
            AssessmentContact(
                full_name="Иванов Иван Иванович",
                job_title="директор по маркетингу",
                normalized_role=ContactRole.MARKETING,
                verification_status="актуально: официальный сайт",
                evidence_urls=["https://brand.ru/team"],
                source_refs=[source],
            )
        ],
        source_refs=[source],
    )


def _unmatched_identity() -> IdentityResolution:
    return IdentityResolution(
        status=IdentityResolutionStatus.NOT_FOUND,
        method=IdentityMatchMethod.NONE,
        confidence_score=0,
        reason_code="KONTUR_COMPANY_NOT_FOUND",
        reason_message="Не найдено",
    )


def test_prepare_pipeline_company_supports_brand_without_inn() -> None:
    assessment = _assessment()
    company = prepare_pipeline_company(
        MergedLead(
            company_key=assessment.company_key,
            assessment=assessment,
            identity=_unmatched_identity(),
        )
    )

    assert company.inn is None
    assert company.legal_name is None
    assert company.brand_name == "ГК Тест"
    assert company.entity_type == EntityType.UNKNOWN
    assert company.initial_people[0].confidence_score == 83
    coverage = evaluate_contact_coverage(company)
    assert coverage.status == CoverageResolutionStatus.PARTIAL
    assert coverage.reason_code == "TARGET_PERSON_WITHOUT_PERSONAL_CHANNEL"


def test_prepare_pipeline_company_merges_kontur_and_prefers_brand_website() -> None:
    assessment = _assessment()
    kontur_source = _source("kontur")
    kontur = CompanyInput(
        input_row_id="Контрагенты:2",
        legal_name='ООО "Тест"',
        inn="1234567894",
        entity_type=EntityType.LEGAL_ENTITY,
        website="https://legal-entity.ru",
        company_channels=[
            ContactChannel(
                channel_type=ChannelType.PHONE,
                value="+78631234567",
                scope=ChannelScope.COMPANY,
                source_refs=[kontur_source],
            )
        ],
        source_refs=[kontur_source],
    )
    identity = IdentityResolution(
        status=IdentityResolutionStatus.MATCHED,
        method=IdentityMatchMethod.DOMAIN,
        confidence_score=92,
        reason_code="UNIQUE_DOMAIN_MATCH",
        reason_message="Совпало",
        matched_inn=kontur.inn,
        candidate_inns=[kontur.inn],
    )

    company = prepare_pipeline_company(
        MergedLead(
            company_key="inn:1234567894",
            assessment=assessment,
            kontur_company=kontur,
            identity=identity,
        )
    )

    assert company.company_key == "inn:1234567894"
    assert company.legal_name == 'ООО "Тест"'
    assert company.brand_name == "ГК Тест"
    assert company.website == "https://brand.ru"
    assert len(company.company_channels) == 1
    assert {ref.source_id for ref in company.company_channels[0].source_refs} == {
        "assessment",
        "kontur",
    }


def test_coverage_requires_personal_channel_for_resolved() -> None:
    personal_email = ContactChannel(
        channel_type=ChannelType.EMAIL,
        value="person@example.ru",
        scope=ChannelScope.PERSONAL,
    )
    company = CompanyInput(
        company_key="brand:test",
        input_row_id="test:2",
        brand_name="Тест",
        initial_people=[
            PersonContact(
                contact_id=uuid4(),
                full_name="Иванов Иван",
                normalized_role=ContactRole.SALES,
                confidence_score=80,
                channels=[personal_email],
            )
        ],
    )

    coverage = evaluate_contact_coverage(company)

    assert coverage.status == CoverageResolutionStatus.RESOLVED
    assert coverage.has_personal_direct_channel
    assert coverage.missing_roles == [ContactRole.MARKETING]


def test_coverage_routes_empty_company_to_manual_queue() -> None:
    company = CompanyInput(
        company_key="brand:empty",
        input_row_id="test:3",
        brand_name="Пустая компания",
    )

    coverage = evaluate_contact_coverage(company)

    assert coverage.status == CoverageResolutionStatus.MANUAL_REQUIRED
    assert coverage.reason_code == "NO_ACTIONABLE_CONTACT"
