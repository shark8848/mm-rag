from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, BinaryIO, Optional
from urllib.parse import urlparse

from fastapi import UploadFile

from app.config import settings
from app.logging_utils import get_pipeline_logger, log_timing

try:
    from minio import Minio
except ImportError:  # pragma: no cover - optional dependency
    Minio = None  # type: ignore

logger = get_pipeline_logger("pipeline.storage")

_minio_client: Optional[Any] = None
_minio_bucket_ready = False


def _relative_to_data_root(path: Path) -> Optional[str]:
    try:
        rel = path.relative_to(settings.data_root)
        return rel.as_posix()
    except ValueError:
        return None


def _minio_endpoint_parts(endpoint: str) -> tuple[str, bool]:
    parsed = urlparse(endpoint)
    if parsed.scheme:
        host = parsed.netloc or parsed.path
        secure = parsed.scheme == "https"
    else:
        host = endpoint
        secure = endpoint.startswith("https")
    return host, secure


def _get_minio_client() -> Optional[Any]:
    global _minio_client  # pylint: disable=global-statement
    if not settings.minio_enabled:
        logger.debug("MinIO sync disabled; skipping client initialization")
        return None
    if Minio is None:
        logger.warning("MinIO sync enabled but 'minio' package is not installed")
        return None
    if not settings.minio_access_key or not settings.minio_secret_key:
        logger.warning("MinIO sync enabled but credentials are missing")
        return None
    if _minio_client is not None:
        return _minio_client
    host, secure = _minio_endpoint_parts(settings.minio_endpoint)
    try:
        _minio_client = Minio(
            host,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=secure,
        )
        logger.info("Initialized MinIO client for %s (secure=%s)", host, secure)
    except Exception as exc:  # pragma: no cover - network failure
        logger.error("Failed to initialize MinIO client: %s", exc)
        _minio_client = None
    return _minio_client


def _ensure_bucket(client: Any) -> bool:
    global _minio_bucket_ready  # pylint: disable=global-statement
    if _minio_bucket_ready:
        return True
    bucket = settings.minio_bucket
    try:
        if client.bucket_exists(bucket):
            _minio_bucket_ready = True
            return True
        client.make_bucket(bucket)
        _minio_bucket_ready = True
        logger.info("Created MinIO bucket %s", bucket)
        return True
    except Exception as exc:  # pragma: no cover - network failure
        logger.error("Failed to ensure MinIO bucket %s: %s", bucket, exc)
        return False


def _object_name_for(path: Path, fallback_prefix: str) -> str:
    rel = _relative_to_data_root(path)
    if rel:
        return rel
    prefix = fallback_prefix.strip("/")
    return f"{prefix}/{path.name}" if prefix else path.name


def _sync_to_minio(local_path: Path, fallback_prefix: str) -> None:
    client = _get_minio_client()
    if client is None:
        return
    if not _ensure_bucket(client):
        return
    object_name = _object_name_for(local_path, fallback_prefix)
    try:
        client.fput_object(settings.minio_bucket, object_name, str(local_path))
        logger.info("Synced %s to MinIO as %s", local_path, object_name)
    except Exception as exc:  # pragma: no cover - network failure
        logger.warning("Failed to sync %s to MinIO: %s", local_path, exc)


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def sync_artifact(local_path: Path, fallback_prefix: str = "intermediate") -> None:
    """Best-effort MinIO sync for an already materialized artifact."""

    if not local_path.exists():
        logger.debug("Skipping MinIO sync for missing artifact %s", local_path)
        return
    _sync_to_minio(local_path, fallback_prefix)


def save_raw_upload(upload: UploadFile, document_id: str) -> Path:
    """Persist the original user upload to raw storage."""

    destination = _ensure_dir(settings.raw_storage_dir) / f"{document_id}_{upload.filename}"
    with log_timing(logger, f"Saving raw upload for {document_id}"):
        with destination.open("wb") as buffer:
            shutil.copyfileobj(upload.file, buffer)
    upload.file.seek(0)
    logger.info("Stored raw upload for %s at %s", document_id, destination)
    _sync_to_minio(destination, "raw")
    return destination


def save_raw_path(src_path: Path, document_id: str) -> Path:
    """Copy an existing file into raw storage."""

    destination = _ensure_dir(settings.raw_storage_dir) / f"{document_id}_{src_path.name}"
    with log_timing(logger, f"Copying raw file for {document_id}"):
        shutil.copy(src_path, destination)
    logger.info("Copied raw path for %s from %s to %s", document_id, src_path, destination)
    _sync_to_minio(destination, "raw")
    return destination


def persist_intermediate(content: BinaryIO, target_dir: Path, file_name: str) -> Path:
    target_dir = _ensure_dir(target_dir)
    target_path = target_dir / file_name
    with log_timing(logger, f"Persisting intermediate artifact {file_name}"):
        with target_path.open("wb") as buffer:
            shutil.copyfileobj(content, buffer)
    logger.debug("Persisted intermediate artifact %s", target_path)
    prefix = _relative_to_data_root(target_dir) or "intermediate"
    sync_artifact(target_path, prefix)
    return target_path


def persist_json(document_id: str, payload: dict) -> Path:
    """Store the final structured output for auditing or replays."""

    final_dir = _ensure_dir(settings.final_instances_dir)
    target = final_dir / f"{document_id}.json"
    with log_timing(logger, f"Persisting final JSON for {document_id}"):
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    logger.info("Persisted final schema artifact for %s at %s", document_id, target)
    _sync_to_minio(target, "final_instances")
    return target
