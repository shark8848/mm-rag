from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

from app.config import settings
from app.logging_utils import get_pipeline_logger, log_timing
from app.models.mm_schema import Chunk, ChunkContent, TemporalInfo, TextContent, TextSegment, VectorInfo
from app.services import storage
from app.services.pdf_parsers import get_pdf_parser
from app.services.vector_service import vector_service

logger = get_pipeline_logger("pipeline.pdf")

def _normalize_pages(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    pages = (
        payload.get("pages")
        or payload.get("data", {}).get("pages")
        or payload.get("result", {}).get("pages")
        or []
    )
    if not pages and payload.get("blocks"):
        pages = [{"page_number": 1, "blocks": payload.get("blocks")}]  # type: ignore[list-item]
    normalized: List[Dict[str, Any]] = []
    for idx, raw_page in enumerate(pages, start=1):
        page_number = raw_page.get("page_number") or raw_page.get("pageIndex") or raw_page.get("page") or idx
        blocks = raw_page.get("blocks") or raw_page.get("elements") or raw_page.get("items") or []
        if isinstance(blocks, dict):
            blocks = [blocks]
        if isinstance(blocks, str):
            blocks = [{"text": blocks}]
        if not blocks and raw_page.get("text"):
            blocks = [{"text": raw_page.get("text")}]  # type: ignore[list-item]
        normalized.append(
            {
                "page_number": int(page_number),
                "blocks": blocks,
            }
        )
    return normalized or [{"page_number": 1, "blocks": payload.get("blocks", [])}]


def _build_segments(blocks: List[Dict[str, Any]]) -> Tuple[List[TextSegment], List[str]]:
    segments: List[TextSegment] = []
    texts: List[str] = []
    for idx, block in enumerate(blocks):
        text = block.get("text") or block.get("content") or ""
        if not text:
            continue
        normalized_text = str(text).strip()
        if not normalized_text:
            continue
        segments.append(
            TextSegment(
                index=idx,
                start_time=float(idx),
                end_time=float(idx),
                text=normalized_text,
            )
        )
        texts.append(normalized_text)
    return segments, texts


def _build_text_content(segments: List[TextSegment]) -> TextContent:
    full_text = "\n".join(seg.text for seg in segments).strip()
    word_count = len(full_text.split()) if full_text else 0
    return TextContent(full_text=full_text, segments=segments, language="zh", word_count=word_count)


def build_pdf_chunks(
    pdf_path: Path,
    document_id: str,
    processing_options: Dict[str, Any] | None = None,
) -> Tuple[List[Chunk], Dict[str, Any]]:
    parser = get_pdf_parser()
    parser_options = (processing_options or {}).get("mineru") if isinstance(processing_options, dict) else None
    with log_timing(logger, f"PDF parsing via {parser.__class__.__name__} for {pdf_path.name}"):
        payload, extras = parser.parse(pdf_path, document_id, parser_options)
    extras = extras or {}
    parser_name = (extras.get("parser") or parser.__class__.__name__).lower()
    artifact_category = f"pdf_{parser_name}"
    artifact_path = storage.persist_auxiliary_json(document_id, payload, category=artifact_category)
    extras.setdefault("artifacts", {})["pdf_payload_path"] = str(artifact_path)
    pages = _normalize_pages(payload)

    prepared_pages: List[Dict[str, Any]] = []
    texts_for_embedding: List[str] = []
    for page in pages:
        segments, texts = _build_segments(page.get("blocks", []))
        if not segments:
            continue
        text_content = _build_text_content(segments)
        prepared_pages.append({
            "page_number": page["page_number"],
            "segments": segments,
            "text_content": text_content,
        })
        texts_for_embedding.append(text_content.full_text)

    if not prepared_pages and payload:
        # Ensure at least one chunk exists even if no structured blocks were produced.
        fallback_segment = TextSegment(index=0, start_time=0.0, end_time=0.0, text="(no textual content)")
        prepared_pages.append(
            {
                "page_number": 1,
                "segments": [fallback_segment],
                "text_content": _build_text_content([fallback_segment]),
            }
        )
        texts_for_embedding.append(prepared_pages[0]["text_content"].full_text)

    vectors = vector_service.embed_texts(texts_for_embedding)
    chunks: List[Chunk] = []
    for idx, page in enumerate(prepared_pages):
        text_content: TextContent = page["text_content"]
        embedding = vectors[idx] if idx < len(vectors) else []
        vector = VectorInfo(
            embedding=embedding,
            model=vector_service.model_name or settings.embedding_model,
            model_version="1.0",
            dimension=len(embedding) or settings.embedding_dimension,
            embedding_type="text",
        )
        temporal = TemporalInfo(
            start_time=float(page["page_number"] - 1),
            end_time=float(page["page_number"]),
            duration=0.0,
            chunk_index=idx + 1,
        )
        processing_step = f"{parser_name}_parse"
        chunk = Chunk(
            chunk_id=f"{document_id}-p{page['page_number']}",
            media_type="pdf",
            temporal=temporal,
            content=ChunkContent(text=text_content),
            vector=vector,
            processing={"steps": [{"step_name": processing_step, "status": "success"}]},
            analysis={"page_number": page["page_number"], "block_count": len(page["segments"] or [])},
        )
        chunks.append(chunk)

    logger.info("Built %d PDF chunks for %s", len(chunks), pdf_path.name)
    extras.setdefault("metrics", {})["pdf_chunks"] = len(chunks)
    return chunks, extras
