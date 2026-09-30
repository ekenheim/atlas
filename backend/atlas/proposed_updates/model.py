"""What a proposed update is, as the API shows it: the published version it flags, the event
that contradicted it, the contradicting Evidence, the findings and Candidates it concerns, and
the owner's resolution."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, RowMapping, text

from atlas.proposed_updates.triggers import Trigger

ProposedUpdateState = Literal["open", "accepted", "dismissed"]
EvidenceKind = Literal["assertion", "relationship", "source_version", "counterevidence"]


class ContradictingEvidence(BaseModel):
    """One piece of Evidence against the version: what changed, and where it is stated."""

    model_config = ConfigDict(frozen=True)

    kind: EvidenceKind
    id: uuid.UUID = Field(
        description="the Assertion reviewed, the Relationship rejected, the revised Source"
        " Version, or the counterevidence item"
    )
    description: str
    state: str | None = Field(description="the Assertion's or Relationship's review state")
    note: str | None = Field(description="the reviewer's note, if any")
    # Where the contradicting statement is: the successor or counterevidence Assertion and its
    # quote, or the revised Source Version (and the version it revises).
    assertion_id: uuid.UUID | None
    source_version_id: uuid.UUID | None
    quote: str | None
    revises_source_version_id: uuid.UUID | None
    contradicts_assertion_ids: list[uuid.UUID] = Field(
        description="the version's Assertions this bears on"
    )


class AffectedFinding(BaseModel):
    model_config = ConfigDict(frozen=True)

    index: int = Field(description="the finding's position in the version, from 0")
    claim_text: str
    assertion_ids: list[uuid.UUID] = Field(description="its contradicted Assertions")


class ProposedUpdate(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    hypothesis_id: uuid.UUID
    hypothesis_version: int = Field(description="the published version it flags")
    hypothesis_version_id: uuid.UUID
    trigger: Trigger
    trigger_key: str
    summary: str
    evidence: list[ContradictingEvidence]
    affected_findings: list[AffectedFinding]
    candidate_ids: list[uuid.UUID] = Field(description="the Candidates it concerns")
    detected_by_job_id: uuid.UUID | None
    state: ProposedUpdateState
    resolved_by: str | None
    resolved_at: datetime | None
    resolution_note: str | None
    dismiss_reason: str | None
    correction_version: int | None = Field(description="the correction an acceptance started")
    created_at: datetime


_SELECT = (
    "SELECT u.*, v.version AS hypothesis_version FROM proposed_update u"
    " JOIN hypothesis_version v ON v.id = u.hypothesis_version_id"
)


def proposed_update_from_row(row: RowMapping) -> ProposedUpdate:
    values: dict[str, Any] = dict(row)
    return ProposedUpdate.model_validate(values)


def get_proposed_update(
    connection: Connection, proposed_update_id: uuid.UUID
) -> ProposedUpdate | None:
    row = (
        connection.execute(text(f"{_SELECT} WHERE u.id = :id"), {"id": proposed_update_id})
        .mappings()
        .one_or_none()
    )
    return None if row is None else proposed_update_from_row(row)


def list_proposed_updates(
    connection: Connection,
    *,
    hypothesis_id: uuid.UUID | None,
    candidate_id: uuid.UUID | None,
    state: ProposedUpdateState | None,
    limit: int,
    offset: int,
) -> tuple[list[ProposedUpdate], int]:
    where = (
        " WHERE (CAST(:hypothesis AS uuid) IS NULL OR u.hypothesis_id = :hypothesis)"
        " AND (CAST(:candidate AS uuid) IS NULL OR :candidate = ANY(u.candidate_ids))"
        " AND (CAST(:state AS text) IS NULL OR u.state = :state)"
    )
    params = {
        "hypothesis": hypothesis_id,
        "candidate": candidate_id,
        "state": state,
        "limit": limit,
        "offset": offset,
    }
    total = connection.execute(
        text(f"SELECT count(*) FROM proposed_update u{where}"),  # noqa: S608 (constant)
        params,
    ).scalar_one()
    rows = connection.execute(
        text(f"{_SELECT}{where} ORDER BY u.created_at, u.id LIMIT :limit OFFSET :offset"),
        params,
    ).mappings()
    return [proposed_update_from_row(row) for row in rows], int(total)
