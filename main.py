from __future__ import annotations

import json
import uuid
from collections import deque
from pathlib import Path
from typing import Any, Dict, Literal, Optional

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.config import settings
from app.logging_utils import configure_logging, get_pipeline_logger
from app.pipeline.ingest import UnsupportedMediaType, process_document
from app.services import storage
from app.services.search_client import search_client
from app.tasks import task_store

configure_logging()
api_logger = get_pipeline_logger("pipeline.api")

app = FastAPI(title="Multimodal RAG Pipeline", version="1.0.0")


class ProcessingOptions(BaseModel):
    frame_strategy: Literal["interval", "scene"] = Field("interval")
    frame_interval_seconds: Optional[float] = Field(default=None, ge=0.5)
    scene_threshold: float = Field(default=0.3, ge=0.05, le=1.0)


class UserMetadata(BaseModel):
    document_id: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    custom_attributes: Dict[str, Any] = Field(default_factory=dict)


class IngestRequest(BaseModel):
    media_type: Literal["audio", "video"]
    source_path: str
    metadata: UserMetadata = Field(default_factory=UserMetadata)
    processing_options: Optional[ProcessingOptions] = None


class QueryRequest(BaseModel):
    query: str
    top_k: int = Field(default=5, le=20)


def _tail_log(lines: int) -> list[str]:
    log_file = settings.logs_dir / "pipeline.log"
    if not log_file.exists():
        return []
    buffer: deque[str] = deque(maxlen=lines)
    with log_file.open("r", encoding="utf-8", errors="ignore") as handle:
        for row in handle:
            buffer.append(row.rstrip())
    return list(buffer)


class TaskResponse(BaseModel):
    task_id: str
    status: str
    detail: Optional[str] = None
    result: Optional[dict] = None


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


def _background_run(
    task_id: str,
    source_path: Path,
    media_type: str,
    metadata: dict,
    processing_options: Optional[dict] = None,
) -> None:
    api_logger.info("Task %s started", task_id)
    try:
        document = process_document(source_path, media_type, metadata, processing_options)
        task_store.update(task_id, "completed", result=document.model_dump())
        api_logger.info("Task %s completed successfully", task_id)
    except UnsupportedMediaType as exc:
        task_store.update(task_id, "failed", detail=str(exc))
        api_logger.warning("Task %s failed due to unsupported media: %s", task_id, exc)
    except Exception as exc:  # pylint: disable=broad-except
        task_store.update(task_id, "failed", detail=str(exc))
        api_logger.exception("Task %s encountered an unexpected error", task_id)


@app.post("/ingest", response_model=TaskResponse)
def ingest(request: IngestRequest, background_tasks: BackgroundTasks) -> TaskResponse:
    task_id = request.metadata.document_id or str(uuid.uuid4())
    task_store.create(task_id)

    source_path = Path(request.source_path)
    if not source_path.exists():
        raise HTTPException(status_code=404, detail="source_path not found")
    raw_copy = storage.save_raw_path(source_path, task_id)

    metadata = request.metadata.model_dump()
    metadata.setdefault("document_id", task_id)

    proc_opts = request.processing_options.model_dump() if request.processing_options else None
    background_tasks.add_task(
        _background_run,
        task_id,
        raw_copy,
        request.media_type,
        metadata,
        proc_opts,
    )
    return TaskResponse(task_id=task_id, status="pending")


@app.post("/ingest/upload", response_model=TaskResponse)
def ingest_upload(
    background_tasks: BackgroundTasks,
    media_type: Literal["audio", "video"] = Form(...),
    metadata: str = Form("{}"),
    file: UploadFile = File(...),
    processing_options: Optional[str] = Form(None),
) -> TaskResponse:
    try:
        metadata_dict = json.loads(metadata)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid metadata JSON") from exc

    task_id = metadata_dict.get("document_id") or str(uuid.uuid4())
    task_store.create(task_id)
    raw_path = storage.save_raw_upload(file, task_id)
    metadata_dict.setdefault("title", file.filename)
    metadata_dict.setdefault("document_id", task_id)

    proc_opts = None
    if processing_options:
        try:
            proc_opts = json.loads(processing_options)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="Invalid processing_options JSON") from exc
    background_tasks.add_task(
        _background_run,
        task_id,
        raw_path,
        media_type,
        metadata_dict,
        proc_opts,
    )
    return TaskResponse(task_id=task_id, status="pending")


@app.get("/tasks/{task_id}", response_model=TaskResponse)
def task_status(task_id: str) -> TaskResponse:
    record = task_store.get(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail="task_id not found")
    return TaskResponse(task_id=task_id, status=record.status, detail=record.detail, result=record.result)


@app.post("/query")
def query(request: QueryRequest) -> JSONResponse:
    hits = search_client.search(request.query, request.top_k)
    return JSONResponse({"hits": hits})


@app.get("/logs/tail")
def tail_logs(lines: int = 200) -> dict:
    return {"lines": _tail_log(lines)}


@app.get("/logs/{task_id}")
def task_logs(task_id: str, lines: int = 200) -> dict:
    scoped = [line for line in _tail_log(lines * 3) if task_id in line]
    return {"task_id": task_id, "lines": scoped[-lines:]}
