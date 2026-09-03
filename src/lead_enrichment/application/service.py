from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from lead_enrichment.engine import EnrichmentOrchestrator, create_inn_leads
from lead_enrichment.infrastructure import CheckpointRegistry
from lead_enrichment.infrastructure.excel import (
    export_batch_enrichment_workbook,
    read_kontur_workbook,
)
from lead_enrichment.infrastructure.http import HttpClient
from lead_enrichment.models import BatchEnrichmentResult, ContactRole, KonturImportResult
from lead_enrichment.sources import SiteCrawlPlugin

StatusCallback = Callable[[str], None]
ProgressCallback = Callable[[int, int], None]
CancelCheck = Callable[[], bool]


@dataclass(frozen=True, slots=True)
class PipelineRunRequest:
    kontur_file: Path
    output_file: Path
    checkpoint_file: Path
    target_roles: tuple[ContactRole, ...] = (
        ContactRole.MARKETING,
        ContactRole.SALES,
    )


@dataclass(frozen=True, slots=True)
class InputInspection:
    total_rows: int
    imported_companies: int
    skipped_rows: int
    invalid_inn_rows: int
    duplicate_inn_rows: int
    legal_entities: int
    individual_entrepreneurs: int
    rows_with_website: int
    rows_with_manager: int
    rows_with_phones: int
    rows_with_emails: int


def inspect_kontur_input(kontur_file: Path) -> InputInspection:
    imported = read_kontur_workbook(kontur_file)
    return _inspection(imported)


def run_kontur_pipeline(
    request: PipelineRunRequest,
    *,
    status_callback: StatusCallback | None = None,
    progress_callback: ProgressCallback | None = None,
    should_cancel: CancelCheck | None = None,
) -> BatchEnrichmentResult:
    _validate_request(request)
    _status(status_callback, "Читаю выгрузку Контур и проверяю ИНН")
    imported = read_kontur_workbook(request.kontur_file)
    if not imported.companies:
        raise ValueError("В выгрузке Контур нет строк с валидным ИНН")

    _status(status_callback, "Подготавливаю компании и идентифицирую их по ИНН")
    leads = create_inn_leads(imported)
    registry = CheckpointRegistry(request.checkpoint_file)
    _status(status_callback, "Запускаю поиск контактов на официальных сайтах")
    with HttpClient() as http_client:
        orchestrator = EnrichmentOrchestrator(
            [SiteCrawlPlugin(http_client)],
            checkpoint_registry=registry,
        )
        batch = orchestrator.run(
            leads,
            run_id=_run_id(imported.summary.source_sha256),
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


def _inspection(imported: KonturImportResult) -> InputInspection:
    summary = imported.summary
    invalid_inn_rows = sum(issue.code == "INVALID_INN" for issue in summary.issues)
    return InputInspection(
        total_rows=summary.total_rows,
        imported_companies=summary.imported_rows,
        skipped_rows=summary.skipped_rows,
        invalid_inn_rows=invalid_inn_rows,
        duplicate_inn_rows=summary.duplicate_inn_rows,
        legal_entities=summary.legal_entities,
        individual_entrepreneurs=summary.individual_entrepreneurs,
        rows_with_website=summary.rows_with_website,
        rows_with_manager=summary.rows_with_initial_person,
        rows_with_phones=summary.rows_with_phones,
        rows_with_emails=summary.rows_with_emails,
    )


def _validate_request(request: PipelineRunRequest) -> None:
    if request.kontur_file.resolve() == request.output_file.resolve():
        raise ValueError("Итоговый файл не может перезаписывать выгрузку Контур")
    if not request.target_roles:
        raise ValueError("Нужно выбрать хотя бы одну целевую роль")


def _run_id(kontur_hash: str) -> str:
    return f"kontur-{kontur_hash[:24]}"


def _status(callback: StatusCallback | None, message: str) -> None:
    if callback is not None:
        callback(message)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
