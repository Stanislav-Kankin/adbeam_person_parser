from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from lead_enrichment.models.contact import ContactChannel, PersonContact
from lead_enrichment.models.evidence import SourceReference


class EntityType(str, Enum):
    LEGAL_ENTITY = "LEGAL_ENTITY"
    INDIVIDUAL_ENTREPRENEUR = "INDIVIDUAL_ENTREPRENEUR"
    UNKNOWN = "UNKNOWN"


class CompanyFinancials(BaseModel):
    model_config = ConfigDict(frozen=True)

    revenue: str | None = Field(default=None, max_length=500)
    balance: str | None = Field(default=None, max_length=500)
    net_profit_loss: str | None = Field(default=None, max_length=500)
    arbitration_defendant: str | None = Field(default=None, max_length=500)


class CompanyInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    input_row_id: str = Field(min_length=1, max_length=200)
    legal_name: str = Field(min_length=1, max_length=1000)
    inn: str = Field(pattern=r"^\d{10}(?:\d{2})?$")
    kpp: str | None = Field(default=None, pattern=r"^\d{9}$")
    ogrn: str | None = Field(default=None, pattern=r"^\d{13}(?:\d{2})?$")
    entity_type: EntityType
    registration_date: date | None = None
    address: str | None = Field(default=None, max_length=5000)
    region: str | None = Field(default=None, max_length=500)
    operating_status: str | None = Field(default=None, max_length=500)
    msp_category: str | None = Field(default=None, max_length=500)
    focus_url: str | None = Field(default=None, max_length=2048)
    website: str | None = Field(default=None, max_length=2048)
    primary_activity: str | None = Field(default=None, max_length=5000)
    other_activities: list[str] = Field(default_factory=list)
    licenses: list[str] = Field(default_factory=list)
    financials: CompanyFinancials = Field(default_factory=CompanyFinancials)
    employee_count: int | None = Field(default=None, ge=0)
    branches: list[str] = Field(default_factory=list)
    branch_count: int | None = Field(default=None, ge=0)
    source_label: str | None = Field(default=None, max_length=500)
    segment_name: str | None = Field(default=None, max_length=500)
    company_channels: list[ContactChannel] = Field(default_factory=list)
    initial_people: list[PersonContact] = Field(default_factory=list)
    source_refs: list[SourceReference] = Field(default_factory=list)
