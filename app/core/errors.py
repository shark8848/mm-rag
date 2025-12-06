"""Centralized error codes and response helpers for the multimodal engine."""
from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class ErrorCode:
    code: str
    status: HTTPStatus
    message: str
    zh_message: str | None = None

    def as_dict(self, detail: Optional[str] = None) -> Dict[str, Any]:
        payload = {
            "status": "failure",
            "error_code": self.code,
            "error_status": self.status.value,
            "message": detail or self.message,
            "zh_message": self.zh_message or self.message,
        }
        return payload


class APIError(Exception):
    """Raised when a request violates contract or system state."""

    def __init__(self, error: ErrorCode, *, detail: Optional[str] = None, context: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(detail or error.message)
        self.error = error
        self.detail = detail
        self.context = context or {}

    def to_response(self) -> Dict[str, Any]:
        payload = self.error.as_dict(self.detail)
        if self.context:
            payload["context"] = self.context
        return payload


ERRORS: Dict[str, ErrorCode] = {
    "ERR_AUTH_REQUIRED": ErrorCode(
        code="ERR_AUTH_REQUIRED",
        status=HTTPStatus.UNAUTHORIZED,
        message="Authentication is required",
        zh_message="缺少认证信息",
    ),
    "ERR_AUTH_INVALID": ErrorCode(
        code="ERR_AUTH_INVALID",
        status=HTTPStatus.UNAUTHORIZED,
        message="Invalid app credentials",
        zh_message="appid 或 key 不正确",
    ),
    "ERR_MEDIA_TOO_LARGE": ErrorCode(
        code="ERR_MEDIA_TOO_LARGE",
        status=HTTPStatus.BAD_REQUEST,
        message="Media file exceeds configured limit",
        zh_message="媒体大小超过限制",
    ),
    "ERR_MEDIA_UNSUPPORTED": ErrorCode(
        code="ERR_MEDIA_UNSUPPORTED",
        status=HTTPStatus.BAD_REQUEST,
        message="Unsupported media type",
        zh_message="不支持的媒体类型",
    ),
    "ERR_THROTTLED": ErrorCode(
        code="ERR_THROTTLED",
        status=HTTPStatus.TOO_MANY_REQUESTS,
        message="Request rejected by throttling policy",
        zh_message="请求被限流",
    ),
    "ERR_DEPENDENCY_FAILURE": ErrorCode(
        code="ERR_DEPENDENCY_FAILURE",
        status=HTTPStatus.BAD_GATEWAY,
        message="Downstream dependency failed",
        zh_message="依赖服务异常",
    ),
    "ERR_INTERNAL": ErrorCode(
        code="ERR_INTERNAL",
        status=HTTPStatus.INTERNAL_SERVER_ERROR,
        message="Internal server error",
        zh_message="内部错误",
    ),
}


def get_error(code: str) -> ErrorCode:
    if code not in ERRORS:
        return ERRORS["ERR_INTERNAL"]
    return ERRORS[code]
