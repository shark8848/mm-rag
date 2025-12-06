from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.routes_ingest import router as ingest_router
from app.api.routes_logs import router as logs_router
from app.api.routes_query import router as query_router
from app.api.schemas import ErrorEnvelope
from app.core.errors import APIError
from app.core.tracking import clear_context, new_context
from app.logging_utils import configure_logging

configure_logging()

app = FastAPI(title="Multimodal RAG Pipeline", version="0.1.0")
app.include_router(ingest_router)
app.include_router(logs_router)
app.include_router(query_router)


@app.middleware("http")
async def request_context(request: Request, call_next):
    ctx = new_context()
    request.state.request_id = ctx.request_id
    try:
        response = await call_next(request)
        return response
    finally:
        clear_context()


@app.exception_handler(APIError)
async def api_error_handler(_: Request, exc: APIError):
    payload = ErrorEnvelope(**exc.to_response())
    return JSONResponse(status_code=exc.error.status.value, content=payload.model_dump())


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}

