"""Ingest plans: what a first backfill ingest of a company is about to fetch and retain.

The staged universe rollout (ticket 27) brings in one company at a time. Before a backfill
ingest of a company that has nothing in the ledger yet fetches anything, it records the
documents it discovered (after the lookback and 8-K selection), their count and an estimate
of the retain operations they'll submit (one per parsed document; companyfacts is
normalized, not retained), with its `--max-retains` cap. `GET /api/v1/ingest-plans` lists
them, so the owner can compare the estimate with the Codex budget before the next window.

A plan is recorded once per ingest job (a retried attempt keeps the first) and audited as
`ingest_plan.recorded`.
"""

import json
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy import Connection, Engine, text

from atlas.audit import Actor, content_hash, record
from atlas.sources import SourceCandidate

# Candidate kinds whose parsed Source Version gets a retain operation.
_RETAINED_KINDS = frozenset({"sec_filing_document"})


class IngestPlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    job_id: uuid.UUID
    company_id: uuid.UUID
    company: str  # the slug
    since: datetime | None
    forms: list[str] | None
    documents: list[dict[str, JsonValue]]
    document_count: int
    estimated_retain_operations: int
    max_retains: int | None
    created_at: datetime


def has_versions(connection: Connection, company_id: uuid.UUID) -> bool:
    """Whether the ledger holds any Source Version of the company (it was ingested before)."""
    return connection.execute(
        text(
            "SELECT EXISTS (SELECT FROM source_version v JOIN source_document d"
            " ON d.id = v.source_document_id WHERE d.company_id = :company)"
        ),
        {"company": company_id},
    ).scalar_one()


def record_plan(
    engine: Engine,
    actor: Actor,
    *,
    job_id: uuid.UUID,
    company_id: uuid.UUID,
    candidates: list[SourceCandidate],
    since: datetime | None,
    forms: list[str] | None,
    max_retains: int | None,
) -> uuid.UUID | None:
    """Record the plan for a first ingest of the company; None if it was ingested before.

    Called after discovery and before any fetch, so a retry finds the versions its first
    attempt recorded and keeps the first attempt's plan.
    """
    documents: list[dict[str, JsonValue]] = [_document(c) for c in candidates]
    estimate = sum(1 for c in candidates if c.kind in _RETAINED_KINDS)
    with engine.begin() as connection:
        if has_versions(connection, company_id):
            return None
        row = (
            connection.execute(
                text(
                    "INSERT INTO ingest_plan (id, job_id, company_id, since, forms, documents,"
                    " document_count, estimated_retain_operations, max_retains) VALUES"
                    " (:id, :job, :company, :since, CAST(:forms AS jsonb),"
                    " CAST(:documents AS jsonb), :count, :estimate, :max_retains)"
                    " ON CONFLICT (job_id) DO NOTHING RETURNING *"
                ),
                {
                    "id": uuid.uuid4(),
                    "job": job_id,
                    "company": company_id,
                    "since": since,
                    "forms": None if forms is None else json.dumps(forms),
                    "documents": json.dumps(documents),
                    "count": len(documents),
                    "estimate": estimate,
                    "max_retains": max_retains,
                },
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        record(
            connection,
            actor,
            "ingest_plan.recorded",
            entity_type="ingest_plan",
            entity_id=str(row["id"]),
            new_hash=content_hash(dict(row)),
        )
        return row["id"]


def list_plans(engine: Engine, company: str | None = None) -> list[IngestPlan]:
    """Ingest plans, newest first; only the company's (by slug) when given."""
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT p.*, c.slug AS company FROM ingest_plan p"
                " JOIN company c ON c.id = p.company_id"
                " WHERE CAST(:company AS text) IS NULL OR c.slug = :company"
                " ORDER BY p.created_at DESC, p.id"
            ),
            {"company": company},
        ).mappings()
        return [IngestPlan.model_validate(dict(row)) for row in rows]


def _document(candidate: SourceCandidate) -> dict[str, JsonValue]:
    entry: dict[str, Any] = {
        "url": candidate.url,
        "kind": candidate.kind,
        "title": candidate.title,
        "document_type": candidate.document_type,
        "available_at": candidate.available_at.isoformat(),
        "retained": candidate.kind in _RETAINED_KINDS,
    }
    if candidate.filing is not None:
        entry["form"] = candidate.filing.form
        entry["accession_number"] = candidate.filing.accession_number
    return entry
