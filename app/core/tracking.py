"""Request scoped tracking utilities."""
from __future__ import annotations

import contextvars
import time
import uuid
from dataclasses import dataclass
from typing import Optional


@dataclass
class RequestContext:
    request_id: str
    task_id: Optional[str] = None
    app_id: Optional[str] = None
    started_at: float = time.time()


_current_context: contextvars.ContextVar[RequestContext | None] = contextvars.ContextVar("request_context", default=None)


def new_context(task_id: Optional[str] = None, app_id: Optional[str] = None) -> RequestContext:
    ctx = RequestContext(request_id=str(uuid.uuid4()), task_id=task_id, app_id=app_id, started_at=time.time())
    _current_context.set(ctx)
    return ctx


def get_context() -> RequestContext:
    ctx = _current_context.get()
    if ctx is None:
        ctx = new_context()
    return ctx


def clear_context() -> None:
    _current_context.set(None)
