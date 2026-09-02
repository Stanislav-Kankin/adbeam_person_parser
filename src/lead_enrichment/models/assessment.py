from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from lead_enrichment.models.contact import ContactChannel, ContactRole
from lead_enrichment.models.evidence import SourceReference
from lead_enrichment.models.pipeline import ImportIssue


class LeadPriority(str, Enum):
    TIR_1 = "TIR 1"
    TIR_2 = "TIR 2"
    TIR_3 = "TIR 3"
    UNKNOWN = "UNKNOWN"


class AssessmentScores(BaseModel):
    model_config = ConfigDict(frozen=True)

    commercial_potential: int | None = Field(default=None, ge=0)
    marketing_need: int | None = Field(default=None, ge=0)
    digital_opportunity: int | None = Field(default=None, ge=0)
    outreach_accessibility: int | None = Field(default=None, ge=0)
    total: int | None = Field(default=None, ge=0)


class AssessmentContact(BaseModel):
    """A person seed copied from the client's verified LPR sheet.

    Confidence is deliberately not assigned during import. The workbook status,
    evidence URLs and subsequent source plugins are evaluated later by scoring.
    """

    model_config = ConfigDict(frozen=True)

    full_name: str = Field(min_length=1, max_length=500)
    job_title: str | None = Field(default=None, max_length=1000)
    normalized_role: ContactRole = ContactRole.UNKNOWN
    is_primary: bool = True
    verification_status: str | None = Field(default=None, max_length=2000)
    outreach_recommendation: str | None = Field(default=None, max_length=2000)
    comment: str | None = Field(default=None, max_length=5000)
    evidence_urls: list[str] = Field(default_factory=list)
    source_refs: list[SourceReference] = Field(default_factory=list)


AssessmentScalar = str | int | float | date | None


class AssessmentCompany(BaseModel):
    model_config = ConfigDict(frozen=True)

    company_key: str = Field(min_length=1, max_length=500)
    input_row_id: str = Field(min_length=1, max_length=200)
    assessment_row: int = Field(ge=2)
    brand_name: str = Field(min_length=1, max_length=1000)
    region: str | None = Field(default=None, max_length=500)
    assessment_date: date | None = None
    source_rating_date: date | None = None
    erz_id: str | None = Field(default=None, max_length=200)
    erz_url: str | None = Field(default=None, max_length=2048)
    website: str | None = Field(default=None, max_length=2048)
    address: str | None = Field(default=None, max_length=5000)
    projects: list[str] = Field(default_factory=list)
    project_cities: list[str] = Field(default_factory=list)
    company_channels: list[ContactChannel] = Field(default_factory=list)
    contacts: list[AssessmentContact] = Field(default_factory=list)
    scale_type: str | None = Field(default=None, max_length=200)
    stage1_status: str | None = Field(default=None, max_length=200)
    lead_priority: LeadPriority = LeadPriority.UNKNOWN
    cap_rule: str | None = Field(default=None, max_length=200)
    scores: AssessmentScores = Field(default_factory=AssessmentScores)
    indigo_match_status: str | None = Field(default=None, max_length=200)
    matched_indigo_group: str | None = Field(default=None, max_length=1000)
    matched_indigo_alias: str | None = Field(default=None, max_length=1000)
    indigo_match_type: str | None = Field(default=None, max_length=200)
    workflow_status: str | None = Field(default=None, max_length=200)
    owner: str | None = Field(default=None, max_length=500)
    last_touch_date: date | None = None
    outreach_hook: str | None = Field(default=None, max_length=10_000)
    next_action: str | None = Field(default=None, max_length=2000)
    missing_data: str | None = Field(default=None, max_length=5000)
    source_urls: list[str] = Field(default_factory=list)
    comments: str | None = Field(default=None, max_length=10_000)
    source_fields: dict[str, AssessmentScalar] = Field(default_factory=dict)
    source_refs: list[SourceReference] = Field(default_factory=list)


class AssessmentImportSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_file_name: str
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    main_sheet_name: str
    lpr_sheet_name: str
    total_rows: int = Field(ge=0)
    imported_rows: int = Field(ge=0)
    skipped_rows: int = Field(ge=0)
    rows_with_website: int = Field(ge=0)
    rows_with_sales_phones: int = Field(ge=0)
    primary_contacts: int = Field(ge=0)
    alternative_contacts: int = Field(ge=0)
    indigo_matches: int = Field(ge=0)
    tier_counts: dict[str, int] = Field(default_factory=dict)
    issues: list[ImportIssue] = Field(default_factory=list)


class AssessmentImportResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    summary: AssessmentImportSummary
    companies: list[AssessmentCompany] = Field(default_factory=list)
