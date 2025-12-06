"""Fallback PDF parser plugin using local extraction."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Tuple

from app.logging_utils import get_pipeline_logger

logger = get_pipeline_logger("pdf_parser.local")

try:  # Optional dependency
    from pdfminer.high_level import extract_text as pdfminer_extract_text  # type: ignore
except Exception:  # pragma: no cover
    pdfminer_extract_text = None


class LocalPdfParser:
    name = "local"

    @property
    def enabled(self) -> bool:  # pragma: no cover
        return True

    def parse(self, pdf_path: Path, document_id: str, options: Dict[str, Any] | None = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        logger.info("Using local fallback parser for %s", pdf_path)
        text = ""
        if pdfminer_extract_text is not None:
            try:
                text = pdfminer_extract_text(str(pdf_path))
            except Exception as exc:  # pragma: no cover
                logger.warning("pdfminer extraction failed: %s", exc)
        if not text:
            try:
                text = pdf_path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                text = ""
        paragraphs = [seg.strip() for seg in text.splitlines() if seg.strip()]
        blocks = [{"text": para} for para in paragraphs] or [{"text": "(empty document)"}]
        payload = {"pages": [{"page_number": 1, "blocks": blocks}]}
        extras = {"parser": self.name}
        return payload, extras
