from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

# Force the official client to send compatibility headers supported by ES 8.x
# before the transport is imported or instantiated.
os.environ.setdefault("ELASTIC_CLIENT_APIVERSIONING", "true")

from app.config import settings

try:
    from elasticsearch import Elasticsearch
except ImportError:
    Elasticsearch = None  # type: ignore


class SearchClient:
    """Thin wrapper that falls back to in-memory indexing when ES is unavailable."""

    def __init__(self) -> None:
        self.segments_index = settings.es_index
        self.documents_index = f"{settings.es_index}-docs"
        if (Elasticsearch is None) or (not settings.es_enabled):
            self.client = None
            self._memory_index: List[Dict[str, Any]] = []
        else:
            auth = None
            if settings.es_user and settings.es_password:
                auth = (settings.es_user, settings.es_password)
            compat_headers = {
                "accept": "application/vnd.elasticsearch+json; compatible-with=8",
                "content-type": "application/vnd.elasticsearch+json; compatible-with=8",
            }
            try:
                base_client = Elasticsearch(
                    settings.es_host,
                    basic_auth=auth,
                    verify_certs=not settings.es_skip_tls,
                    ssl_show_warn=not settings.es_skip_tls,
                )
                self.client = base_client.options(headers=compat_headers)
            except Exception:  # pragma: no cover - fallback path
                self.client = None
            self._memory_index = []

    def _format_chunk_document(self, chunk: Dict[str, Any], document: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        metadata = (document or {}).get("document_metadata", {})
        source_info = metadata.get("source_info", {}) if isinstance(metadata, dict) else {}

        content_text = ""
        chunk_content = chunk.get("content")
        audio_path = None
        video_path = None
        thumbnail_url = None
        if isinstance(chunk_content, dict):
            text_blob = chunk_content.get("text") or {}
            if isinstance(text_blob, dict):
                content_text = text_blob.get("full_text") or ""
                if not content_text:
                    segments = text_blob.get("segments") or []
                    for segment in segments:
                        text = segment.get("text")
                        if text:
                            content_text += (text + " ")
            frame_desc = " ".join(
                frame.get("description")
                for frame in chunk_content.get("keyframes") or []
                if isinstance(frame, dict) and frame.get("description")
            )
            if frame_desc:
                content_text = (content_text + "\n" + frame_desc).strip()
            audio_info = chunk_content.get("audio")
            if isinstance(audio_info, dict):
                audio_path = audio_info.get("url")
            video_info = chunk_content.get("video")
            if isinstance(video_info, dict):
                video_path = video_info.get("url")
            keyframes = chunk_content.get("keyframes") or []
            for frame in keyframes:
                if isinstance(frame, dict) and frame.get("thumbnail_url"):
                    thumbnail_url = frame.get("thumbnail_url")
                    break

        if not content_text:
            fallback = metadata.get("description") if isinstance(metadata, dict) else None
            content_text = fallback or chunk.get("chunk_id", "")

        vector_payload: List[float] = []
        vector_info = chunk.get("vector")
        if isinstance(vector_info, dict):
            vector_payload = list(vector_info.get("embedding") or [])
        if vector_payload:
            target_dim = settings.embedding_dimension
            if len(vector_payload) > target_dim:
                vector_payload = vector_payload[:target_dim]
            elif len(vector_payload) < target_dim:
                vector_payload = vector_payload + [0.0] * (target_dim - len(vector_payload))

        es_doc = {
            "chunk_id": chunk.get("chunk_id"),
            "document_id": (document or {}).get("document_id"),
            "title": metadata.get("title") if isinstance(metadata, dict) else chunk.get("chunk_id"),
            "path": source_info.get("file_path"),
            "content": content_text,
            "vector": vector_payload,
            "media_type": chunk.get("media_type"),
            "temporal": chunk.get("temporal"),
            "thumbnail": thumbnail_url,
            "video_path": video_path or source_info.get("file_path"),
            "audio_path": audio_path,
        }
        return es_doc

    def index_chunk(self, chunk: Dict[str, Any], document: Optional[Dict[str, Any]] = None) -> None:
        if self.client is None:
            self._memory_index.append(chunk)
            return
        payload = self._format_chunk_document(chunk, document)
        try:
            self.client.index(index=self.segments_index, id=chunk["chunk_id"], document=payload)
        except Exception:
            self._memory_index.append(chunk)

    def index_document(self, document: Dict[str, Any]) -> None:
        if self.client is None:
            self._memory_index.append(document)
            return
        try:
            self.client.index(index=self.documents_index, id=document["document_id"], document=document)
        except Exception:
            self._memory_index.append(document)

    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        if self.client is None:
            return self._memory_search(query, top_k)
        response = self.client.search(
            index=self.segments_index,
            query={
                "multi_match": {
                    "query": query,
                    "fields": ["content^2", "title"],
                }
            },
            size=top_k,
        )
        return [hit["_source"] for hit in response["hits"]["hits"]]

    def _memory_search(self, query: str, top_k: int) -> List[Dict[str, Any]]:
        hits: List[Dict[str, Any]] = []
        for doc in self._memory_index:
            content = doc.get("content", {})
            text_blob = ""
            if isinstance(content, dict):
                text = content.get("text")
                if isinstance(text, dict):
                    text_blob = text.get("full_text", "")
            if query.lower() in text_blob.lower():
                hits.append(doc)
            if len(hits) >= top_k:
                break
        return hits


search_client = SearchClient()
