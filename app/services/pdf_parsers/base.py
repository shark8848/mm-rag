"""Protocol for PDF parser plugins."""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, Tuple


class PdfParser(ABC):
    name: str

    @property
    @abstractmethod
    def enabled(self) -> bool:  # pragma: no cover - simple property
        ...

    @abstractmethod
    def parse(self, pdf_path: Path, document_id: str, options: Dict[str, Any] | None = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Return normalized payload and metadata.

        Expected response: (parsed_payload, extras)
        extras may contain artifacts or metrics.
        """
        ...
