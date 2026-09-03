from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from lead_enrichment.models.company import CompanyInput
from lead_enrichment.models.contact import ContactRole
from lead_enrichment.models.coverage import ContactCoverage
from lead_enrichment.models.identity import MergedLead
from lead_enrichment.models.pipeline import SourceOutcome, SourceResult


class PipelineStepRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    company_key: str = Field(min_length=1, max_length=500)
    source_id: str = Field(min_length=1, max_length=100)
    source_version: str = Field(min_length=1, max_length=50)
    outcome: SourceOutcome
    reason_code: str = Field(min_length=1, max_length=100)
    reason_message: str = Field(min_length=1, max_length=1000)
    from_checkpoint: bool = False
    duration_ms: int = Field(default=0, ge=0)


class EnrichedLeadResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    lead: MergedLead
    company: CompanyInput
    coverage: ContactCoverage
    source_results: list[SourceResult] = Field(default_factory=list)
    steps: list[PipelineStepRecord] = Field(default_factory=list)
    manual_search_urls: list[str] = Field(default_factory=list)


class BatchEnrichmentSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_companies: int = Field(ge=0)
    resolved: int = Field(ge=0)
    partial: int = Field(ge=0)
    manual_required: int = Field(ge=0)
    checkpoint_hits: int = Field(ge=0)
    source_executions: int = Field(ge=0)


class BatchEnrichmentResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str = Field(min_length=1, max_length=200)
    target_roles: list[ContactRole] = Field(default_factory=list)
    cancelled: bool = False
    summary: BatchEnrichmentSummary
    leads: list[EnrichedLeadResult] = Field(default_factory=list)
