from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from lead_enrichment.engine import EnrichmentOrchestrator, merge_assessment_with_kontur
from lead_enrichment.infrastructure import CheckpointRegistry
from lead_enrichment.infrastructure.excel import (
    export_batch_enrichment_workbook,
    read_assessment_workbook,
    read_kontur_workbook,
)
from lead_enrichment.infrastructure.http import HttpClient
from lead_enrichment.models import (
    BatchEnrichmentResult,
    ContactRole,
    KonturImportResult,
    KonturImportSummary,
)
from lead_enrichment.sources import SiteCrawlPlugin

StatusCallback = Callable[[str], None]
ProgressCallback = Callable[[int, int], None]
CancelCheck = Callable[[], bool]


@dataclass(frozen=True, slots=True)
class PipelineRunRequest:
    assessment_file: Path
    output_file: Path
    checkpoint_file: Path
    kontur_file: Path | None = None
    target_roles: tuple[ContactRole, ...] = (
        ContactRole.MARKETING,
        ContactRole.SALES,
    )


@dataclass(frozen=True, slots=True)
class InputInspection:
    assessment_rows: int
    rows_with_website: int
    primary_contacts: int
    alternative_contacts: int
    indigo_matches: int
    tier_counts: dict[str, int]
    kontur_rows: int
    matched_rows: int
    ambiguous_rows: int
    not_found_rows: int


def inspect_inputs(
    assessment_file: Path,
    kontur_file: Path | None = None,
) -> InputInspection:
    assessment = read_assessment_workbook(assessment_file)
    kontur = read_kontur_workbook(kontur_file) if kontur_file else _empty_kontur_result()
    merge = merge_assessment_with_kontur(assessment, kontur)
    return InputInspection(
        assessment_rows=assessment.summary.imported_rows,
        rows_with_website=assessment.summary.rows_with_website,
        primary_contacts=assessment.summary.primary_contacts,
        alternative_contacts=assessment.summary.alternative_contacts,
        indigo_matches=assessment.summary.indigo_matches,
        tier_counts=assessment.summary.tier_counts,
        kontur_rows=kontur.summary.imported_rows,
        matched_rows=merge.summary.matched_rows,
        ambiguous_rows=merge.summary.ambiguous_rows,
        not_found_rows=merge.summary.not_found_rows,
    )


def run_assessment_pipeline(
    request: PipelineRunRequest,
    *,
    status_callback: StatusCallback | None = None,
    progress_callback: ProgressCallback | None = None,
    should_cancel: CancelCheck | None = None,
) -> BatchEnrichmentResult:
    _validate_request(request)
    _status(status_callback, "Читаю клиентский assessment")
    assessment = read_assessment_workbook(request.assessment_file)
    if request.kontur_file:
        _status(status_callback, "Читаю выгрузку Контур")
        kontur = read_kontur_workbook(request.kontur_file)
    else:
        kontur = _empty_kontur_result()

    _status(status_callback, "Сопоставляю бренды и юридические лица")
    merge = merge_assessment_with_kontur(assessment, kontur)
    run_id = _run_id(
        assessment.summary.source_sha256,
        kontur.summary.source_sha256,
    )
    registry = CheckpointRegistry(request.checkpoint_file)

    _status(status_callback, "Запускаю поиск контактов на официальных сайтах")
    with HttpClient() as http_client:
        orchestrator = EnrichmentOrchestrator(
            [SiteCrawlPlugin(http_client)],
            checkpoint_registry=registry,
        )
        batch = orchestrator.run(
            merge.leads,
            run_id=run_id,
            collected_at=_utc_now(),
            target_roles=request.target_roles,
            progress_callback=progress_callback,
            should_cancel=should_cancel,
        )

    _status(status_callback, "Формирую итоговый Excel")
    export_batch_enrichment_workbook(batch, request.output_file)
    _status(
        status_callback,
        "Обработка отменена; частичный результат сохранён"
        if batch.cancelled
        else "Готово",
    )
    return batch


def _validate_request(request: PipelineRunRequest) -> None:
    assessment = request.assessment_file.resolve()
    output = request.output_file.resolve()
    if assessment == output:
        raise ValueError("Итоговый файл не может перезаписывать assessment")
    if request.kontur_file and request.kontur_file.resolve() == output:
        raise ValueError("Итоговый файл не может перезаписывать выгрузку Контур")
    if not request.target_roles:
        raise ValueError("Нужно выбрать хотя бы одну целевую роль")


def _empty_kontur_result() -> KonturImportResult:
    return KonturImportResult(
        summary=KonturImportSummary(
            source_file_name="",
            source_sha256="0" * 64,
            sheet_name="",
            total_rows=0,
            imported_rows=0,
            skipped_rows=0,
            blank_rows=0,
            duplicate_inn_rows=0,
            legal_entities=0,
            individual_entrepreneurs=0,
            rows_with_initial_person=0,
            rows_with_phones=0,
            rows_with_emails=0,
            rows_with_website=0,
        )
    )


def _run_id(assessment_hash: str, kontur_hash: str) -> str:
    digest = hashlib.sha256(f"{assessment_hash}:{kontur_hash}".encode("ascii")).hexdigest()
    return f"assessment-{digest[:24]}"


def _status(callback: StatusCallback | None, message: str) -> None:
    if callback is not None:
        callback(message)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
