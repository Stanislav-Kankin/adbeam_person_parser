from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from lead_enrichment.models.contact import ContactRole


class CoverageResolutionStatus(str, Enum):
    RESOLVED = "RESOLVED"
    PARTIAL = "PARTIAL"
    MANUAL_REQUIRED = "MANUAL_REQUIRED"


class ContactCoverage(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: CoverageResolutionStatus
    reason_code: str = Field(min_length=1, max_length=100)
    reason_message: str = Field(min_length=1, max_length=1000)
    target_roles: list[ContactRole] = Field(default_factory=list)
    found_roles: list[ContactRole] = Field(default_factory=list)
    missing_roles: list[ContactRole] = Field(default_factory=list)
    has_qualified_target_person: bool = False
    has_personal_direct_channel: bool = False
    has_company_direct_channel: bool = False
