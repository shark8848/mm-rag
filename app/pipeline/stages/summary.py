"""Document summary generation stage wrapper."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from app.pipeline.ingest import _build_summary
from app.pipeline.stages.base import Context, Stage


def _inline_deserialize(chunks: List[Dict[str, Any]]) -> List[Any]:
    from app.models.mm_schema import Chunk  # local import to avoid circular deps

    return [Chunk.model_validate(item) for item in chunks]


@dataclass
class SummaryStage(Stage):
    name: str = "generate_summary"
    queue: str = "ingest_cpu"

    def run(self, context: Context) -> Context:
        raw_chunks = context.get("chunks", [])
        chunks = _inline_deserialize(raw_chunks) if raw_chunks else []
        metadata = context.get("document_metadata", {})
        title = metadata.get("title", "Untitled") if isinstance(metadata, dict) else "Untitled"
        context["document_summary"] = _build_summary(chunks, title)
        return context
