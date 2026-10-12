"""Opening, closing, recording and reading research sessions."""

import json
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue
from sqlalchemy import Connection, Engine, text

from atlas.audit import Actor, content_hash, record
from atlas.facts import Fact, list_facts
from atlas.issues import create_session_issues

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
    facts: int = Field(description="the Facts recorded in it")


class ResearchSession(SessionSummary):
    card: dict[str, JsonValue] | None
    card_markdown: str | None
    fact_items: list[Fact]


_SUMMARY = """
    SELECT s.id, s.question, s.theme, s.seed_company_ids, s.as_of, s.kind, s.model, s.actor,
           s.investigation_id, s.started_at, s.finished_at, s.usage,
           (SELECT count(*) FROM fact f WHERE f.session_id = s.id
               OR (s.investigation_id IS NOT NULL AND f.investigation_id = s.investigation_id)
           ) AS facts
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
        facts=row.facts,
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


class Sessions:
    def __init__(self, engine: Engine, actor: Actor) -> None:
        self._engine = engine
        self._actor = actor

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
                    " kind, model, actor) VALUES (:id, :question, :theme, :seeds, :as_of, :kind,"
                    " :model, :actor)"
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
        with self._engine.begin() as connection:
            row = connection.execute(
                text("SELECT finished_at, kind FROM research_session WHERE id = :id FOR UPDATE"),
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
                    "card": None if request.card is None else json.dumps(request.card),
                    "markdown": request.card_markdown,
                },
            )
            session = get_session(connection, session_id)
            assert session is not None
            create_session_issues(
                connection,
                self._actor,
                session_id=session_id,
                question=session.question,
                theme=session.theme,
                seed_company_ids=session.seed_company_ids,
                card=request.card,
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
