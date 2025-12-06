"""Task detail and log retrieval endpoints."""
from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Deque, List

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import authenticate
from app.api.schemas import TaskResponse
from app.config import settings
from app.core.security import Credential
from app.tasks import task_store

router = APIRouter(tags=["logs"])


def _tail_log(path: Path, lines: int) -> List[str]:
    if not path.exists():
        raise FileNotFoundError(path)
    buffer: Deque[str] = deque(maxlen=max(1, lines))
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for row in handle:
            buffer.append(row.rstrip("\n"))
    return list(buffer)


@router.get("/tasks/{task_id}", response_model=TaskResponse)
def get_task(task_id: str, credential: Credential = Depends(authenticate)) -> TaskResponse:
    task = task_store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskResponse(task_id=task_id, status=task.status, detail=task.detail, result=task.result)


@router.get("/logs/tail")
def tail_logs(lines: int = 200, credential: Credential = Depends(authenticate)):
    log_path = settings.logs_dir / "pipeline.log"
    try:
        return {"lines": _tail_log(log_path, lines)}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Log file not found")


@router.get("/logs/{task_id}")
def task_log(task_id: str, credential: Credential = Depends(authenticate)):
    log_path = settings.logs_dir / "pipeline.log"
    try:
        lines = _tail_log(log_path, 600)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Log file not found")
    scoped = [line for line in lines if task_id in line]
    if not scoped:
        record = task_store.get(task_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Task not found")
    return {"task_id": task_id, "lines": scoped[-200:]}