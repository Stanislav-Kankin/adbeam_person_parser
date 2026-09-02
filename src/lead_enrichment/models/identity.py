from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from lead_enrichment.models.assessment import AssessmentCompany
from lead_enrichment.models.company import CompanyInput


class IdentityResolutionStatus(str, Enum):
    MATCHED = "MATCHED"
    AMBIGUOUS = "AMBIGUOUS"
    NOT_FOUND = "NOT_FOUND"


class IdentityMatchMethod(str, Enum):
    DOMAIN = "DOMAIN"
    DOMAIN_AND_NAME = "DOMAIN_AND_NAME"
    NORMALIZED_NAME = "NORMALIZED_NAME"
    NONE = "NONE"


class IdentityResolution(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: IdentityResolutionStatus
    method: IdentityMatchMethod
    confidence_score: int = Field(ge=0, le=100)
    reason_code: str = Field(min_length=1, max_length=100)
    reason_message: str = Field(min_length=1, max_length=1000)
    matched_inn: str | None = Field(default=None, pattern=r"^\d{10}(?:\d{2})?$")
    candidate_inns: list[str] = Field(default_factory=list)


class MergedLead(BaseModel):
    model_config = ConfigDict(frozen=True)

    company_key: str = Field(min_length=1, max_length=500)
    assessment: AssessmentCompany
    kontur_company: CompanyInput | None = None
    identity: IdentityResolution


class AssessmentKonturMergeSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    assessment_rows: int = Field(ge=0)
    kontur_rows: int = Field(ge=0)
    matched_rows: int = Field(ge=0)
    ambiguous_rows: int = Field(ge=0)
    not_found_rows: int = Field(ge=0)
    matched_by_method: dict[str, int] = Field(default_factory=dict)


class AssessmentKonturMergeResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    summary: AssessmentKonturMergeSummary
    leads: list[MergedLead] = Field(default_factory=list)
