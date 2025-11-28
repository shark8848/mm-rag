from __future__ import annotations

import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.logging_utils import get_pipeline_logger, log_timing

from app.config import settings
from app.models.mm_schema import Chunk, Document, DocumentMetadata, SourceInfo
from app.processors.audio import build_audio_chunks
from app.processors.video import build_video_chunks
from app.services import storage
from app.services.bailian import bailian_client
from app.services.search_client import search_client

logger = get_pipeline_logger("pipeline.ingest")
summary_logger = get_pipeline_logger("pipeline.summary")


class UnsupportedMediaType(ValueError):
    pass


def _build_metadata(source_path: Path, user_metadata: Dict[str, Any]) -> DocumentMetadata:
    stat = source_path.stat()
    source_info = SourceInfo(
        file_name=source_path.name,
        file_path=str(source_path),
        file_size=stat.st_size,
        format=source_path.suffix.lstrip("."),
        created_at=datetime.fromtimestamp(stat.st_ctime),
    )
    return DocumentMetadata(
        title=user_metadata.get("title") or source_path.stem,
        description=user_metadata.get("description"),
        source_info=source_info,
        tags=user_metadata.get("tags") or [],
        custom_attributes=user_metadata.get("custom_attributes") or {},
    )


def _dispatch_chunks(
    media_type: str,
    source_path: Path,
    base_chunk_id: str,
    processing_options: Optional[Dict[str, Any]] = None,
):
    if media_type == "audio":
        return build_audio_chunks(source_path, base_chunk_id)
    if media_type == "video":
        return build_video_chunks(source_path, base_chunk_id, processing_options)
    raise UnsupportedMediaType(media_type)


def _collect_text(chunks: List[Chunk]) -> str:
    texts: List[str] = []
    for chunk in chunks:
        text = chunk.content.text.full_text if chunk.content and chunk.content.text else ""
        if text:
            texts.append(text)
    return "\n".join(texts)


def _build_summary(chunks: List[Chunk], title: str) -> Dict[str, Any]:
    fallback = {
        "abstract": f"Auto generated summary for {title}",
        "key_points": ["Placeholder summary"],
    }
    if not bailian_client.enabled:
        summary_logger.info(
            "Bailian model %s disabled, using fallback summary for %s",
            settings.bailian_multimodal_model,
            title,
        )
        return fallback
    corpus = _collect_text(chunks)
    if not corpus:
        summary_logger.info("No transcript content available for %s, returning fallback summary", title)
        return fallback
    prompt = (
        "请阅读以下内容并给出50字以内摘要，同时列出3-5个关键要点，使用中文输出。内容如下：\n"
        + corpus[:4000]
    )
    try:
        summary_text = bailian_client.multimodal_summary(prompt)
        if not summary_text:
            summary_logger.warning("Empty summary response for %s, fallback", title)
            return fallback
        sentences = [seg.strip() for seg in summary_text.splitlines() if seg.strip()]
        abstract = sentences[0]
        key_points = sentences[1:6] or sentences[:1]
        summary_logger.info(
            "Summary generated via Bailian model %s for %s",
            settings.bailian_multimodal_model,
            title,
        )
        return {"abstract": abstract, "key_points": key_points}
    except Exception:
        summary_logger.exception("Summary generation failed for %s, fallback", title)
        return fallback


def process_document(
    source_path: Path,
    media_type: str,
    user_metadata: Dict[str, Any],
    processing_options: Optional[Dict[str, Any]] = None,
) -> Document:
    document_id = user_metadata.get("document_id") or str(uuid.uuid4())
    metadata = _build_metadata(source_path, user_metadata)
    proc_opts = processing_options or {}

    start = time.time()
    logger.info(
        "Processing document %s (%s) from %s", document_id, media_type, source_path,
    )
    with log_timing(logger, f"Chunk generation for {document_id} ({media_type})"):
        chunks = _dispatch_chunks(media_type, source_path, document_id, proc_opts)
    logger.info("Generated %d %s chunks for %s", len(chunks), media_type, document_id)
    metadata.total_chunks = len(chunks)

    with log_timing(summary_logger, f"Summary generation for {document_id}"):
        document_summary = _build_summary(chunks, metadata.title)

    document = Document(
        document_id=document_id,
        document_metadata=metadata,
        chunks=chunks,
        document_summary=document_summary,
    )

    summary_points = len((document.document_summary or {}).get("key_points", []))
    logger.info("Document %s summary ready with %d key points", document_id, summary_points)

    duration = time.time() - start
    for chunk in document.chunks:
        chunk.processing |= {
            "pipeline_version": settings.pipeline_version,
            "processing_time": duration,
        }

    payload = document.model_dump(mode="json")
    with log_timing(logger, f"Persisting structured output for {document_id}"):
        artifact_path = storage.persist_json(document_id, payload)
    logger.info("Persisted document %s output to %s", document_id, artifact_path)
    logger.info("Indexing document %s and %d chunks into search backend", document_id, len(payload["chunks"]))
    with log_timing(logger, f"Indexing payload for {document_id}"):
        search_client.index_document(payload)
        for chunk in payload["chunks"]:
            search_client.index_chunk(chunk, payload)
    logger.info("Completed indexing for document %s", document_id)
    logger.info("Pipeline run for %s finished in %.2fs", document_id, duration)
    return document
