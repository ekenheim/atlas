"""`/api/v1/snapshots`: Research Snapshots, frozen when a Hypothesis version is published
(spec §5.7; ticket 20).

- `GET /snapshots[?hypothesis_id=]`: the snapshots' rows (hash, archive URI, cutoff), oldest
  first.
- `GET /snapshots/{id}`: one snapshot with its content, **verified on every read**: the
  archived canonical JSON must hash to the row's SHA-256 and name the row's version; if it
  was altered or is missing, 500 `snapshot_integrity_failed`, never the altered content.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import Engine

from atlas.api.common import (
    NOT_FOUND,
    Page,
    Pagination,
    error_response,
    error_responses,
    not_found,
    pagination,
)
from atlas.archive import Archive
from atlas.snapshots import (
    ResearchSnapshot,
    ResearchSnapshotRecord,
    SnapshotError,
    list_snapshots,
    read_snapshot,
)

Paged = Annotated[Pagination, Depends(pagination)]


def snapshots_router(engine: Engine, archive: Archive) -> APIRouter:
    router = APIRouter(prefix="/api/v1/snapshots", tags=["snapshots"])

    @router.get("", response_model=Page[ResearchSnapshotRecord])
    def listing(  # pyright: ignore[reportUnusedFunction]
        page: Paged, hypothesis_id: uuid.UUID | None = None
    ) -> Page[ResearchSnapshotRecord]:
        with engine.connect() as connection:
            items, total = list_snapshots(
                connection, hypothesis_id=hypothesis_id, limit=page.limit, offset=page.offset
            )
        return Page(items=items, total=total, limit=page.limit, offset=page.offset)

    @router.get(
        "/{snapshot_id}",
        response_model=ResearchSnapshot,
        responses={**NOT_FOUND, **error_responses(500)},
    )
    def snapshot(snapshot_id: uuid.UUID) -> ResearchSnapshot | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        try:
            with engine.connect() as connection:
                found = read_snapshot(connection, archive, snapshot_id)
        except SnapshotError as error:
            return error_response(error.status, error.code, error.message)
        return found if found is not None else not_found("snapshot")

    return router
