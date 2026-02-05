"""
Task persistence repository (SQLite via async SQLAlchemy).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import select

from app.db.models import TaskRecord
from app.db.session import get_sessionmaker
from app.models.task import Task


class TaskRepository:
    def __init__(self) -> None:
        self._sessionmaker = get_sessionmaker()

    async def upsert(self, task: Task) -> None:
        async with self._sessionmaker() as session:
            existing = await session.get(TaskRecord, task.task_id)
            if existing is None:
                session.add(self._to_record(task))
            else:
                self._apply(existing, task)
            await session.commit()

    async def get(self, task_id: str) -> Optional[Task]:
        async with self._sessionmaker() as session:
            record = await session.get(TaskRecord, task_id)
            return self._to_model(record) if record else None

    async def list_recent(self, limit: int = 50) -> list[Task]:
        async with self._sessionmaker() as session:
            stmt = select(TaskRecord).order_by(TaskRecord.created_at.desc()).limit(limit)
            rows = (await session.execute(stmt)).scalars().all()
            return [self._to_model(r) for r in rows]

    def _to_record(self, task: Task) -> TaskRecord:
        return TaskRecord(
            task_id=task.task_id,
            task_type=str(task.task_type),
            status=str(task.status),
            params=task.params or {},
            progress=task.progress,
            message=task.message,
            result=task.result,
            error_message=task.error_message,
            error_details=task.error_details,
            created_at=task.created_at,
            started_at=task.started_at,
            completed_at=task.completed_at,
        )

    def _apply(self, record: TaskRecord, task: Task) -> None:
        record.task_type = str(task.task_type)
        record.status = str(task.status)
        record.params = task.params or {}
        record.progress = task.progress
        record.message = task.message
        record.result = task.result
        record.error_message = task.error_message
        record.error_details = task.error_details
        record.created_at = task.created_at
        record.started_at = task.started_at
        record.completed_at = task.completed_at

    def _to_model(self, record: TaskRecord) -> Task:
        # Import here to avoid circular typing issues
        return Task(
            task_id=record.task_id,
            task_type=record.task_type,
            status=record.status,
            params=record.params or {},
            progress=record.progress,
            message=record.message,
            result=record.result,
            error_message=record.error_message,
            error_details=record.error_details,
            created_at=record.created_at,
            started_at=record.started_at,
            completed_at=record.completed_at,
        )

