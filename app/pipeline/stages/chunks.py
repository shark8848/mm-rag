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
        dispatched = _dispatch_chunks(media_type, source_path, document_id, options)
        if isinstance(dispatched, tuple):
            chunks, extras = dispatched
        else:  # backward compatibility
            chunks, extras = dispatched, {}
        context["chunks"] = serialize_chunks(chunks)
        context.setdefault("metrics", {})["chunks"] = len(chunks)
        if extras:
            from app.logging_utils import get_pipeline_logger
            logger = get_pipeline_logger("pipeline.chunks")
            artifacts = extras.get("artifacts", {})
            if artifacts:
                logger.info("ChunkStage received artifacts: %s", list(artifacts.keys()))
            for key, value in extras.items():
                if key == "metrics" and isinstance(value, dict):
                    context.setdefault("metrics", {}).update(value)
                elif isinstance(value, dict) and key in {"artifacts"}:
                    context.setdefault(key, {}).update(value)
                else:
                    context[key] = value
            if "artifacts" in context:
                logger.info("ChunkStage context now has artifacts: %s", list(context["artifacts"].keys()))
        return context
