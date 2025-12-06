"""Vector query endpoint with authentication."""
from __future__ import annotations

import datetime as dt
from typing import Dict

from fastapi import APIRouter, Depends

from app.api.dependencies import authenticate
from app.api.schemas import QueryHit, QueryRequest, QueryResponse
from app.core.security import Credential
from app.core.tracking import new_context
from app.services.search_client import search_client

router = APIRouter(tags=["query"])


@router.post("/query", response_model=QueryResponse)
def query(
    request: QueryRequest,
    credential: Credential = Depends(authenticate),
) -> QueryResponse:
    new_context(app_id=credential.app_id)
    issued_at = dt.datetime.utcnow().isoformat()
    hits = search_client.search(request.query, request.top_k)
    normalized = [QueryHit(**hit) for hit in hits]
    return QueryResponse(issued_at=issued_at, query=request.query, hits=normalized)