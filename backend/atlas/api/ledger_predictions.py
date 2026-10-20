"""`/api/v1/ledger-predictions`: the predictions the scheduled tasks' editions made (atlas-record
ticket 05), each recorded the first time its ID was seen, with its state derived now.

- `GET /ledger-predictions?state=&theme=&due_before=`: soonest deadline first. `state` is `open`,
  `lapsed`, `met` or `missed`; `theme` a theme's slug or `council`; `due_before` a day, the
  predictions whose deadline day is on or before it (one with a deadline that reads as no day is
  never due).
- `GET /ledger-predictions/{id}`: one, with its settlement.

The name is `ledger-predictions` because `/api/v1/predictions` is the Hypothesis predictions'
(ticket 07 retires those). The state is read against the application clock's day (UTC). Errors
use the envelope.
"""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import Engine

from atlas.api.common import INVALID, NOT_FOUND, Page, Pagination, not_found, pagination
from atlas.jobs.pacing import Clock, utc_now
from atlas.record.predictions import (
    LedgerPredictionState,
    RecordedPrediction,
    get_ledger_prediction,
    list_ledger_predictions,
    today_of,
)

Paged = Annotated[Pagination, Depends(pagination)]


def ledger_predictions_router(engine: Engine, clock: Clock = utc_now) -> APIRouter:
    router = APIRouter(prefix="/api/v1/ledger-predictions", tags=["ledger-predictions"])

    @router.get("", response_model=Page[RecordedPrediction], responses=INVALID)
    def ledger_predictions(  # pyright: ignore[reportUnusedFunction]
        page: Paged,
        state: Annotated[
            LedgerPredictionState | None, Query(description="open, lapsed, met or missed")
        ] = None,
        theme: Annotated[
            str | None, Query(description="a theme's slug; `council` for the council's")
        ] = None,
        due_before: Annotated[
            date | None, Query(description="deadline day on or before this day")
        ] = None,
    ) -> Page[RecordedPrediction]:
        items, total = list_ledger_predictions(
            engine,
            today_of(clock()),
            state=state,
            theme=theme,
            due_before=due_before,
            limit=page.limit,
            offset=page.offset,
        )
        return Page(items=items, total=total, limit=page.limit, offset=page.offset)

    @router.get("/{prediction_id}", response_model=RecordedPrediction, responses=NOT_FOUND)
    def ledger_prediction(  # pyright: ignore[reportUnusedFunction]
        prediction_id: uuid.UUID,
    ) -> RecordedPrediction | JSONResponse:
        found = get_ledger_prediction(engine, prediction_id, today_of(clock()))
        return found if found is not None else not_found("prediction")

    return router
