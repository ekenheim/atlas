"""What a Hypothesis is, as the API shows it (spec §5.6, §8.1): its lifecycle status, its
immutable versions (content, content hash, provenance, publication) and its transitions."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, RowMapping, text

from atlas.audit import content_hash
from atlas.investigations.model import CardContradiction, CardFinding, UnsupportedFinding

DRAFT_HYPOTHESIS_KIND = "draft_hypothesis"
RUN_KIND = "hypothesis_draft"

HypothesisStatus = Literal[
    "draft",
    "researching",
    "evidence_ready",
    "reviewed",
    "paper_tracking",
    "closed",
    "rejected",
    "needs_more_evidence",
]
HYPOTHESIS_STATUSES: tuple[HypothesisStatus, ...] = (
    "draft",
    "researching",
    "evidence_ready",
    "reviewed",
    "paper_tracking",
    "closed",
    "rejected",
    "needs_more_evidence",
)
# The §5.6 lifecycle, `draft -> researching -> evidence_ready -> reviewed -> paper_tracking ->
# closed` with the side branches `rejected` and `needs_more_evidence`. `reviewed` is reached
# only by publishing a version (the `publish` transition, behind the publish gate).
TRANSITIONS: dict[HypothesisStatus, tuple[HypothesisStatus, ...]] = {
    "draft": ("researching", "evidence_ready", "needs_more_evidence", "rejected"),
    "researching": ("evidence_ready", "needs_more_evidence", "rejected"),
    "needs_more_evidence": ("researching", "evidence_ready", "rejected"),
    "evidence_ready": ("researching", "needs_more_evidence", "rejected"),
    "reviewed": ("paper_tracking", "needs_more_evidence", "rejected", "closed"),
    "paper_tracking": ("closed",),
    "closed": (),
    "rejected": (),
}
# Where publishing a version is allowed: the first publication from `evidence_ready` (which
# makes the Hypothesis `reviewed`); a correction's publication while `reviewed` or
# `paper_tracking` (the status stays).
PUBLISHABLE_FROM: tuple[HypothesisStatus, ...] = ("evidence_ready", "reviewed", "paper_tracking")

DraftStatus = Literal["queued", "drafted", "failed"]
VersionOrigin = Literal["editor_draft", "correction"]


class Mechanism(BaseModel):
    """§8.1's mechanism: what drives demand, what may constrain it, who may capture value."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    demand_driver: str | None
    possible_constraint: str | None
    economic_capture_question: str | None


class HypothesisContent(BaseModel):
    """A version's content. Only `findings` state facts, each citing accepted Claims (and so
    their Assertions and spans); the rest is the Editor's or the researcher's proposal.
    `unsupported_findings` records what was dropped for citing no accepted Claim: never
    promoted to a finding. `contradictions` is the Skeptic's accepted counterevidence from the
    investigation's research card (each finding lists the independent items against its
    Claims in `counterevidence_ids`); versions drafted before ticket 15 have none."""

    model_config = ConfigDict(frozen=True)

    thesis_statement: str
    mechanism: Mechanism
    measurable_predictions: list[str]
    catalysts: list[str]
    falsifiers: list[str]
    required_evidence: list[str]
    alternative_explanations: list[str]
    unresolved_questions: list[str]
    findings: list[CardFinding]
    unsupported_findings: list[UnsupportedFinding]
    contradictions: list[CardContradiction] = Field(default_factory=list[CardContradiction])

    def sha256(self) -> str:
        return content_hash(self.model_dump(mode="json"))


class VersionProvenance(BaseModel):
    """Where a version came from: the investigation and its run (the research card's Editor
    call), and for the Editor's draft its own run and call."""

    model_config = ConfigDict(frozen=True)

    investigation_id: uuid.UUID
    investigation_run_id: uuid.UUID | None
    research_card_role_call_id: uuid.UUID | None
    draft_run_id: uuid.UUID | None
    editor_role_call_id: uuid.UUID | None


class HypothesisVersion(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    version: int
    based_on_version: int | None
    origin: VersionOrigin
    content: HypothesisContent
    content_sha256: str
    provenance: VersionProvenance
    note: str | None
    created_by: str
    created_at: datetime
    published: bool
    published_at: datetime | None
    published_by: str | None


class HypothesisTransition(BaseModel):
    model_config = ConfigDict(frozen=True)

    seq: int
    from_status: HypothesisStatus
    to_status: HypothesisStatus
    action: Literal["transition", "publish"]
    version: int | None
    actor: str
    note: str | None
    at: datetime


class Hypothesis(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    theme_id: str
    investigation_id: uuid.UUID
    related_company_ids: list[uuid.UUID]
    status: HypothesisStatus
    allowed_transitions: list[HypothesisStatus]
    author: str
    draft_status: DraftStatus  # the Editor's drafting of version 1
    draft_job_id: uuid.UUID
    draft_run_id: uuid.UUID | None
    draft_error: str | None
    created_at: datetime
    updated_at: datetime
    first_published_at: datetime | None
    next_review_at: datetime | None
    latest_version: int | None
    versions: list[HypothesisVersion]
    transitions: list[HypothesisTransition]


def get_hypothesis(connection: Connection, hypothesis_id: uuid.UUID) -> Hypothesis | None:
    row = (
        connection.execute(text("SELECT * FROM hypothesis WHERE id = :id"), {"id": hypothesis_id})
        .mappings()
        .one_or_none()
    )
    return None if row is None else _hypothesis(connection, row)


def list_hypotheses(
    connection: Connection,
    *,
    theme_id: str | None,
    status: str | None,
    limit: int,
    offset: int,
) -> tuple[list[Hypothesis], int]:
    where = (
        " WHERE (CAST(:theme AS text) IS NULL OR theme_id = :theme)"
        " AND (CAST(:status AS text) IS NULL OR status = :status)"
    )
    params = {"theme": theme_id, "status": status, "limit": limit, "offset": offset}
    total = connection.execute(
        text(f"SELECT count(*) FROM hypothesis{where}"),  # noqa: S608 (constant)
        params,
    ).scalar_one()
    rows = connection.execute(
        text(
            f"SELECT * FROM hypothesis{where}"  # noqa: S608 (constant)
            " ORDER BY created_at DESC, id LIMIT :limit OFFSET :offset"
        ),
        params,
    ).mappings()
    return [_hypothesis(connection, row) for row in list(rows)], int(total)


def get_version(
    connection: Connection, hypothesis_id: uuid.UUID, version: int
) -> HypothesisVersion | None:
    row = (
        connection.execute(
            text(
                "SELECT * FROM hypothesis_version WHERE hypothesis_id = :id AND version = :version"
            ),
            {"id": hypothesis_id, "version": version},
        )
        .mappings()
        .one_or_none()
    )
    return None if row is None else version_from_row(row)


def version_from_row(row: RowMapping) -> HypothesisVersion:
    values: dict[str, Any] = dict(row)
    values.pop("hypothesis_id")
    return HypothesisVersion.model_validate(values | {"published": row["published_at"] is not None})


def _hypothesis(connection: Connection, row: RowMapping) -> Hypothesis:
    params = {"id": row["id"]}
    versions = [
        version_from_row(each)
        for each in connection.execute(
            text("SELECT * FROM hypothesis_version WHERE hypothesis_id = :id ORDER BY version"),
            params,
        ).mappings()
    ]
    transitions = [
        HypothesisTransition.model_validate(dict(each))
        for each in connection.execute(
            text(
                "SELECT seq, from_status, to_status, action, version, actor, note, at"
                " FROM hypothesis_transition WHERE hypothesis_id = :id ORDER BY seq"
            ),
            params,
        ).mappings()
    ]
    status: HypothesisStatus = row["status"]
    values: dict[str, Any] = dict(row)
    return Hypothesis.model_validate(
        values
        | {
            "allowed_transitions": list(TRANSITIONS[status]),
            "latest_version": versions[-1].version if versions else None,
            "versions": versions,
            "transitions": transitions,
        }
    )
