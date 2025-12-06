"""Shared API schemas aligning with the new engine contract."""
from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


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


class ProcessingOptions(BaseModel):
    frame_strategy: Literal["interval", "scene"] = Field("interval")
    frame_interval_seconds: Optional[float] = Field(default=None, ge=0.5)
    scene_threshold: float = Field(default=0.3, ge=0.05, le=1.0)


class UserMetadata(BaseModel):
    document_id: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    custom_attributes: Dict[str, Any] = Field(default_factory=dict)


class IngestRequest(BaseModel):
    media_type: Literal["audio", "video"]
    source_path: str
    metadata: UserMetadata = Field(default_factory=UserMetadata)
    processing_options: Optional[ProcessingOptions] = None


class QueryHit(BaseModel):
    model_config = ConfigDict(extra="allow")
    chunk_id: Optional[str] = None
    document_id: Optional[str] = None
    score: float | None = None
    title: Optional[str] = None
    content: Any = None
    media_type: Optional[str] = None
    thumbnail: Optional[str] = None
    video_path: Optional[str] = None
    audio_path: Optional[str] = None


class QueryResponse(BaseModel):
    query: str
    issued_at: str
    hits: list[QueryHit]


class QueryRequest(BaseModel):
    query: str
    top_k: int = Field(default=5, le=20)
