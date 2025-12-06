from __future__ import annotations

from typing import Any, Dict, Iterable, List

from celery import chain

from app.celery_app import celery_app
from app.logging_utils import get_pipeline_logger
from app.pipeline.stages.base import Stage
from app.pipeline.stages.chunks import ChunkStage
from app.pipeline.stages.index import IndexStage
from app.pipeline.stages.metadata import MetadataStage
from app.pipeline.stages.persist import PersistStage
from app.pipeline.stages.summary import SummaryStage
from app.pipeline.stages.utils import Context
from app.pipeline.stages.validation import ValidationStage
from app.pipeline.stages.vector import VectorStage

logger = get_pipeline_logger("pipeline.celery")


def _as_task_signature(stage: Stage) -> Any:
    @celery_app.task(name=f"pipeline.{stage.name}", queue=stage.queue)
    def _task(context: Context) -> Context:
        logger.info("Running stage %s", stage.name)
        return stage.run(context)

    return _task


def _build_stage_instances() -> List[Stage]:
    from app.core.limits import LimitChecker, LimitPolicy, MediaLimit
    from app.config import settings

    policy = LimitPolicy(
        default=MediaLimit(
            max_size_mb=max(settings.audio_max_size_mb, settings.video_max_size_mb, settings.pdf_max_size_mb)
        ),
        per_media={
            "audio": MediaLimit(
                max_size_mb=settings.audio_max_size_mb,
                max_duration_seconds=settings.audio_max_duration_sec,
            ),
            "video": MediaLimit(
                max_size_mb=settings.video_max_size_mb,
                max_duration_seconds=settings.video_max_duration_sec,
            ),
            "pdf": MediaLimit(max_size_mb=settings.pdf_max_size_mb),
        },
    )
    return [
        ValidationStage(checker=LimitChecker(policy)),
        MetadataStage(),
        ChunkStage(),
        SummaryStage(),
        VectorStage(),
        PersistStage(),
        IndexStage(),
    ]


STAGES: List[Stage] = _build_stage_instances()
TASKS: List[Any] = [_as_task_signature(stage) for stage in STAGES]


def enqueue_pipeline(context: Dict[str, Any]):
    workflow = chain(TASKS[0].s(context), *(sig.s() for sig in TASKS[1:]))
    return workflow.apply_async(task_id=context["document_id"])
