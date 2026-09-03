from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Callable, Iterable
from datetime import datetime
from urllib.parse import urlencode

from lead_enrichment.engine.contracts import SourcePlugin
from lead_enrichment.engine.lead_preparation import (
    DEFAULT_TARGET_ROLES,
    apply_source_result,
    evaluate_contact_coverage,
    prepare_pipeline_company,
)
from lead_enrichment.infrastructure.checkpoint import CheckpointRegistry
from lead_enrichment.models import (
    BatchEnrichmentResult,
    BatchEnrichmentSummary,
    CompanyInput,
    ContactCoverage,
    ContactRole,
    CoverageResolutionStatus,
    EnrichedLeadResult,
    IdentityResolutionStatus,
    MergedLead,
    PipelineContext,
    PipelineStepRecord,
    SourceOutcome,
    SourceResult,
)


class EnrichmentOrchestrator:
    def __init__(
        self,
        plugins: Iterable[SourcePlugin],
        *,
        checkpoint_registry: CheckpointRegistry | None = None,
        minimum_confidence: int = 70,
    ) -> None:
        self._plugins = list(plugins)
        self._checkpoints = checkpoint_registry
        self._minimum_confidence = minimum_confidence

    def run(
        self,
        leads: Iterable[MergedLead],
        *,
        run_id: str,
        collected_at: datetime,
        target_roles: Iterable[ContactRole] = DEFAULT_TARGET_ROLES,
        config_hash: str | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> BatchEnrichmentResult:
        if collected_at.tzinfo is None or collected_at.utcoffset() is None:
            raise ValueError("collected_at must be timezone-aware")
        targets = list(dict.fromkeys(target_roles))
        effective_config_hash = config_hash or _config_hash(
            targets,
            self._minimum_confidence,
        )
        lead_list = list(leads)
        results: list[EnrichedLeadResult] = []
        checkpoint_hits = 0
        source_executions = 0
        cancelled = False

        for lead in lead_list:
            if should_cancel is not None and should_cancel():
                cancelled = True
                break
            company = prepare_pipeline_company(lead)
            coverage = self._coverage(company, lead, targets)
            source_results: list[SourceResult] = []
            steps: list[PipelineStepRecord] = []

            if coverage.status != CoverageResolutionStatus.RESOLVED:
                for plugin in self._plugins:
                    metadata = plugin.metadata
                    cached = self._cached_result(
                        run_id=run_id,
                        company_key=company.company_key,
                        source_id=metadata.source_id,
                        source_version=metadata.version,
                        config_hash=effective_config_hash,
                    )
                    from_checkpoint = cached is not None
                    if cached is not None:
                        source_result = cached
                        checkpoint_hits += 1
                    else:
                        source_result = self._execute_plugin(
                            plugin,
                            run_id=run_id,
                            company=company,
                            collected_at=collected_at,
                            target_roles=targets,
                        )
                        source_executions += 1
                        if (
                            self._checkpoints is not None
                            and source_result.outcome != SourceOutcome.FAILED
                        ):
                            self._checkpoints.save_source_result(
                                run_id=run_id,
                                company_key=company.company_key,
                                config_hash=effective_config_hash,
                                result=source_result,
                            )

                    source_results.append(source_result)
                    steps.append(
                        PipelineStepRecord(
                            company_key=company.company_key,
                            source_id=source_result.source_id,
                            source_version=source_result.source_version,
                            outcome=source_result.outcome,
                            reason_code=source_result.reason_code,
                            reason_message=source_result.reason_message,
                            from_checkpoint=from_checkpoint,
                            duration_ms=source_result.metrics.duration_ms,
                        )
                    )
                    company = apply_source_result(company, source_result)
                    coverage = self._coverage(company, lead, targets)
                    if coverage.status == CoverageResolutionStatus.RESOLVED:
                        break

            manual_urls = (
                []
                if coverage.status == CoverageResolutionStatus.RESOLVED
                else _manual_search_urls(company, coverage.missing_roles or targets)
            )
            results.append(
                EnrichedLeadResult(
                    lead=lead,
                    company=company,
                    coverage=coverage,
                    source_results=source_results,
                    steps=steps,
                    manual_search_urls=manual_urls,
                )
            )
            if progress_callback is not None:
                progress_callback(len(results), len(lead_list))

        status_counts = Counter(result.coverage.status for result in results)
        return BatchEnrichmentResult(
            run_id=run_id,
            target_roles=targets,
            cancelled=cancelled,
            summary=BatchEnrichmentSummary(
                total_companies=len(results),
                resolved=status_counts[CoverageResolutionStatus.RESOLVED],
                partial=status_counts[CoverageResolutionStatus.PARTIAL],
                manual_required=status_counts[CoverageResolutionStatus.MANUAL_REQUIRED],
                checkpoint_hits=checkpoint_hits,
                source_executions=source_executions,
            ),
            leads=results,
        )

    def _coverage(
        self,
        company,
        lead: MergedLead,
        target_roles: list[ContactRole],
    ) -> ContactCoverage:
        coverage = evaluate_contact_coverage(
            company,
            target_roles=target_roles,
            minimum_confidence=self._minimum_confidence,
        )
        if lead.identity.status == IdentityResolutionStatus.AMBIGUOUS:
            return coverage.model_copy(
                update={
                    "status": CoverageResolutionStatus.PARTIAL,
                    "reason_code": "IDENTITY_AMBIGUOUS",
                    "reason_message": (
                        "Контакты найдены, но связь бренда с юрлицом неоднозначна; "
                        "требуется ручная проверка"
                    ),
                }
            )
        indigo_status = (
            (lead.assessment.indigo_match_status or "").casefold()
            if lead.assessment is not None
            else ""
        )
        if indigo_status and indigo_status != "no_match":
            return coverage.model_copy(
                update={
                    "status": CoverageResolutionStatus.PARTIAL,
                    "reason_code": "INDIGO_MATCH_MANUAL_REVIEW",
                    "reason_message": (
                        "Есть совпадение с Indigo; перед outreach требуется сверка с CRM"
                    ),
                }
            )
        return coverage

    def _cached_result(
        self,
        *,
        run_id: str,
        company_key: str,
        source_id: str,
        source_version: str,
        config_hash: str,
    ) -> SourceResult | None:
        if self._checkpoints is None:
            return None
        return self._checkpoints.get_source_result(
            run_id=run_id,
            company_key=company_key,
            source_id=source_id,
            source_version=source_version,
            config_hash=config_hash,
        )

    @staticmethod
    def _execute_plugin(
        plugin: SourcePlugin,
        *,
        run_id: str,
        company,
        collected_at: datetime,
        target_roles: list[ContactRole],
    ) -> SourceResult:
        metadata = plugin.metadata
        context = PipelineContext(
            run_id=run_id,
            company=company,
            collected_at=collected_at,
            target_roles=target_roles,
        )
        try:
            applicability = plugin.is_applicable(context)
            if not applicability.applicable:
                return SourceResult(
                    source_id=metadata.source_id,
                    source_version=metadata.version,
                    outcome=SourceOutcome.SKIPPED,
                    reason_code=applicability.reason_code,
                    reason_message=applicability.reason_message,
                    continue_reason="Источник неприменим; нужен следующий этап",
                )
            result = plugin.execute(context)
            if result.source_id != metadata.source_id or result.source_version != metadata.version:
                return _failed_result(
                    metadata.source_id,
                    metadata.version,
                    "PLUGIN_CONTRACT_VIOLATION",
                    "Плагин вернул результат с несовпадающим идентификатором или версией",
                )
            return result
        except Exception:
            return _failed_result(
                metadata.source_id,
                metadata.version,
                "PLUGIN_EXECUTION_FAILED",
                "Источник завершился внутренней ошибкой без сохранения чувствительных деталей",
            )


def _failed_result(
    source_id: str,
    source_version: str,
    reason_code: str,
    reason_message: str,
) -> SourceResult:
    return SourceResult(
        source_id=source_id,
        source_version=source_version,
        outcome=SourceOutcome.FAILED,
        reason_code=reason_code,
        reason_message=reason_message,
        continue_reason="Нужен следующий источник или ручная проверка",
    )


def _config_hash(target_roles: list[ContactRole], minimum_confidence: int) -> str:
    value = "|".join([*(role.value for role in target_roles), str(minimum_confidence)])
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _manual_search_urls(
    company: CompanyInput,
    roles: Iterable[ContactRole],
) -> list[str]:
    role_labels = {
        ContactRole.MARKETING: "директор по маркетингу",
        ContactRole.SALES: "коммерческий директор директор по продажам",
        ContactRole.OWNER: "собственник учредитель",
        ContactRole.LEADER: "генеральный директор",
        ContactRole.PROCUREMENT: "директор по закупкам",
        ContactRole.UNKNOWN: "руководитель",
    }
    company_name = company.brand_name or company.legal_name or company.inn
    urls: list[str] = []
    for role in dict.fromkeys(roles):
        query = f'"{company_name}" {role_labels[role]}'
        urls.append(f"https://yandex.ru/search/?{urlencode({'text': query})}")
        urls.append(f"https://www.google.com/search?{urlencode({'q': query})}")
    return urls
