from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SourceKind(str, Enum):
    KONTUR_EXPORT = "KONTUR_EXPORT"
    COMPANY_SITE = "COMPANY_SITE"
    OFFICIAL_REGISTRY = "OFFICIAL_REGISTRY"
    PROCUREMENT = "PROCUREMENT"
    BUSINESS_DIRECTORY = "BUSINESS_DIRECTORY"
    JOB_BOARD = "JOB_BOARD"
    MEDIA = "MEDIA"
    COMPANY_SOCIAL = "COMPANY_SOCIAL"
    WHOIS = "WHOIS"
    MANUAL = "MANUAL"


class SourceReference(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_id: str = Field(min_length=1, max_length=100)
    source_kind: SourceKind
    source_name: str = Field(min_length=1, max_length=200)
    locator: str = Field(min_length=1, max_length=500)
    collected_at: datetime
    url: str | None = Field(default=None, max_length=2048)
    reliability: int = Field(ge=0, le=100)

    @field_validator("collected_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("collected_at must be timezone-aware")
        return value
