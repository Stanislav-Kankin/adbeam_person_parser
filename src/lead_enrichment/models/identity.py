from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from lead_enrichment.models.assessment import AssessmentCompany
from lead_enrichment.models.company import CompanyInput


class IdentityResolutionStatus(str, Enum):
    MATCHED = "MATCHED"
    AMBIGUOUS = "AMBIGUOUS"
    NOT_FOUND = "NOT_FOUND"


class IdentityMatchMethod(str, Enum):
    INN = "INN"
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
    assessment: AssessmentCompany | None = None
    kontur_company: CompanyInput | None = None
    identity: IdentityResolution

    @model_validator(mode="after")
    def require_input_company(self) -> MergedLead:
        if self.assessment is None and self.kontur_company is None:
            raise ValueError("assessment or kontur_company is required")
        return self


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
