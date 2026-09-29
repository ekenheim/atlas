"""`/api/v1/runs` reads.

- `GET /runs/{id}/role-calls`: every research-role call in the run, oldest first: the prompt
  version, the request and quoted retrieved data sent, each chat completion's routed model,
  tokens, raw content and validation errors, and the outcome (accepted with its output, or
  quarantined, failed or budget exhausted, with no output); plus the run's token totals.
"""

import uuid

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import Engine

from atlas.api.common import NOT_FOUND, not_found
from atlas.roles import RunRoleCalls, run_role_calls


def runs_router(engine: Engine) -> APIRouter:
    router = APIRouter(prefix="/api/v1/runs", tags=["runs"])

    @router.get("/{run_id}/role-calls", response_model=RunRoleCalls, responses=NOT_FOUND)
    def role_calls(  # pyright: ignore[reportUnusedFunction]
        run_id: uuid.UUID,
    ) -> RunRoleCalls | JSONResponse:
        with engine.connect() as connection:
            found = run_role_calls(connection, run_id)
        return found if found is not None else not_found("run")

    return router
