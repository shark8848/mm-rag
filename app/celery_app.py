from __future__ import annotations

from celery import Celery

from app.config import settings

celery_app = Celery(
    "mm_rag_pipeline",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_default_queue=settings.celery_default_queue,
    task_routes={
        "pipeline.build_metadata": {"queue": settings.celery_io_queue},
        "pipeline.generate_chunks": {"queue": settings.celery_cpu_queue},
        "pipeline.generate_summary": {"queue": settings.celery_cpu_queue},
        "pipeline.persist_artifacts": {"queue": settings.celery_io_queue},
        "pipeline.index_document": {"queue": settings.celery_cpu_queue},
    },
    worker_hijack_root_logger=False,
)

celery_app.autodiscover_tasks(["app.pipeline"], related_name="celery_tasks")
