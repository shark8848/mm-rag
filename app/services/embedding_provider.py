"""Compatibility shim for legacy imports."""
from __future__ import annotations

from app.services.vector_service import VectorService, VectorServiceConfig, vector_service

# Backwards compatibility for modules still importing embedding_client.
embedding_client = vector_service

__all__ = ["VectorService", "VectorServiceConfig", "vector_service", "embedding_client"]
