from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import List

from app.config import settings
from app.logging_utils import get_pipeline_logger, log_timing
from app.models.mm_schema import TextSegment
from app.services.bailian import bailian_client

try:
    import whisper
except ImportError:  # pragma: no cover - optional dependency
    whisper = None  # type: ignore


logger = get_pipeline_logger("pipeline.asr")


def _fallback_transcribe(audio_path: Path) -> List[TextSegment]:
    base = audio_path.stem.replace("_", " ") or "audio segment"
    segments: List[TextSegment] = []
    for idx, word in enumerate(base.split()):
        segments.append(
            TextSegment(
                index=idx,
                start_time=float(idx * 2),
                end_time=float(idx * 2 + 1.5),
                text=f"{word} placeholder transcription",
                speaker_id="spk1",
                confidence=0.0,
            )
        )
    return segments or [
        TextSegment(index=0, start_time=0.0, end_time=1.5, text="fallback transcription", speaker_id="spk1", confidence=0.0)
    ]


@lru_cache(maxsize=1)
def _load_model():
    if whisper is None:
        return None
    return whisper.load_model(settings.whisper_model)


def transcribe(audio_path: Path) -> List[TextSegment]:
    if bailian_client.enabled:
        try:
            with log_timing(logger, f"Bailian ASR for {audio_path.name}"):
                segments = bailian_client.transcribe_audio(audio_path, settings.asr_language)
            if segments:
                return segments
        except Exception as exc:  # pragma: no cover - bailian call best-effort
            logger.warning("Bailian ASR failed, falling back to Whisper: %s", exc)

    model = _load_model()
    if model is None:
        return _fallback_transcribe(audio_path)
    with log_timing(logger, f"Whisper ASR for {audio_path.name}"):
        result = model.transcribe(
            str(audio_path),
            language=settings.asr_language,
            verbose=False,
        )
    segments: List[TextSegment] = []
    for idx, seg in enumerate(result.get("segments", [])):
        segments.append(
            TextSegment(
                index=idx,
                start_time=float(seg.get("start", 0.0)),
                end_time=float(seg.get("end", 0.0)),
                text=seg.get("text", "").strip(),
                speaker_id=seg.get("speaker"),
                confidence=seg.get("avg_logprob"),
            )
        )
    return segments or _fallback_transcribe(audio_path)
