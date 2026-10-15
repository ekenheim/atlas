"""`/api/v1/calls` and a published Hypothesis's predictions (atlas-beliefs ticket 19).

- `GET /calls?theme=&origin=&state=&company_id=`: the dated record of what Atlas said, newest
  first, each call with its companies (and TradingView symbols), its checkpoints at +1, +3 and
  +6 months (the change since the call date, the theme's equal-weighted change over the same
  days, and the difference) and what falls due next. `origin` is `belief` (a Belief judged
  `proven`), `hypothesis` (a published version) or `signal` (a Scout session's question Issue
  escalating an archive lead); `state` is `open`, `settled` (all three checkpoints) or
  `unpriced`. Read-only: calls are made by those three events and settled by the daily
  `settle_calls` job; closes are never evidence.
- `POST /hypotheses/{id}/predictions` (201): record a prediction on a published version
  (`version`, `measure` or `prediction_index`, `expected_low`/`expected_high`, `deadline`,
  `source`: `fact`, `financial_observation` or `price`, `company_id`); 409
  `version_not_published`, 422 `deadline_not_after_publication`.
- `GET /hypotheses/{id}/predictions`, `GET /predictions?state=&hypothesis_status=`: each with its
  state (`open`, `settled`, `lapsed`) and settlement; every Hypothesis's, rejected ones included.
- `POST /hypotheses/{id}/predictions/{prediction_id}/settle`: append the settlement from the
  named source (`fact_id`, `observation_id`, or `day` for a stored close); 409 `already_settled`,
  `no_price`.

Every write is audited. Errors use the envelope.
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import Engine, text

from atlas.api.common import (
    CONFLICT,
    INVALID,
    NOT_FOUND,
    Page,
    Pagination,
    error_response,
    not_found,
    pagination,
)
from atlas.audit import Actor
from atlas.calls.model import Call, CallState, Origin
from atlas.calls.reads import list_calls
from atlas.hypotheses.model import HypothesisStatus
from atlas.hypotheses.predictions import (
    Prediction,
    PredictionCreate,
    PredictionError,
    Predictions,
    PredictionSettle,
    PredictionState,
    list_predictions,
)
from atlas.jobs.pacing import Clock, utc_now

Paged = Annotated[Pagination, Depends(pagination)]


def calls_router(engine: Engine) -> APIRouter:
    router = APIRouter(prefix="/api/v1/calls", tags=["calls"])

    @router.get("", response_model=Page[Call], responses=INVALID)
    def calls(  # pyright: ignore[reportUnusedFunction]
        page: Paged,
        theme: Annotated[str | None, Query(description="only this theme's")] = None,
        origin: Annotated[Origin | None, Query(description="belief, hypothesis or signal")] = None,
        state: Annotated[CallState | None, Query(description="open, settled or unpriced")] = None,
        company_id: Annotated[uuid.UUID | None, Query(description="only calls naming it")] = None,
    ) -> Page[Call]:
        with engine.connect() as connection:
            items, total = list_calls(
                connection,
                theme=theme,
                origin=origin,
                state=state,
                company_id=company_id,
                limit=page.limit,
                offset=page.offset,
            )
        return Page(items=items, total=total, limit=page.limit, offset=page.offset)

    return router


def predictions_router(engine: Engine, actor: Actor, clock: Clock = utc_now) -> APIRouter:
    router = APIRouter(tags=["predictions"])
    service = Predictions(engine, actor)

    def failed(error: PredictionError) -> JSONResponse:
        return error_response(error.status, error.code, str(error))

    @router.post(
        "/api/v1/hypotheses/{hypothesis_id}/predictions",
        status_code=201,
        response_model=Prediction,
        responses={**NOT_FOUND, **INVALID, **CONFLICT},
    )
    def record_prediction(  # pyright: ignore[reportUnusedFunction]
        hypothesis_id: uuid.UUID, request: PredictionCreate
    ) -> Prediction | JSONResponse:
        try:
            return service.create(hypothesis_id, request, clock().astimezone(UTC).date())
        except PredictionError as error:
            return failed(error)

    @router.get(
        "/api/v1/hypotheses/{hypothesis_id}/predictions",
        response_model=Page[Prediction],
        responses=NOT_FOUND,
    )
    def hypothesis_predictions(  # pyright: ignore[reportUnusedFunction]
        hypothesis_id: uuid.UUID, page: Paged
    ) -> Page[Prediction] | JSONResponse:
        with engine.connect() as connection:
            known = connection.execute(
                text("SELECT 1 FROM hypothesis WHERE id = :id"), {"id": hypothesis_id}
            ).first()
            if known is None:
                return not_found("hypothesis")
            items, total = list_predictions(
                connection,
                clock().astimezone(UTC).date(),
                hypothesis_id=hypothesis_id,
                limit=page.limit,
                offset=page.offset,
            )
        return Page(items=items, total=total, limit=page.limit, offset=page.offset)

    @router.post(
        "/api/v1/hypotheses/{hypothesis_id}/predictions/{prediction_id}/settle",
        response_model=Prediction,
        responses={**NOT_FOUND, **INVALID, **CONFLICT},
    )
    def settle_prediction(  # pyright: ignore[reportUnusedFunction]
        hypothesis_id: uuid.UUID, prediction_id: uuid.UUID, request: PredictionSettle
    ) -> Prediction | JSONResponse:
        now: datetime = clock()
        try:
            return service.settle(hypothesis_id, prediction_id, request, now)
        except PredictionError as error:
            return failed(error)

    @router.get("/api/v1/predictions", response_model=Page[Prediction], responses=INVALID)
    def predictions(  # pyright: ignore[reportUnusedFunction]
        page: Paged,
        state: Annotated[
            PredictionState | None, Query(description="open, settled or lapsed")
        ] = None,
        hypothesis_status: Annotated[
            HypothesisStatus | None, Query(description="e.g. rejected: those are kept and listed")
        ] = None,
        hypothesis_id: Annotated[uuid.UUID | None, Query()] = None,
    ) -> Page[Prediction]:
        with engine.connect() as connection:
            items, total = list_predictions(
                connection,
                clock().astimezone(UTC).date(),
                hypothesis_id=hypothesis_id,
                state=state,
                hypothesis_status=hypothesis_status,
                limit=page.limit,
                offset=page.offset,
            )
        return Page(items=items, total=total, limit=page.limit, offset=page.offset)

    return router
