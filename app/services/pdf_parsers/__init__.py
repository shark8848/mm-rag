"""PDF parser plugin registry."""
from __future__ import annotations

from typing import Dict

from app.config import settings
from app.logging_utils import get_pipeline_logger

from .base import PdfParser
from .fallback import LocalPdfParser
from .mineru import MinerUPdfParser

logger = get_pipeline_logger("pdf_parser.registry")

_PARSERS: Dict[str, PdfParser] = {}


def _build_registry() -> Dict[str, PdfParser]:
    registry: Dict[str, PdfParser] = {
        "local": LocalPdfParser(),
    }
    mineru_parser = MinerUPdfParser()
    if mineru_parser.enabled:
        registry["mineru"] = mineru_parser
    return registry


def get_pdf_parser() -> PdfParser:
    if not _PARSERS:
        _PARSERS.update(_build_registry())
    parser_name = (settings.pdf_parser or "mineru").lower()
    parser = _PARSERS.get(parser_name)
    if parser is None:
        logger.warning("Requested PDF parser '%s' unavailable, falling back to local parser", parser_name)
        parser = _PARSERS.get("local")
    return parser
