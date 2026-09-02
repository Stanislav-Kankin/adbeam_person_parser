from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

from lead_enrichment.models import SourceResult


class CheckpointRegistry:
    def __init__(self, database_path: Path) -> None:
        self.path = Path(database_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def get_source_result(
        self,
        *,
        run_id: str,
        company_key: str,
        source_id: str,
        source_version: str,
        config_hash: str,
    ) -> SourceResult | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT payload_json
                FROM source_checkpoints
                WHERE run_id = ? AND company_key = ? AND source_id = ?
                  AND source_version = ? AND config_hash = ?
                """,
                (run_id, company_key, source_id, source_version, config_hash),
            ).fetchone()
        return SourceResult.model_validate_json(row[0]) if row else None

    def save_source_result(
        self,
        *,
        run_id: str,
        company_key: str,
        config_hash: str,
        result: SourceResult,
    ) -> None:
        completed_at = datetime.now(timezone.utc).isoformat()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO source_checkpoints (
                    run_id, company_key, source_id, source_version, config_hash,
                    outcome, payload_json, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (
                    run_id, company_key, source_id, source_version, config_hash
                ) DO UPDATE SET
                    outcome = excluded.outcome,
                    payload_json = excluded.payload_json,
                    completed_at = excluded.completed_at
                """,
                (
                    run_id,
                    company_key,
                    result.source_id,
                    result.source_version,
                    config_hash,
                    result.outcome.value,
                    result.model_dump_json(),
                    completed_at,
                ),
            )

    def delete_company(self, company_key: str) -> int:
        with self._connection() as connection:
            cursor = connection.execute(
                "DELETE FROM source_checkpoints WHERE company_key = ?",
                (company_key,),
            )
            return max(cursor.rowcount, 0)

    def clear_run(self, run_id: str) -> int:
        with self._connection() as connection:
            cursor = connection.execute(
                "DELETE FROM source_checkpoints WHERE run_id = ?",
                (run_id,),
            )
            return max(cursor.rowcount, 0)

    def count(self) -> int:
        with self._connection() as connection:
            row = connection.execute("SELECT COUNT(*) FROM source_checkpoints").fetchone()
        return int(row[0])

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS source_checkpoints (
                    run_id TEXT NOT NULL,
                    company_key TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    source_version TEXT NOT NULL,
                    config_hash TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    completed_at TEXT NOT NULL,
                    PRIMARY KEY (
                        run_id, company_key, source_id, source_version, config_hash
                    )
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_source_checkpoints_company
                ON source_checkpoints (company_key)
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()
