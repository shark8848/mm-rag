"""Media safety limits shared by API and pipeline."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from app.core.errors import APIError, get_error


@dataclass
class MediaLimit:
    max_size_mb: float
    max_duration_seconds: float | None = None


@dataclass
class LimitPolicy:
    default: MediaLimit
    per_media: Dict[str, MediaLimit]
    max_batch_files: int = 4
    max_batch_size_mb: float = 4096.0


class LimitChecker:
    def __init__(self, policy: LimitPolicy) -> None:
        self.policy = policy

    def _limit_for(self, media_type: str) -> MediaLimit:
        return self.policy.per_media.get(media_type, self.policy.default)

    def assert_file_size(self, media_type: str, path: Path) -> None:
        size_mb = path.stat().st_size / (1024 * 1024)
        limit = self._limit_for(media_type)
        if size_mb > limit.max_size_mb:
            raise APIError(
                get_error("ERR_MEDIA_TOO_LARGE"),
                detail=f"File {path.name} = {size_mb:.2f}MB exceeds {limit.max_size_mb}MB",
            )

    def assert_batch(self, file_count: int, total_size_mb: float) -> None:
        if file_count > self.policy.max_batch_files:
            raise APIError(
                get_error("ERR_THROTTLED"),
                detail=f"Batch has {file_count} files, limit {self.policy.max_batch_files}",
            )
        if total_size_mb > self.policy.max_batch_size_mb:
            raise APIError(
                get_error("ERR_MEDIA_TOO_LARGE"),
                detail=f"Batch size {total_size_mb:.1f}MB exceeds {self.policy.max_batch_size_mb}MB",
            )

    def assert_duration(self, media_type: str, duration_seconds: Optional[float]) -> None:
        if duration_seconds is None:
            return
        limit = self._limit_for(media_type)
        if limit.max_duration_seconds and duration_seconds > limit.max_duration_seconds:
            raise APIError(
                get_error("ERR_MEDIA_TOO_LARGE"),
                detail=f"Duration {duration_seconds:.0f}s exceeds {limit.max_duration_seconds:.0f}s",
            )
