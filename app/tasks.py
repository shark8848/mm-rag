from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Dict, Optional

from celery.result import AsyncResult

from app.celery_app import celery_app


@dataclass
class TaskRecord:
    status: str
    detail: Optional[str] = None
    result: Optional[dict] = None
    celery_id: Optional[str] = None


class TaskStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tasks: Dict[str, TaskRecord] = {}

    def create(self, task_id: str) -> None:
        with self._lock:
            self._tasks[task_id] = TaskRecord(status="pending")

    def attach_celery(self, task_id: str, celery_id: str) -> None:
        with self._lock:
            record = self._tasks.get(task_id)
            if record is None:
                record = TaskRecord(status="pending")
                self._tasks[task_id] = record
            record.celery_id = celery_id

    def update(self, task_id: str, status: str, detail: Optional[str] = None, result: Optional[dict] = None) -> None:
        with self._lock:
            record = self._tasks.get(task_id)
            if record is None:
                record = TaskRecord(status=status)
                self._tasks[task_id] = record
            record.status = status
            record.detail = detail
            record.result = result

    def get(self, task_id: str) -> Optional[TaskRecord]:
        with self._lock:
            record = self._tasks.get(task_id)
        if record is None or not record.celery_id:
            return record
        async_result = AsyncResult(record.celery_id, app=celery_app)
        record.status = async_result.state.lower()
        if async_result.failed():
            record.detail = str(async_result.info)
        elif async_result.successful():
            payload = async_result.result or {}
            record.result = payload.get("document") or payload
            record.detail = None
        with self._lock:
            self._tasks[task_id] = record
        return record


task_store = TaskStore()
