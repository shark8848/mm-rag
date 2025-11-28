from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

import dashscope
from dashscope.aigc.multimodal_conversation import MultiModalConversation
from dashscope.audio.asr import Transcription
from dashscope.embeddings.text_embedding import TextEmbedding
from dashscope.utils.oss_utils import upload_file

from app.config import settings
from app.logging_utils import get_pipeline_logger
from app.models.mm_schema import TextSegment


logger = get_pipeline_logger("pipeline.bailian")


class BailianClient:
    """Wrapper around Alibaba Bailian (DashScope) APIs with SDK-first access."""

    def __init__(self) -> None:
        self.api_key = settings.bailian_api_key or os.environ.get("DASHSCOPE_API_KEY")
        base = settings.bailian_base_url.rstrip("/") if settings.bailian_base_url else None
        if base:
            os.environ.setdefault("DASHSCOPE_HTTP_BASE_URL", base)
            if base.startswith("https://"):
                os.environ.setdefault("DASHSCOPE_WEBSOCKET_BASE_URL", base.replace("https://", "wss://"))
        if self.api_key:
            dashscope.api_key = self.api_key
        self.base_url = base or os.environ.get("DASHSCOPE_HTTP_BASE_URL", "https://dashscope.aliyuncs.com/api/v1")
        self.enabled = bool(self.api_key)

    # -------- Internal helpers --------
    def _headers(self, content_type: str | None = None) -> Dict[str, str]:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def _post_json(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self.enabled:
            raise RuntimeError("Bailian API key is not configured")
        response = requests.post(
            f"{self.base_url}{path}",
            headers=self._headers("application/json"),
            data=json.dumps(payload),
            timeout=45,
        )
        response.raise_for_status()
        return response.json()

    def _parse_segments(self, payload: Dict[str, Any]) -> List[TextSegment]:
        segments_raw = (
            payload.get("result", {}).get("segments")
            or payload.get("output", {}).get("segments")
            or payload.get("segments")
            or []
        )
        segments: List[TextSegment] = []
        for idx, seg in enumerate(segments_raw):
            start_val = seg.get("start_time") or seg.get("begin_time") or seg.get("start") or 0.0
            end_val = seg.get("end_time") or seg.get("stop_time") or seg.get("end") or start_val
            segments.append(
                TextSegment(
                    index=idx,
                    start_time=float(start_val),
                    end_time=float(end_val),
                    text=str(seg.get("text") or seg.get("sentence") or "").strip(),
                    speaker_id=seg.get("speaker_id") or seg.get("speaker"),
                    confidence=seg.get("confidence") or seg.get("score"),
                )
            )
        return segments

    def _transcribe_via_sdk(self, audio_path: Path, language: Optional[str]) -> List[TextSegment]:
        if not self.enabled:
            raise RuntimeError("Bailian API key is not configured")
        logger.info(
            "Invoking DashScope ASR model %s via SDK for %s",
            settings.bailian_asr_model,
            audio_path.name,
        )
        # Upload local media to OSS via DashScope helper utilities.
        upload_url = upload_file(settings.bailian_asr_model, f"file://{audio_path}", self.api_key)
        request_kwargs: Dict[str, Any] = {}
        if language:
            request_kwargs["language"] = language
        response = Transcription.call(
            model=settings.bailian_asr_model,
            file_urls=[upload_url],
            **request_kwargs,
        )
        task_info = response.output or {}
        if task_info.get("task_status") != "SUCCEEDED":
            raise RuntimeError(task_info.get("message") or "ASR task failed")
        results = task_info.get("results") or []
        if not results:
            return []
        # SDK responses list segments per file entry.
        segments = results[0].get("segments") or []
        if not segments:
            raise RuntimeError("ASR task returned no segments")
        normalized_payload = {"segments": segments}
        return self._parse_segments(normalized_payload)

    # -------- Public endpoints --------
    def transcribe_audio(self, audio_path: Path, language: Optional[str] = None) -> List[TextSegment]:
        if not self.enabled:
            raise RuntimeError("Bailian API key is not configured")
        try:
            return self._transcribe_via_sdk(audio_path, language)
        except Exception as exc:
            logger.warning("DashScope SDK ASR failed, falling back to REST: %s", exc)

        # Fallback to legacy REST endpoint for compatibility.
        data = {"model": settings.bailian_asr_model}
        if language:
            data["language"] = language
        logger.info(
            "Invoking Bailian REST ASR model %s for %s",
            settings.bailian_asr_model,
            audio_path.name,
        )
        with audio_path.open("rb") as audio_file:
            files = {"file": (audio_path.name, audio_file, "application/octet-stream")}
            response = requests.post(
                f"{self.base_url}/api/v1/services/audio/asr",
                headers=self._headers(),
                data=data,
                files=files,
                timeout=90,
            )
        response.raise_for_status()
        payload = response.json()
        return self._parse_segments(payload)

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        if self.enabled:
            try:
                logger.info(
                    "Invoking DashScope embedding model %s for %d texts",
                    settings.bailian_embedding_model,
                    len(texts),
                )
                resp = TextEmbedding.call(
                    model=settings.bailian_embedding_model,
                    input=texts,
                    output_type="embedding",
                )
                vectors: List[List[float]] = []
                for item in resp.output.get("embeddings", []):
                    vectors.append(item.get("embedding", []))
                if vectors:
                    return vectors
            except Exception as exc:  # pragma: no cover - API failure best-effort
                logger.warning("DashScope embedding failed, using REST fallback: %s", exc)

        payload = {"model": settings.bailian_embedding_model, "input": texts}
        logger.info(
            "Invoking Bailian REST embedding model %s for %d texts",
            settings.bailian_embedding_model,
            len(texts),
        )
        data = self._post_json("/api/v1/services/embeddings/text-embedding", payload)
        vectors: List[List[float]] = []
        for item in data.get("data", []):
            vectors.append(item.get("embedding", []))
        return vectors

    def multimodal_summary(self, prompt: str) -> str:
        if self.enabled:
            try:
                messages = [{"role": "user", "content": [{"text": prompt}]}]
                logger.info(
                    "Invoking DashScope multimodal model %s for summary",
                    settings.bailian_multimodal_model,
                )
                resp = MultiModalConversation.call(
                    model=settings.bailian_multimodal_model,
                    messages=messages,
                )
                choices = resp.output.get("choices", [])
                if choices:
                    contents = choices[0].get("message", {}).get("content", [])
                    for content in contents:
                        if "text" in content:
                            return content["text"].strip()
            except Exception as exc:  # pragma: no cover - API failure best-effort
                logger.warning("DashScope multimodal summary failed, using REST fallback: %s", exc)

        payload = {
            "model": settings.bailian_multimodal_model,
            "input": [
                {
                    "role": "user",
                    "content": [{"text": prompt}],
                }
            ],
        }
        logger.info(
            "Invoking Bailian REST multimodal model %s for summary",
            settings.bailian_multimodal_model,
        )
        data = self._post_json("/api/v1/services/vision/multimodal-conversation", payload)
        outputs = data.get("output", {}).get("choices", [])
        if not outputs:
            return ""
        messages = outputs[0].get("message", {}).get("content", [])
        for content in messages:
            if "text" in content:
                return content["text"].strip()
        return ""

    def chat_completion(self, messages: List[Dict[str, str]]) -> str:
        payload = {"model": settings.bailian_llm_model, "input": messages}
        logger.info(
            "Invoking Bailian REST LLM model %s with %d messages",
            settings.bailian_llm_model,
            len(messages),
        )
        data = self._post_json("/api/v1/services/aigc/text-generation", payload)
        choices = data.get("output", {}).get("choices", [])
        if not choices:
            return ""
        return choices[0].get("text", "").strip()

    def describe_image(self, image_path: Path, prompt: str | None = None) -> str:
        if not self.enabled:
            return ""
        instruction = prompt or "请用一句话描述画面内容。"
        logger.info(
            "Invoking DashScope multimodal model %s for frame %s",
            settings.bailian_multimodal_model,
            image_path.name,
        )
        messages = [
            {
                "role": "user",
                "content": [
                    {"image": f"file://{image_path}"},
                    {"text": instruction},
                ],
            }
        ]
        try:
            resp = MultiModalConversation.call(
                model=settings.bailian_multimodal_model,
                messages=messages,
            )
        except Exception as exc:  # pragma: no cover - API failure best-effort
            logger.warning("Frame understanding failed: %s", exc)
            return ""
        choices = resp.output.get("choices", [])
        if not choices:
            return ""
        contents = choices[0].get("message", {}).get("content", [])
        for content in contents:
            if "text" in content:
                return content["text"].strip()
        return ""

bailian_client = BailianClient()
