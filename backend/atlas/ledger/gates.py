"""Fetch gate decisions in the ledger: recording each one (audited) and reading them back.

A decision is recorded before its request is made, so an `allowed` fetch observation can
name it (`fetch_observation.gate_decision_id`); a `blocked` one stands alone, and is how a
source that forbids automation stays visible instead of silently missing.
"""

import json
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, JsonValue
from sqlalchemy import Connection, Engine, text

from atlas.audit import Actor, content_hash, record
from atlas.sources.gate import GateDecision

Purpose = Literal["discovery", "document"]


class FetchGateDecision(BaseModel):
    """Whether Atlas was allowed to request a URL, and which gate decided."""

    id: uuid.UUID
    job_id: uuid.UUID | None
    company_id: uuid.UUID | None
    provider: str
    purpose: str  # discovery (the feed's search) or document
    url: str
    status: str  # allowed or blocked
    blocked_by: str | None  # register, terms or robots
    reason: str
    site: str | None
    terms: dict[str, JsonValue] | None
    robots: dict[str, JsonValue] | None
    user_agent_token: str
    decided_at: datetime
    recorded_at: datetime


_SELECT = (
    "SELECT id, job_id, company_id, provider, purpose, url, status, blocked_by, reason, site,"
    " terms, robots, user_agent_token, decided_at, recorded_at FROM fetch_gate_decision"
)
_WHERE = " WHERE company_id = :company AND (CAST(:status AS text) IS NULL OR status = :status)"
_COUNT = "SELECT count(*) FROM fetch_gate_decision" + _WHERE  # noqa: S608 (constant fragments)
_PAGE = (
    _SELECT + _WHERE + " ORDER BY decided_at DESC, recorded_at DESC, id LIMIT :limit OFFSET :offset"
)


def record_decision(
    engine: Engine,
    actor: Actor,
    decision: GateDecision,
    *,
    provider: str,
    purpose: Purpose,
    company_id: uuid.UUID | None,
    job_id: uuid.UUID | None,
) -> uuid.UUID:
    """Append one decision, audited `fetch_gate.<status>` in the same transaction."""
    row: dict[str, Any] = {
        "id": uuid.uuid4(),
        "job_id": job_id,
        "company_id": company_id,
        "provider": provider,
        "purpose": purpose,
        "url": decision.url,
        "status": decision.status,
        "blocked_by": decision.blocked_by,
        "reason": decision.reason,
        "site": decision.site,
        "terms": None if decision.terms is None else decision.terms.model_dump(mode="json"),
        "robots": None if decision.robots is None else decision.robots.model_dump(mode="json"),
        "user_agent_token": decision.user_agent_token,
        "decided_at": decision.decided_at,
    }
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO fetch_gate_decision (id, job_id, company_id, provider, purpose, url,"
                " status, blocked_by, reason, site, terms, robots, user_agent_token, decided_at)"
                " VALUES (:id, :job_id, :company_id, :provider, :purpose, :url, :status,"
                " :blocked_by, :reason, :site, CAST(:terms AS jsonb), CAST(:robots AS jsonb),"
                " :user_agent_token, :decided_at)"
            ),
            {
                **row,
                "terms": None if row["terms"] is None else json.dumps(row["terms"]),
                "robots": None if row["robots"] is None else json.dumps(row["robots"]),
            },
        )
        record(
            connection,
            actor,
            f"fetch_gate.{decision.status}",
            entity_type="fetch_gate_decision",
            entity_id=str(row["id"]),
            new_hash=content_hash(row),
        )
    return row["id"]


def list_decisions(
    connection: Connection,
    company_id: uuid.UUID,
    *,
    status: str | None,
    limit: int,
    offset: int,
) -> tuple[list[FetchGateDecision], int]:
    """A company's gate decisions, newest first; `status` filters (e.g. `blocked`)."""
    params: dict[str, Any] = {"company": company_id, "status": status}
    total = connection.execute(text(_COUNT), params).scalar_one()
    rows = connection.execute(text(_PAGE), {**params, "limit": limit, "offset": offset}).mappings()
    return [FetchGateDecision.model_validate(dict(row)) for row in rows], total


def get_decision(connection: Connection, decision_id: uuid.UUID) -> FetchGateDecision | None:
    row = (
        connection.execute(
            text(_SELECT + " WHERE id = :id"),
            {"id": decision_id},
        )
        .mappings()
        .one_or_none()
    )
    return None if row is None else FetchGateDecision.model_validate(dict(row))
