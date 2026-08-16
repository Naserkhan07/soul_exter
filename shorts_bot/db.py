from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

from .models import Job, JobStatus

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    source_url TEXT NOT NULL,
    status TEXT NOT NULL,
    progress_message TEXT NOT NULL DEFAULT '',
    source_title TEXT,
    short_title TEXT,
    short_description TEXT,
    output_path TEXT,
    youtube_video_id TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_user_created ON jobs(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
"""


class JobRepository:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat(timespec="seconds")

    @staticmethod
    def _from_row(row: sqlite3.Row) -> Job:
        return Job(
            id=row["id"],
            chat_id=row["chat_id"],
            user_id=row["user_id"],
            source_url=row["source_url"],
            status=JobStatus(row["status"]),
            progress_message=row["progress_message"],
            source_title=row["source_title"],
            short_title=row["short_title"],
            short_description=row["short_description"],
            output_path=row["output_path"],
            youtube_video_id=row["youtube_video_id"],
            error=row["error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def create(self, chat_id: int, user_id: int, source_url: str) -> Job:
        job_id = uuid.uuid4().hex[:12]
        now = self._now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO jobs (
                    id, chat_id, user_id, source_url, status, progress_message,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    chat_id,
                    user_id,
                    source_url,
                    JobStatus.QUEUED.value,
                    "Waiting in queue",
                    now,
                    now,
                ),
            )
        job = self.get(job_id)
        assert job is not None
        return job

    def get(self, job_id: str) -> Job | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return self._from_row(row) if row else None

    def update(self, job_id: str, **fields: str | None) -> Job:
        allowed = {
            "status",
            "progress_message",
            "source_title",
            "short_title",
            "short_description",
            "output_path",
            "youtube_video_id",
            "error",
        }
        unknown = fields.keys() - allowed
        if unknown:
            raise ValueError(f"Unknown job fields: {', '.join(sorted(unknown))}")
        if "status" in fields and isinstance(fields["status"], JobStatus):
            fields["status"] = fields["status"].value
        fields["updated_at"] = self._now()
        assignments = ", ".join(f"{key} = ?" for key in fields)
        values = [*fields.values(), job_id]
        with self._connect() as connection:
            cursor = connection.execute(
                f"UPDATE jobs SET {assignments} WHERE id = ?",  # noqa: S608
                values,
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Unknown job {job_id}")
        job = self.get(job_id)
        assert job is not None
        return job

    def list_recent(self, user_id: int, limit: int = 10) -> list[Job]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def list_queued(self) -> list[Job]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs WHERE status = ? ORDER BY created_at",
                (JobStatus.QUEUED.value,),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def fail_interrupted(self) -> int:
        running = (
            JobStatus.DOWNLOADING,
            JobStatus.ANALYZING,
            JobStatus.RENDERING,
            JobStatus.UPLOADING,
        )
        placeholders = ",".join("?" for _ in running)
        with self._connect() as connection:
            cursor = connection.execute(
                f"""
                UPDATE jobs
                SET status = ?, progress_message = ?, error = ?, updated_at = ?
                WHERE status IN ({placeholders})
                """,  # noqa: S608
                (
                    JobStatus.FAILED.value,
                    "Stopped when the service restarted",
                    "The worker stopped before this job finished. Submit it again.",
                    self._now(),
                    *(status.value for status in running),
                ),
            )
            return cursor.rowcount
