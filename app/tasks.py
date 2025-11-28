from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class TaskRecord:
    status: str
    detail: Optional[str] = None
    result: Optional[dict] = None


class TaskStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tasks: Dict[str, TaskRecord] = {}

    def create(self, task_id: str) -> None:
        with self._lock:
            self._tasks[task_id] = TaskRecord(status="pending")

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
            return self._tasks.get(task_id)


task_store = TaskStore()
