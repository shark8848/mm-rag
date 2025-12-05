"""Shared API schemas aligning with the new engine contract."""
from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class ErrorEnvelope(BaseModel):
    status: str = Field(default="failure")
    error_code: str
    error_status: int
    message: str
    zh_message: Optional[str] = None
    context: Dict[str, Any] | None = None


class SuccessEnvelope(BaseModel):
    status: str = Field(default="success")
    data: Dict[str, Any]


class TaskResponse(BaseModel):
    task_id: str
    status: str
    detail: Optional[str] = None
    result: Optional[Dict[str, Any]] = None


class QueryHit(BaseModel):
    chunk_id: str
    document_id: str
    score: float | None = None
    title: Optional[str] = None
    content: Dict[str, Any] = Field(default_factory=dict)
    media_type: Optional[str] = None
    thumbnail: Optional[str] = None
    video_path: Optional[str] = None
    audio_path: Optional[str] = None


class QueryResponse(BaseModel):
    hits: list[QueryHit]
