"""Media chunk generation stage."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

from app.pipeline.ingest import _dispatch_chunks
from app.pipeline.stages.base import Context, Stage
from app.pipeline.stages.utils import serialize_chunks


@dataclass
class ChunkStage(Stage):
    name: str = "generate_chunks"
    queue: str = "ingest_cpu"

    def run(self, context: Context) -> Context:
        source_path = Path(context["source_path"])
        document_id = context["document_id"]
        media_type = context["media_type"]
        options = context.get("processing_options")
        chunks = _dispatch_chunks(media_type, source_path, document_id, options)
        context["chunks"] = serialize_chunks(chunks)
        context.setdefault("metrics", {})["chunks"] = len(chunks)
        return context
