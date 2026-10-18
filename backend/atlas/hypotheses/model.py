"""What a Hypothesis is, as the API shows it (spec §5.6, §8.1): its lifecycle status, its
immutable versions (content, content hash, provenance, publication) and its transitions."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, RowMapping, text

from atlas.audit import content_hash
from atlas.hypotheses.steps import HypothesisStep
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
    # A Hypothesis drafted from proven Beliefs (ticket 14): its argument's steps, each with the
    # Beliefs it rests on, and the Beliefs the thesis statement cites. Empty for one saved from
    # an investigation, whose `findings` state the facts instead.
    steps: list[HypothesisStep] = Field(default_factory=list[HypothesisStep])
    thesis_belief_ids: list[uuid.UUID] = Field(default_factory=list[uuid.UUID])
    # The finding judge's verdict on the thesis statement against its Beliefs' Facts (ticket 24):
    # `supported`, or `misstated` after one rewrite (the publish gate then fails
    # `thesis_misstated` until a correction changes the thesis); None: not judged (the judge is
    # off or its call failed, or the version was not drafted from Beliefs).
    thesis_judged: Literal["supported", "misstated"] | None = None
    thesis_misstated_reason: str | None = None

    def sha256(self) -> str:
        return content_hash(self.model_dump(mode="json"))


class VersionProvenance(BaseModel):
    """Where a version came from: the investigation and its run (the research card's Editor
    call), and for the Editor's draft its own run and call."""

    model_config = ConfigDict(frozen=True)

    investigation_id: uuid.UUID | None = None
    investigation_run_id: uuid.UUID | None = None
    research_card_role_call_id: uuid.UUID | None = None
    draft_run_id: uuid.UUID | None = None
    editor_role_call_id: uuid.UUID | None = None
    # A Hypothesis drafted from Beliefs: the sessions asked for and the Beliefs it was sent.
    session_ids: list[uuid.UUID] = Field(default_factory=list[uuid.UUID])
    belief_ids: list[uuid.UUID] = Field(default_factory=list[uuid.UUID])


class ThesisJudgement(BaseModel):
    """The finding judge's word on a Belief-backed version's thesis, and where it comes from
    (ticket 30): the draft's own judging (`draft`), the judging of a correction that changed the
    thesis (`correction`), or a later judging of the version on its own (`rejudge`: an insert-only
    `hypothesis_thesis_judgement` row). `unjudged`: a judging that found nothing to judge it
    against. A version no judge has seen has none."""

    model_config = ConfigDict(frozen=True)

    verdict: Literal["supported", "misstated", "unjudged"]
    reason: str | None
    at: datetime
    by: str
    source: Literal["draft", "correction", "rejudge"]


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
    # The effective verdict on the thesis of a version drafted from Beliefs: its latest
    # `hypothesis_thesis_judgement` row, else what its content records (`content.thesis_judged`,
    # which stays as stored); null when no judge has seen it. Filled when a Hypothesis or a
    # version is read, not when a version is written.
    thesis_judgement: ThesisJudgement | None = None


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
    # The investigation it was saved from, or null for one drafted from Beliefs, which has
    # its own `question`, cutoff (`as_of`) and `session_ids` instead (migration 0107).
    investigation_id: uuid.UUID | None
    question: str | None
    as_of: datetime | None
    session_ids: list[uuid.UUID]
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
    # Later Evidence contradicting a published version, awaiting the owner (ticket 21:
    # GET /hypotheses/{id}/proposed-updates).
    open_proposed_updates: int
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
    return next(
        (each for each in _versions(connection, hypothesis_id) if each.version == version), None
    )


def _versions(connection: Connection, hypothesis_id: uuid.UUID) -> list[HypothesisVersion]:
    """The Hypothesis's versions in order, each with its effective thesis judgement."""
    versions = [
        version_from_row(each)
        for each in connection.execute(
            text("SELECT * FROM hypothesis_version WHERE hypothesis_id = :id ORDER BY version"),
            {"id": hypothesis_id},
        ).mappings()
    ]
    judgements = thesis_judgements(connection, hypothesis_id, versions)
    return [
        each.model_copy(update={"thesis_judgement": judgements[each.version]}) for each in versions
    ]


def thesis_judgements(
    connection: Connection, hypothesis_id: uuid.UUID, versions: list[HypothesisVersion]
) -> dict[int, ThesisJudgement | None]:
    """Each version's effective thesis judgement (ticket 30; `docs/decisions.md`, "A corrected
    thesis is judged"). A version's own latest `hypothesis_thesis_judgement` row decides
    (`rejudge`). A correction that left the thesis as its base had it has its base's verdict,
    whatever that rests on. Otherwise it is what the version's content records: the draft's
    (`draft`) or the correction's (`correction`); none when the content records none."""
    latest: dict[int, ThesisJudgement] = {}
    for row in connection.execute(
        text(
            "SELECT version, verdict, reason, actor, at FROM hypothesis_thesis_judgement"
            " WHERE hypothesis_id = :id ORDER BY at, id"
        ),
        {"id": hypothesis_id},
    ).mappings():
        latest[row["version"]] = ThesisJudgement(
            verdict=row["verdict"],
            reason=row["reason"],
            at=row["at"],
            by=row["actor"],
            source="rejudge",
        )
    by_number = {each.version: each for each in versions}
    effective: dict[int, ThesisJudgement | None] = {}
    for each in versions:  # in order: a base is settled before the corrections of it
        base = None if each.based_on_version is None else by_number.get(each.based_on_version)
        content = each.content
        if each.version in latest:
            effective[each.version] = latest[each.version]
        elif (
            base is not None
            and each.origin == "correction"
            and base.content.thesis_statement == content.thesis_statement
        ):
            effective[each.version] = effective[base.version]
        elif content.thesis_judged is None:
            effective[each.version] = None
        else:
            effective[each.version] = ThesisJudgement(
                verdict=content.thesis_judged,
                reason=content.thesis_misstated_reason,
                at=each.created_at,
                by=each.created_by,
                source="draft" if each.origin == "editor_draft" else "correction",
            )
    return effective


def thesis_judgement(
    connection: Connection, hypothesis_id: uuid.UUID, version: int
) -> ThesisJudgement | None:
    """The effective thesis judgement of one version of the Hypothesis, or None."""
    versions = [
        version_from_row(each)
        for each in connection.execute(
            text("SELECT * FROM hypothesis_version WHERE hypothesis_id = :id ORDER BY version"),
            {"id": hypothesis_id},
        ).mappings()
    ]
    return thesis_judgements(connection, hypothesis_id, versions).get(version)


def version_from_row(row: RowMapping) -> HypothesisVersion:
    values: dict[str, Any] = dict(row)
    values.pop("hypothesis_id")
    return HypothesisVersion.model_validate(values | {"published": row["published_at"] is not None})


def _hypothesis(connection: Connection, row: RowMapping) -> Hypothesis:
    params = {"id": row["id"]}
    versions = _versions(connection, row["id"])
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
    open_updates = connection.execute(
        text("SELECT count(*) FROM proposed_update WHERE hypothesis_id = :id AND state = 'open'"),
        params,
    ).scalar_one()
    status: HypothesisStatus = row["status"]
    values: dict[str, Any] = dict(row)
    return Hypothesis.model_validate(
        values
        | {
            "allowed_transitions": list(TRANSITIONS[status]),
            "latest_version": versions[-1].version if versions else None,
            "open_proposed_updates": int(open_updates),
            "versions": versions,
            "transitions": transitions,
        }
    )
