from __future__ import annotations

from typing import Protocol

from lead_enrichment.models.pipeline import (
    PipelineContext,
    SourceApplicability,
    SourceMetadata,
    SourceResult,
)


class SourcePlugin(Protocol):
    @property
    def metadata(self) -> SourceMetadata: ...

    def is_applicable(self, context: PipelineContext) -> SourceApplicability: ...

    def execute(self, context: PipelineContext) -> SourceResult: ...
