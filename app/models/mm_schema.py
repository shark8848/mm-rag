from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, validator


class SourceInfo(BaseModel):
    file_name: str
    file_path: str
    file_size: int
    format: str
    created_at: datetime


class DocumentMetadata(BaseModel):
    title: str
    description: Optional[str] = None
    source_info: SourceInfo
    duration: Optional[float] = None
    total_chunks: Optional[int] = None
    tags: List[str] = Field(default_factory=list)
    custom_attributes: dict = Field(default_factory=dict)


class TextSegment(BaseModel):
    index: int
    start_time: float
    end_time: float
    text: str
    speaker_id: Optional[str] = None
    confidence: Optional[float] = None


class TextContent(BaseModel):
    full_text: str
    segments: List[TextSegment]
    language: str = "zh"
    word_count: int


class AudioContent(BaseModel):
    url: str
    format: str
    duration: float
    sample_rate: int
    channels: int
    bitrate: Optional[int] = None
    codec: Optional[str] = None


class Resolution(BaseModel):
    width: int
    height: int


class VideoContent(BaseModel):
    url: str
    format: str
    duration: float
    resolution: Resolution
    fps: float
    bitrate: Optional[int] = None
    codec: Optional[str] = None
    aspect_ratio: Optional[str] = None


class Keyframe(BaseModel):
    timestamp: float
    thumbnail_url: str
    description: Optional[str] = None
    scene_change: bool = False
    embedding: List[float] = Field(default_factory=list)


class ChunkContent(BaseModel):
    text: Optional[TextContent] = None
    audio: Optional[AudioContent] = None
    video: Optional[VideoContent] = None
    keyframes: List[Keyframe] = Field(default_factory=list)


class TemporalInfo(BaseModel):
    start_time: float
    end_time: float
    duration: float
    chunk_index: int


class VectorInfo(BaseModel):
    embedding: List[float]
    model: str
    model_version: str
    dimension: int
    embedding_type: str

    @validator("dimension")
    def check_dimension(cls, v, values):
        embedding = values.get("embedding")
        if embedding and len(embedding) != v:
            raise ValueError("dimension must match embedding length")
        return v


class Chunk(BaseModel):
    chunk_id: str
    media_type: str
    temporal: TemporalInfo
    content: ChunkContent
    vector: VectorInfo
    analysis: dict = Field(default_factory=dict)
    quality_metrics: dict = Field(default_factory=dict)
    relations: dict = Field(default_factory=dict)
    processing: dict = Field(default_factory=dict)
    custom_fields: dict = Field(default_factory=dict)


class Document(BaseModel):
    document_id: str
    document_metadata: DocumentMetadata
    document_summary: Optional[dict] = None
    structure: List[dict] = Field(default_factory=list)
    chunks: List[Chunk]
