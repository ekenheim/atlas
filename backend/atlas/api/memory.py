"""`/api/v1` reads of retention into memory.

- `GET /source-versions/{id}/memory`: the version's section documents in the research bank,
  with their retain states, fact counts, and the Hindsight operations that retained them.
- `GET /memory/health[?company_id=]`: what the bank holds and what it lost, from Atlas's
  records and Hindsight's read-only listings (`atlas.retention.health`); a failed Hindsight
  listing makes only its part `unavailable`. 404 for an unknown company.
- `GET /memory/reconciliations?limit=&offset=`: the bank's reconciliations of Atlas's records
  with Memory (memory-quality ticket 22, `atlas.retention.reconciliation`), newest first.
- `GET /memory/reconciliations/{id}`: one, with its samples, details and usage table; 404.
"""

import uuid
from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import Engine

from atlas.api.common import NOT_FOUND, Page, Pagination, not_found, pagination
from atlas.companies import Universe, extend_universe
from atlas.hindsight import HindsightGateway
from atlas.retention import SourceVersionMemory, source_version_memory
from atlas.retention.health import MemoryHealth, memory_health
from atlas.retention.reconciliation import (
    ReconciliationRun,
    ReconciliationSummary,
    get_reconciliation,
    list_reconciliations,
)

Paged = Annotated[Pagination, Depends(pagination)]


def memory_router(
    engine: Engine,
    bank_id: str,
    gateway: HindsightGateway | None = None,
    universe: Callable[[], Universe] | None = None,
    *,
    stuck_after_hours: float,
    window_days: int | None = None,
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
            found = memory_health(
                connection,
                bank_id,
                gateway,
                companies,
                company_id,
                stuck_after_hours=stuck_after_hours,
                window_days=window_days,
            )
        return found if found is not None else not_found("company")

    @router.get("/memory/reconciliations", response_model=Page[ReconciliationSummary])
    def reconciliations(page: Paged) -> Page[ReconciliationSummary]:  # pyright: ignore[reportUnusedFunction]
        with engine.connect() as connection:
            items, total = list_reconciliations(
                connection, bank_id, limit=page.limit, offset=page.offset
            )
        return Page(items=items, total=total, limit=page.limit, offset=page.offset)

    @router.get(
        "/memory/reconciliations/{reconciliation_id}",
        response_model=ReconciliationRun,
        responses=NOT_FOUND,
    )
    def reconciliation(  # pyright: ignore[reportUnusedFunction]
        reconciliation_id: uuid.UUID,
    ) -> ReconciliationRun | JSONResponse:
        with engine.connect() as connection:
            found = get_reconciliation(connection, reconciliation_id)
        if found is None or found.bank_id != bank_id:
            return not_found("reconciliation")
        return found

    return router
