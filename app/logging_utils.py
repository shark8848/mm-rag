from __future__ import annotations

import logging
import logging.config
import time
from contextlib import contextmanager
from pathlib import Path

from app.config import settings

_LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
_configured = False


def _build_logging_config(log_file: Path) -> dict:
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {"format": _LOG_FORMAT},
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "standard",
                "level": settings.log_level,
            },
            "pipeline_file": {
                "class": "logging.handlers.RotatingFileHandler",
                "formatter": "standard",
                "level": settings.log_level,
                "filename": str(log_file),
                "maxBytes": 5 * 1024 * 1024,
                "backupCount": 5,
                "encoding": "utf-8",
            },
        },
        "root": {
            "level": settings.log_level,
            "handlers": ["console"],
        },
        "loggers": {
            "pipeline": {
                "handlers": ["console", "pipeline_file"],
                "level": settings.log_level,
                "propagate": False,
            },
            "pipeline.storage": {
                "handlers": ["pipeline_file"],
                "level": settings.log_level,
                "propagate": True,
            },
        },
    }


def configure_logging() -> None:
    global _configured  # noqa: PLW0603
    if _configured:
        return
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = settings.logs_dir / "pipeline.log"
    logging.config.dictConfig(_build_logging_config(log_file))
    _configured = True


def get_pipeline_logger(name: str = "pipeline") -> logging.Logger:
    if not _configured:
        configure_logging()
    return logging.getLogger(name)


@contextmanager
def log_timing(logger: logging.Logger, operation: str, level: int = logging.INFO):
    start = time.perf_counter()
    try:
        yield
    except Exception:  # pragma: no cover - log and re-raise
        duration = time.perf_counter() - start
        logger.exception("%s failed after %.2fs", operation, duration)
        raise
    else:
        duration = time.perf_counter() - start
        logger.log(level, "%s completed in %.2fs", operation, duration)
