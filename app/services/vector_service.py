"""Configurable vector service with provider failover."""
from __future__ import annotations

import hashlib
import random
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Sequence

import requests

from app.config import settings
from app.logging_utils import get_pipeline_logger
from app.services.bailian import bailian_client

logger = get_pipeline_logger("pipeline.vector")


@dataclass
class VectorServiceConfig:
    provider: str = field(default_factory=lambda: (settings.embedding_provider or "bailian"))
    dimension: int = settings.embedding_dimension
    ollama_url: str = settings.ollama_base_url.rstrip("/")
    ollama_timeout: int = settings.ollama_timeout
    max_retries: int = 2
    deterministic_seed_bytes: int = 16


class VectorService:
    def __init__(self, config: VectorServiceConfig) -> None:
        self.config = config
        self.provider = self._normalize_provider(config.provider)
        self._session = requests.Session()
        self._metrics: Dict[str, Any] = {
            "requests": 0,
            "provider_failures": 0,
            "fallback_vectors": 0,
        }

    # ------------------------- Public API -------------------------
    @property
    def model_name(self) -> str:
        if self.provider == "ollama":
            return settings.ollama_embedding_model
        if self.provider == "bailian":
            return settings.bailian_embedding_model
        return settings.embedding_model

    def embed_texts(self, texts: Sequence[str]) -> List[List[float]]:
        texts = [text or "" for text in texts]
        if not texts:
            return []
        self._metrics["requests"] += 1
        start = time.time()
        try:
            vectors = self._dispatch_provider(texts)
            if not vectors or any(len(vec) == 0 for vec in vectors):
                raise RuntimeError("Provider returned empty vectors")
            return [self._normalize_vector(vec) for vec in vectors]
        except Exception as exc:  # pragma: no cover - network optional
            self._metrics["provider_failures"] += 1
            logger.warning("Vector provider %s failed: %s", self.provider, exc)
            fallback_vectors = [self._fallback_vector(text) for text in texts]
            self._metrics["fallback_vectors"] += len(fallback_vectors)
            return fallback_vectors
        finally:
            duration = time.time() - start
            logger.debug(
                "vector_service provider=%s texts=%d duration=%.3fs",
                self.provider,
                len(texts),
                duration,
            )

    def health_snapshot(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model_name,
            "metrics": dict(self._metrics),
            "bailian_enabled": bailian_client.enabled,
        }

    # ------------------------- Internals -------------------------
    def _dispatch_provider(self, texts: Sequence[str]) -> List[List[float]]:
        retries = max(0, self.config.max_retries)
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            try:
                if self.provider == "ollama":
                    return self._embed_via_ollama(texts)
                if self.provider == "bailian":
                    return bailian_client.embed_texts(list(texts))
                return []
            except Exception as exc:  # pragma: no cover - provider optional
                last_exc = exc
                logger.warning(
                    "Vector attempt %s/%s failed via %s: %s",
                    attempt + 1,
                    retries + 1,
                    self.provider,
                    exc,
                )
                time.sleep(min(0.2 * (attempt + 1), 1.0))
        if last_exc:
            raise last_exc
        return []

    def _embed_via_ollama(self, texts: Sequence[str]) -> List[List[float]]:
        url = f"{self.config.ollama_url}/api/embeddings"
        vectors: List[List[float]] = []
        for text in texts:
            payload = {"model": settings.ollama_embedding_model, "prompt": text}
            response = self._session.post(url, json=payload, timeout=self.config.ollama_timeout)
            response.raise_for_status()
            data = response.json()
            vectors.append(data.get("embedding", []))
        return vectors

    def _normalize_vector(self, vector: Sequence[float]) -> List[float]:
        vec = list(vector)
        dim = self.config.dimension
        if len(vec) > dim:
            return vec[:dim]
        if len(vec) < dim:
            vec.extend([0.0] * (dim - len(vec)))
        return vec

    def _fallback_vector(self, text: str) -> List[float]:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        seed = int(digest[: self.config.deterministic_seed_bytes], 16)
        rnd = random.Random(seed)
        return [rnd.uniform(-1, 1) for _ in range(self.config.dimension)]

    @staticmethod
    def _normalize_provider(provider: str) -> str:
        normalized = (provider or "bailian").lower()
        if normalized not in {"bailian", "ollama"}:
            logger.warning("Unknown embedding provider %s, defaulting to bailian", provider)
            return "bailian"
        return normalized


vector_service = VectorService(VectorServiceConfig())
