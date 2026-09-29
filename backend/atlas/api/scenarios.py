"""`/api/v1/hypotheses/{id}/scenarios`: deterministic low/base/high scenarios attached to a
Hypothesis version (spec Phase 5 "Scenario"; §5.7, §8.2; ticket 19).

- `POST /hypotheses/{id}/scenarios` (201, `{"version", "as_of"?, "note"?, "assumptions"?}`):
  compute and store scenarios for that version. With `assumptions` (the researcher's table:
  `company_id`, `product`, `currency`, `inputs`), one scenario; every sourced input's source
  must stand as of the cutoff, or 422 `invalid_scenario` lists each problem (a figure with
  neither a source nor a basis is a 422 `invalid_request`). Without it, one scenario per table
  the investigation's Financial Analyst proposed (409 `no_analyst_proposal` if none). The
  cutoff is `as_of`, default the investigation's as-of time.
- `GET /hypotheses/{id}/scenarios[?version=]`: the scenarios, oldest first.
- `GET /hypotheses/{id}/scenarios/{scenario_id}`: one scenario.

Each scenario shows its inputs with their provenance, its outputs (every line per case, the
±20% sensitivity), the assumption and output hashes, the canonical output bytes, and whether
recomputing it gives the same bytes.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy import Engine

from atlas.api.common import CONFLICT, INVALID, NOT_FOUND, error_response, not_found
from atlas.audit import Actor
from atlas.hypotheses import get_hypothesis
from atlas.scenarios.model import AssumptionTable
from atlas.scenarios.service import (
    Scenario,
    ScenarioError,
    Scenarios,
    get_scenario,
    list_scenarios,
)


class ScenarioCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1, description="the Hypothesis version the scenarios attach to")
    as_of: AwareDatetime | None = Field(
        default=None, description="the cutoff for the sources; default the investigation's"
    )
    note: Annotated[str, Field(max_length=2000)] | None = None
    assumptions: AssumptionTable | None = Field(
        default=None,
        description="the researcher's assumption table; omitted: the Financial Analyst's",
    )


class ScenarioList(BaseModel):
    items: list[Scenario]


def scenarios_router(engine: Engine, actor: Actor) -> APIRouter:
    router = APIRouter(prefix="/api/v1/hypotheses", tags=["scenarios"])
    scenarios = Scenarios(engine)

    @router.post(
        "/{hypothesis_id}/scenarios",
        status_code=201,
        response_model=ScenarioList,
        responses={**NOT_FOUND, **CONFLICT, **INVALID},
    )
    def create(  # pyright: ignore[reportUnusedFunction]
        hypothesis_id: uuid.UUID, request: ScenarioCreate
    ) -> ScenarioList | JSONResponse:
        note = request.note.strip() or None if request.note is not None else None
        try:
            ids = scenarios.create(
                actor,
                hypothesis_id,
                request.version,
                assumptions=request.assumptions,
                as_of=request.as_of,
                note=note,
            )
        except ScenarioError as error:
            return error_response(error.status, error.code, error.message)
        with engine.connect() as connection:
            found = [get_scenario(connection, hypothesis_id, each) for each in ids]
        return ScenarioList(items=[each for each in found if each is not None])

    @router.get("/{hypothesis_id}/scenarios", response_model=ScenarioList, responses=NOT_FOUND)
    def listing(  # pyright: ignore[reportUnusedFunction]
        hypothesis_id: uuid.UUID, version: int | None = Query(default=None, ge=1)
    ) -> ScenarioList | JSONResponse:
        with engine.connect() as connection:
            if get_hypothesis(connection, hypothesis_id) is None:
                return not_found("hypothesis")
            return ScenarioList(items=list_scenarios(connection, hypothesis_id, version))

    @router.get(
        "/{hypothesis_id}/scenarios/{scenario_id}",
        response_model=Scenario,
        responses=NOT_FOUND,
    )
    def scenario(  # pyright: ignore[reportUnusedFunction]
        hypothesis_id: uuid.UUID, scenario_id: uuid.UUID
    ) -> Scenario | JSONResponse:
        with engine.connect() as connection:
            found = get_scenario(connection, hypothesis_id, scenario_id)
        return found if found is not None else not_found("scenario")

    return router
