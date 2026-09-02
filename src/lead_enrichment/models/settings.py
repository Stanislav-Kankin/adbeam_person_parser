from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class HttpClientSettings(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_agent: str = "AdBeamPersonParser/0.1 (+local desktop contact research)"
    connect_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    read_timeout_seconds: float = Field(default=10.0, gt=0, le=120)
    write_timeout_seconds: float = Field(default=10.0, gt=0, le=120)
    pool_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    max_connections: int = Field(default=10, ge=1, le=50)
    max_keepalive_connections: int = Field(default=5, ge=0, le=50)
    max_attempts: int = Field(default=3, ge=1, le=5)
    retry_min_seconds: float = Field(default=0.25, ge=0, le=30)
    retry_max_seconds: float = Field(default=3.0, ge=0, le=60)
    per_host_delay_seconds: float = Field(default=0.5, ge=0, le=60)
    max_redirects: int = Field(default=5, ge=0, le=10)
    max_response_bytes: int = Field(default=2_000_000, ge=1_024, le=20_000_000)


class SiteCrawlSettings(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_pages: int = Field(default=4, ge=1, le=10)
    max_link_candidates: int = Field(default=12, ge=1, le=50)
    respect_robots_txt: bool = True
