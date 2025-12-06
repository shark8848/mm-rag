"""Persist structured artifacts stage."""
from __future__ import annotations

from dataclasses import dataclass

from app.pipeline.stages.base import Context, Stage
from app.pipeline.stages.utils import build_document_payload
from app.services import storage


@dataclass
class PersistStage(Stage):
    name: str = "persist_artifacts"
    queue: str = "ingest_io"

    def run(self, context: Context) -> Context:
        payload = build_document_payload(context)
        artifact_path = storage.persist_json(context["document_id"], payload)
        context["payload"] = payload
        context["artifact_path"] = str(artifact_path)
        return context
