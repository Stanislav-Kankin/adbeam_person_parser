from __future__ import annotations

from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from lead_enrichment.models.evidence import SourceReference


class ContactRole(str, Enum):
    OWNER = "OWNER"
    LEADER = "LEADER"
    MARKETING = "MARKETING"
    SALES = "SALES"
    PROCUREMENT = "PROCUREMENT"
    UNKNOWN = "UNKNOWN"


class ChannelType(str, Enum):
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    SOCIAL = "SOCIAL"


class ChannelScope(str, Enum):
    PERSONAL = "PERSONAL"
    COMPANY = "COMPANY"
    UNKNOWN = "UNKNOWN"


class ContactChannel(BaseModel):
    model_config = ConfigDict(frozen=True)

    channel_type: ChannelType
    value: str = Field(min_length=1, max_length=2048)
    scope: ChannelScope = ChannelScope.UNKNOWN
    source_refs: list[SourceReference] = Field(default_factory=list)


class PersonContact(BaseModel):
    model_config = ConfigDict(frozen=True)

    contact_id: UUID
    full_name: str = Field(min_length=1, max_length=500)
    job_title: str | None = Field(default=None, max_length=500)
    normalized_role: ContactRole = ContactRole.UNKNOWN
    confidence_score: int = Field(ge=0, le=100)
    channels: list[ContactChannel] = Field(default_factory=list)
    source_refs: list[SourceReference] = Field(default_factory=list)
