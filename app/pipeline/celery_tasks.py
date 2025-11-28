from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List

from celery import chain

from app.celery_app import celery_app
from app.config import settings
from app.logging_utils import get_pipeline_logger
from app.models.mm_schema import Chunk, Document, DocumentMetadata
from app.pipeline.ingest import _build_metadata, _build_summary, _dispatch_chunks
from app.services import storage
from app.services.search_client import search_client

logger = get_pipeline_logger("pipeline.celery")

Context = Dict[str, Any]


def _serialize_chunks(chunks: List[Chunk]) -> List[Dict[str, Any]]:
    payloads: List[Dict[str, Any]] = []
    for chunk in chunks:
        payload = chunk.model_dump(mode="json")
        processing = payload.get("processing") or {}
        processing.setdefault("pipeline_version", settings.pipeline_version)
        payload["processing"] = processing
        payloads.append(payload)
    return payloads


def _deserialize_chunks(raw_chunks: List[Dict[str, Any]]) -> List[Chunk]:
    return [Chunk.model_validate(raw) for raw in raw_chunks]


def _metadata_from_payload(payload: Dict[str, Any]) -> DocumentMetadata:
    return DocumentMetadata.model_validate(payload)


def _build_document(context: Context) -> Document:
    metadata = _metadata_from_payload(context["document_metadata"])
    chunks = _deserialize_chunks(context["chunks"])
    summary = context.get("document_summary")
    document = Document(
        document_id=context["document_id"],
        document_metadata=metadata,
        chunks=chunks,
        document_summary=summary,
    )
    duration = time.time() - context.get("started_at", time.time())
    for chunk in document.chunks:
        processing = chunk.processing or {}
        processing["processing_time"] = duration
        processing["pipeline_version"] = settings.pipeline_version
        chunk.processing = processing
    return document


@celery_app.task(name="pipeline.build_metadata")
def build_metadata_task(context: Context) -> Context:
    source_path = Path(context["source_path"])
    metadata = _build_metadata(source_path, context["user_metadata"])
    context["document_metadata"] = metadata.model_dump(mode="json")
    logger.info("Metadata prepared for %s", context["document_id"])
    return context


@celery_app.task(name="pipeline.generate_chunks")
def generate_chunks_task(context: Context) -> Context:
    start = time.time()
    document_id = context["document_id"]
    source_path = Path(context["source_path"])
    processing_options = context.get("processing_options") or None
    chunks = _dispatch_chunks(context["media_type"], source_path, document_id, processing_options)
    context["chunks"] = _serialize_chunks(chunks)
    context.setdefault("metrics", {})["chunk_build_seconds"] = time.time() - start
    logger.info("Generated %d chunks for %s", len(chunks), document_id)
    return context


@celery_app.task(name="pipeline.generate_summary")
def generate_summary_task(context: Context) -> Context:
    metadata = _metadata_from_payload(context["document_metadata"])
    chunks = _deserialize_chunks(context.get("chunks", []))
    context["document_summary"] = _build_summary(chunks, metadata.title)
    logger.info("Summary generated for %s", context["document_id"])
    return context


@celery_app.task(name="pipeline.persist_artifacts")
def persist_artifacts_task(context: Context) -> Context:
    document = _build_document(context)
    payload = document.model_dump(mode="json")
    artifact_path = storage.persist_json(document.document_id, payload)
    context["payload"] = payload
    context["artifact_path"] = str(artifact_path)
    logger.info("Persisted artifacts for %s", document.document_id)
    return context


@celery_app.task(name="pipeline.index_document")
def index_document_task(context: Context) -> Dict[str, Any]:
    payload = context["payload"]
    search_client.index_document(payload)
    for chunk in payload.get("chunks", []):
        search_client.index_chunk(chunk, payload)
    logger.info("Indexed document %s", payload["document_id"])
    return {
        "document": payload,
        "artifact_path": context.get("artifact_path"),
    }


def enqueue_pipeline(context: Context):
    workflow = chain(
        build_metadata_task.s(context),
        generate_chunks_task.s(),
        generate_summary_task.s(),
        persist_artifacts_task.s(),
        index_document_task.s(),
    )
    return workflow.apply_async(task_id=context["document_id"])
