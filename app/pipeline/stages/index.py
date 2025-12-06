"""Search indexing stage."""
from __future__ import annotations

from dataclasses import dataclass

from app.pipeline.stages.base import Context, Stage
from app.services.search_client import search_client


@dataclass
class IndexStage(Stage):
    name: str = "index_document"
    queue: str = "ingest_cpu"

    def run(self, context: Context) -> Context:
        payload = context.get("payload") or {}
        if payload:
            search_client.index_document(payload)
            for chunk in payload.get("chunks", []):
                search_client.index_chunk(chunk, payload)
        context.setdefault("metrics", {})["indexed_chunks"] = len(payload.get("chunks", []))
        return context
