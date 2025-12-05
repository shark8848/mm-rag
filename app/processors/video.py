from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.config import settings
from app.logging_utils import get_pipeline_logger, log_timing
from app.models.mm_schema import Chunk, ChunkContent, Keyframe, Resolution, VideoContent
from app.processors.audio import build_audio_chunks
from app.services.bailian import bailian_client
from app.services.vector_service import vector_service
from app.services.storage import sync_artifact


logger = get_pipeline_logger("pipeline.video")


def _mock_video_metadata(video_path: Path) -> dict:
    """当 ffprobe 失败时根据文件大小粗略推断时长/分辨率。"""

    size = video_path.stat().st_size if video_path.exists() else 10_000_000
    duration = max(30.0, size / 500_000)
    return {
        "duration": duration,
        "fps": 25.0,
        "resolution": Resolution(width=1280, height=720),
        "aspect_ratio": "16:9",
    }


def _parse_frame_rate(value: str | None) -> float:
    """容错解析 ffprobe 帧率，默认回落到 25fps。"""

    if not value or value == "0/0":
        return 25.0
    if "/" in value:
        num, denom = value.split("/", 1)
        try:
            return float(num) / float(denom)
        except (ValueError, ZeroDivisionError):
            return 25.0
    try:
        return float(value)
    except ValueError:
        return 25.0


def _probe_video(video_path: Path) -> dict:
    """调用 ffprobe 获取时长、fps、分辨率等基础信息。"""

    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_streams",
        "-show_format",
        str(video_path),
    ]
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        info = json.loads(result.stdout)
    except Exception as exc:  # pragma: no cover - ffmpeg optional
        logger.warning("ffprobe failed, using mock metadata: %s", exc)
        return _mock_video_metadata(video_path)

    video_stream = None
    for stream in info.get("streams", []):
        if stream.get("codec_type") == "video":
            video_stream = stream
            break
    if not video_stream:
        return _mock_video_metadata(video_path)

    width = int(video_stream.get("width", 1280))
    height = int(video_stream.get("height", 720))
    duration = float(
        video_stream.get("duration")
        or info.get("format", {}).get("duration")
        or _mock_video_metadata(video_path)["duration"]
    )
    fps = _parse_frame_rate(video_stream.get("avg_frame_rate"))
    aspect_ratio = video_stream.get("display_aspect_ratio") or f"{width}:{height}"
    return {
        "duration": duration,
        "fps": fps,
        "resolution": Resolution(width=width, height=height),
        "aspect_ratio": aspect_ratio,
    }


def _prepare_frame_dir(document_id: str) -> Path:
    """为关键帧生成独立目录，并清理历史帧。"""

    target_dir = settings.video_intermediate_dir / document_id
    target_dir.mkdir(parents=True, exist_ok=True)
    for frame_file in target_dir.glob("frame_*.jpg"):
        frame_file.unlink()
    return target_dir


def _resolve_frame_options(options: Optional[Dict[str, Any]]) -> Tuple[str, float, float]:
    """解析 UI 传入的抽帧策略，限制边界防止异常输入。"""

    opts = options or {}
    strategy = opts.get("frame_strategy") or "interval"
    if strategy not in {"interval", "scene"}:
        strategy = "interval"
    interval = opts.get("frame_interval_seconds") or settings.frame_interval_seconds
    try:
        interval_value = float(interval)
    except (TypeError, ValueError):
        interval_value = settings.frame_interval_seconds
    interval_value = max(0.5, interval_value)
    scene_threshold = opts.get("scene_threshold", 0.3)
    try:
        threshold_value = float(scene_threshold)
    except (TypeError, ValueError):
        threshold_value = 0.3
    threshold_value = min(max(threshold_value, 0.05), 1.0)
    return strategy, interval_value, threshold_value


def _extract_frames(
    video_path: Path,
    document_id: str,
    strategy: str,
    interval_seconds: float,
    scene_threshold: float,
    clip_duration: float,
) -> List[Tuple[float, Path]]:
    """根据策略抽帧，生成 (timestamp, frame_path) 对。"""

    target_dir = _prepare_frame_dir(document_id)
    output_pattern = target_dir / "frame_%04d.jpg"
    if strategy == "scene":
        vf_filter = f"select='eq(n,0)+gt(scene,{scene_threshold})'"
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(video_path),
            "-vf",
            vf_filter,
            "-vsync",
            "vfr",
            "-q:v",
            "2",
            str(output_pattern),
        ]
    else:
        vf_filter = f"fps=1/{interval_seconds}"
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(video_path),
            "-vf",
            vf_filter,
            "-q:v",
            "2",
            str(output_pattern),
        ]
    try:
        subprocess.run(cmd, check=True)
    except Exception as exc:  # pragma: no cover - ffmpeg optional
        logger.warning("Frame extraction failed, falling back to mock keyframes: %s", exc)
        return []

    frame_paths = sorted(target_dir.glob("frame_*.jpg"))
    if not frame_paths:
        logger.warning("No frames extracted for %s", video_path.name)
        return []

    limited_paths = frame_paths[: settings.video_max_keyframes]
    for frame_path in limited_paths:
        sync_artifact(frame_path, "intermediate/video")

    if strategy == "scene":
        if len(limited_paths) == 1:
            timestamps = [0.0]
        else:
            step = max(clip_duration / max(len(limited_paths) - 1, 1), 0.5)
            timestamps = [min(idx * step, clip_duration) for idx in range(len(limited_paths))]
    else:
        timestamps = [min(idx * interval_seconds, clip_duration) for idx in range(len(limited_paths))]

    frames: List[Tuple[float, Path]] = []
    for timestamp, frame in zip(timestamps, limited_paths):
        frames.append((timestamp, frame))
    return frames


def _describe_frames(frame_paths: Sequence[Path]) -> List[str]:
    """调用图像理解模型生成关键帧描述，若未启用则返回空串。"""

    descriptions: List[str] = []
    if not bailian_client.enabled:
        return ["" for _ in frame_paths]
    with log_timing(logger, f"Frame captioning x{len(frame_paths)}"):
        for frame_path in frame_paths:
            description = bailian_client.describe_image(frame_path)
            descriptions.append(description)
    return descriptions


def _embed_descriptions(descriptions: Sequence[str]) -> List[List[float]]:
    """对非空描述批量生成文本向量，保持与帧索引对应。"""

    non_empty = [(idx, desc) for idx, desc in enumerate(descriptions) if desc]
    if not non_empty:
        return [[] for _ in descriptions]
    vectors = vector_service.embed_texts([desc for _, desc in non_empty])
    embeddings: List[List[float]] = [[] for _ in descriptions]
    for (idx, _), vector in zip(non_empty, vectors):
        embeddings[idx] = vector
    return embeddings


def _build_keyframes(entries: List[Tuple[float, Path]]) -> List[Keyframe]:
    """把抽帧结果扩展为带描述+向量的 Keyframe 模型。"""

    if not entries:
        return []
    timestamps = [entry[0] for entry in entries]
    frame_paths = [entry[1] for entry in entries]
    descriptions = _describe_frames(frame_paths)
    embeddings = _embed_descriptions(descriptions)

    keyframes: List[Keyframe] = []
    for idx, (timestamp, frame_path) in enumerate(entries):
        description = descriptions[idx] or f"Frame at {timestamp:.1f}s"
        embedding = embeddings[idx] if idx < len(embeddings) else []
        keyframes.append(
            Keyframe(
                timestamp=timestamp,
                thumbnail_url=str(frame_path),
                description=description,
                scene_change=idx % 5 == 0,
                embedding=embedding,
            )
        )
    return keyframes


def _assign_keyframes(chunks: List[Chunk], keyframes: List[Keyframe]) -> None:
    """按时间范围把关键帧挂载到 Chunk，缺省时整体共享。"""

    if not keyframes:
        return
    for chunk in chunks:
        relevant = [
            frame
            for frame in keyframes
            if chunk.temporal.start_time <= frame.timestamp <= chunk.temporal.end_time
        ]
        chunk.content.keyframes = relevant or keyframes


def _fallback_frames(interval_seconds: float, clip_duration: float) -> List[Tuple[float, Path]]:
    """当 ffmpeg 抽帧失败时生成占位帧路径，确保后续流程不中断。"""

    effective_interval = max(interval_seconds, 0.5)
    steps = max(1, math.floor(clip_duration / effective_interval))
    return [
        (min(idx * effective_interval, clip_duration), Path(f"frames/frame_{idx:04d}.jpg"))
        for idx in range(steps)
    ][: settings.video_max_keyframes]


def build_video_chunks(
    video_path: Path,
    base_chunk_id: str,
    processing_options: Optional[Dict[str, Any]] = None,
) -> List[Chunk]:
    """视频流程=音频 Chunk + 关键帧增强 + 视频元数据。"""

    with log_timing(logger, f"Audio chunk generation for {video_path.name}"):
        audio_chunks = build_audio_chunks(video_path, base_chunk_id)
    with log_timing(logger, f"Video metadata probe for {video_path.name}"):
        metadata = _probe_video(video_path)

    strategy, interval_seconds, scene_threshold = _resolve_frame_options(processing_options)
    logger.info(
        "Video frame strategy=%s interval=%.2fs scene_threshold=%.2f",
        strategy,
        interval_seconds,
        scene_threshold,
    )

    with log_timing(logger, f"Frame extraction for {video_path.name}"):
        frame_entries = _extract_frames(
            video_path,
            base_chunk_id,
            strategy,
            interval_seconds,
            scene_threshold,
            metadata["duration"],
        )
    if not frame_entries:
        frame_entries = _fallback_frames(interval_seconds, metadata["duration"])
    with log_timing(logger, f"Frame understanding for {video_path.name}"):
        keyframes = _build_keyframes(frame_entries)

    video_content = VideoContent(
        url=str(video_path),
        format=video_path.suffix.lstrip("."),
        duration=metadata["duration"],
        resolution=metadata["resolution"],
        fps=metadata["fps"],
        bitrate=1200,
        codec="h264",
        aspect_ratio=metadata["aspect_ratio"],
    )

    augmented_chunks: List[Chunk] = []
    _assign_keyframes(audio_chunks, keyframes)
    for chunk in audio_chunks:
        chunk.media_type = "audio_video"
        chunk.content.video = video_content
        augmented_chunks.append(chunk)
    logger.info(
        "Video processing complete for %s with %d keyframes",
        video_path.name,
        len(keyframes),
    )
    return augmented_chunks
