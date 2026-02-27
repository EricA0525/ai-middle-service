from __future__ import annotations

"""报告任务 SQLite 存储。"""

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from ..config import settings
from ..logging_config import get_logger

logger = get_logger(__name__)


def _now_iso() -> str:
    return datetime.now().isoformat()


def _to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _from_json(value: Optional[str], default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


class JobStore:
    """任务存储（SQLite）。"""

    def __init__(self, db_path: Optional[Path] = None):
        configured = getattr(settings, "job_db_path", "")
        default_path = settings.output_path / ".jobs" / "report_jobs.db"
        self.db_path = Path(configured).resolve() if configured else default_path
        if db_path is not None:
            self.db_path = Path(db_path).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            str(self.db_path), check_same_thread=False, timeout=5.0
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.execute("PRAGMA busy_timeout=5000;")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    report_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    input_json TEXT NOT NULL,
                    error_code TEXT,
                    error_message TEXT,
                    current_stage TEXT,
                    progress_json TEXT,
                    result_json TEXT
                );

                CREATE TABLE IF NOT EXISTS job_sections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    section_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    attempt INTEGER DEFAULT 1,
                    status TEXT NOT NULL,
                    metrics_json TEXT,
                    error_code TEXT,
                    latency_ms INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES jobs(job_id)
                );

                CREATE INDEX IF NOT EXISTS idx_job_sections_job_id
                ON job_sections(job_id);

                CREATE TABLE IF NOT EXISTS job_artifacts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    artifact_type TEXT NOT NULL,
                    section_id TEXT,
                    content_json_or_html TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES jobs(job_id)
                );

                CREATE INDEX IF NOT EXISTS idx_job_artifacts_job_id
                ON job_artifacts(job_id);

                CREATE TABLE IF NOT EXISTS job_idempotency (
                    idempotency_key TEXT PRIMARY KEY,
                    payload_hash TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_job_idempotency_expires_at
                ON job_idempotency(expires_at);
                """
            )
            # 兼容历史表结构
            self._migrate_idempotency_key(conn)
            self._migrate_job_idempotency_table(conn)


    @staticmethod
    def _migrate_idempotency_key(conn: sqlite3.Connection) -> None:
        """安全添加 jobs.idempotency_key 列，并移除历史唯一索引。"""
        try:
            cols = [row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()]
            if "idempotency_key" not in cols:
                conn.execute("ALTER TABLE jobs ADD COLUMN idempotency_key TEXT")
                logger.info("db_migration", action="added idempotency_key column")
            conn.execute("DROP INDEX IF EXISTS idx_jobs_idempotency_key")
        except Exception as exc:
            logger.warning("db_migration_skip", error=str(exc))

    @staticmethod
    def _migrate_job_idempotency_table(conn: sqlite3.Connection) -> None:
        """
        兼容旧版 job_idempotency 表结构。

        旧版本若对 job_id 增加外键约束，会阻塞「先 claim 后建 job」流程。
        """
        try:
            foreign_keys = conn.execute("PRAGMA foreign_key_list(job_idempotency)").fetchall()
            if foreign_keys:
                conn.execute("DROP TABLE IF EXISTS job_idempotency")
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS job_idempotency (
                        idempotency_key TEXT PRIMARY KEY,
                        payload_hash TEXT NOT NULL,
                        job_id TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        expires_at TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_job_idempotency_expires_at ON job_idempotency(expires_at)"
                )
                logger.info("db_migration", action="recreated job_idempotency table without foreign key")
        except Exception as exc:
            logger.warning("db_migration_skip", table="job_idempotency", error=str(exc))

    def claim_idempotency(
        self,
        idempotency_key: str,
        payload_hash: str,
        job_id: str,
    ) -> dict[str, str]:
        """
        申请幂等键。

        Returns:
            {"status": "claimed"|"replay"|"conflict", "job_id": "..."}
        """
        now = datetime.now()
        created_at = now.isoformat()
        expires_at = (now + timedelta(seconds=max(1, int(settings.idempotency_ttl_seconds)))).isoformat()

        with self._connect() as conn:
            conn.execute("DELETE FROM job_idempotency WHERE expires_at <= ?", (created_at,))
            try:
                conn.execute(
                    """
                    INSERT INTO job_idempotency (
                        idempotency_key, payload_hash, job_id, created_at, expires_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (idempotency_key, payload_hash, job_id, created_at, expires_at),
                )
                return {"status": "claimed", "job_id": job_id}
            except sqlite3.IntegrityError:
                row = conn.execute(
                    """
                    SELECT idempotency_key, payload_hash, job_id
                    FROM job_idempotency
                    WHERE idempotency_key = ?
                    """,
                    (idempotency_key,),
                ).fetchone()
                if row is None:
                    return {"status": "claimed", "job_id": job_id}

                existing_job_id = str(row["job_id"])
                exists = conn.execute(
                    "SELECT 1 FROM jobs WHERE job_id = ? LIMIT 1",
                    (existing_job_id,),
                ).fetchone()
                if exists is None:
                    conn.execute("DELETE FROM job_idempotency WHERE idempotency_key = ?", (idempotency_key,))
                    conn.execute(
                        """
                        INSERT INTO job_idempotency (
                            idempotency_key, payload_hash, job_id, created_at, expires_at
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (idempotency_key, payload_hash, job_id, created_at, expires_at),
                    )
                    return {"status": "claimed", "job_id": job_id}

                if str(row["payload_hash"]) == payload_hash:
                    return {"status": "replay", "job_id": existing_job_id}
                return {"status": "conflict", "job_id": existing_job_id}

    def release_idempotency(self, idempotency_key: str, job_id: Optional[str] = None) -> None:
        """释放幂等键占位（在任务创建失败时调用）。"""
        with self._connect() as conn:
            if job_id:
                conn.execute(
                    "DELETE FROM job_idempotency WHERE idempotency_key = ? AND job_id = ?",
                    (idempotency_key, job_id),
                )
            else:
                conn.execute(
                    "DELETE FROM job_idempotency WHERE idempotency_key = ?",
                    (idempotency_key,),
                )

    def recover_stale_running_jobs(self) -> int:
        """将进程重启前遗留的 queued/running 任务标记为 failed。"""
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE jobs
                SET status = ?,
                    finished_at = ?,
                    current_stage = ?,
                    error_code = ?,
                    error_message = ?
                WHERE status IN ('queued', 'running')
                """,
                (
                    'failed',
                    _now_iso(),
                    'failed',
                    'orchestrator_restarted',
                    '服务重启导致任务中断，请重新提交生成任务',
                ),
            )
            return int(cursor.rowcount or 0)

    def create_job(
        self,
        job_id: str,
        report_type: str,
        input_json: dict[str, Any],
        idempotency_key: Optional[str] = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs (
                    job_id, report_type, status, created_at, input_json,
                    current_stage, progress_json, idempotency_key
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    report_type,
                    "queued",
                    _now_iso(),
                    _to_json(input_json),
                    "queued",
                    _to_json({"stage": "queued", "completed_sections": 0, "total_sections": 0}),
                    idempotency_key,
                ),
            )
        logger.info("job_created", job_id=job_id, idempotency_key=idempotency_key or "none")

    def find_by_idempotency_key(self, key: str) -> Optional[dict[str, Any]]:
        """兼容查询：通过 job_idempotency 映射查找任务。"""
        now = _now_iso()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT j.*
                FROM job_idempotency i
                JOIN jobs j ON j.job_id = i.job_id
                WHERE i.idempotency_key = ? AND i.expires_at > ?
                """,
                (key, now),
            ).fetchone()
            if row is None:
                return None
            return self._row_to_dict(row)

    def cleanup_old_jobs(self, days: int = 30) -> int:
        """清理 N 天前已完成的任务及其关联数据。"""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        with self._connect() as conn:
            # 先获取待删除的 job_id 列表
            rows = conn.execute(
                "SELECT job_id FROM jobs WHERE status IN ('succeeded','failed','cancelled','failed_quality_gate') AND finished_at < ?",
                (cutoff,),
            ).fetchall()
            if not rows:
                return 0
            job_ids = [r["job_id"] for r in rows]
            placeholders = ",".join("?" * len(job_ids))
            conn.execute(f"DELETE FROM job_sections WHERE job_id IN ({placeholders})", job_ids)
            conn.execute(f"DELETE FROM job_artifacts WHERE job_id IN ({placeholders})", job_ids)
            conn.execute(f"DELETE FROM job_idempotency WHERE job_id IN ({placeholders})", job_ids)
            conn.execute(f"DELETE FROM jobs WHERE job_id IN ({placeholders})", job_ids)
            conn.execute("DELETE FROM job_idempotency WHERE expires_at <= ?", (_now_iso(),))
            logger.info("jobs_cleaned_up", count=len(job_ids), cutoff=cutoff)
            return len(job_ids)

    def update_stage(self, job_id: str, stage: str, progress: Optional[dict[str, Any]] = None) -> None:
        payload = _to_json(progress) if progress is not None else None
        with self._connect() as conn:
            if payload is not None:
                conn.execute(
                    "UPDATE jobs SET current_stage = ?, progress_json = ? WHERE job_id = ?",
                    (stage, payload, job_id),
                )
            else:
                conn.execute(
                    "UPDATE jobs SET current_stage = ? WHERE job_id = ?",
                    (stage, job_id),
                )

    def mark_running(self, job_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET status = ?, started_at = COALESCE(started_at, ?), current_stage = ?
                WHERE job_id = ?
                """,
                ("running", _now_iso(), "running", job_id),
            )

    def mark_succeeded(self, job_id: str, result_json: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET status = ?, finished_at = ?, current_stage = ?, result_json = ?, error_code = NULL, error_message = NULL
                WHERE job_id = ?
                """,
                ("succeeded", _now_iso(), "completed", _to_json(result_json), job_id),
            )

    def mark_failed(
        self,
        job_id: str,
        error_code: str,
        error_message: str,
        status: str = "failed",
        current_stage: str = "failed",
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET status = ?, finished_at = ?, current_stage = ?, error_code = ?, error_message = ?
                WHERE job_id = ?
                """,
                (status, _now_iso(), current_stage, error_code, error_message, job_id),
            )

    def cancel_job(self, job_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE jobs
                SET status = ?, finished_at = ?, current_stage = ?, error_code = ?, error_message = ?
                WHERE job_id = ? AND status IN ('queued', 'running')
                """,
                (
                    "cancelled",
                    _now_iso(),
                    "cancelled",
                    "cancelled",
                    "Job cancelled by user",
                    job_id,
                ),
            )
            return cursor.rowcount > 0

    def append_section_log(
        self,
        job_id: str,
        section_id: str,
        stage: str,
        attempt: int,
        status: str,
        metrics: Optional[dict[str, Any]] = None,
        error_code: Optional[str] = None,
        latency_ms: int = 0,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO job_sections (
                    job_id, section_id, stage, attempt, status, metrics_json, error_code, latency_ms, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    section_id,
                    stage,
                    int(attempt),
                    status,
                    _to_json(metrics or {}),
                    error_code,
                    int(latency_ms),
                    _now_iso(),
                ),
            )

    def save_artifact(
        self,
        job_id: str,
        artifact_type: str,
        content: str,
        section_id: Optional[str] = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO job_artifacts (
                    job_id, artifact_type, section_id, content_json_or_html, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (job_id, artifact_type, section_id, content, _now_iso()),
            )

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "job_id": row["job_id"],
            "report_type": row["report_type"],
            "status": row["status"],
            "created_at": row["created_at"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "input": _from_json(row["input_json"], {}),
            "error_code": row["error_code"],
            "error_message": row["error_message"],
            "current_stage": row["current_stage"],
            "progress": _from_json(row["progress_json"], {}),
            "result": _from_json(row["result_json"], None),
        }

    def get_job(self, job_id: str) -> Optional[dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            if row is None:
                return None
            return self._row_to_dict(row)

    def get_result(self, job_id: str) -> Optional[dict[str, Any]]:
        row = self.get_job(job_id)
        if row is None:
            return None
        result = row.get("result")
        return result if isinstance(result, dict) else None

    def list_section_logs(self, job_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT section_id, stage, attempt, status, metrics_json, error_code, latency_ms, created_at
                FROM job_sections
                WHERE job_id = ?
                ORDER BY id ASC
                """,
                (job_id,),
            ).fetchall()
        return [
            {
                "section_id": row["section_id"],
                "stage": row["stage"],
                "attempt": row["attempt"],
                "status": row["status"],
                "metrics": _from_json(row["metrics_json"], {}),
                "error_code": row["error_code"],
                "latency_ms": row["latency_ms"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def list_artifacts(self, job_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT artifact_type, section_id, content_json_or_html, created_at
                FROM job_artifacts
                WHERE job_id = ?
                ORDER BY id ASC
                """,
                (job_id,),
            ).fetchall()
        return [
            {
                "artifact_type": row["artifact_type"],
                "section_id": row["section_id"],
                "content": row["content_json_or_html"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]


_job_store: Optional[JobStore] = None


def get_job_store() -> JobStore:
    global _job_store
    if _job_store is None:
        _job_store = JobStore()
    return _job_store
