from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from lead_enrichment.models.company import CompanyInput
from lead_enrichment.models.contact import ContactChannel, ContactRole, PersonContact


class ImportIssueSeverity(str, Enum):
    WARNING = "WARNING"
    ERROR = "ERROR"


class ImportIssue(BaseModel):
    model_config = ConfigDict(frozen=True)

    row_index: int = Field(ge=1)
    code: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=1000)
    severity: ImportIssueSeverity


class KonturImportSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_file_name: str
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sheet_name: str
    total_rows: int = Field(ge=0)
    imported_rows: int = Field(ge=0)
    skipped_rows: int = Field(ge=0)
    blank_rows: int = Field(ge=0)
    duplicate_inn_rows: int = Field(ge=0)
    legal_entities: int = Field(ge=0)
    individual_entrepreneurs: int = Field(ge=0)
    rows_with_initial_person: int = Field(ge=0)
    rows_with_phones: int = Field(ge=0)
    rows_with_emails: int = Field(ge=0)
    rows_with_website: int = Field(ge=0)
    issues: list[ImportIssue] = Field(default_factory=list)


class KonturImportResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    summary: KonturImportSummary
    companies: list[CompanyInput] = Field(default_factory=list)


class SourceOutcome(str, Enum):
    FOUND = "FOUND"
    PARTIAL = "PARTIAL"
    NOT_FOUND = "NOT_FOUND"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


class SourceMetadata(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_id: str = Field(min_length=1, max_length=100)
    version: str = Field(min_length=1, max_length=50)
    display_name: str = Field(min_length=1, max_length=200)
    network_access: bool = False


class SourceApplicability(BaseModel):
    model_config = ConfigDict(frozen=True)

    applicable: bool
    reason_code: str = Field(min_length=1, max_length=100)
    reason_message: str = Field(min_length=1, max_length=1000)


class SourceMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    duration_ms: int = Field(default=0, ge=0)
    request_count: int = Field(default=0, ge=0)
    checked_page_count: int = Field(default=0, ge=0)


class PipelineContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str = Field(min_length=1, max_length=200)
    company: CompanyInput
    collected_at: datetime
    target_roles: list[ContactRole] = Field(default_factory=list)

    @field_validator("collected_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("collected_at must be timezone-aware")
        return value


class SourceResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_id: str = Field(min_length=1, max_length=100)
    source_version: str = Field(min_length=1, max_length=50)
    outcome: SourceOutcome
    reason_code: str = Field(min_length=1, max_length=100)
    reason_message: str = Field(min_length=1, max_length=1000)
    continue_reason: str | None = Field(default=None, max_length=1000)
    company_channels: list[ContactChannel] = Field(default_factory=list)
    person_contacts: list[PersonContact] = Field(default_factory=list)
    checked_urls: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    metrics: SourceMetrics = Field(default_factory=SourceMetrics)
