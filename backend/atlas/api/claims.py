"""`/api/v1/claims` and `/api/v1/claim-extractions`: what the Investigator proposed and why
each Claim was accepted (with the Assertion it became) or rejected (with its reason).

- `GET /claims?extraction_id=&run_id=&source_version_id=&outcome=&reason_code=` (in the
  order proposed) and `GET /claims/{id}`
- `GET /claim-extractions/{id}`: an `extract_claims` job's extraction (the job's artifacts
  name it): its run, the passages chosen and why, progress by batch, and the counts
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import Engine

from atlas.api.common import INVALID, NOT_FOUND, Page, Pagination, not_found, pagination
from atlas.claims import (
    Claim,
    ClaimExtraction,
    ClaimOutcome,
    get_claim,
    get_extraction,
    list_claims,
)

Paged = Annotated[Pagination, Depends(pagination)]


def claims_router(engine: Engine) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["claims"])

    @router.get("/claims", response_model=Page[Claim], responses=INVALID)
    def claims(  # pyright: ignore[reportUnusedFunction]
        page: Paged,
        extraction_id: uuid.UUID | None = None,
        run_id: uuid.UUID | None = None,
        source_version_id: uuid.UUID | None = None,
        outcome: ClaimOutcome | None = None,
        reason_code: str | None = None,
    ) -> Page[Claim]:
        with engine.connect() as connection:
            items, total = list_claims(
                connection,
                extraction_id=extraction_id,
                run_id=run_id,
                source_version_id=source_version_id,
                outcome=outcome,
                reason_code=reason_code,
                limit=page.limit,
                offset=page.offset,
            )
        return Page(items=items, total=total, limit=page.limit, offset=page.offset)

    @router.get("/claims/{claim_id}", response_model=Claim, responses={**NOT_FOUND, **INVALID})
    def claim(claim_id: uuid.UUID) -> Claim | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        with engine.connect() as connection:
            found = get_claim(connection, claim_id)
        return found if found is not None else not_found("claim")

    @router.get(
        "/claim-extractions/{extraction_id}",
        response_model=ClaimExtraction,
        responses={**NOT_FOUND, **INVALID},
    )
    def extraction(  # pyright: ignore[reportUnusedFunction]
        extraction_id: uuid.UUID,
    ) -> ClaimExtraction | JSONResponse:
        with engine.connect() as connection:
            found = get_extraction(connection, extraction_id)
        return found if found is not None else not_found("claim extraction")

    return router
