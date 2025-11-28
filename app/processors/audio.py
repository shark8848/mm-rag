from __future__ import annotations

import hashlib
import random
import shutil
import subprocess
from pathlib import Path
from typing import List

from app.config import settings
from app.logging_utils import get_pipeline_logger, log_timing
from app.models.mm_schema import AudioContent, Chunk, ChunkContent, TemporalInfo, TextContent, TextSegment, VectorInfo
from app.services.asr import transcribe
from app.services.bailian import bailian_client
from app.services.storage import sync_artifact


def _deterministic_random(seed: str) -> random.Random:
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    seed_int = int(digest[:16], 16)
    return random.Random(seed_int)


def chunk_text_segments(segments: List[TextSegment], chunk_duration: float) -> List[List[TextSegment]]:
    """Group segments by time windows."""

    grouped: List[List[TextSegment]] = []
    current: List[TextSegment] = []
    window_start = 0.0

    for seg in segments:
        if current and seg.end_time - window_start > chunk_duration:
            grouped.append(current)
            current = []
            window_start = seg.start_time
        if not current:
            window_start = seg.start_time
        current.append(seg)
    if current:
        grouped.append(current)
    return grouped


def _build_text_content(chunks: List[TextSegment]) -> TextContent:
    full_text = " ".join(seg.text for seg in chunks)
    word_count = len(full_text.split())
    return TextContent(full_text=full_text, segments=chunks, language="zh", word_count=word_count)


logger = get_pipeline_logger("pipeline.audio")


def _fake_embedding(text: str) -> List[float]:
    rnd = _deterministic_random(text)
    return [rnd.uniform(-1, 1) for _ in range(settings.embedding_dimension)]


def _build_embedding(text: str) -> List[float]:
    if bailian_client.enabled:
        try:
            vectors = bailian_client.embed_texts([text])
            if vectors:
                return vectors[0]
        except Exception as exc:  # pragma: no cover - API failure handled gracefully
            logger.warning(
                "Embedding model %s failed, fallback to deterministic vector: %s",
                settings.bailian_embedding_model,
                exc,
            )
    return _fake_embedding(text)


def _prepare_audio_track(source_path: Path, document_id: str) -> Path:
    settings.audio_intermediate_dir.mkdir(parents=True, exist_ok=True)
    target_path = settings.audio_intermediate_dir / f"{document_id}.wav"
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(source_path),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        str(settings.audio_sample_rate),
        "-ac",
        "1",
        str(target_path),
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        sync_artifact(target_path, "intermediate/audio")
        return target_path
    except Exception as exc:  # pragma: no cover - ffmpeg optional
        logger.warning("Audio extraction failed, falling back to source: %s", exc)
        try:
            shutil.copy(source_path, target_path)
            sync_artifact(target_path, "intermediate/audio")
            return target_path
        except Exception as copy_exc:  # pragma: no cover - best-effort fallback
            logger.warning("Audio copy fallback failed: %s", copy_exc)
    return source_path


def build_audio_chunks(audio_path: Path, base_chunk_id: str) -> List[Chunk]:
    prepared_audio = _prepare_audio_track(audio_path, base_chunk_id)
    with log_timing(logger, f"ASR transcription for {prepared_audio.name}"):
        segments = transcribe(prepared_audio)
    grouped = chunk_text_segments(segments, settings.chunk_max_duration)
    chunks: List[Chunk] = []
    total_duration = segments[-1].end_time if segments else 0.0

    with log_timing(logger, f"Chunk assembly for {audio_path.name}"):
        for idx, group in enumerate(grouped, start=1):
            text_content = _build_text_content(group)
            temporal = TemporalInfo(
                start_time=group[0].start_time,
                end_time=group[-1].end_time,
                duration=group[-1].end_time - group[0].start_time,
                chunk_index=idx,
            )
            embedding = _build_embedding(text_content.full_text)
            vector_model = settings.bailian_embedding_model if bailian_client.enabled else settings.embedding_model
            vector_dimension = len(embedding) or settings.embedding_dimension
            vector = VectorInfo(
                embedding=embedding,
                model=vector_model,
                model_version="1.0",
                dimension=vector_dimension,
                embedding_type="text",
            )
            audio_content = AudioContent(
                url=str(prepared_audio),
                format=prepared_audio.suffix.lstrip(".") or "wav",
                duration=temporal.duration,
                sample_rate=settings.audio_sample_rate,
                channels=1,
                codec="pcm_s16le",
            )
            chunk = Chunk(
                chunk_id=f"{base_chunk_id}-a{idx}",
                media_type="audio",
                temporal=temporal,
                content=ChunkContent(text=text_content, audio=audio_content),
                vector=vector,
                processing={"steps": [{"step_name": "whisper_transcribe", "status": "success"}]},
            )
            chunks.append(chunk)
    logger.info(
        "Built %d audio chunks for %s (%.2fs total)",
        len(chunks),
        audio_path.name,
        total_duration,
    )
    return chunks
