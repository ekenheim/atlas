"""The TradingView catalog's read side: which documents TradingView lists for a company."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import Connection, text

from atlas.ledger.service import canonical_url
from atlas.tradingview.model import PROVIDER_ID, transcript_url


class CatalogView(BaseModel):
    id: str
    type: str  # transcript, summary or pdf
    # The Source Version recorded from this view (transcripts only), if any.
    source_version_id: uuid.UUID | None = None


class CatalogEntry(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    symbol: str
    document_id: str
    category: str | None
    event: str | None
    form: str | None
    fiscal_period: str | None
    fiscal_year: str | None
    reported_at: datetime | None
    status: str | None
    title: str
    upstream_provider: str | None
    views: list[CatalogView]
    owner_override: str
    first_seen_at: datetime
    last_seen_at: datetime


def list_catalog(
    connection: Connection,
    *,
    company_id: uuid.UUID | None,
    category: str | None,
    has_transcript: bool | None,
    limit: int,
    offset: int,
) -> tuple[list[CatalogEntry], int]:
    """Catalog entries, most recently reported first."""
    where = """
        WHERE (CAST(:company AS uuid) IS NULL OR e.company_id = :company)
        AND (CAST(:category AS text) IS NULL OR e.category = :category)
        AND (CAST(:transcript AS boolean) IS NULL OR :transcript = EXISTS (
            SELECT 1 FROM jsonb_array_elements(e.views) v WHERE v->>'type' = 'transcript'))
    """
    params: dict[str, Any] = {
        "company": company_id,
        "category": category,
        "transcript": has_transcript,
    }
    total = connection.execute(
        text(f"SELECT count(*) FROM tradingview_catalog_entry e {where}"),  # noqa: S608 (constant SQL)
        params,
    ).scalar_one()
    rows = list(
        connection.execute(
            text(
                "SELECT e.id, e.company_id, e.symbol, e.document_id, e.category, e.event, e.form,"  # noqa: S608 (constant SQL)
                " e.fiscal_period, e.fiscal_year, e.reported_at, e.status, e.title,"
                " e.upstream_provider, e.views, e.owner_override, e.first_seen_at,"
                f" e.last_seen_at FROM tradingview_catalog_entry e {where}"
                " ORDER BY e.reported_at DESC NULLS LAST, e.document_id"
                " LIMIT :limit OFFSET :offset"
            ),
            {**params, "limit": limit, "offset": offset},
        ).mappings()
    )
    urls = {
        (row["document_id"], view["id"]): canonical_url(
            transcript_url(row["document_id"], view["id"])
        )
        for row in rows
        for view in row["views"]
        if view.get("type") == "transcript"
    }
    versions = dict(
        connection.execute(
            text(
                "SELECT DISTINCT ON (d.canonical_url) d.canonical_url, v.id FROM source_document d"
                " JOIN source_version v ON v.source_document_id = d.id"
                " WHERE d.provider = :provider AND d.canonical_url = ANY(:urls)"
                " ORDER BY d.canonical_url, v.version_number DESC"
            ),
            {"provider": PROVIDER_ID, "urls": list(urls.values())},
        ).all()
    )
    entries = [
        CatalogEntry.model_validate(
            {
                **row,
                "views": [
                    {
                        "id": view["id"],
                        "type": view["type"],
                        "source_version_id": versions.get(
                            urls.get((row["document_id"], view["id"]))
                        ),
                    }
                    for view in row["views"]
                ],
            }
        )
        for row in rows
    ]
    return entries, int(total)
