"""FastAPI dependencies for auth, limits, and request context."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import Depends, Header

from app.config import BASE_DIR, settings
from app.core.limits import LimitChecker, LimitPolicy, MediaLimit
from app.core.security import AuthConfig, AuthManager, Credential
from app.services.vector_service import VectorService, vector_service


def _resolve_secrets_path(path_value: Optional[str]) -> Optional[Path]:
    if not path_value:
        return None
    candidate = Path(path_value)
    if not candidate.is_absolute():
        candidate = BASE_DIR / candidate
    return candidate


auth_config = AuthConfig(
    required=settings.api_auth_required,
    secrets_path=_resolve_secrets_path(settings.api_secrets_path),
)

auth_manager = AuthManager(auth_config)

limit_policy = LimitPolicy(
    default=MediaLimit(max_size_mb=max(settings.audio_max_size_mb, settings.video_max_size_mb)),
    per_media={
        "audio": MediaLimit(
            max_size_mb=settings.audio_max_size_mb,
            max_duration_seconds=settings.audio_max_duration_sec,
        ),
        "video": MediaLimit(
            max_size_mb=settings.video_max_size_mb,
            max_duration_seconds=settings.video_max_duration_sec,
        ),
    },
    max_batch_files=settings.upload_max_files,
    max_batch_size_mb=settings.upload_max_batch_mb,
)

limit_checker = LimitChecker(limit_policy)


def authenticate(
    app_id: Optional[str] = Header(default=None, alias="X-Appid"),
    app_key: Optional[str] = Header(default=None, alias="X-Key"),
) -> Credential:
    return auth_manager.assert_credentials(app_id, app_key)


def get_limit_checker() -> LimitChecker:
    return limit_checker


def get_vector_service() -> VectorService:
    return vector_service