"""What Atlas already holds for a question: a session's starting state (atlas-beliefs ticket 26).

LLM sessions are stateless, so a session that starts from nothing records again what the last one
did: the MCP session on question 2 (`19c130c7`) took 35 of its 38 Facts from documents the closing
session (`8e4dbf23`) had already cited, and 15 overlapped a span already recorded. The objective
(catch a bottleneck early, keep the thesis on the shelf, notice confirmation) needs research that
compounds, so `GET /api/v1/research/prior-work` answers, bounded by an as-of time:

- the **Facts** already recorded for the companies (and steps): statement, status, period, the
  document's title and date, newest document first, capped with the count beyond the cap. Only
  Facts that stand (`unreviewed`, `corroborated`): a disputed or rejected one is not offered;
- the **Beliefs** of any judgement that name the companies or sit on the steps, stalest first,
  with who judged them and when they were last examined. The judgement is the Belief's current
  one, whatever its time (as `list_beliefs` and `get_belief` show it: a judgement is an author's
  act on the evidence Atlas holds, and `judged_at` is when it was made); the open flags and
  notices are bounded: a notice whose Fact, and a flag raised by a citation, are of a document
  public after `as_of` are not counted (the rule of the MCP `get_belief`);
- the **documents read** in earlier sessions (a read, a locate or a recorded Fact), with each
  reading session's as-of time, and `latest_session_as_of`: the point after which the documents
  are new to Atlas;
- the earlier **sessions** and the open questions their cards named;
- the open **Issues** that touch the companies or steps (an Issue whose parent does too, so the
  gaps a card named are in it).

Everything is bounded by `as_of`: a Fact by the time its document became public (effective
availability, `source_version_availability`), a Belief by its own as-of time, a session by its
as-of time (a later session is future research, counted in `hidden_sessions`), a document by
availability and by the sessions that read it, an Issue by the as-of time of the session that
opened it (else by when it was created), and an examination by its session's as-of time. A
Fact is bounded by its document's availability alone, not by the as-of time of the session that
recorded it, and so is a document's count of standing Facts: a Fact is public record once its
document is, and what Atlas holds is what the asker should cite instead of recording again.
`exclude_session_id` leaves out the asking session's own work. No LLM, no Memory: Atlas's records.
"""

import uuid
from datetime import UTC, datetime
from typing import Any, Literal, cast

from pydantic import BaseModel, Field
from sqlalchemy import Connection, text

from atlas.beliefs.service import list_beliefs
from atlas.issues import Issue, list_issues

DEFAULT_LIMIT = 40
MAX_LIMIT = 200
STANDING = ("unreviewed", "corroborated")
_ISSUE_SCAN = 500
_ISSUE_SCAN_LIMIT = 2_000


class PriorFact(BaseModel):
    id: uuid.UUID
    company: str = Field(description="the slug of the company it is about")
    step: str
    status: str
    statement: str
    period: str | None
    period_resolved: str | None
    source_version_id: uuid.UUID
    document_title: str | None
    document_available_at: datetime
    session_id: uuid.UUID | None
    same_span_as: uuid.UUID | None
    created_at: datetime


class PriorBelief(BaseModel):
    id: uuid.UUID
    statement: str
    step: str
    as_of: datetime
    companies: list[str]
    judgement: str
    confidence: float
    judged_by: str
    judged_at: datetime
    open_flags: int = Field(description="the open flags not raised by a document after `as_of`")
    open_notices: int = Field(
        description="the open confirmations whose Fact's document is not after `as_of`"
    )
    last_examined_at: datetime | None
    last_examined_as_of: datetime | None
    last_examined_outcome: str | None
    examined_through: datetime = Field(
        description="the as-of time the Belief has been tested against: its last examination's,"
        " else its own. Documents public after it are new to it"
    )


class ReadBy(BaseModel):
    session_id: uuid.UUID
    session_as_of: datetime
    question: str
    first_read_at: datetime


class DocumentRead(BaseModel):
    source_version_id: uuid.UUID
    company: str
    title: str | None
    form_type: str | None
    available_at: datetime
    facts: int = Field(description="the standing Facts recorded from it")
    read_by: list[ReadBy]


class PriorSession(BaseModel):
    id: uuid.UUID
    kind: Literal["claude", "pipeline"]
    question: str
    same_question: bool = Field(description="its question is this one, ignoring case and spacing")
    as_of: datetime
    actor: str
    started_at: datetime
    finished_at: datetime | None
    facts: int
    open_questions: list[str] = Field(description="what its card said it could not establish")


class PriorIssue(BaseModel):
    id: uuid.UUID
    title: str
    kind: str
    priority: int
    companies: list[str]
    parent_title: str | None
    produced_by: uuid.UUID | None


class Capped[T](BaseModel):
    total: int
    shown: int
    beyond: int = Field(description="`total` - `shown`: what the cap left out")
    items: list[T]


class PriorWork(BaseModel):
    as_of: datetime
    theme: str
    companies: list[str] = Field(description="the slugs asked about")
    steps: list[str] = Field(description="the steps asked about; empty: all")
    latest_session_as_of: datetime | None = Field(
        description="the as-of time of the latest earlier session that read a document of these"
        " companies: documents public after it are new to Atlas (`newest_documents(since=...)`)"
    )
    hidden_sessions: int = Field(description="earlier sessions with an as-of time after this one")
    isolated: bool = Field(
        default=False,
        description="the asking session is isolated (ticket 29a): nothing is listed, whatever"
        " Atlas holds",
    )
    facts: Capped[PriorFact]
    beliefs: Capped[PriorBelief]
    documents_read: Capped[DocumentRead]
    sessions: Capped[PriorSession]
    issues: Capped[PriorIssue]


def _capped[T](items: list[T], limit: int) -> Capped[T]:
    return Capped(
        total=len(items),
        shown=min(len(items), limit),
        beyond=max(0, len(items) - limit),
        items=items[:limit],
    )


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _same_question(a: str, b: str) -> bool:
    return " ".join(a.lower().split()) == " ".join(b.lower().split())


def no_prior_work(
    *, theme: str, as_of: datetime, company_slugs: list[str], steps: list[str]
) -> PriorWork:
    """What an isolated session is given (ticket 29a): nothing. The scorecard replays an old
    as-of time, and what Atlas holds was chosen later, with hindsight."""
    return PriorWork(
        as_of=_aware(as_of),
        theme=theme,
        companies=company_slugs,
        steps=steps,
        latest_session_as_of=None,
        hidden_sessions=0,
        isolated=True,
        facts=Capped[PriorFact](total=0, shown=0, beyond=0, items=[]),
        beliefs=Capped[PriorBelief](total=0, shown=0, beyond=0, items=[]),
        documents_read=Capped[DocumentRead](total=0, shown=0, beyond=0, items=[]),
        sessions=Capped[PriorSession](total=0, shown=0, beyond=0, items=[]),
        issues=Capped[PriorIssue](total=0, shown=0, beyond=0, items=[]),
    )


def prior_work(
    connection: Connection,
    *,
    theme: str,
    company_ids: list[uuid.UUID],
    explicit_companies: bool,
    steps: list[str],
    question: str | None,
    as_of: datetime,
    exclude_session_id: uuid.UUID | None,
    limit: int = DEFAULT_LIMIT,
) -> PriorWork:
    """The read. `company_ids` are the companies asked about (the theme's when none was named;
    `explicit_companies` says whether the caller named them: a Belief or Issue is then matched by
    them, else every one of the theme's is in)."""
    as_of = _aware(as_of)
    slugs: dict[uuid.UUID, str] = {
        row.id: row.slug for row in connection.execute(text("SELECT id, slug FROM company"))
    }
    facts = _facts(connection, company_ids, steps, as_of, exclude_session_id, slugs)
    beliefs = _beliefs(connection, theme, company_ids, explicit_companies, steps, as_of, slugs)
    reads = _documents_read(connection, theme, company_ids, as_of, exclude_session_id, slugs)
    sessions, hidden = _sessions(connection, theme, question, as_of, exclude_session_id)
    issues = _issues(connection, theme, company_ids, explicit_companies, steps, as_of, slugs)
    latest = max((each.session_as_of for doc in reads for each in doc.read_by), default=None)
    return PriorWork(
        as_of=as_of,
        theme=theme,
        companies=[slugs[each] for each in company_ids if each in slugs],
        steps=steps,
        latest_session_as_of=latest,
        hidden_sessions=hidden,
        facts=_capped(facts, limit),
        beliefs=_capped(beliefs, limit),
        documents_read=_capped(reads, limit),
        sessions=_capped(sessions, limit),
        issues=_capped(issues, limit),
    )


def _facts(
    connection: Connection,
    company_ids: list[uuid.UUID],
    steps: list[str],
    as_of: datetime,
    exclude_session_id: uuid.UUID | None,
    slugs: dict[uuid.UUID, str],
) -> list[PriorFact]:
    rows = connection.execute(
        text(
            "SELECT f.assertion_id, f.step, f.status, f.session_id, f.created_at, f.same_span_as,"
            " a.value_json, a.subject_company_id, a.source_version_id, d.title, av.available_at"
            " FROM fact f JOIN assertion a ON a.id = f.assertion_id"
            " JOIN source_version v ON v.id = a.source_version_id"
            " JOIN source_document d ON d.id = v.source_document_id"
            " JOIN source_version_availability av ON av.source_version_id = v.id"
            " WHERE a.subject_company_id = ANY(:companies)"
            " AND (cardinality(CAST(:steps AS text[])) = 0 OR f.step = ANY(:steps))"
            " AND av.available_at <= :as_of AND a.verification_status = ANY(:standing)"
            " AND (CAST(:exclude AS uuid) IS NULL OR f.session_id IS DISTINCT FROM :exclude)"
            " ORDER BY av.available_at DESC, f.created_at DESC, f.assertion_id"
        ),
        {
            "companies": company_ids,
            "steps": steps,
            "as_of": as_of,
            "standing": list(STANDING),
            "exclude": exclude_session_id,
        },
    )
    found: list[PriorFact] = []
    for row in rows:
        value = cast(dict[str, Any], row.value_json)
        found.append(
            PriorFact(
                id=row.assertion_id,
                company=slugs[row.subject_company_id],
                step=row.step,
                status=row.status,
                statement=str(value["statement"]),
                period=value.get("period"),
                period_resolved=value.get("period_resolved"),
                source_version_id=row.source_version_id,
                document_title=row.title,
                document_available_at=row.available_at,
                session_id=row.session_id,
                same_span_as=row.same_span_as,
                created_at=row.created_at,
            )
        )
    return found


def _beliefs(
    connection: Connection,
    theme: str,
    company_ids: list[uuid.UUID],
    explicit_companies: bool,
    steps: list[str],
    as_of: datetime,
    slugs: dict[uuid.UUID, str],
) -> list[PriorBelief]:
    """Active Beliefs of the theme whose own as-of time is by `as_of`, of any judgement: those
    naming a company asked about or on a step asked about (all of the theme's when neither was
    asked). Stalest first."""
    ids = list(
        connection.execute(
            text(
                "SELECT b.id FROM belief b WHERE b.theme = :theme AND b.status = 'active'"
                " AND b.as_of <= :as_of AND ("
                " (NOT :by_company AND cardinality(CAST(:steps AS text[])) = 0)"
                " OR (:by_company AND EXISTS (SELECT FROM belief_company bc"
                "   WHERE bc.belief_id = b.id AND bc.company_id = ANY(:companies)))"
                " OR b.step = ANY(:steps))"
            ),
            {
                "theme": theme,
                "as_of": as_of,
                "by_company": explicit_companies,
                "steps": steps,
                "companies": company_ids,
            },
        ).scalars()
    )
    if not ids:
        return []
    summaries, _ = list_beliefs(connection, ids=ids, sort="stalest", limit=MAX_LIMIT * 5, offset=0)
    # An examination by a session whose as-of time is after ours is future research: not seen.
    # The outcome and time are those of the examination with the furthest as-of time.
    seen = {
        row.belief_id: row
        for row in connection.execute(
            text(
                "SELECT DISTINCT ON (belief_id) belief_id, as_of, at, outcome"
                " FROM belief_examination WHERE belief_id = ANY(:ids) AND as_of <= :as_of"
                " ORDER BY belief_id, as_of DESC, at DESC, id DESC"
            ),
            {"ids": ids, "as_of": as_of},
        )
    }
    # A notice is raised by a Fact, a flag by a citation: one of a document public after `as_of`
    # would say what that document said, so it is not counted.
    notices = {
        row.belief_id: row.n
        for row in connection.execute(
            text(
                "SELECT n.belief_id, count(*) AS n FROM belief_notice n"
                " JOIN assertion a ON a.id = n.ref_id"
                " JOIN source_version_availability av ON av.source_version_id = a.source_version_id"
                " WHERE n.belief_id = ANY(:ids) AND n.cleared_by IS NULL"
                " AND av.available_at <= :as_of GROUP BY 1"
            ),
            {"ids": ids, "as_of": as_of},
        )
    }
    flags = {
        row.belief_id: row.n
        for row in connection.execute(
            text(
                "SELECT f.belief_id, count(*) AS n FROM belief_flag f"
                " WHERE f.belief_id = ANY(:ids) AND f.cleared_by IS NULL AND NOT EXISTS ("
                "  SELECT FROM belief_citation c JOIN assertion a ON a.id = c.ref_id"
                "  JOIN source_version_availability av"
                "   ON av.source_version_id = a.source_version_id"
                "  WHERE c.belief_id = f.belief_id AND c.ref_id = f.ref_id"
                "  AND av.available_at > :as_of) GROUP BY 1"
            ),
            {"ids": ids, "as_of": as_of},
        )
    }
    found: list[PriorBelief] = []
    for each in summaries:
        examined = seen.get(each.id)
        found.append(
            PriorBelief(
                id=each.id,
                statement=each.statement,
                step=each.step,
                as_of=each.as_of,
                companies=[company.slug for company in each.companies],
                judgement=each.judgement.judgement,
                confidence=each.judgement.confidence,
                judged_by=each.judgement.actor,
                judged_at=each.judgement.at,
                open_flags=flags.get(each.id, 0),
                open_notices=notices.get(each.id, 0),
                last_examined_at=None if examined is None else examined.at,
                last_examined_as_of=None if examined is None else examined.as_of,
                last_examined_outcome=None if examined is None else examined.outcome,
                examined_through=each.as_of if examined is None else examined.as_of,
            )
        )
    found.sort(key=lambda each: (each.examined_through, each.as_of, str(each.id)))
    return found


_READS = """
    WITH reads AS (
        SELECT c.session_id, (c.arguments->>'version_id')::uuid AS version_id,
               min(c.created_at) AS first_at
        FROM session_tool_call c
        WHERE c.tool IN ('read', 'locate', 'record_fact') AND c.outcome = 'ok'
          AND length(c.arguments->>'version_id') = 36
          AND c.arguments->>'version_id' ~* '^[0-9a-f-]+$'
        GROUP BY 1, 2
        UNION ALL
        SELECT coalesce(f.session_id, s.id), a.source_version_id, min(f.created_at)
        FROM fact f JOIN assertion a ON a.id = f.assertion_id
        LEFT JOIN research_session s ON s.investigation_id = f.investigation_id
        WHERE coalesce(f.session_id, s.id) IS NOT NULL
        GROUP BY 1, 2
    )
    SELECT r.version_id, min(r.first_at) AS first_at, r.session_id, s.as_of AS session_as_of,
           s.question, d.company_id, d.title, d.form_type, av.available_at
    FROM reads r
    JOIN research_session s ON s.id = r.session_id
    JOIN source_version v ON v.id = r.version_id
    JOIN source_document d ON d.id = v.source_document_id
    JOIN source_version_availability av ON av.source_version_id = v.id
    WHERE s.theme = :theme AND s.as_of <= :as_of
      AND (CAST(:exclude AS uuid) IS NULL OR s.id <> :exclude)
      AND d.company_id = ANY(:companies) AND av.available_at <= :as_of
    GROUP BY r.version_id, r.session_id, s.as_of, s.question, d.company_id, d.title, d.form_type,
             av.available_at
    ORDER BY av.available_at DESC, r.version_id, s.as_of DESC
"""


def _documents_read(
    connection: Connection,
    theme: str,
    company_ids: list[uuid.UUID],
    as_of: datetime,
    exclude_session_id: uuid.UUID | None,
    slugs: dict[uuid.UUID, str],
) -> list[DocumentRead]:
    rows = connection.execute(
        text(_READS),
        {"theme": theme, "as_of": as_of, "exclude": exclude_session_id, "companies": company_ids},
    ).all()
    by_version: dict[uuid.UUID, DocumentRead] = {}
    for row in rows:
        document = by_version.get(row.version_id)
        if document is None:
            document = by_version[row.version_id] = DocumentRead(
                source_version_id=row.version_id,
                company=slugs[row.company_id],
                title=row.title,
                form_type=row.form_type,
                available_at=row.available_at,
                facts=0,
                read_by=[],
            )
        document.read_by.append(
            ReadBy(
                session_id=row.session_id,
                session_as_of=row.session_as_of,
                question=row.question,
                first_read_at=row.first_at,
            )
        )
    if by_version:
        counts = {
            row.source_version_id: row.n
            for row in connection.execute(
                text(
                    "SELECT a.source_version_id, count(*) AS n FROM fact f"
                    " JOIN assertion a ON a.id = f.assertion_id"
                    " WHERE a.source_version_id = ANY(:ids)"
                    " AND a.verification_status = ANY(:standing) GROUP BY 1"
                ),
                {"ids": list(by_version), "standing": list(STANDING)},
            )
        }
        for version_id, document in by_version.items():
            document.facts = counts.get(version_id, 0)
    return list(by_version.values())


def _sessions(
    connection: Connection,
    theme: str,
    question: str | None,
    as_of: datetime,
    exclude_session_id: uuid.UUID | None,
) -> tuple[list[PriorSession], int]:
    rows = connection.execute(
        text(
            "SELECT s.id, s.kind, s.question, s.as_of, s.actor, s.started_at, s.finished_at,"
            " (SELECT count(*) FROM fact f WHERE f.session_id = s.id"
            "   OR (s.investigation_id IS NOT NULL AND f.investigation_id = s.investigation_id)"
            " ) AS facts, s.card->'open_questions' AS open_questions"
            " FROM research_session s WHERE s.theme = :theme"
            " AND (CAST(:exclude AS uuid) IS NULL OR s.id <> :exclude)"
            " ORDER BY s.as_of DESC, s.started_at DESC, s.id"
        ),
        {"theme": theme, "exclude": exclude_session_id},
    ).all()
    found: list[PriorSession] = []
    hidden = 0
    for row in rows:
        if row.as_of > as_of:
            hidden += 1
            continue
        raw: Any = row.open_questions
        questions = [str(each) for each in cast(list[Any], raw)] if isinstance(raw, list) else []
        found.append(
            PriorSession(
                id=row.id,
                kind=row.kind,
                question=row.question,
                same_question=question is not None and _same_question(row.question, question),
                as_of=row.as_of,
                actor=row.actor,
                started_at=row.started_at,
                finished_at=row.finished_at,
                facts=row.facts,
                open_questions=questions,
            )
        )
    return found, hidden


def _issues(
    connection: Connection,
    theme: str,
    company_ids: list[uuid.UUID],
    explicit_companies: bool,
    steps: list[str],
    as_of: datetime,
    slugs: dict[uuid.UUID, str],
) -> list[PriorIssue]:
    everything: dict[uuid.UUID, Issue] = {}
    scanned = 0
    while scanned < _ISSUE_SCAN_LIMIT:
        page, total = list_issues(connection, theme=theme, limit=_ISSUE_SCAN, offset=scanned)
        everything.update({each.id: each for each in page})
        scanned += len(page)
        if not page or scanned >= total:
            break
    produced = {
        row.id: row.as_of
        for row in connection.execute(
            text("SELECT id, as_of FROM research_session WHERE theme = :theme"), {"theme": theme}
        )
    }
    asked = set(company_ids)

    def visible(issue: Issue) -> bool:
        if issue.produced_by is not None and issue.produced_by in produced:
            return produced[issue.produced_by] <= as_of
        return _aware(issue.created_at) <= as_of

    def touches(issue: Issue) -> bool:
        if not explicit_companies and not steps:
            return True
        parent = everything.get(issue.parent_id) if issue.parent_id else None
        near: set[uuid.UUID] = set(issue.company_ids)
        if parent is not None:
            near |= set(parent.company_ids)
        if explicit_companies and near & asked:
            return True
        return any(issue.kind == "step" and issue.body.startswith(f"{step}:") for step in steps)

    found = [
        PriorIssue(
            id=each.id,
            title=each.title,
            kind=each.kind,
            priority=each.priority,
            companies=[slugs[c] for c in each.company_ids if c in slugs],
            parent_title=each.parent_title,
            produced_by=each.produced_by,
        )
        for each in sorted(
            everything.values(), key=lambda each: (-each.priority, each.created_at, str(each.id))
        )
        if each.status == "active" and visible(each) and touches(each)
    ]
    return found
