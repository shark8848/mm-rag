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


class MineruOptions(BaseModel):
    """Fine-grained options for MinerU PDF parsing, exposed in /docs for PDF ingest."""

    split_mode: Literal["page", "section", "auto"] = Field(
        "page",
        description="控制 MinerU 的拆分粒度：page=逐页，section=按章节，auto=由 MinerU 自动判定。",
    )
    page_range: Optional[str] = Field(
        default=None,
        description="可选，限制解析页范围，形如 '1-5,8,10-'。缺省表示全文。",
    )
    include_images: bool = Field(
        default=False,
        description="是否提取并返回图像/表格截图等资源引用，默认为否以减少体积。",
    )
    table_format: Literal["markdown", "html", "raw"] = Field(
        "markdown",
        description="表格内容的目标格式，支持 markdown/html/raw JSON。",
    )


class ProcessingOptions(BaseModel):
    frame_strategy: Literal["interval", "scene"] = Field(
        "interval",
        description="video 媒体的抽帧策略：interval=定间隔，scene=场景变化。",
    )
    frame_interval_seconds: Optional[float] = Field(
        default=None,
        ge=0.5,
        description="interval 策略的抽帧间隔（秒），未指定时使用全局配置。",
    )
    scene_threshold: float = Field(
        default=0.3,
        ge=0.05,
        le=1.0,
        description="scene 策略的场景变化灵敏度，0.05-1.0，值越高越少帧。",
    )
    mineru: Optional[MineruOptions] = Field(
        default=None,
        description="PDF 解析时的 MinerU 透传参数，仅在 media_type=pdf 时生效。",
    )
    mineru: Dict[str, Any] | None = None


class UserMetadata(BaseModel):
    document_id: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    custom_attributes: Dict[str, Any] = Field(default_factory=dict)


class IngestRequest(BaseModel):
    media_type: Literal["audio", "video", "pdf"] = Field(
        description="媒体类型：audio/video/pdf。PDF 会自动走 MinerU 解析。"
    )
    source_path: str = Field(description="后台可访问的绝对路径，例如 /data/raw/file.pdf。")
    metadata: UserMetadata = Field(
        default_factory=UserMetadata,
        description="业务侧可注入的标题/标签/自定义属性，最终写入 mm-schema。",
    )
    processing_options: Optional[ProcessingOptions] = Field(
        default=None,
        description="媒体处理参数：视频抽帧/场景、PDF 的 MinerU 设置等。",
    )


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
