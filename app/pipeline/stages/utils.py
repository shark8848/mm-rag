"""Shared helpers for pipeline stages."""
from __future__ import annotations

import time
from typing import Any, Dict, List

from app.config import settings
from app.models.mm_schema import Chunk, Document, DocumentMetadata

Context = Dict[str, Any]


def serialize_chunks(chunks: List[Chunk]) -> List[Dict[str, Any]]:
    payloads: List[Dict[str, Any]] = []
    for chunk in chunks:
        payload = chunk.model_dump(mode="json")
        processing = payload.get("processing") or {}
        processing.setdefault("pipeline_version", settings.pipeline_version)
        payload["processing"] = processing
        payloads.append(payload)
    return payloads


def deserialize_chunks(raw_chunks: List[Dict[str, Any]]) -> List[Chunk]:
    return [Chunk.model_validate(raw) for raw in raw_chunks]


def metadata_from_context(context: Context) -> DocumentMetadata:
    payload = context["document_metadata"]
    return DocumentMetadata.model_validate(payload)


def build_document_payload(context: Context) -> Dict[str, Any]:
    metadata = metadata_from_context(context)
    chunks = deserialize_chunks(context.get("chunks", []))
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
    return document.model_dump(mode="json")
