"""Ingestion endpoints with authentication and media limits."""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import ValidationError

from app.api.dependencies import authenticate, get_limit_checker
from app.api.schemas import IngestRequest, ProcessingOptions, TaskResponse, UserMetadata
from app.core.errors import APIError, get_error
from app.core.limits import LimitChecker
from app.core.security import Credential
from app.core.tracking import new_context
from app.pipeline.celery_tasks import enqueue_pipeline
from app.services import storage
from app.tasks import task_store

router = APIRouter(tags=["ingest"])


def _serialize_processing_options(options: Optional[ProcessingOptions]) -> dict:
    return options.model_dump() if options else {}


def _dump_metadata(metadata: UserMetadata, fallback_title: Optional[str] = None) -> dict:
    data = metadata.model_dump()
    if fallback_title and not data.get("title"):
        data["title"] = fallback_title
    return data


def _as_megabytes(path: Path) -> float:
    return path.stat().st_size / (1024 * 1024)


@router.post("/ingest", response_model=TaskResponse)
def ingest(
    request: IngestRequest,
    credential: Credential = Depends(authenticate),
    checker: LimitChecker = Depends(get_limit_checker),
) -> TaskResponse:
    task_id = request.metadata.document_id or str(uuid.uuid4())
    source_path = Path(request.source_path)
    if not source_path.exists():
        raise HTTPException(status_code=404, detail="source_path not found")

    checker.assert_batch(1, _as_megabytes(source_path))
    checker.assert_file_size(request.media_type, source_path)

    task_store.create(task_id)
    new_context(task_id=task_id, app_id=credential.app_id)

    raw_copy = storage.save_raw_path(source_path, task_id)
    metadata = _dump_metadata(request.metadata)
    metadata.setdefault("document_id", task_id)

    context = {
        "document_id": task_id,
        "media_type": request.media_type,
        "source_path": str(raw_copy),
        "user_metadata": metadata,
        "processing_options": _serialize_processing_options(request.processing_options),
        "started_at": time.time(),
        "app_id": credential.app_id,
    }
    async_result = enqueue_pipeline(context)
    task_store.attach_celery(task_id, async_result.id)
    task_store.update(task_id, "queued")
    return TaskResponse(task_id=task_id, status="queued")


@router.post("/ingest/upload", response_model=TaskResponse)
def ingest_upload(
    media_type: Literal["audio", "video", "pdf"] = Form(...),
    metadata: str = Form("{}"),
    file: UploadFile = File(...),
    processing_options: Optional[str] = Form(None),
    credential: Credential = Depends(authenticate),
    checker: LimitChecker = Depends(get_limit_checker),
) -> TaskResponse:
    if media_type not in {"audio", "video", "pdf"}:
        raise APIError(get_error("ERR_MEDIA_UNSUPPORTED"))
    try:
        metadata_dict = json.loads(metadata)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid metadata JSON") from exc

    try:
        options_dict = json.loads(processing_options) if processing_options else None
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid processing_options JSON") from exc

    task_id = metadata_dict.get("document_id") or str(uuid.uuid4())
    try:
        metadata_model = UserMetadata(**metadata_dict)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail="Invalid metadata schema") from exc
    task_store.create(task_id)
    new_context(task_id=task_id, app_id=credential.app_id)

    # Estimate file size before persisting to enforce batch limits.
    current_pos = file.file.tell()
    file.file.seek(0, 2)
    size_bytes = file.file.tell()
    file.file.seek(current_pos)
    checker.assert_batch(1, size_bytes / (1024 * 1024))

    raw_path = storage.save_raw_upload(file, task_id)
    checker.assert_file_size(media_type, raw_path)

    metadata_dump = _dump_metadata(metadata_model, fallback_title=file.filename)
    metadata_dump.setdefault("document_id", task_id)

    try:
        proc_opts = ProcessingOptions(**options_dict) if options_dict else None
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail="Invalid processing_options schema") from exc

    context = {
        "document_id": task_id,
        "media_type": media_type,
        "source_path": str(raw_path),
        "user_metadata": metadata_dump,
        "processing_options": _serialize_processing_options(proc_opts),
        "started_at": time.time(),
        "app_id": credential.app_id,
    }
    async_result = enqueue_pipeline(context)
    task_store.attach_celery(task_id, async_result.id)
    task_store.update(task_id, "queued")
    return TaskResponse(task_id=task_id, status="queued")