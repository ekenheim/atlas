"""`/api/v1` as-of financials from XBRL companyfacts (spec Phase 5; ticket 18).

- `GET /companies/{id}/financials?as_of=&metric=`: canonical metrics (revenue, capex, debt,
  diluted shares, ...) per period and unit as of the cutoff, reported or derived (Q4 =
  FY - 9M), each with the observations it came from
- `GET /companies/{id}/financial-observations?as_of=&taxonomy=&concept=&unit=`: the as-of
  observation of every period key
- `GET /financial-observations/{id}`: one observation and its key's whole history
  (restatements and reaffirmations, in filing order)

`as_of` defaults to now. A value is visible only from its filing's `available_at`. Errors use
the envelope: 404 `not_found`, 422 `invalid_request` (e.g. an unknown metric).
"""

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime
from sqlalchemy import Engine

from atlas.api.common import INVALID, NOT_FOUND, Page, Pagination, error_response, not_found
from atlas.api.common import pagination as page_query
from atlas.companies import get_company
from atlas.financials import (
    FinancialFigures,
    FinancialObservation,
    FinancialObservationHistory,
    financial_figures,
    load_metric_catalog,
    observation_history,
    selected_observations,
)

AsOf = Annotated[
    AwareDatetime | None,
    Query(description="the cutoff (ISO 8601 with a time zone); default now"),
]
Paged = Annotated[Pagination, Depends(page_query)]


def financials_router(engine: Engine, metrics_config: Path) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["financials"])

    @router.get(
        "/companies/{company_id}/financials",
        response_model=FinancialFigures,
        responses={**NOT_FOUND, **INVALID},
    )
    def company_financials(  # pyright: ignore[reportUnusedFunction]
        company_id: uuid.UUID,
        as_of: AsOf = None,
        metric: Annotated[
            list[str] | None, Query(description="only these metrics (repeatable)")
        ] = None,
    ) -> FinancialFigures | JSONResponse:
        catalog = load_metric_catalog(metrics_config)  # read per request: it's small
        unknown = sorted(set(metric or ()) - set(catalog.metrics))
        if unknown:
            return error_response(
                422, "invalid_request", f"unknown metric(s): {', '.join(unknown)}"
            )
        with engine.connect() as connection:
            if get_company(connection, company_id) is None:
                return not_found("company")
            return financial_figures(
                connection, company_id, catalog, as_of or datetime.now(UTC), metric or None
            )

    @router.get(
        "/companies/{company_id}/financial-observations",
        response_model=Page[FinancialObservation],
        responses=NOT_FOUND,
    )
    def company_financial_observations(  # pyright: ignore[reportUnusedFunction]
        company_id: uuid.UUID,
        page: Paged,
        as_of: AsOf = None,
        taxonomy: str | None = None,
        concept: str | None = None,
        unit: str | None = None,
    ) -> Page[FinancialObservation] | JSONResponse:
        with engine.connect() as connection:
            if get_company(connection, company_id) is None:
                return not_found("company")
            items = selected_observations(
                connection,
                company_id,
                as_of or datetime.now(UTC),
                taxonomy=taxonomy,
                concept=concept,
                unit=unit,
            )
        return Page(
            items=items[page.offset : page.offset + page.limit],
            total=len(items),
            limit=page.limit,
            offset=page.offset,
        )

    @router.get(
        "/financial-observations/{observation_id}",
        response_model=FinancialObservationHistory,
        responses=NOT_FOUND,
    )
    def financial_observation(  # pyright: ignore[reportUnusedFunction]
        observation_id: uuid.UUID,
    ) -> FinancialObservationHistory | JSONResponse:
        with engine.connect() as connection:
            found = observation_history(connection, observation_id)
        return found if found is not None else not_found("financial observation")

    return router
