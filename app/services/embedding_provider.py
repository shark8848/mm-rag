from __future__ import annotations

from typing import List

import requests

from app.config import settings
from app.logging_utils import get_pipeline_logger
from app.services.bailian import bailian_client

logger = get_pipeline_logger("pipeline.embedding")


class EmbeddingClient:
    """Provider-agnostic embedding helper supporting Bailian or Ollama."""

    def __init__(self) -> None:
        self.provider = (settings.embedding_provider or "bailian").lower()
        if self.provider not in {"bailian", "ollama"}:
            logger.warning("Unknown embedding provider %s, defaulting to Bailian", self.provider)
            self.provider = "bailian"
        self._session = requests.Session()
        self._ollama_url = settings.ollama_base_url.rstrip("/")

    @property
    def model_name(self) -> str:
        if self.provider == "ollama":
            return settings.ollama_embedding_model
        if self.provider == "bailian":
            return settings.bailian_embedding_model
        return settings.embedding_model

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        if self.provider == "ollama":
            return self._embed_via_ollama(texts)
        return self._embed_via_bailian(texts)

    def _embed_via_bailian(self, texts: List[str]) -> List[List[float]]:
        if not bailian_client.enabled:
            logger.warning("Bailian embedding requested but API key is missing")
            return []
        try:
            return bailian_client.embed_texts(texts)
        except Exception as exc:  # pragma: no cover - best effort
            logger.warning("Bailian embedding failed: %s", exc)
            return []

    def _embed_via_ollama(self, texts: List[str]) -> List[List[float]]:
        url = f"{self._ollama_url}/api/embeddings"
        vectors: List[List[float]] = []
        for text in texts:
            payload = {
                "model": settings.ollama_embedding_model,
                "prompt": text,
            }
            try:
                response = self._session.post(url, json=payload, timeout=settings.ollama_timeout)
                response.raise_for_status()
            except Exception as exc:  # pragma: no cover - local service optional
                logger.warning("Ollama embedding request failed: %s", exc)
                vectors.append([])
                continue
            data = response.json()
            vectors.append(data.get("embedding", []))
        return vectors


embedding_client = EmbeddingClient()
