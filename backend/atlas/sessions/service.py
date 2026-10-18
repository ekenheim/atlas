"""Opening, closing, recording and reading research sessions."""

import json
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, JsonValue
from sqlalchemy import Connection, Engine, text

from atlas.audit import Actor, content_hash, record
from atlas.facts import Fact, list_facts
from atlas.issues import create_session_issues

if TYPE_CHECKING:
    from atlas.judging import Judges

type SessionKind = Literal["claude", "pipeline"]


class SessionNotFound(Exception):
    pass


class SessionAlreadyClosed(Exception):
    pass


class UnknownCompany(Exception):
    pass


class SessionOpen(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1)
    theme: str = Field(min_length=1)
    seed_company_ids: list[uuid.UUID] = Field(default_factory=list[uuid.UUID])
    as_of: datetime
    kind: Literal["claude"] = "claude"
    model: str | None = None
    actor: str | None = Field(default=None, description="who researches; default: the caller")
    isolated: bool = Field(
        default=False,
        description="an isolated session starts from nothing and leaves nothing for others"
        " (the early-call scorecard, ticket 29a): `prior_work` returns nothing to it, a Fact it"
        " records is never matched with a standing one, `recall` of the conclusions bank,"
        " `list_beliefs` and `get_belief` are refused, and a Belief it proposed can never be"
        " judged. Atlas enforces it; it is fixed when the session opens",
    )


class SessionClose(BaseModel):
    model_config = ConfigDict(extra="forbid")

    usage: dict[str, JsonValue] = Field(default_factory=dict[str, JsonValue])
    card: dict[str, JsonValue] | None = Field(
        default=None, description="the argument plan's card shape: steps, question parts, ..."
    )
    card_markdown: str | None = None


class SessionSummary(BaseModel):
    id: uuid.UUID
    question: str
    theme: str
    seed_company_ids: list[uuid.UUID]
    as_of: datetime
    kind: SessionKind
    model: str | None
    actor: str
    investigation_id: uuid.UUID | None
    started_at: datetime
    finished_at: datetime | None
    usage: dict[str, JsonValue]
    isolated: bool = Field(
        default=False,
        description="opened isolated (ticket 29a): no prior work, no Fact reuse, no conclusions"
        " bank, its Beliefs never judged",
    )
    facts: int = Field(description="the Facts recorded in it")
    tool_calls: int = Field(
        description="the calls it made through the Atlas MCP server, as Atlas counted them"
        " (`session_tool_call`; the usage it reports itself is its own)"
    )
    facts_reused: int = Field(
        default=0,
        description="the times it recorded a span an earlier Fact already covers and was given"
        " that Fact instead of a new one (`session_fact_reuse`, ticket 26)",
    )


class ResearchSession(SessionSummary):
    card: dict[str, JsonValue] | None
    card_markdown: str | None
    fact_items: list[Fact]


_SUMMARY = """
    SELECT s.id, s.question, s.theme, s.seed_company_ids, s.as_of, s.kind, s.model, s.actor,
           s.investigation_id, s.started_at, s.finished_at, s.usage, s.isolated,
           (SELECT count(*) FROM fact f WHERE f.session_id = s.id
               OR (s.investigation_id IS NOT NULL AND f.investigation_id = s.investigation_id)
           ) AS facts,
           (SELECT count(*) FROM session_tool_call c WHERE c.session_id = s.id) AS tool_calls,
           (SELECT count(*) FROM session_fact_reuse r WHERE r.session_id = s.id) AS facts_reused
    FROM research_session s
"""


def _summary(row: Any) -> SessionSummary:
    return SessionSummary(
        id=row.id,
        question=row.question,
        theme=row.theme,
        seed_company_ids=list(row.seed_company_ids),
        as_of=row.as_of,
        kind=row.kind,
        model=row.model,
        actor=row.actor,
        investigation_id=row.investigation_id,
        started_at=row.started_at,
        finished_at=row.finished_at,
        usage=row.usage,
        isolated=row.isolated,
        facts=row.facts,
        tool_calls=row.tool_calls,
        facts_reused=row.facts_reused,
    )


def list_sessions(
    connection: Connection, *, theme: str | None = None, limit: int, offset: int
) -> tuple[list[SessionSummary], int]:
    """Newest first."""
    params: dict[str, Any] = {"theme": theme, "limit": limit, "offset": offset}
    where = " WHERE (CAST(:theme AS text) IS NULL OR s.theme = :theme)"
    total = connection.execute(
        text(f"SELECT count(*) FROM research_session s {where}"),  # noqa: S608 (constants)
        params,
    ).scalar_one()
    rows = connection.execute(
        text(f"{_SUMMARY} {where} ORDER BY s.started_at DESC, s.id LIMIT :limit OFFSET :offset"),
        params,
    ).all()
    return [_summary(row) for row in rows], total


def get_session(connection: Connection, session_id: uuid.UUID) -> ResearchSession | None:
    row = connection.execute(
        text(f"{_SUMMARY} WHERE s.id = :id"),
        {"id": session_id},
    ).one_or_none()
    if row is None:
        return None
    extra = connection.execute(
        text("SELECT card, card_markdown FROM research_session WHERE id = :id"),
        {"id": session_id},
    ).one()
    summary = _summary(row)
    items, _ = list_facts(
        connection,
        session_id=None if summary.investigation_id else session_id,
        investigation_id=summary.investigation_id,
        limit=1000,
        offset=0,
    )
    return ResearchSession(
        **summary.model_dump(), card=extra.card, card_markdown=extra.card_markdown, fact_items=items
    )


class ToolCall(BaseModel):
    """One call a session made through the Atlas MCP server, as Atlas recorded it."""

    id: uuid.UUID
    tool: str
    arguments: dict[str, JsonValue] = Field(description="the arguments as received")
    outcome: Literal["ok", "refused", "error"]
    reason: str | None = Field(description="the refusal's or error's code")
    at: datetime


def list_tool_calls(connection: Connection, session_id: uuid.UUID) -> list[ToolCall] | None:
    """The session's recorded tool calls, in the order they were made (`session_tool_call`,
    insert-only); None when there is no such session. For classifying a scorecard run's misses
    (ticket 29a): what it searched, read and recorded, and what Atlas refused it."""
    if not connection.execute(
        text("SELECT EXISTS (SELECT FROM research_session WHERE id = :id)"), {"id": session_id}
    ).scalar_one():
        return None
    rows = connection.execute(
        text(
            "SELECT id, tool, arguments, outcome, reason, created_at FROM session_tool_call"
            " WHERE session_id = :id ORDER BY created_at, id"
        ),
        {"id": session_id},
    ).all()
    return [
        ToolCall(
            id=row.id,
            tool=row.tool,
            arguments=row.arguments,
            outcome=row.outcome,
            reason=row.reason,
            at=row.created_at,
        )
        for row in rows
    ]


def session_is_isolated(connection: Connection, session_id: uuid.UUID | None) -> bool:
    """Whether the session was opened isolated (ticket 29a). No session, or an unknown one,
    is not isolated: the callers that matter name a session they have checked."""
    if session_id is None:
        return False
    return bool(
        connection.execute(
            text("SELECT isolated FROM research_session WHERE id = :id"), {"id": session_id}
        ).scalar_one_or_none()
    )


def card_fact_ids(card: dict[str, JsonValue]) -> list[uuid.UUID]:
    """The Facts a card's statements cite, in card order and without repeats: the `fact_id` of
    each of `steps[*].statements[*].facts` (and each of a statement's `fact_ids`)."""
    found: dict[uuid.UUID, None] = {}

    def add(value: Any) -> None:
        try:
            found.setdefault(uuid.UUID(str(value)), None)
        except ValueError:
            pass

    steps: Any = card.get("steps")
    for step in cast(list[Any], steps) if isinstance(steps, list) else []:
        statements: Any = (
            cast(dict[str, Any], step).get("statements") if isinstance(step, dict) else None
        )
        for statement in cast(list[Any], statements) if isinstance(statements, list) else []:
            if not isinstance(statement, dict):
                continue
            cited = cast(dict[str, Any], statement)
            facts: Any = cited.get("facts")
            for fact in cast(list[Any], facts) if isinstance(facts, list) else []:
                if isinstance(fact, dict):
                    add(cast(dict[str, Any], fact).get("fact_id"))
            fact_ids: Any = cited.get("fact_ids")
            for fact_id in cast(list[Any], fact_ids) if isinstance(fact_ids, list) else []:
                add(fact_id)
    return list(found)


class Sessions:
    def __init__(self, engine: Engine, actor: Actor, judges: "Judges | None" = None) -> None:
        self._engine = engine
        self._actor = actor
        self._judges = judges

    def _is_open_claude_session(self, session_id: uuid.UUID) -> bool:
        with self._engine.connect() as connection:
            row = connection.execute(
                text("SELECT finished_at, kind FROM research_session WHERE id = :id"),
                {"id": session_id},
            ).one_or_none()
        return row is not None and row.finished_at is None and row.kind == "claude"

    def _judge_thesis(
        self, session_id: uuid.UUID, card: dict[str, JsonValue]
    ) -> dict[str, JsonValue] | None:
        """The judge's verdict on the card's `thesis` against the Facts its statements cite
        (ticket 23), for the card's `thesis_judged`, judged as a thesis (`finding_judge.v5`, ticket
        24: its bare hedged proposition needs no basis); None when the card has no thesis or the
        judge is off. A misstated thesis is flagged here, never refused."""
        # Imported here: the judge's modules read the Facts, which the sessions package lists.
        from atlas.investigations.argument import fact_rows
        from atlas.judging import MAX_THESIS_FACTS, JudgeUnavailable

        thesis = card.get("thesis")
        if self._judges is None or not self._judges.judges_session():
            return None
        if not isinstance(thesis, str) or not thesis.strip():
            return None
        with self._engine.connect() as connection:
            question = connection.execute(
                text("SELECT question FROM research_session WHERE id = :id"), {"id": session_id}
            ).scalar_one_or_none()
            rows = fact_rows(connection, card_fact_ids(card)[:MAX_THESIS_FACTS])
        if question is None:
            return None
        base: dict[str, JsonValue] = {"fact_ids": [str(row["id"]) for row in rows]}
        if not rows:
            return {
                **base,
                "verdict": "unjudged",
                "reason": "the card's statements cite no recorded Fact to judge the thesis against",
            }
        try:
            verdict = self._judges.judge(
                "thesis_judge", question=question, statement=thesis, rows=rows, thesis=True
            )
        except JudgeUnavailable as unavailable:
            return {**base, "verdict": "unjudged", "reason": unavailable.reason}
        return {
            **base,
            "verdict": verdict.verdict,
            "reason": verdict.reason,
            "beyond": list(verdict.beyond),
            "kinds": list(verdict.kinds),
            "unverified": list(verdict.unverified),
            "judge": verdict.judge,
            "run_id": str(verdict.run_id),
        }

    def open(self, request: SessionOpen) -> SessionSummary:
        session_id = uuid.uuid4()
        with self._engine.begin() as connection:
            if request.seed_company_ids:
                known = connection.execute(
                    text("SELECT count(*) FROM company WHERE id = ANY(:ids)"),
                    {"ids": list(set(request.seed_company_ids))},
                ).scalar_one()
                if known != len(set(request.seed_company_ids)):
                    raise UnknownCompany("a seed company is not in the universe")
            connection.execute(
                text(
                    "INSERT INTO research_session (id, question, theme, seed_company_ids, as_of,"
                    " kind, model, actor, isolated) VALUES (:id, :question, :theme, :seeds, :as_of,"
                    " :kind, :model, :actor, :isolated)"
                ),
                {
                    "id": session_id,
                    "question": request.question,
                    "theme": request.theme,
                    "seeds": list(request.seed_company_ids),
                    "as_of": request.as_of,
                    "kind": request.kind,
                    "model": request.model,
                    "actor": request.actor or self._actor.name,
                    "isolated": request.isolated,
                },
            )
            row = connection.execute(
                text(f"{_SUMMARY} WHERE s.id = :id"),
                {"id": session_id},
            ).one()
            summary = _summary(row)
            record(
                connection,
                self._actor,
                "research_session.opened",
                entity_type="research_session",
                entity_id=str(session_id),
                new_hash=content_hash(summary.model_dump(mode="json")),
            )
        return summary

    def close(self, session_id: uuid.UUID, request: SessionClose) -> ResearchSession:
        card = request.card
        if card is not None and self._is_open_claude_session(session_id):
            # Judged before the transaction: an LLM call never holds the session's row lock.
            judged = self._judge_thesis(session_id, card)
            if judged is not None:
                card = {**card, "thesis_judged": judged}
        with self._engine.begin() as connection:
            row = connection.execute(
                text(
                    "SELECT finished_at, kind, isolated FROM research_session"
                    " WHERE id = :id FOR UPDATE"
                ),
                {"id": session_id},
            ).one_or_none()
            if row is None:
                raise SessionNotFound(str(session_id))
            if row.finished_at is not None or row.kind != "claude":
                raise SessionAlreadyClosed(str(session_id))
            connection.execute(
                text(
                    "UPDATE research_session SET finished_at = now(),"
                    " usage = CAST(:usage AS jsonb),"
                    " card = CAST(:card AS jsonb), card_markdown = :markdown WHERE id = :id"
                ),
                {
                    "id": session_id,
                    "usage": json.dumps(request.usage),
                    "card": None if card is None else json.dumps(card),
                    "markdown": request.card_markdown,
                },
            )
            session = get_session(connection, session_id)
            assert session is not None
            if not row.isolated:
                # An isolated session (ticket 29a) leaves no Issue: its question and open
                # questions would be the frontier of the next run.
                create_session_issues(
                    connection,
                    self._actor,
                    session_id=session_id,
                    question=session.question,
                    theme=session.theme,
                    seed_company_ids=session.seed_company_ids,
                    card=card,
                )
            record(
                connection,
                self._actor,
                "research_session.closed",
                entity_type="research_session",
                entity_id=str(session_id),
                new_hash=content_hash(session.model_dump(mode="json", exclude={"fact_items"})),
            )
        return session


def record_pipeline_session(
    connection: Connection,
    actor: Actor,
    *,
    investigation: Any,
    card: dict[str, Any],
    usage: dict[str, Any],
) -> uuid.UUID:
    """Record (or update, after a follow-up round) the session of an argument-plan
    investigation, in the transaction that stores its card."""
    existing = connection.execute(
        text("SELECT id FROM research_session WHERE investigation_id = :id"),
        {"id": investigation["id"]},
    ).scalar_one_or_none()
    params = {"card": json.dumps(card), "usage": json.dumps(usage)}
    if existing is None:
        session_id = uuid.uuid4()
        connection.execute(
            text(
                "INSERT INTO research_session (id, question, theme, seed_company_ids, as_of,"
                " kind, model, actor, investigation_id, started_at, finished_at, usage, card)"
                " VALUES (:id, :question, :theme, :seeds, :as_of, 'pipeline', NULL, :actor,"
                " :investigation, :started, now(), CAST(:usage AS jsonb), CAST(:card AS jsonb))"
            ),
            {
                **params,
                "id": session_id,
                "question": investigation["question"],
                "theme": investigation["theme"],
                "seeds": list(investigation["seed_company_ids"]),
                "as_of": investigation["as_of"],
                "actor": investigation["created_by"],
                "investigation": investigation["id"],
                "started": investigation["created_at"],
            },
        )
        action = "research_session.recorded"
    else:
        session_id = existing
        connection.execute(
            text(
                "UPDATE research_session SET card = CAST(:card AS jsonb),"
                " usage = CAST(:usage AS jsonb), finished_at = now() WHERE id = :id"
            ),
            {**params, "id": session_id},
        )
        action = "research_session.updated"
    record(
        connection,
        actor,
        action,
        entity_type="research_session",
        entity_id=str(session_id),
        new_hash=content_hash({"card": card, "usage": usage}),
    )
    return session_id
