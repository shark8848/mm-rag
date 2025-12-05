"""Vector enrichment stage stub."""
from __future__ import annotations

from dataclasses import dataclass

from app.services.embedding_provider import embedding_client
from app.pipeline.stages.base import Context, Stage


@dataclass
class VectorStage(Stage):
    name: str = "vector_enrichment"
    queue: str = "ingest_cpu"

    def run(self, context: Context) -> Context:
        # Placeholder: actual implementation will iterate over chunks and refresh embeddings
        if "chunks" in context:
            chunk_count = len(context["chunks"])
            context.setdefault("metrics", {})["vector_chunks"] = chunk_count
        context.setdefault("vector_provider", embedding_client.model_name)
        return context
