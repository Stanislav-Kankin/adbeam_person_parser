from lead_enrichment.engine.identity_resolution import merge_assessment_with_kontur
from lead_enrichment.models import (
    AssessmentCompany,
    AssessmentImportResult,
    AssessmentImportSummary,
    CompanyInput,
    EntityType,
    IdentityMatchMethod,
    IdentityResolutionStatus,
    KonturImportResult,
    KonturImportSummary,
)

HASH = "0" * 64


def _assessment(*companies: AssessmentCompany) -> AssessmentImportResult:
    return AssessmentImportResult(
        summary=AssessmentImportSummary(
            source_file_name="assessment.xlsx",
            source_sha256=HASH,
            main_sheet_name="Ростовская область",
            lpr_sheet_name="ЛПР 2026 verified",
            total_rows=len(companies),
            imported_rows=len(companies),
            skipped_rows=0,
            rows_with_website=sum(company.website is not None for company in companies),
            rows_with_sales_phones=0,
            primary_contacts=0,
            alternative_contacts=0,
            indigo_matches=0,
        ),
        companies=list(companies),
    )


def _kontur(*companies: CompanyInput) -> KonturImportResult:
    return KonturImportResult(
        summary=KonturImportSummary(
            source_file_name="kontur.xlsx",
            source_sha256=HASH,
            sheet_name="Контрагенты",
            total_rows=len(companies),
            imported_rows=len(companies),
            skipped_rows=0,
            blank_rows=0,
            duplicate_inn_rows=0,
            legal_entities=len(companies),
            individual_entrepreneurs=0,
            rows_with_initial_person=0,
            rows_with_phones=0,
            rows_with_emails=0,
            rows_with_website=sum(company.website is not None for company in companies),
        ),
        companies=list(companies),
    )


def _assessment_company(row: int, name: str, website: str | None = None) -> AssessmentCompany:
    return AssessmentCompany(
        company_key=f"assessment:{row}",
        input_row_id=f"Ростовская область:{row}",
        assessment_row=row,
        brand_name=name,
        website=website,
    )


def _kontur_company(inn: str, name: str, website: str | None = None) -> CompanyInput:
    return CompanyInput(
        input_row_id=f"Контрагенты:{inn}",
        legal_name=name,
        inn=inn,
        entity_type=EntityType.LEGAL_ENTITY,
        website=website,
    )


def test_merge_uses_unique_domain_before_different_legal_name() -> None:
    result = merge_assessment_with_kontur(
        _assessment(_assessment_company(2, "Бренд группы", "https://brand.ru")),
        _kontur(_kontur_company("1234567894", 'ООО "Техническое юрлицо"', "https://www.brand.ru/")),
    )

    lead = result.leads[0]
    assert lead.company_key == "inn:1234567894"
    assert lead.kontur_company is not None
    assert lead.identity.status == IdentityResolutionStatus.MATCHED
    assert lead.identity.method == IdentityMatchMethod.DOMAIN
    assert lead.identity.confidence_score == 92


def test_merge_uses_name_to_disambiguate_shared_domain() -> None:
    result = merge_assessment_with_kontur(
        _assessment(_assessment_company(2, "ГК Альфа", "https://group.ru")),
        _kontur(
            _kontur_company("1234567894", 'ООО "Альфа"', "https://group.ru"),
            _kontur_company("1234567895", 'ООО "Бета"', "https://group.ru"),
        ),
    )

    assert result.leads[0].identity.method == IdentityMatchMethod.DOMAIN_AND_NAME
    assert result.leads[0].identity.matched_inn == "1234567894"


def test_merge_keeps_shared_domain_ambiguous_without_name_match() -> None:
    result = merge_assessment_with_kontur(
        _assessment(_assessment_company(2, "Неизвестный бренд", "https://group.ru")),
        _kontur(
            _kontur_company("1234567894", 'ООО "Альфа"', "https://group.ru"),
            _kontur_company("1234567895", 'ООО "Бета"', "https://group.ru"),
        ),
    )

    lead = result.leads[0]
    assert lead.kontur_company is None
    assert lead.identity.status == IdentityResolutionStatus.AMBIGUOUS
    assert lead.identity.candidate_inns == ["1234567894", "1234567895"]


def test_merge_matches_legal_form_normalized_name_and_reports_not_found() -> None:
    result = merge_assessment_with_kontur(
        _assessment(
            _assessment_company(2, "ГК Альфа"),
            _assessment_company(3, "Нет в Контуре"),
        ),
        _kontur(_kontur_company("1234567894", 'ООО СЗ "Альфа"')),
    )

    matched, missing = result.leads
    assert matched.identity.status == IdentityResolutionStatus.MATCHED
    assert matched.identity.method == IdentityMatchMethod.NORMALIZED_NAME
    assert missing.identity.status == IdentityResolutionStatus.NOT_FOUND
    assert missing.company_key == "assessment:3"
    assert result.summary.matched_rows == 1
    assert result.summary.not_found_rows == 1
    assert result.summary.matched_by_method == {"NORMALIZED_NAME": 1}
