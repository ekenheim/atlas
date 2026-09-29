"""`/api/v1/memory`: recall and reflect with resolved citations (spec Part B stories 16-25).

- `POST /memory/recall`: synchronous, strictly scoped by company and theme IDs; each memory
  comes with its provenance (resolved to a Source Version section, or why not) and the
  response lists the Evidence behind the resolved ones
- `POST /memory/reflect` (202): records a pending research answer and enqueues its `reflect`
  job; an optional response schema must be a JSON Schema object without union types
- `GET /memory/reflect/{id}`: the stored research answer: text, structured output and its
  error, raw citations, and every citation with its state (resolved, unverified, broken);
  only resolved citations are presented as `evidence`

Refusals use the error envelope: 422 `unknown_company` / `unknown_theme` /
`invalid_response_schema` / `invalid_request`, 503 `hindsight_not_configured`, 502
`hindsight_unavailable` / `hindsight_error` (recall), 404 `not_found`.
"""

import uuid
from functools import cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import Engine

from atlas.api.common import NOT_FOUND, ErrorEnvelope, error_response, not_found
from atlas.archive import Archive
from atlas.audit import Actor
from atlas.companies import Universe, load_universe
from atlas.hindsight import HindsightError, HindsightGateway, HindsightUnavailable
from atlas.research import (
    RecallRequest,
    RecallResponse,
    ReflectRequest,
    Research,
    ResearchAnswer,
    ResearchRefused,
    research_answer,
)

_INVALID: dict[int | str, dict[str, Any]] = {422: {"model": ErrorEnvelope}}
_UNAVAILABLE: dict[int | str, dict[str, Any]] = {
    502: {"model": ErrorEnvelope},
    503: {"model": ErrorEnvelope},
}


class ReflectAccepted(BaseModel):
    research_answer: ResearchAnswer
    job_id: uuid.UUID
    audit_event_id: int


def research_router(
    engine: Engine,
    archive: Archive,
    gateway: HindsightGateway | None,
    actor: Actor,
    themes_config: Path,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/memory", tags=["memory"])

    @cache
    def universe() -> Universe:  # read on first use, so the app starts without it
        return load_universe(themes_config)

    research = Research(engine, archive, gateway, actor, universe) if gateway is not None else None

    def not_configured() -> JSONResponse:
        return error_response(
            503, "hindsight_not_configured", "Hindsight is not configured (ATLAS_HINDSIGHT_URL)"
        )

    @router.post("/recall", response_model=RecallResponse, responses={**_INVALID, **_UNAVAILABLE})
    def recall(request: RecallRequest) -> RecallResponse | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        if research is None:
            return not_configured()
        try:
            return research.recall(request)
        except ResearchRefused as refusal:
            return error_response(422, refusal.code, refusal.message)
        except HindsightUnavailable as error:
            return error_response(502, "hindsight_unavailable", str(error))
        except HindsightError as error:
            return error_response(502, "hindsight_error", str(error))

    @router.post(
        "/reflect",
        status_code=202,
        response_model=ReflectAccepted,
        responses={**_INVALID, **_UNAVAILABLE},
    )
    def reflect(request: ReflectRequest) -> ReflectAccepted | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        if research is None:
            return not_configured()
        try:
            answer_id, job_id, event = research.request_reflect(request)
        except ResearchRefused as refusal:
            return error_response(422, refusal.code, refusal.message)
        with engine.connect() as connection:
            stored = research_answer(connection, answer_id)
        assert stored is not None
        return ReflectAccepted(research_answer=stored, job_id=job_id, audit_event_id=event.id)

    @router.get(
        "/reflect/{answer_id}",
        response_model=ResearchAnswer,
        responses={**NOT_FOUND, **_INVALID},
    )
    def reflect_answer(answer_id: uuid.UUID) -> ResearchAnswer | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        with engine.connect() as connection:
            found = research_answer(connection, answer_id)
        return found if found is not None else not_found("research answer")

    return router
