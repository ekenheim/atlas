"""`/api/v1/evaluations` reads: gold-set evaluation runs (`atlas evaluate`) and their results.

- `GET /evaluations?limit=&offset=`: runs, newest first: mode (`fake`: scripted model answers;
  `live`: the real model), model, code version, the gold manifest's hash, the cases asked
  for, status and pass counts.
- `GET /evaluations/{id}`: one run with its per-category tallies and every case's result:
  pass/fail, the score per metric, each gold check with what was observed, the predicted
  output and any error.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import Engine

from atlas.api.common import NOT_FOUND, Page, Pagination, not_found, pagination
from atlas.evaluation import EvaluationRun, EvaluationRunSummary, get_run, list_runs

Paged = Annotated[Pagination, Depends(pagination)]


def evaluations_router(engine: Engine) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["evaluations"])

    @router.get("/evaluations", response_model=Page[EvaluationRunSummary])
    def evaluations(page: Paged) -> Page[EvaluationRunSummary]:  # pyright: ignore[reportUnusedFunction]
        with engine.connect() as connection:
            items, total = list_runs(connection, limit=page.limit, offset=page.offset)
        return Page(items=items, total=total, limit=page.limit, offset=page.offset)

    @router.get("/evaluations/{run_id}", response_model=EvaluationRun, responses=NOT_FOUND)
    def evaluation(run_id: uuid.UUID) -> EvaluationRun | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        with engine.connect() as connection:
            found = get_run(connection, run_id)
        return found if found is not None else not_found("evaluation run")

    return router
