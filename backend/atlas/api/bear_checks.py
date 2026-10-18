"""`GET /api/v1/companies/{id}/bear-checks?as_of=` (Chokepoint Watch ticket W4): the mechanical
bear checks of a company as of a time (default now), deterministic and with no model call:
dilution, shelf or ATM filings, GAAP gross margin, customer concentration, going-concern
language and net cash (`atlas.bear_checks`). Each check is `flag`, `clear` or `unknown` with its
value, its basis in words and its sources (XBRL observations, or a Source Version and the span
of the sentence). Errors use the envelope: 404 `not_found`.
"""

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime
from sqlalchemy import Engine

from atlas.api.common import NOT_FOUND, not_found
from atlas.archive import Archive
from atlas.bear_checks import BearChecks, UnknownCompany, bear_checks


def bear_checks_router(engine: Engine, archive: Archive, metrics_config: Path) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["bear-checks"])

    @router.get(
        "/companies/{company_id}/bear-checks",
        response_model=BearChecks,
        responses=NOT_FOUND,
    )
    def company_bear_checks(  # pyright: ignore[reportUnusedFunction]
        company_id: uuid.UUID,
        as_of: Annotated[
            AwareDatetime | None,
            Query(description="the cutoff (ISO 8601 with a time zone); default now"),
        ] = None,
    ) -> BearChecks | JSONResponse:
        try:
            return bear_checks(
                engine, archive, metrics_config, company_id, as_of or datetime.now(UTC)
            )
        except UnknownCompany:
            return not_found("company")

    return router
