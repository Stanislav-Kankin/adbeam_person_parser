from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from lead_enrichment.models.company import CompanyInput


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
