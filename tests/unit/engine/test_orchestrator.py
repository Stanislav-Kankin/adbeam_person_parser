from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from lead_enrichment.engine import EnrichmentOrchestrator
from lead_enrichment.infrastructure import CheckpointRegistry
from lead_enrichment.models import (
    AssessmentCompany,
    ChannelScope,
    ChannelType,
    ContactChannel,
    ContactRole,
    CoverageResolutionStatus,
    IdentityMatchMethod,
    IdentityResolution,
    IdentityResolutionStatus,
    MergedLead,
    PersonContact,
    SourceApplicability,
    SourceMetadata,
    SourceOutcome,
    SourceResult,
)

NOW = datetime(2026, 9, 2, tzinfo=timezone.utc)


class _PersonalContactPlugin:
    def __init__(self) -> None:
        self.calls = 0

    @property
    def metadata(self) -> SourceMetadata:
        return SourceMetadata(
            source_id="personal_test",
            version="1.0.0",
            display_name="Тестовый источник",
        )

    def is_applicable(self, _context) -> SourceApplicability:
        return SourceApplicability(
            applicable=True,
            reason_code="APPLICABLE",
            reason_message="Применим",
        )

    def execute(self, _context) -> SourceResult:
        self.calls += 1
        return SourceResult(
            source_id="personal_test",
            source_version="1.0.0",
            outcome=SourceOutcome.FOUND,
            reason_code="PERSON_FOUND",
            reason_message="Найден персональный контакт",
            person_contacts=[
                PersonContact(
                    contact_id=uuid4(),
                    full_name="Иванов Иван",
                    normalized_role=ContactRole.SALES,
                    confidence_score=85,
                    channels=[
                        ContactChannel(
                            channel_type=ChannelType.EMAIL,
                            value="person@example.ru",
                            scope=ChannelScope.PERSONAL,
                        )
                    ],
                )
            ],
        )


def _lead(*, indigo_status: str = "no_match") -> MergedLead:
    assessment = AssessmentCompany(
        company_key="assessment:erz:1",
        input_row_id="Ростовская область:2",
        assessment_row=2,
        brand_name="ГК Тест",
        indigo_match_status=indigo_status,
    )
    return MergedLead(
        company_key=assessment.company_key,
        assessment=assessment,
        identity=IdentityResolution(
            status=IdentityResolutionStatus.NOT_FOUND,
            method=IdentityMatchMethod.NONE,
            confidence_score=0,
            reason_code="KONTUR_COMPANY_NOT_FOUND",
            reason_message="Не найдено",
        ),
    )


def test_orchestrator_resumes_source_result_from_checkpoint(tmp_path: Path) -> None:
    plugin = _PersonalContactPlugin()
    registry = CheckpointRegistry(tmp_path / "checkpoints.sqlite3")
    orchestrator = EnrichmentOrchestrator([plugin], checkpoint_registry=registry)

    first = orchestrator.run([_lead()], run_id="run-1", collected_at=NOW)
    second = orchestrator.run([_lead()], run_id="run-1", collected_at=NOW)

    assert first.summary.resolved == 1
    assert first.summary.source_executions == 1
    assert first.leads[0].coverage.status == CoverageResolutionStatus.RESOLVED
    assert second.summary.checkpoint_hits == 1
    assert second.summary.source_executions == 0
    assert second.leads[0].steps[0].from_checkpoint
    assert plugin.calls == 1


def test_orchestrator_routes_indigo_match_to_manual_review() -> None:
    plugin = _PersonalContactPlugin()

    result = EnrichmentOrchestrator([plugin]).run(
        [_lead(indigo_status="company_match")],
        run_id="run-indigo",
        collected_at=NOW,
    )

    lead = result.leads[0]
    assert lead.coverage.status == CoverageResolutionStatus.PARTIAL
    assert lead.coverage.reason_code == "INDIGO_MATCH_MANUAL_REVIEW"
    assert lead.manual_search_urls


def test_orchestrator_converts_plugin_exception_to_safe_failure() -> None:
    class BrokenPlugin(_PersonalContactPlugin):
        def execute(self, _context) -> SourceResult:
            self.calls += 1
            raise RuntimeError("secret details")

    result = EnrichmentOrchestrator([BrokenPlugin()]).run(
        [_lead()],
        run_id="run-failed",
        collected_at=NOW,
    )

    source_result = result.leads[0].source_results[0]
    assert source_result.outcome == SourceOutcome.FAILED
    assert source_result.reason_code == "PLUGIN_EXECUTION_FAILED"
    assert "secret" not in source_result.reason_message
