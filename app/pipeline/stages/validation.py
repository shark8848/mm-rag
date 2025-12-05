"""Input validation stage for media safety limits."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.core.limits import LimitChecker
from app.pipeline.stages.base import Context, Stage


@dataclass
class ValidationStage(Stage):
    checker: LimitChecker
    name: str = "validate_input"
    queue: str = "ingest_io"

    def run(self, context: Context) -> Context:
        media_type = context["media_type"]
        source_path = Path(context["source_path"])
        self.checker.assert_file_size(media_type, source_path)
        return context
