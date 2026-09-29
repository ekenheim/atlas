"""Triage decisions: the insert-only record of whether each section is retained (ticket 30).

A section's **effective** decision is its latest `triage_decision` row: a later on-demand
retain of a skipped section is a new row, never an edit. Every row is audited in the
transaction that inserts it.
"""

import hashlib
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Connection, RowMapping, text

from atlas.audit import Actor, content_hash, record

Verdict = Literal["retain", "skip"]
Method = Literal["rule", "inherited", "role", "default", "on_demand"]
METHODS: tuple[Method, ...] = ("rule", "inherited", "role", "default", "on_demand")


def section_sha256(section_text: str) -> str:
    """The SHA-256 (hex) of a section's text as UTF-8: how an unchanged section is recognized
    in a later Source Version (the section-level form of ticket 11's content hash)."""
    return hashlib.sha256(section_text.encode("utf-8")).hexdigest()


class TriageDecision(BaseModel):
    """One decision about one section of a Source Version."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    source_version_id: uuid.UUID
    company_id: uuid.UUID | None
    section_anchor: str
    section_heading: str | None
    char_start: int
    char_end: int
    sectioner_version: str
    content_sha256: str
    decision: Verdict
    category: str
    reason: str
    method: Method
    rubric_version: str
    rules_version: str
    role_call_id: uuid.UUID | None
    inherited_from_id: uuid.UUID | None
    requested_by: str | None
    investigation_id: uuid.UUID | None
    decided_at: datetime
    effective: bool  # the section's latest decision, the one retention follows


_SELECT = (
    "SELECT t.id, t.source_version_id, d.company_id, t.section_anchor, t.section_heading,"
    " t.char_start, t.char_end, t.sectioner_version, t.content_sha256, t.decision, t.category,"
    " t.reason, t.method, t.rubric_version, t.rules_version, t.role_call_id,"
    " t.inherited_from_id, t.requested_by, t.investigation_id, t.decided_at,"
    " NOT EXISTS (SELECT FROM triage_decision later"
    "   WHERE later.source_version_id = t.source_version_id"
    "   AND later.section_anchor = t.section_anchor AND later.seq > t.seq) AS effective"
    " FROM triage_decision t"
    " JOIN source_version v ON v.id = t.source_version_id"
    " JOIN source_document d ON d.id = v.source_document_id"
)


def effective_decisions(connection: Connection, version_id: uuid.UUID) -> dict[str, RowMapping]:
    """The version's effective decision per section anchor."""
    rows = connection.execute(
        text(
            "SELECT DISTINCT ON (section_anchor) * FROM triage_decision"
            " WHERE source_version_id = :version ORDER BY section_anchor, seq DESC"
        ),
        {"version": version_id},
    ).mappings()
    return {row["section_anchor"]: row for row in rows}


def lock_decisions(connection: Connection, version_id: uuid.UUID) -> None:
    """Serialize decision-making for one version until the transaction ends (the triage job
    and an on-demand request), so a section is never decided twice by accident."""
    connection.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"triage_decision:{version_id}"},
    )


def has_decision(connection: Connection, version_id: uuid.UUID, anchor: str) -> bool:
    return (
        connection.execute(
            text(
                "SELECT 1 FROM triage_decision"
                " WHERE source_version_id = :version AND section_anchor = :anchor LIMIT 1"
            ),
            {"version": version_id, "anchor": anchor},
        ).one_or_none()
        is not None
    )


def insert_decision(connection: Connection, actor: Actor, **fields: Any) -> RowMapping:
    """Insert one decision (the column values as keyword arguments) and audit it."""
    values: dict[str, Any] = {
        "id": uuid.uuid4(),
        "role_call_id": None,
        "inherited_from_id": None,
        "requested_by": None,
        "investigation_id": None,
        **fields,
    }
    row = (
        connection.execute(
            text(
                "INSERT INTO triage_decision (id, source_version_id, section_anchor,"
                " section_heading, char_start, char_end, sectioner_version, content_sha256,"
                " decision, category, reason, method, rubric_version, rules_version,"
                " role_call_id, inherited_from_id, requested_by, investigation_id)"
                " VALUES (:id, :source_version_id, :section_anchor, :section_heading,"
                " :char_start, :char_end, :sectioner_version, :content_sha256, :decision,"
                " :category, :reason, :method, :rubric_version, :rules_version,"
                " :role_call_id, :inherited_from_id, :requested_by, :investigation_id)"
                " RETURNING *"
            ),
            values,
        )
        .mappings()
        .one()
    )
    record(
        connection,
        actor,
        f"triage_decision.{row['method']}",
        entity_type="triage_decision",
        entity_id=str(row["id"]),
        new_hash=content_hash(dict(row)),
    )
    return row


def get_decision(connection: Connection, decision_id: uuid.UUID) -> TriageDecision | None:
    row = connection.execute(text(f"{_SELECT} WHERE t.id = :id"), {"id": decision_id}).mappings()
    found = row.one_or_none()
    return None if found is None else TriageDecision.model_validate(dict(found))


def list_decisions(
    connection: Connection,
    *,
    source_version_id: uuid.UUID | None = None,
    company_id: uuid.UUID | None = None,
    decision: Verdict | None = None,
    category: str | None = None,
    method: Method | None = None,
    effective_only: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[TriageDecision], int]:
    """Decisions matching every given filter, newest first, and how many match in all."""
    where = (
        "WHERE (CAST(:version AS uuid) IS NULL OR t.source_version_id = :version)"
        " AND (CAST(:company AS uuid) IS NULL OR d.company_id = :company)"
        " AND (CAST(:decision AS text) IS NULL OR t.decision = :decision)"
        " AND (CAST(:category AS text) IS NULL OR t.category = :category)"
        " AND (CAST(:method AS text) IS NULL OR t.method = :method)"
    )
    params: dict[str, Any] = {
        "version": source_version_id,
        "company": company_id,
        "decision": decision,
        "category": category,
        "method": method,
        "limit": limit,
        "offset": offset,
    }
    matching = f"SELECT * FROM ({_SELECT} {where}) AS matching"  # noqa: S608 (constant fragments)
    if effective_only:
        matching += " WHERE effective"
    total = connection.execute(
        text(f"SELECT count(*) FROM ({matching}) AS counted"),  # noqa: S608 (constant fragments)
        params,
    ).scalar_one()
    rows = connection.execute(
        text(
            f"{matching} ORDER BY decided_at DESC, source_version_id,"
            " char_start DESC, id LIMIT :limit OFFSET :offset"
        ),
        params,
    ).mappings()
    return [TriageDecision.model_validate(dict(row)) for row in rows], total
