"""Proposing, citing, judging, superseding and reading Beliefs (beliefs ticket 02).

Rules (the spec's "Beliefs"): a proposal carries at least one load-bearing citation with positive
valence and is born `unproven`; the judgement is set only by `judge` (an author, named), is
insert-only and clears the Belief's open flags; the valence is recorded, never computed (a
citation may name the counter-judge's relation instead, which maps to a default valence);
superseding keeps the old Belief's citations and history; every write is audited.
"""

import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Connection, Engine, text

from atlas.audit import Actor, content_hash, record
from atlas.beliefs.flags import flag_counterevidence
from atlas.beliefs.memory_jobs import enqueue_retain_belief
from atlas.beliefs.notices import confirm_by_citation
from atlas.calls.record import belief_call
from atlas.sessions import SessionSummary, get_session

type Step = Literal[
    "constraint", "demand_vs_supply", "relief", "control", "capture", "invalidation"
]
type Judgement = Literal["proven", "disproven", "unproven", "undecidable"]
type Weight = Literal["load_bearing", "context"]
type Status = Literal["active", "superseded", "withdrawn"]
type Relation = Literal["contradicts", "limits", "dates", "qualifies", "supports"]
type FlagKind = Literal[
    "counterevidence_stands", "source_revised", "assertion_reviewed", "fact_superseded"
]
type NoticeKind = Literal["belief_confirmed"]
type ExaminationOutcome = Literal["confirmed", "qualified", "contradicted", "nothing_new"]
type Sort = Literal["created", "stalest"]

# The counter-judge's relation to a default valence (a citation may set its own).
RELATION_VALENCE: dict[str, float] = {
    "contradicts": -1.0,
    "limits": -0.5,
    "dates": -0.5,
    "qualifies": -0.25,
    "supports": 0.5,
}
STANDING_STATES = ("unreviewed", "corroborated")


def on_belief_changed(connection: Connection, belief_id: uuid.UUID, event: str) -> None:
    """A published Hypothesis version resting on the Belief gets a proposed update (ticket 14).
    Imported here: the proposed-updates package reads Hypotheses, which read Beliefs."""
    from atlas.proposed_updates.triggers import on_belief_changed as hook

    hook(connection, belief_id, event)


class BeliefNotFound(Exception):
    pass


class BeliefNotActive(Exception):
    pass


class BeliefRefused(Exception):
    """A request the rules refuse; `code` is the API error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class CitationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["fact", "assertion"] = "fact"
    ref_id: uuid.UUID = Field(description="the Fact's ID (its Assertion's), or an Assertion's")
    valence: float | None = Field(default=None, ge=-1, le=1)
    relation: Relation | None = Field(
        default=None, description="the counter-judge's relation; sets a default valence"
    )
    weight: Weight = "context"
    note: str | None = None
    actor: str | None = Field(default=None, description="who cites; default: the caller")

    @model_validator(mode="after")
    def _signed(self) -> Self:
        if self.valence is None and self.relation is None:
            raise ValueError("a citation needs a valence or a relation")
        return self

    def signed(self) -> float:
        return self.valence if self.valence is not None else RELATION_VALENCE[str(self.relation)]


class BeliefPropose(BaseModel):
    model_config = ConfigDict(extra="forbid")

    statement: str = Field(min_length=1)
    theme: str = Field(min_length=1)
    step: Step
    company_ids: list[uuid.UUID] = Field(default_factory=list[uuid.UUID])
    as_of: datetime
    session_id: uuid.UUID | None = None
    actor: str | None = Field(default=None, description="who proposes; default: the caller")
    citations: list[CitationIn] = Field(default_factory=list[CitationIn])


class BeliefJudge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor: str = Field(min_length=1, description="the author setting the judgement")
    judgement: Judgement
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1)


class BeliefExamine(BaseModel):
    """A session tested the Belief (ticket 26): what it found, against what was public by the
    session's as-of time. It records no judgement; only an author's `judge` does that."""

    model_config = ConfigDict(extra="forbid")

    session_id: uuid.UUID = Field(description="the research session that tested it")
    outcome: ExaminationOutcome = Field(
        description="confirmed: newer evidence supports it; qualified: newer evidence limits,"
        " dates or narrows it; contradicted: newer evidence contradicts it; nothing_new: it read"
        " what came after and found nothing that bears on it"
    )
    note: str | None = None
    actor: str | None = Field(default=None, description="who examines; default: the session's")


class BeliefSupersede(BaseModel):
    model_config = ConfigDict(extra="forbid")

    by: list[uuid.UUID] = Field(min_length=1, description="the Beliefs that replace it")
    reason: str = Field(min_length=1)
    actor: str | None = None
    session_id: uuid.UUID | None = Field(
        default=None,
        description="the asking research session. An isolated one (ticket 29a) may supersede"
        " only Beliefs it proposed, by Beliefs it proposed: 422 `belief_not_in_session`",
    )


class CompanyRef(BaseModel):
    id: uuid.UUID
    slug: str
    display_name: str


class JudgementRecord(BaseModel):
    id: uuid.UUID
    judgement: Judgement
    confidence: float
    actor: str
    reason: str
    at: datetime


class BeliefSummary(BaseModel):
    id: uuid.UUID
    statement: str
    theme: str
    step: Step
    as_of: datetime
    status: Status
    companies: list[CompanyRef]
    judgement: JudgementRecord = Field(description="the judgement current at the read's time")
    open_flags: int
    open_notices: int = Field(
        description="notices beside the flags that are no doubt (`belief_confirmed`): cleared by"
        " a judgement like a flag, never counted in `open_flags`",
    )
    citation_count: int
    produced_by: uuid.UUID | None
    created_by: str
    created_at: datetime
    last_examined_at: datetime | None = Field(
        description="when a session last tested it (`examine`)"
    )
    last_examined_as_of: datetime | None = Field(
        description="the furthest as-of time of the sessions that tested it: it has been tested"
        " against what was public by then, so the next test reads what came after. None: never"
        " tested (read from its own `as_of`)",
    )
    last_examined_outcome: ExaminationOutcome | None


class CitationRecord(BaseModel):
    id: uuid.UUID
    kind: Literal["fact", "assertion"]
    ref_id: uuid.UUID
    valence: float
    weight: Weight
    note: str | None
    actor: str
    created_at: datetime
    company_id: uuid.UUID
    company_name: str
    statement: str | None = Field(description="the Fact's statement; none for an Assertion")
    quote: str
    span_start: int
    span_end: int
    source_version_id: uuid.UUID
    source_title: str | None
    available_at: datetime
    review_state: str
    stands: bool = Field(description="the cited statement is neither disputed nor withdrawn")


class FlagRecord(BaseModel):
    id: uuid.UUID
    kind: FlagKind
    ref_id: uuid.UUID
    detail: str
    raised_at: datetime
    cleared_by: uuid.UUID | None


class NoticeRecord(BaseModel):
    id: uuid.UUID
    kind: NoticeKind
    ref_id: uuid.UUID
    detail: str
    raised_at: datetime
    cleared_by: uuid.UUID | None


class ExaminationRecord(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    outcome: ExaminationOutcome
    as_of: datetime
    actor: str
    note: str | None
    at: datetime


class BeliefLink(BaseModel):
    id: uuid.UUID
    statement: str
    actor: str
    reason: str
    at: datetime


class Belief(BeliefSummary):
    citations: list[CitationRecord]
    counterevidence: list[CitationRecord] = Field(description="the citations with valence < 0")
    flags: list[FlagRecord]
    notices: list[NoticeRecord] = Field(
        description="what supports it that a flag does not carry; shown beside the flags",
    )
    examinations: list[ExaminationRecord] = Field(
        description="every test by a session, oldest first",
    )
    history: list[JudgementRecord] = Field(description="every judgement, oldest first")
    supersedes: list[BeliefLink]
    superseded_by: list[BeliefLink]
    session: SessionSummary | None


_SUMMARY = """
    SELECT b.id, b.statement, b.theme, b.step, b.as_of, b.status, b.produced_by, b.created_by,
           b.created_at, b.last_examined_at, b.last_examined_as_of, b.last_examined_outcome,
           j.id AS j_id, j.judgement, j.confidence, j.actor AS j_actor,
           j.reason AS j_reason, j.at AS j_at,
           (SELECT count(*) FROM belief_flag f WHERE f.belief_id = b.id
              AND f.cleared_by IS NULL) AS open_flags,
           (SELECT count(*) FROM belief_notice n WHERE n.belief_id = b.id
              AND n.cleared_by IS NULL) AS open_notices,
           (SELECT count(*) FROM belief_citation c WHERE c.belief_id = b.id) AS citations
    FROM belief b
    JOIN LATERAL (
        SELECT * FROM belief_judgement x WHERE x.belief_id = b.id
            AND (CAST(:as_of AS timestamptz) IS NULL OR x.at <= :as_of)
        ORDER BY x.at DESC, x.id DESC LIMIT 1
    ) j ON true
"""

_CITATIONS = """
    SELECT c.id, c.kind, c.ref_id, c.valence, c.weight, c.note, c.actor, c.created_at,
           a.subject_company_id AS company_id, co.display_name AS company_name,
           CASE WHEN f.assertion_id IS NULL THEN NULL
                ELSE a.value_json->>'statement' END AS statement,
           a.quote, a.span_start, a.span_end, a.source_version_id,
           d.title AS source_title, v.available_at, a.verification_status AS review_state
    FROM belief_citation c
    JOIN assertion a ON a.id = c.ref_id
    JOIN company co ON co.id = a.subject_company_id
    JOIN source_version v ON v.id = a.source_version_id
    JOIN source_document d ON d.id = v.source_document_id
    LEFT JOIN fact f ON f.assertion_id = c.ref_id
    WHERE c.belief_id = :id
    ORDER BY v.available_at, c.created_at, c.id
"""


def _judgement(row: Any) -> JudgementRecord:
    return JudgementRecord(
        id=row.j_id,
        judgement=row.judgement,
        confidence=row.confidence,
        actor=row.j_actor,
        reason=row.j_reason,
        at=row.j_at,
    )


def _companies(connection: Connection, belief_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[Any]]:
    found: dict[uuid.UUID, list[Any]] = {each: [] for each in belief_ids}
    rows = connection.execute(
        text(
            "SELECT bc.belief_id, c.id, c.slug, c.display_name FROM belief_company bc"
            " JOIN company c ON c.id = bc.company_id WHERE bc.belief_id = ANY(:ids)"
            " ORDER BY c.display_name"
        ),
        {"ids": belief_ids},
    )
    for row in rows:
        found[row.belief_id].append(
            CompanyRef(id=row.id, slug=row.slug, display_name=row.display_name)
        )
    return found


def _summaries(connection: Connection, rows: list[Any]) -> list[BeliefSummary]:
    companies = _companies(connection, [row.id for row in rows])
    return [
        BeliefSummary(
            id=row.id,
            statement=row.statement,
            theme=row.theme,
            step=row.step,
            as_of=row.as_of,
            status=row.status,
            companies=companies[row.id],
            judgement=_judgement(row),
            open_flags=row.open_flags,
            open_notices=row.open_notices,
            citation_count=row.citations,
            produced_by=row.produced_by,
            created_by=row.created_by,
            created_at=row.created_at,
            last_examined_at=row.last_examined_at,
            last_examined_as_of=row.last_examined_as_of,
            last_examined_outcome=row.last_examined_outcome,
        )
        for row in rows
    ]


def list_beliefs(
    connection: Connection,
    *,
    theme: str | None = None,
    step: str | None = None,
    company_id: uuid.UUID | None = None,
    judgement: str | None = None,
    status: str | None = None,
    flagged: bool | None = None,
    as_of: datetime | None = None,
    ids: list[uuid.UUID] | None = None,
    sort: Sort = "created",
    limit: int,
    offset: int,
) -> tuple[list[BeliefSummary], int]:
    """Oldest first (`sort="created"`), or stalest first (`"stalest"`: by `examined_through`, the
    `last_examined_as_of` else the Belief's own `as_of`, never-tested ones first; ticket 26).
    With `as_of`, each Belief's judgement is the one current then, and a Belief with none yet
    is left out."""
    params: dict[str, Any] = {
        "theme": theme,
        "step": step,
        "company": company_id,
        "judgement": judgement,
        "status": status,
        "flagged": flagged,
        "as_of": as_of,
        "ids": ids,
        "limit": limit,
        "offset": offset,
    }
    where = (
        " WHERE (CAST(:theme AS text) IS NULL OR b.theme = :theme)"
        " AND (CAST(:step AS text) IS NULL OR b.step = :step)"
        " AND (CAST(:ids AS uuid[]) IS NULL OR b.id = ANY(:ids))"
        " AND (CAST(:status AS text) IS NULL OR b.status = :status)"
        " AND (CAST(:judgement AS text) IS NULL OR j.judgement = :judgement)"
        " AND (CAST(:company AS uuid) IS NULL OR EXISTS (SELECT FROM belief_company bc"
        "   WHERE bc.belief_id = b.id AND bc.company_id = :company))"
        " AND (CAST(:flagged AS boolean) IS NULL OR :flagged = EXISTS (SELECT FROM belief_flag f"
        "   WHERE f.belief_id = b.id AND f.cleared_by IS NULL))"
    )
    total = connection.execute(
        text(f"SELECT count(*) FROM ({_SUMMARY} {where}) s"),  # noqa: S608 (constants)
        params,
    ).scalar_one()
    order = (
        "(b.last_examined_as_of IS NOT NULL), coalesce(b.last_examined_as_of, b.as_of),"
        " b.created_at, b.id"
        if sort == "stalest"
        else "b.created_at, b.id"
    )
    rows = connection.execute(
        text(f"{_SUMMARY} {where} ORDER BY {order} LIMIT :limit OFFSET :offset"),
        params,
    ).all()
    return _summaries(connection, list(rows)), total


def get_belief(
    connection: Connection, belief_id: uuid.UUID, *, as_of: datetime | None = None
) -> Belief | None:
    row = connection.execute(
        text(f"{_SUMMARY} WHERE b.id = :id"),
        {"id": belief_id, "as_of": as_of},
    ).one_or_none()
    if row is None:
        return None
    [summary] = _summaries(connection, [row])
    citations = [
        CitationRecord(**each, stands=each["review_state"] in STANDING_STATES)
        for each in connection.execute(text(_CITATIONS), {"id": belief_id}).mappings()
    ]
    flags = [
        FlagRecord(**each)
        for each in connection.execute(
            text(
                "SELECT id, kind, ref_id, detail, raised_at, cleared_by FROM belief_flag"
                " WHERE belief_id = :id ORDER BY raised_at, id"
            ),
            {"id": belief_id},
        ).mappings()
    ]
    notices = [
        NoticeRecord(**each)
        for each in connection.execute(
            text(
                "SELECT id, kind, ref_id, detail, raised_at, cleared_by FROM belief_notice"
                " WHERE belief_id = :id ORDER BY raised_at, id"
            ),
            {"id": belief_id},
        ).mappings()
    ]
    examinations = [
        ExaminationRecord(**each)
        for each in connection.execute(
            text(
                "SELECT id, session_id, outcome, as_of, actor, note, at FROM belief_examination"
                " WHERE belief_id = :id ORDER BY at, id"
            ),
            {"id": belief_id},
        ).mappings()
    ]
    history = [
        JudgementRecord(**each)
        for each in connection.execute(
            text(
                "SELECT id, judgement, confidence, actor, reason, at FROM belief_judgement"
                " WHERE belief_id = :id ORDER BY at, id"
            ),
            {"id": belief_id},
        ).mappings()
    ]
    link = (
        "SELECT b.id, b.statement, s.actor, s.reason, s.at FROM belief_supersession s"
        " JOIN belief b ON b.id = s.{other} WHERE s.{own} = :id ORDER BY s.at, b.id"
    )
    supersedes = [
        BeliefLink(**each)
        for each in connection.execute(
            text(link.format(other="superseded_id", own="by_id")), {"id": belief_id}
        ).mappings()
    ]
    superseded_by = [
        BeliefLink(**each)
        for each in connection.execute(
            text(link.format(other="by_id", own="superseded_id")), {"id": belief_id}
        ).mappings()
    ]
    session = None
    if summary.produced_by is not None:
        found = get_session(connection, summary.produced_by)
        session = (
            None
            if found is None
            else SessionSummary(**found.model_dump(exclude={"card", "card_markdown", "fact_items"}))
        )
    return Belief(
        **summary.model_dump(),
        citations=citations,
        counterevidence=[each for each in citations if each.valence < 0],
        flags=flags,
        notices=notices,
        examinations=examinations,
        history=history,
        supersedes=supersedes,
        superseded_by=superseded_by,
        session=session,
    )


class Beliefs:
    def __init__(self, engine: Engine, actor: Actor, themes_config: Path | None = None) -> None:
        self._engine = engine
        self._actor = actor
        # Where a call made by a `proven` judgement finds its companies' TradingView symbols.
        self._themes_config = themes_config

    # --- writes -------------------------------------------------------------------------------

    def propose(self, request: BeliefPropose) -> Belief:
        with self._engine.begin() as connection:
            return self.propose_within(connection, request)

    def propose_within(self, connection: Connection, request: BeliefPropose) -> Belief:
        """Propose in the caller's transaction (the pipeline's Editor task stores its card and
        its Beliefs together)."""
        if not any(
            each.weight == "load_bearing" and each.signed() > 0 for each in request.citations
        ):
            raise BeliefRefused(
                "no_load_bearing_citation",
                "a Belief needs at least one load-bearing citation with positive valence",
            )
        belief_id = uuid.uuid4()
        who = request.actor or self._actor.name
        companies = list(dict.fromkeys(request.company_ids))
        if companies and connection.execute(
            text("SELECT count(*) FROM company WHERE id = ANY(:ids)"), {"ids": companies}
        ).scalar_one() != len(companies):
            raise BeliefRefused("unknown_company", "a company is not in the universe")
        if (
            request.session_id is not None
            and not connection.execute(
                text("SELECT EXISTS (SELECT FROM research_session WHERE id = :id)"),
                {"id": request.session_id},
            ).scalar_one()
        ):
            raise BeliefRefused("unknown_session", "the research session does not exist")
        connection.execute(
            text(
                "INSERT INTO belief (id, statement, theme, step, as_of, produced_by,"
                " created_by) VALUES (:id, :statement, :theme, :step, :as_of, :session,"
                " :actor)"
            ),
            {
                "id": belief_id,
                "statement": request.statement,
                "theme": request.theme,
                "step": request.step,
                "as_of": request.as_of,
                "session": request.session_id,
                "actor": who,
            },
        )
        for company in companies:
            connection.execute(
                text("INSERT INTO belief_company (belief_id, company_id) VALUES (:b, :c)"),
                {"b": belief_id, "c": company},
            )
        connection.execute(
            text(
                "INSERT INTO belief_judgement (id, belief_id, judgement, confidence, actor,"
                " reason) VALUES (:id, :belief, 'unproven', 0, :actor, 'proposed')"
            ),
            {"id": uuid.uuid4(), "belief": belief_id, "actor": who},
        )
        for citation in request.citations:
            self._cite(connection, belief_id, citation)
        belief = get_belief(connection, belief_id)
        assert belief is not None
        record(
            connection,
            self._actor,
            "belief.proposed",
            entity_type="belief",
            entity_id=str(belief_id),
            new_hash=content_hash(belief.model_dump(mode="json")),
        )
        return belief

    def cite(
        self, belief_id: uuid.UUID, citation: CitationIn, session_id: uuid.UUID | None = None
    ) -> Belief:
        with self._engine.begin() as connection:
            return self.cite_within(connection, belief_id, citation, session_id)

    @staticmethod
    def _own_beliefs_only(
        connection: Connection, session_id: uuid.UUID | None, belief_ids: list[uuid.UUID]
    ) -> None:
        """An isolated asking session (ticket 29a) touches only the Beliefs it proposed."""
        if (
            session_id is None
            or not connection.execute(
                text(
                    "SELECT COALESCE((SELECT isolated FROM research_session WHERE id = :id), false)"
                ),
                {"id": session_id},
            ).scalar_one()
        ):
            return
        foreign = connection.execute(
            text(
                "SELECT count(*) FROM belief WHERE id = ANY(:ids)"
                " AND produced_by IS DISTINCT FROM :session"
            ),
            {"ids": belief_ids, "session": session_id},
        ).scalar_one()
        if foreign:
            raise BeliefRefused(
                "belief_not_in_session",
                "an isolated session (the early-call scorecard) may use only the Beliefs it"
                " proposed itself",
            )

    def cite_within(
        self,
        connection: Connection,
        belief_id: uuid.UUID,
        citation: CitationIn,
        session_id: uuid.UUID | None = None,
    ) -> Belief:
        before = self._lock_active(connection, belief_id)
        self._own_beliefs_only(connection, session_id, [belief_id])
        self._cite(connection, belief_id, citation)
        belief = get_belief(connection, belief_id)
        assert belief is not None
        record(
            connection,
            self._actor,
            "belief.cited",
            entity_type="belief",
            entity_id=str(belief_id),
            old_hash=before,
            new_hash=content_hash(belief.model_dump(mode="json")),
        )
        return belief

    def judge(self, belief_id: uuid.UUID, request: BeliefJudge) -> Belief:
        with self._engine.begin() as connection:
            before = self._lock_active(connection, belief_id)
            if connection.execute(
                text(
                    "SELECT s.isolated FROM belief b"
                    " JOIN research_session s ON s.id = b.produced_by WHERE b.id = :id"
                ),
                {"id": belief_id},
            ).scalar_one_or_none():
                # An isolated session's Belief (ticket 29a, the scorecard) is never judged, so it
                # makes no call (`belief_call`) and never reaches the conclusions bank
                # (`enqueue_retain_belief`): refused before any row is written.
                raise BeliefRefused(
                    "isolated_session_belief",
                    "the Belief was proposed by an isolated session (the early-call scorecard):"
                    " it can never be judged, so it makes no call and is never retained",
                )
            judgement_id = uuid.uuid4()
            judged_at: datetime = connection.execute(
                text(
                    "INSERT INTO belief_judgement (id, belief_id, judgement, confidence, actor,"
                    " reason) VALUES (:id, :belief, :judgement, :confidence, :actor, :reason)"
                    " RETURNING at"
                ),
                {
                    "id": judgement_id,
                    "belief": belief_id,
                    "judgement": request.judgement,
                    "confidence": request.confidence,
                    "actor": request.actor,
                    "reason": request.reason,
                },
            ).scalar_one()
            if request.judgement == "proven":
                # The prospective record (ticket 19): proving a Belief is a call, dated now.
                belief_call(
                    connection,
                    self._actor,
                    belief_id,
                    made_at=judged_at,
                    themes_config=self._themes_config,
                )
            connection.execute(
                text(
                    "UPDATE belief_flag SET cleared_by = :judgement"
                    " WHERE belief_id = :belief AND cleared_by IS NULL"
                ),
                {"judgement": judgement_id, "belief": belief_id},
            )
            connection.execute(
                text(
                    "UPDATE belief_notice SET cleared_by = :judgement"
                    " WHERE belief_id = :belief AND cleared_by IS NULL"
                ),
                {"judgement": judgement_id, "belief": belief_id},
            )
            enqueue_retain_belief(connection, belief_id)
            on_belief_changed(connection, belief_id, f"judged:{judgement_id}")
            belief = get_belief(connection, belief_id)
            assert belief is not None
            record(
                connection,
                self._actor,
                "belief.judged",
                entity_type="belief",
                entity_id=str(belief_id),
                old_hash=before,
                new_hash=content_hash(belief.model_dump(mode="json")),
            )
        return belief

    def examine(self, belief_id: uuid.UUID, request: BeliefExamine) -> Belief:
        """Record that a session tested the Belief (ticket 26): an insert-only
        `belief_examination` and the Belief's `last_examined_*` (those of the examination with the
        furthest as-of time, the latest of equals: a replay at an earlier as-of time is recorded
        in the examinations but leaves the Belief's summary as it was). The judgement, its flags and
        its notices are untouched."""
        with self._engine.begin() as connection:
            before = self._lock_active(connection, belief_id)
            session = connection.execute(
                text("SELECT as_of, kind, actor, isolated FROM research_session WHERE id = :id"),
                {"id": request.session_id},
            ).one_or_none()
            if session is None:
                raise BeliefRefused("unknown_session", "the research session does not exist")
            if session.isolated:
                # An isolated session (ticket 29a) reads no Belief, so it tests none: the
                # examination would write `last_examined_*` on a Belief other sessions sort by.
                raise BeliefRefused(
                    "isolated_session",
                    "an isolated session (the early-call scorecard) reads no earlier Belief,"
                    " so it examines none",
                )
            if session.kind != "claude":
                raise BeliefRefused(
                    "session_not_claude", "only a research session of a Claude examines a Belief"
                )
            belief_as_of = connection.execute(
                text("SELECT as_of FROM belief WHERE id = :id"), {"id": belief_id}
            ).scalar_one()
            if belief_as_of > session.as_of:
                raise BeliefRefused(
                    "belief_after_as_of", "that Belief's as-of time is after the session's"
                )
            connection.execute(
                text(
                    "INSERT INTO belief_examination (id, belief_id, session_id, outcome, as_of,"
                    " actor, note) VALUES (:id, :belief, :session, :outcome, :as_of, :actor,"
                    " :note)"
                ),
                {
                    "id": uuid.uuid4(),
                    "belief": belief_id,
                    "session": request.session_id,
                    "outcome": request.outcome,
                    "as_of": session.as_of,
                    "actor": request.actor or session.actor,
                    "note": request.note,
                },
            )
            connection.execute(
                text(
                    "UPDATE belief SET last_examined_at = now(), last_examined_outcome = :outcome,"
                    " last_examined_as_of = :as_of WHERE id = :id"
                    " AND (last_examined_as_of IS NULL OR :as_of >= last_examined_as_of)"
                ),
                {"id": belief_id, "outcome": request.outcome, "as_of": session.as_of},
            )
            belief = get_belief(connection, belief_id)
            assert belief is not None
            record(
                connection,
                self._actor,
                "belief.examined",
                entity_type="belief",
                entity_id=str(belief_id),
                old_hash=before,
                new_hash=content_hash(belief.model_dump(mode="json")),
            )
        return belief

    def supersede(self, belief_id: uuid.UUID, request: BeliefSupersede) -> Belief:
        successors = list(dict.fromkeys(request.by))
        if belief_id in successors:
            raise BeliefRefused("invalid_successor", "a Belief cannot supersede itself")
        who = request.actor or self._actor.name
        with self._engine.begin() as connection:
            before = self._lock_active(connection, belief_id)
            self._own_beliefs_only(connection, request.session_id, [belief_id, *successors])
            found = {
                row.id: row.status
                for row in connection.execute(
                    text("SELECT id, status FROM belief WHERE id = ANY(:ids)"),
                    {"ids": successors},
                )
            }
            for successor in successors:
                if successor not in found:
                    raise BeliefRefused("invalid_successor", f"Belief {successor} does not exist")
                if found[successor] != "active":
                    raise BeliefRefused(
                        "invalid_successor", f"Belief {successor} is {found[successor]}"
                    )
            if connection.execute(
                text(
                    "SELECT EXISTS (SELECT FROM belief_supersession"
                    " WHERE superseded_id = ANY(:successors) AND by_id = :belief)"
                ),
                {"successors": successors, "belief": belief_id},
            ).scalar_one():
                raise BeliefRefused("invalid_successor", "a successor already is superseded by it")
            for successor in successors:
                connection.execute(
                    text(
                        "INSERT INTO belief_supersession (superseded_id, by_id, actor, reason)"
                        " VALUES (:old, :new, :actor, :reason)"
                    ),
                    {"old": belief_id, "new": successor, "actor": who, "reason": request.reason},
                )
            connection.execute(
                text("UPDATE belief SET status = 'superseded' WHERE id = :id"), {"id": belief_id}
            )
            enqueue_retain_belief(connection, belief_id)
            on_belief_changed(connection, belief_id, "superseded")
            belief = get_belief(connection, belief_id)
            assert belief is not None
            record(
                connection,
                self._actor,
                "belief.superseded",
                entity_type="belief",
                entity_id=str(belief_id),
                old_hash=before,
                new_hash=content_hash(belief.model_dump(mode="json")),
            )
        return belief

    # --- helpers ------------------------------------------------------------------------------

    def _lock_active(self, connection: Connection, belief_id: uuid.UUID) -> str:
        """Lock the Belief; raises if it is unknown or no longer active. Its hash before."""
        row = connection.execute(
            text("SELECT status FROM belief WHERE id = :id FOR UPDATE"), {"id": belief_id}
        ).one_or_none()
        if row is None:
            raise BeliefNotFound(str(belief_id))
        if row.status != "active":
            raise BeliefNotActive(str(belief_id))
        before = get_belief(connection, belief_id)
        assert before is not None
        return content_hash(before.model_dump(mode="json"))

    def _cite(self, connection: Connection, belief_id: uuid.UUID, citation: CitationIn) -> None:
        owner = connection.execute(
            text(
                "SELECT b.produced_by FROM belief b JOIN research_session s ON s.id = b.produced_by"
                " WHERE b.id = :id AND s.isolated"
            ),
            {"id": belief_id},
        ).scalar_one_or_none()
        if owner is not None and (
            citation.kind != "fact"
            or not connection.execute(
                text(
                    "SELECT EXISTS (SELECT FROM fact WHERE assertion_id = :id AND session_id = :s)"
                ),
                {"id": citation.ref_id, "s": owner},
            ).scalar_one()
        ):
            # The Belief of an isolated session (ticket 29a) rests on that session's own Facts:
            # another session's were chosen with hindsight.
            raise BeliefRefused(
                "fact_not_in_session",
                "a Belief of an isolated session (the early-call scorecard) may cite only Facts"
                " that session recorded itself",
            )
        if citation.kind == "fact":
            exists = connection.execute(
                text("SELECT EXISTS (SELECT FROM fact WHERE assertion_id = :id)"),
                {"id": citation.ref_id},
            ).scalar_one()
        else:
            exists = connection.execute(
                text("SELECT EXISTS (SELECT FROM assertion WHERE id = :id)"),
                {"id": citation.ref_id},
            ).scalar_one()
        if not exists:
            raise BeliefRefused("unknown_citation", f"no {citation.kind} {citation.ref_id}")
        if connection.execute(
            text(
                "SELECT EXISTS (SELECT FROM belief_citation"
                " WHERE belief_id = :belief AND ref_id = :ref)"
            ),
            {"belief": belief_id, "ref": citation.ref_id},
        ).scalar_one():
            raise BeliefRefused("already_cited", "the Belief cites it already")
        valence = citation.signed()
        connection.execute(
            text(
                "INSERT INTO belief_citation (id, belief_id, kind, ref_id, valence, weight,"
                " note, actor) VALUES (:id, :belief, :kind, :ref, :valence, :weight, :note,"
                " :actor)"
            ),
            {
                "id": uuid.uuid4(),
                "belief": belief_id,
                "kind": citation.kind,
                "ref": citation.ref_id,
                "valence": valence,
                "weight": citation.weight,
                "note": citation.note,
                "actor": citation.actor or self._actor.name,
            },
        )
        flag_counterevidence(connection, belief_id, citation.ref_id, valence, citation.weight)
        if citation.relation == "supports":
            confirm_by_citation(connection, belief_id, citation.ref_id)
