from __future__ import annotations

import shutil
from pathlib import Path
from typing import BinaryIO

from fastapi import UploadFile

import json

from app.config import settings
from app.logging_utils import get_pipeline_logger, log_timing

logger = get_pipeline_logger("pipeline.storage")


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_raw_upload(upload: UploadFile, document_id: str) -> Path:
    """Persist the original user upload to raw storage."""

    destination = _ensure_dir(settings.raw_storage_dir) / f"{document_id}_{upload.filename}"
    with log_timing(logger, f"Saving raw upload for {document_id}"):
        with destination.open("wb") as buffer:
            shutil.copyfileobj(upload.file, buffer)
    upload.file.seek(0)
    logger.info("Stored raw upload for %s at %s", document_id, destination)
    return destination


def save_raw_path(src_path: Path, document_id: str) -> Path:
    """Copy an existing file into raw storage."""

    destination = _ensure_dir(settings.raw_storage_dir) / f"{document_id}_{src_path.name}"
    with log_timing(logger, f"Copying raw file for {document_id}"):
        shutil.copy(src_path, destination)
    logger.info("Copied raw path for %s from %s to %s", document_id, src_path, destination)
    return destination


def persist_intermediate(content: BinaryIO, target_dir: Path, file_name: str) -> Path:
    target_dir = _ensure_dir(target_dir)
    target_path = target_dir / file_name
    with log_timing(logger, f"Persisting intermediate artifact {file_name}"):
        with target_path.open("wb") as buffer:
            shutil.copyfileobj(content, buffer)
    logger.debug("Persisted intermediate artifact %s", target_path)
    return target_path


def persist_json(document_id: str, payload: dict) -> Path:
    """Store the final structured output for auditing or replays."""

    final_dir = _ensure_dir(settings.final_instances_dir)
    target = final_dir / f"{document_id}.json"
    with log_timing(logger, f"Persisting final JSON for {document_id}"):
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    logger.info("Persisted final schema artifact for %s at %s", document_id, target)
    return target
