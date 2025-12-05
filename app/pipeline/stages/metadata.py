"""Metadata preparation stage."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.models.mm_schema import DocumentMetadata
from app.pipeline.stages.base import Context, Stage
from app.pipeline.ingest import _build_metadata


@dataclass
class MetadataStage(Stage):
    name: str = "build_metadata"
    queue: str = "ingest_io"

    def run(self, context: Context) -> Context:
        source_path = Path(context["source_path"])
        metadata = _build_metadata(source_path, context["user_metadata"])
        context["document_metadata"] = metadata.model_dump(mode="json")
        return context
