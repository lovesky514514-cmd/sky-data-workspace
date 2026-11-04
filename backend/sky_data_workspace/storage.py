import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


class RuntimeStore:
    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "sky_data.sqlite3"
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in {0, 1, 2}:
                raise RuntimeError("数据库版本高于当前程序，拒绝覆盖")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS ai_runs (
                    run_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, operation TEXT NOT NULL,
                    model TEXT, status TEXT NOT NULL, error_code TEXT,
                    trace_json TEXT NOT NULL, metrics_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS extracted_records (
                    record_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES ai_runs(run_id),
                    field_name TEXT NOT NULL, source_id TEXT NOT NULL, document_hash TEXT NOT NULL,
                    validation_status TEXT NOT NULL, review_status TEXT NOT NULL, payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_records_source ON extracted_records(source_id);
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY, name TEXT NOT NULL, urls_json TEXT NOT NULL,
                    fields_json TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL, last_run_at TEXT, next_run_at TEXT,
                    interval_seconds INTEGER, generation INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS task_sources (
                    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
                    source_url TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
                    content_hash TEXT, error TEXT, warnings_json TEXT NOT NULL DEFAULT '[]',
                    PRIMARY KEY(task_id,source_url)
                );
                CREATE TABLE IF NOT EXISTS task_records (
                    record_id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
                    source_url TEXT NOT NULL, retrieved_at TEXT NOT NULL, content_hash TEXT NOT NULL,
                    evidence_locator TEXT NOT NULL, raw_reference TEXT NOT NULL,
                    data_json TEXT NOT NULL, review_status TEXT NOT NULL DEFAULT 'pending'
                );
                CREATE INDEX IF NOT EXISTS idx_task_records ON task_records(task_id);
                CREATE TABLE IF NOT EXISTS task_logs (
                    log_id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL, level TEXT NOT NULL, message TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS exports (
                    export_id TEXT PRIMARY KEY, filename TEXT NOT NULL, created_at TEXT NOT NULL
                );
                PRAGMA user_version=2;
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA busy_timeout=10000")
            with db:
                yield db
        finally:
            db.close()

    def record_run(self, operation: str, *, model: str | None, status: str,
                   trace: list, timings: list, error_code: str | None = None,
                   records: list[dict] | None = None) -> str:
        run_id = str(uuid.uuid4())
        with self.connect() as db:
            db.execute("INSERT INTO ai_runs VALUES (?,?,?,?,?,?,?,?)", (
                run_id, datetime.now(timezone.utc).isoformat(), operation, model, status,
                error_code, json.dumps(trace, ensure_ascii=False), json.dumps(timings),
            ))
            for record in records or []:
                db.execute("INSERT INTO extracted_records VALUES (?,?,?,?,?,?,?,?)", (
                    str(uuid.uuid4()), run_id, record["field_name"], record["source_id"],
                    record["document_hash"], record["validation_status"], record["review_status"],
                    json.dumps(record, ensure_ascii=False),
                ))
        return run_id

    def summary(self) -> dict:
        with self.connect() as db:
            return {"runs": db.execute("SELECT count(*) FROM ai_runs").fetchone()[0],
                    "records": db.execute("SELECT count(*) FROM extracted_records").fetchone()[0]}
