"""`/api/v1` reads of retention into memory.

- `GET /source-versions/{id}/memory`: the version's section documents in the research bank,
  with their retain states, fact counts, and the Hindsight operations that retained them.
- `GET /memory/health[?company_id=]`: what the bank holds and what it lost, from Atlas's
  records and Hindsight's read-only listings (`atlas.retention.health`); a failed Hindsight
  listing makes only its part `unavailable`. 404 for an unknown company.
"""

import uuid
from collections.abc import Callable

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import Engine

from atlas.api.common import NOT_FOUND, not_found
from atlas.companies import Universe, extend_universe
from atlas.hindsight import HindsightGateway
from atlas.retention import SourceVersionMemory, source_version_memory
from atlas.retention.health import MemoryHealth, memory_health


def memory_router(
    engine: Engine,
    bank_id: str,
    gateway: HindsightGateway | None = None,
    universe: Callable[[], Universe] | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["memory"])

    @router.get(
        "/source-versions/{version_id}/memory",
        response_model=SourceVersionMemory,
        responses=NOT_FOUND,
    )
    def source_version_memory_documents(  # pyright: ignore[reportUnusedFunction]
        version_id: uuid.UUID,
    ) -> SourceVersionMemory | JSONResponse:
        with engine.connect() as connection:
            found = source_version_memory(connection, version_id, bank_id)
        return found if found is not None else not_found("source version")

    @router.get("/memory/health", response_model=MemoryHealth, responses=NOT_FOUND)
    def health(company_id: uuid.UUID | None = None) -> MemoryHealth | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        with engine.connect() as connection:
            configured = universe() if universe is not None else None
            companies = (
                extend_universe(connection, configured)
                if configured is not None
                else Universe(version=1, name="none", companies={})
            )
            found = memory_health(connection, bank_id, gateway, companies, company_id)
        return found if found is not None else not_found("company")

    return router
