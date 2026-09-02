from pathlib import Path

from lead_enrichment.infrastructure import CheckpointRegistry
from lead_enrichment.models import SourceOutcome, SourceResult


def test_checkpoint_roundtrip_clear_and_erasure(tmp_path: Path) -> None:
    registry = CheckpointRegistry(tmp_path / "state" / "checkpoints.sqlite3")
    result = SourceResult(
        source_id="test_source",
        source_version="1.0.0",
        outcome=SourceOutcome.NOT_FOUND,
        reason_code="NOT_FOUND",
        reason_message="Ничего не найдено",
    )

    registry.save_source_result(
        run_id="run-1",
        company_key="company-1",
        config_hash="config",
        result=result,
    )

    restored = registry.get_source_result(
        run_id="run-1",
        company_key="company-1",
        source_id="test_source",
        source_version="1.0.0",
        config_hash="config",
    )
    assert restored == result
    assert registry.count() == 1
    assert registry.delete_company("company-1") == 1
    assert registry.count() == 0

    registry.save_source_result(
        run_id="run-2",
        company_key="company-2",
        config_hash="config",
        result=result,
    )
    assert registry.clear_run("run-2") == 1
    assert registry.count() == 0
