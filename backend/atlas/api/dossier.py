"""`GET /api/v1/companies/{id}/dossier?as_of=`: the Company dossier (product spec §10.1 B;
ticket 23): identity and listings, pending identity reviews, themes, Source Documents,
Relationships out and in, as-of financials (`as_of` defaults to now) and fetch-gate blocks,
in one read. Errors use the envelope: 404 `not_found`, 422 `invalid_request`.
"""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime
from sqlalchemy import Engine

from atlas.api.common import INVALID, NOT_FOUND, not_found
from atlas.companies import Universe, extend_universe
from atlas.dossier import CompanyDossier, company_dossier
from atlas.financials import load_metric_catalog


def dossier_router(
    engine: Engine, metrics_config: Path, universe: Callable[[], Universe]
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["companies"])

    @router.get(
        "/companies/{company_id}/dossier",
        response_model=CompanyDossier,
        responses={**NOT_FOUND, **INVALID},
    )
    def dossier(  # pyright: ignore[reportUnusedFunction]
        company_id: uuid.UUID,
        as_of: Annotated[
            AwareDatetime | None,
            Query(description="the financials' cutoff (ISO 8601 with a time zone); default now"),
        ] = None,
    ) -> CompanyDossier | JSONResponse:
        catalog = load_metric_catalog(metrics_config)  # read per request: it's small
        with engine.connect() as connection:
            found = company_dossier(
                connection,
                company_id,
                universe=extend_universe(connection, universe()),
                catalog=catalog,
                as_of=as_of or datetime.now(UTC),
            )
        return found if found is not None else not_found("company")

    return router
