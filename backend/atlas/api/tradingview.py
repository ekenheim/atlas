"""`/api/v1/tradingview/catalog`: the TradingView filing and event catalog (ticket 31).

- `GET /tradingview/catalog?company_id=&category=&has_transcript=&limit=&offset=`: the
  documents TradingView listed for the universe's companies, most recently reported first:
  category, event, form, fiscal period, reported time, title, upstream provider, and each
  view's ID and type, with the Source Version recorded from a transcript view. Metadata
  only; every entry records the owner's override. The catalog tells which primary filings
  exist, e.g. for a manual import where no adapter fetches them.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Engine

from atlas.api.common import Page, Pagination, pagination
from atlas.tradingview import CatalogEntry, list_catalog

Paged = Annotated[Pagination, Depends(pagination)]


def tradingview_router(engine: Engine) -> APIRouter:
    router = APIRouter(prefix="/api/v1/tradingview", tags=["tradingview"])

    @router.get("/catalog", response_model=Page[CatalogEntry])
    def catalog(  # pyright: ignore[reportUnusedFunction]
        page: Paged,
        company_id: Annotated[uuid.UUID | None, Query(description="only this company")] = None,
        category: Annotated[str | None, Query(description="e.g. Earnings call")] = None,
        has_transcript: Annotated[
            bool | None, Query(description="only documents with (or without) a transcript")
        ] = None,
    ) -> Page[CatalogEntry]:
        with engine.connect() as connection:
            items, total = list_catalog(
                connection,
                company_id=company_id,
                category=category,
                has_transcript=has_transcript,
                limit=page.limit,
                offset=page.offset,
            )
        return Page(items=items, total=total, limit=page.limit, offset=page.offset)

    return router
