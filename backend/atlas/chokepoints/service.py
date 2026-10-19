"""Reading the board and writing to it: every rule of an event lives here, so the routes and the
MCP tools share it."""

import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, cast

from pydantic import BaseModel, JsonValue, ValidationError
from sqlalchemy import Connection, Engine, text

from atlas.audit import Actor, content_hash, record
from atlas.chokepoints.model import (
    PAYLOADS,
    PROSPECTIVE_WINDOW,
    THESIS_STEPS,
    BoardCounts,
    Chokepoint,
    ChokepointCreate,
    ChokepointDetail,
    ChokepointError,
    ChokepointEvent,
    CreatedPayload,
    EventCreate,
    EventKind,
    EvidenceFact,
    EvidenceIssue,
    EvidenceLead,
    FieldSetPayload,
    HolderState,
    StatusSetPayload,
    StepEvidence,
    StepSetPayload,
    WatchRun,
    WatchRunCreate,
    fold,
)
from atlas.discovery.bounds import lead_bound
from atlas.jobs.pacing import Clock, utc_now

# --- reads ---------------------------------------------------------------------------------

_EVENT_COLUMNS = "id, chokepoint_id, at, actor, session_id, run_id, kind, payload, reason"


def _event(row: Any) -> ChokepointEvent:
    return ChokepointEvent(
        id=row.id,
        chokepoint_id=row.chokepoint_id,
        at=row.at,
        actor=row.actor,
        session_id=row.session_id,
        run_id=row.run_id,
        kind=row.kind,
        payload=row.payload,
        reason=row.reason,
    )


def _linked_issues(events: Sequence[ChokepointEvent]) -> list[uuid.UUID]:
    found: dict[uuid.UUID, None] = {}
    for event in events:
        if event.kind == "field_set":
            for each in cast(list[str], event.payload.get("issue_ids") or []):
                found[uuid.UUID(each)] = None
    return list(found)


def _load(
    connection: Connection, where: str, params: dict[str, Any], now: datetime
) -> list[ChokepointDetail]:
    heads = (
        connection.execute(
            text(
                "SELECT id, theme, created_at, created_by_session, created_by_run"  # noqa: S608
                f" FROM chokepoint WHERE {where}"
            ),
            params,
        )
        .mappings()
        .all()
    )
    by_id: dict[uuid.UUID, list[ChokepointEvent]] = {head["id"]: [] for head in heads}
    for row in connection.execute(
        text(
            f"SELECT {_EVENT_COLUMNS} FROM chokepoint_event"  # noqa: S608 (constants)
            " WHERE chokepoint_id = ANY(:ids) ORDER BY seq"
        ),
        {"ids": list(by_id)},
    ):
        by_id[row.chokepoint_id].append(_event(row))
    linked = list({each for events in by_id.values() for each in _linked_issues(events)})
    active = (
        frozenset(
            connection.execute(
                text("SELECT id FROM issue WHERE id = ANY(:ids) AND status = 'active'"),
                {"ids": linked},
            ).scalars()
        )
        if linked
        else frozenset[uuid.UUID]()
    )
    return [fold(dict(head), by_id[head["id"]], now, active) for head in heads]


def _universe_company_ids(
    connection: Connection, holders: Sequence[HolderState]
) -> tuple[dict[str, uuid.UUID], dict[str, uuid.UUID]]:
    """The researched companies' ids by slug and by (ten-digit) CIK, for the holders named."""
    slugs = sorted({each.slug for each in holders if each.slug})
    ciks = sorted({each.cik.zfill(10) for each in holders if each.cik})
    if not slugs and not ciks:
        return {}, {}
    rows = connection.execute(
        text(
            "SELECT id, slug, cik FROM company WHERE role = 'researched'"
            " AND (slug = ANY(:slugs) OR cik = ANY(:ciks))"
        ),
        {"slugs": slugs, "ciks": ciks},
    )
    by_slug: dict[str, uuid.UUID] = {}
    by_cik: dict[str, uuid.UUID] = {}
    for row in rows:
        by_slug[row.slug] = row.id
        if row.cik:
            by_cik[row.cik] = row.id
    return by_slug, by_cik


def _with_companies[C: Chokepoint](connection: Connection, found: list[C]) -> list[C]:
    """Each holder with the universe company its slug, else its CIK, resolves to: one query for
    every holder of every chokepoint given."""
    by_slug, by_cik = _universe_company_ids(
        connection, [holder for each in found for holder in each.holders]
    )

    def company(holder: HolderState) -> uuid.UUID | None:
        if holder.slug and holder.slug in by_slug:
            return by_slug[holder.slug]
        return by_cik.get(holder.cik.zfill(10)) if holder.cik else None

    return [
        each.model_copy(
            update={
                "holders": [
                    holder.model_copy(update={"company_id": company(holder)})
                    for holder in each.holders
                ]
            }
        )
        for each in found
    ]


def _cited(detail: ChokepointDetail) -> tuple[list[uuid.UUID], list[uuid.UUID], list[uuid.UUID]]:
    """The Facts, leads and Issues the current state cites, once each, in the steps' order (the
    Issues the chokepoint links last)."""
    facts: dict[uuid.UUID, None] = {}
    leads: dict[uuid.UUID, None] = {}
    issues: dict[uuid.UUID, None] = {}
    for step in detail.steps:
        facts.update(dict.fromkeys(step.evidence.fact_ids))
        leads.update(dict.fromkeys(step.evidence.lead_ids))
        issues.update(dict.fromkeys(step.evidence.issue_ids))
    issues.update(dict.fromkeys(detail.issue_ids))
    return list(facts), list(leads), list(issues)


def _with_evidence(
    connection: Connection, detail: ChokepointDetail, session: "SessionInfo | None" = None
) -> ChokepointDetail:
    """The cited Facts, leads and Issues read out: at most one query for each kind, whatever
    the number cited. A session's read shows only what it could see (the rules of the board's
    own checks: a Fact public, a lead first seen and an Issue opened by its as-of time, an Issue
    its own session opened too); the owner's read, with no session, shows everything cited."""
    fact_ids, lead_ids, issue_ids = _cited(detail)
    if session is not None and fact_ids:
        seen = _visible_facts(connection, fact_ids, session)
        fact_ids = [each for each in fact_ids if each in seen]
    facts: dict[uuid.UUID, EvidenceFact] = {}
    if fact_ids:
        for row in connection.execute(
            text(
                "SELECT a.id, a.value_json ->> 'statement' AS statement, a.quote,"
                " c.display_name AS company_name, d.title AS document_title,"
                " v.available_at, a.source_version_id"
                " FROM assertion a JOIN fact f ON f.assertion_id = a.id"
                " JOIN source_version_availability v ON v.source_version_id = a.source_version_id"
                " JOIN source_version sv ON sv.id = a.source_version_id"
                " JOIN source_document d ON d.id = sv.source_document_id"
                " LEFT JOIN company c ON c.id = a.subject_company_id"
                " WHERE a.id = ANY(:ids)"
            ),
            {"ids": fact_ids},
        ):
            facts[row.id] = EvidenceFact(
                id=row.id,
                assertion_id=row.id,
                statement=row.statement,
                quote=row.quote,
                company_name=row.company_name,
                document_title=row.document_title,
                available_at=row.available_at,
                source_version_id=row.source_version_id,
            )
    leads: dict[uuid.UUID, EvidenceLead] = {}
    if lead_ids:
        for row in _leads(connection, lead_ids, session):
            if session is not None and _lead_refusal(row, session) is not None:
                continue
            leads[row.id] = EvidenceLead(
                id=row.id,
                title=row.title,
                url=row.url,
                origin=row.origin,
                published_at=row.published_date,
            )
    issues: dict[uuid.UUID, EvidenceIssue] = {}
    if issue_ids:
        for row in connection.execute(
            text(
                "SELECT id, title, status FROM issue WHERE id = ANY(:ids)"
                " AND (CAST(:as_of AS timestamptz) IS NULL OR created_at <= :as_of"
                "      OR produced_by = :session)"
            ),
            {
                "ids": issue_ids,
                "as_of": session.as_of if session else None,
                "session": session.id if session else None,
            },
        ):
            issues[row.id] = EvidenceIssue(id=row.id, title=row.title, status=row.status)
    return detail.model_copy(
        update={
            "facts": [facts[each] for each in fact_ids if each in facts],
            "leads": [leads[each] for each in lead_ids if each in leads],
            "issues": [issues[each] for each in issue_ids if each in issues],
        }
    )


def get_chokepoint(
    connection: Connection,
    chokepoint_id: uuid.UUID,
    now: datetime,
    session: "SessionInfo | None" = None,
) -> ChokepointDetail | None:
    """The chokepoint. With a reading `session` its cited Facts, leads and Issues are those the
    session could see; without one, all of them."""
    found = _load(connection, "id = :id", {"id": chokepoint_id}, now)
    if not found:
        return None
    return _with_evidence(connection, _with_companies(connection, found)[0], session)


def summary(detail: ChokepointDetail) -> Chokepoint:
    return Chokepoint.model_validate(
        detail.model_dump(exclude={"history", "facts", "leads", "issues"})
    )


def _matches(each: Chokepoint, status: str) -> bool:
    """Whether the chokepoint is in the state: the stored status, or a derived flag."""
    if status == "stale":
        return each.stale
    if status == "needs_review":
        return each.needs_review
    return each.status == status


def board_counts(connection: Connection, now: datetime, *, theme: str | None = None) -> BoardCounts:
    """The chokepoints of the theme (all of them without one) counted by state."""
    found = _load(
        connection, "(CAST(:theme AS text) IS NULL OR theme = :theme)", {"theme": theme}, now
    )
    return BoardCounts(
        lead=sum(_matches(each, "lead") for each in found),
        candidate=sum(_matches(each, "candidate") for each in found),
        thesis_ready=sum(_matches(each, "thesis_ready") for each in found),
        killed=sum(_matches(each, "killed") for each in found),
        stale=sum(_matches(each, "stale") for each in found),
        needs_review=sum(_matches(each, "needs_review") for each in found),
    )


def list_chokepoints(
    connection: Connection,
    now: datetime,
    *,
    theme: str | None = None,
    status: str | None = None,
    limit: int,
    offset: int,
) -> tuple[list[Chokepoint], int]:
    """The latest event first. `status` is the stored status, or `stale` / `needs_review` (the
    derived flags)."""
    found = _load(
        connection, "(CAST(:theme AS text) IS NULL OR theme = :theme)", {"theme": theme}, now
    )
    if status is not None:
        found = [each for each in found if _matches(each, status)]
    found.sort(key=lambda each: (each.last_event_at, str(each.id)), reverse=True)
    page = _with_companies(connection, found[offset : offset + limit])
    return [summary(each) for each in page], len(found)


# --- checks --------------------------------------------------------------------------------


@dataclass(frozen=True)
class SessionInfo:
    id: uuid.UUID
    as_of: datetime
    theme: str
    actor: str


def _check_session(
    connection: Connection, session_id: uuid.UUID | None, now: datetime
) -> SessionInfo | None:
    """The session a write or a read names. It must exist, be open, not be isolated (an isolated
    session, the early-call scorecard's, leaves nothing for others to find) and be of now: the
    board is prospective, so a session whose as-of time is more than 36 hours before `now` (a
    replay) is refused."""
    if session_id is None:
        return None
    row = connection.execute(
        text(
            "SELECT as_of, isolated, theme, actor, kind, finished_at FROM research_session"
            " WHERE id = :id"
        ),
        {"id": session_id},
    ).one_or_none()
    if row is None:
        raise ChokepointError(422, "unknown_session", "no such research session")
    if row.isolated:
        raise ChokepointError(
            422,
            "isolated_session",
            "an isolated session (the early-call scorecard) has no board: it starts from"
            " nothing and leaves nothing for others",
        )
    if row.kind != "claude" or row.finished_at is not None:
        raise ChokepointError(
            422, "session_closed", "the session is closed (or is not a claude one)"
        )
    if row.as_of < now - PROSPECTIVE_WINDOW:
        raise ChokepointError(
            422,
            "not_prospective",
            "the board is prospective: a session whose as-of time is more than 36 hours old is a"
            " replay and may not read or write it",
            as_of=row.as_of.isoformat(),
        )
    return SessionInfo(session_id, row.as_of, row.theme, row.actor)


def check_read_session(
    engine: Engine, session_id: uuid.UUID | None, now: datetime
) -> SessionInfo | None:
    """Refuse a read that names a session the board is closed to; else the session (none: the
    owner's read)."""
    with engine.connect() as connection:
        return _check_session(connection, session_id, now)


def _same_theme(session: SessionInfo | None, theme: str) -> None:
    if session is not None and session.theme != theme:
        raise ChokepointError(
            422,
            "other_theme",
            f"the session is of theme {session.theme!r}, the chokepoint of {theme!r}",
        )


def _check_run(connection: Connection, run_id: uuid.UUID | None) -> None:
    if (
        run_id is not None
        and connection.execute(text("SELECT 1 FROM run WHERE id = :id"), {"id": run_id}).first()
        is None
    ):
        raise ChokepointError(422, "unknown_run", "no such run")


def _unknown(table: str, what: str, wanted: Sequence[uuid.UUID], held: set[uuid.UUID]) -> None:
    if missing := sorted(str(each) for each in set(wanted) - held):
        raise ChokepointError(
            422, f"unknown_{table}", f"no such {what}: {', '.join(missing)}", ids=missing
        )


def _visible_facts(
    connection: Connection, ids: Sequence[uuid.UUID], session: SessionInfo
) -> set[uuid.UUID]:
    """The Facts (by Assertion id) the session may see. The same rule as the MCP tools'
    (`Ctx.visible_version`) and the archive search's: a Fact of a Source Version public after
    the session's as-of time (its effective availability) is not visible to it. A web page (W3)
    is visible when it was public and fetched by the as-of time, or when this session fetched it
    with its as-of time at most `PROSPECTIVE_WINDOW` before that fetch. (The session is never
    isolated here: `_check_session` refused it.)"""
    return {
        row.assertion_id
        for row in connection.execute(
            text(
                "SELECT s.id AS assertion_id FROM assertion s"
                " JOIN source_version v ON v.id = s.source_version_id"
                " JOIN source_document d ON d.id = v.source_document_id"
                " JOIN source_version_availability a ON a.source_version_id = v.id"
                " WHERE s.id = ANY(:ids)"
                "   AND ((d.provider <> 'web' AND a.available_at <= :as_of)"
                "     OR (d.provider = 'web' AND ("
                "       (a.available_at <= :as_of AND v.fetched_at <= :as_of)"
                "       OR EXISTS (SELECT 1 FROM fetch_observation o"
                "         WHERE o.source_version_id = v.id AND o.session_id = :session"
                "           AND o.fetched_at <= :fetched_by))))"
            ),
            {
                "ids": list(set(ids)),
                "as_of": session.as_of,
                "session": session.id,
                "fetched_by": session.as_of + PROSPECTIVE_WINDOW,
            },
        )
    }


def _check_facts(
    connection: Connection, ids: Sequence[uuid.UUID], session: SessionInfo | None
) -> None:
    if not ids:
        return
    found = connection.execute(
        text(
            "SELECT f.assertion_id, a.available_at,"
            " COALESCE(r.isolated, false) AS isolated FROM fact f"
            " JOIN assertion s ON s.id = f.assertion_id"
            " JOIN source_version_availability a ON a.source_version_id = s.source_version_id"
            " LEFT JOIN research_session r ON r.id = f.session_id"
            " WHERE f.assertion_id = ANY(:ids) ORDER BY a.available_at, f.assertion_id"
        ),
        {"ids": list(set(ids))},
    ).all()
    _unknown("fact", "Fact", ids, {row.assertion_id for row in found})
    for row in found:
        if row.isolated:
            raise ChokepointError(
                422,
                "fact_not_in_session",
                "a Fact recorded by an isolated session (the early-call scorecard) is not on the"
                " board's record",
                fact=str(row.assertion_id),
            )
    if session is None:
        return
    visible = _visible_facts(connection, ids, session)
    for row in found:
        if row.assertion_id not in visible:
            raise ChokepointError(
                422,
                "fact_available_after_as_of",
                "that Fact's document became public after the session's as-of time",
                fact=str(row.assertion_id),
                available_at=row.available_at.isoformat(),
                as_of=session.as_of.isoformat(),
            )


def _check_leads(
    connection: Connection, ids: Sequence[uuid.UUID], session: SessionInfo | None
) -> None:
    if not ids:
        return
    found = _leads(connection, list(set(ids)), session)
    _unknown("lead", "lead", ids, {row.id for row in found})
    if session is None:
        return
    for row in found:
        refusal = _lead_refusal(row, session)
        if refusal == "published_after_as_of":
            raise ChokepointError(
                422,
                refusal,
                "that lead dates itself after the last day certainly public by the session's"
                " as-of time",
                lead=str(row.id),
                published_date=row.published_date.isoformat(),
                as_of=session.as_of.isoformat(),
            )
        if refusal == "created_after_as_of":
            raise ChokepointError(
                422,
                refusal,
                "that lead was first seen after the session's as-of time, and not by this"
                " session's own search",
                lead=str(row.id),
            )


def _leads(
    connection: Connection, ids: Sequence[uuid.UUID], session: "SessionInfo | None"
) -> list[Any]:
    """The leads, each with whether the session's own searches (`web_search`, `filing_search`:
    a `discovery_query` of the session) found or saw it again (`found_by_session`)."""
    return list(
        connection.execute(
            text(
                "SELECT l.id, l.title, l.url, l.origin, l.published_date, l.first_seen_at,"
                " EXISTS (SELECT 1 FROM lead_sighting s"
                "  JOIN discovery_query q ON q.id = s.discovery_query_id"
                "  WHERE s.lead_id = l.id AND q.session_id = :session) AS found_by_session"
                " FROM lead l WHERE l.id = ANY(:ids) ORDER BY l.id"
            ),
            {"ids": list(ids), "session": session.id if session else None},
        ).all()
    )


def _lead_refusal(row: Any, session: "SessionInfo") -> str | None:
    """Why a session may not cite a lead, or None (W9; docs/decisions.md, "The Watch's reach").
    A lead first seen by the as-of time was public by then. One first seen after it counts only
    when the session's own search found it, and then only if it does not date itself after the
    last day certainly public by the as-of time (`lead_bound`, the searches' own rule). A lead
    dated after the as-of day is refused whoever found it."""
    published: date | None = row.published_date
    if published is not None and published > session.as_of.astimezone(UTC).date():
        return "published_after_as_of"
    if row.first_seen_at <= session.as_of:
        return None
    if not row.found_by_session:
        return "created_after_as_of"
    if published is not None and published > lead_bound(row.origin, session.as_of):
        return "published_after_as_of"
    return None


def _check_issues(
    connection: Connection, ids: Sequence[uuid.UUID], theme: str, session: SessionInfo | None
) -> None:
    """The Issues exist, are of the chokepoint's theme, and were not opened after the session's
    as-of time (unless that session opened them: an agent links what it has just written)."""
    if not ids:
        return
    found = connection.execute(
        text("SELECT id, theme, created_at, produced_by FROM issue WHERE id = ANY(:ids)"),
        {"ids": list(set(ids))},
    ).all()
    _unknown("issue", "Issue", ids, {row.id for row in found})
    for row in found:
        if row.theme != theme:
            raise ChokepointError(
                422,
                "other_theme",
                f"that Issue is of theme {row.theme!r}, the chokepoint of {theme!r}",
                issue=str(row.id),
            )
        if session is not None and row.created_at > session.as_of and row.produced_by != session.id:
            raise ChokepointError(
                422,
                "created_after_as_of",
                "that Issue was opened after the session's as-of time, by another session",
                issue=str(row.id),
            )


def _check_evidence(
    connection: Connection, evidence: StepEvidence, theme: str, session: SessionInfo | None
) -> None:
    _check_facts(connection, evidence.fact_ids, session)
    _check_leads(connection, evidence.lead_ids, session)
    _check_issues(connection, evidence.issue_ids, theme, session)


def _check_status(status: str, evidence: StepEvidence) -> None:
    if status in ("primary", "contradicted") and not evidence.fact_ids:
        raise ChokepointError(
            422,
            "step_needs_fact",
            f"a step set to {status} cites at least one Fact (evidence.fact_ids)",
        )
    if status == "lead" and not (evidence.lead_ids or evidence.issue_ids):
        raise ChokepointError(
            422,
            "step_needs_lead",
            "a step set to lead cites a lead or an Issue (evidence.lead_ids or issue_ids)",
        )


def _parse[M: BaseModel](model: type[M], payload: dict[str, JsonValue], kind: str) -> M:
    try:
        return model.model_validate(payload)
    except ValidationError as invalid:
        problems = [
            f"{'.'.join(str(part) for part in error['loc']) or 'payload'}: {error['msg']}"
            for error in invalid.errors()
        ]
        raise ChokepointError(422, "invalid_payload", f"{kind}: {'; '.join(problems)}") from None


# --- writes --------------------------------------------------------------------------------


class Chokepoints:
    def __init__(self, engine: Engine, actor: Actor, clock: Clock = utc_now) -> None:
        self._engine = engine
        self._actor = actor
        self._clock = clock

    @staticmethod
    def _insert_event(
        connection: Connection,
        chokepoint_id: uuid.UUID,
        *,
        kind: EventKind,
        payload: dict[str, Any],
        reason: str | None,
        session_id: uuid.UUID | None,
        run_id: uuid.UUID | None,
        actor: str,
        at: datetime,
    ) -> None:
        connection.execute(
            text(
                "INSERT INTO chokepoint_event (id, chokepoint_id, at, actor, session_id, run_id,"
                " kind, payload, reason) VALUES (:id, :chokepoint, :at, :actor, :session, :run,"
                " :kind, CAST(:payload AS jsonb), :reason)"
            ),
            {
                "id": uuid.uuid4(),
                "chokepoint": chokepoint_id,
                "at": at,
                "actor": actor,
                "session": session_id,
                "run": run_id,
                "kind": kind,
                "payload": json.dumps(payload, default=str),
                "reason": reason,
            },
        )

    def _who(self, named: str | None, session: SessionInfo | None) -> Actor:
        return Actor(named or (session.actor if session else None) or self._actor.name)

    def create(self, request: ChokepointCreate) -> ChokepointDetail:
        at = self._clock().astimezone(UTC)
        chokepoint_id = uuid.uuid4()
        with self._engine.begin() as connection:
            session = _check_session(connection, request.session_id, at)
            _same_theme(session, request.theme)
            _check_run(connection, request.run_id)
            actor = self._who(request.actor, session)
            connection.execute(
                text(
                    "INSERT INTO chokepoint (id, theme, created_at, created_by_session,"
                    " created_by_run) VALUES (:id, :theme, :at, :session, :run)"
                ),
                {
                    "id": chokepoint_id,
                    "theme": request.theme,
                    "at": at,
                    "session": request.session_id,
                    "run": request.run_id,
                },
            )
            created = CreatedPayload(
                constraint=request.constraint, layer=request.layer, holders=request.holders
            )
            self._insert_event(
                connection,
                chokepoint_id,
                kind="created",
                payload=created.model_dump(mode="json"),
                reason=None,
                session_id=request.session_id,
                run_id=request.run_id,
                actor=actor.name,
                at=at,
            )
            state = get_chokepoint(connection, chokepoint_id, at)
            assert state is not None
            record(
                connection,
                actor,
                "chokepoint.created",
                entity_type="chokepoint",
                entity_id=str(chokepoint_id),
                new_hash=content_hash(summary(state).model_dump(mode="json")),
            )
        return state

    def append(self, chokepoint_id: uuid.UUID, request: EventCreate) -> ChokepointDetail | None:
        """Append one event; None when there is no such chokepoint."""
        at = self._clock().astimezone(UTC)
        with self._engine.begin() as connection:
            # One writer at a time per chokepoint. (Not SELECT ... FOR UPDATE: the app role has
            # SELECT and INSERT only.)
            connection.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:id))"), {"id": str(chokepoint_id)}
            )
            session = _check_session(connection, request.session_id, at)
            before = get_chokepoint(connection, chokepoint_id, at)
            if before is None:
                return None
            _same_theme(session, before.theme)
            _check_run(connection, request.run_id)
            actor = self._who(request.actor, session)
            payload = self._validated(connection, before, request, session)
            self._insert_event(
                connection,
                chokepoint_id,
                kind=request.kind,
                payload=payload,
                reason=request.reason,
                session_id=request.session_id,
                run_id=request.run_id,
                actor=actor.name,
                at=at,
            )
            after = get_chokepoint(connection, chokepoint_id, at)
            assert after is not None
            record(
                connection,
                actor,
                "chokepoint.updated",
                entity_type="chokepoint",
                entity_id=str(chokepoint_id),
                old_hash=content_hash(summary(before).model_dump(mode="json")),
                new_hash=content_hash(summary(after).model_dump(mode="json")),
            )
        return after

    @staticmethod
    def _validated(
        connection: Connection,
        before: ChokepointDetail,
        request: EventCreate,
        session: SessionInfo | None,
    ) -> dict[str, Any]:
        """The event's payload as it is stored (an append resolved to the list it makes, so the
        fold only ever replaces), once the kind's rules hold."""
        parsed = _parse(PAYLOADS[request.kind], request.payload, request.kind)
        if isinstance(parsed, FieldSetPayload):
            payload = parsed.model_dump(mode="json", exclude_unset=True)
            if parsed.add_issue_ids is not None:
                _check_issues(connection, parsed.add_issue_ids, before.theme, session)
                payload.pop("add_issue_ids")
                linked = [*before.issue_ids]
                linked += [
                    each for each in dict.fromkeys(parsed.add_issue_ids) if each not in linked
                ]
                payload["issue_ids"] = [str(each) for each in linked]
            elif parsed.issue_ids is not None:
                _check_issues(connection, parsed.issue_ids, before.theme, session)
            return payload
        if isinstance(parsed, StepSetPayload):
            appended = parsed.add_evidence is not None
            given = parsed.add_evidence if parsed.add_evidence is not None else parsed.evidence
            current = next(each for each in before.steps if each.step == parsed.step)
            evidence = current.evidence.merged(given) if appended else given
            if (
                before.status == "thesis_ready"
                and parsed.step in THESIS_STEPS
                and parsed.status != "primary"
            ):
                raise ChokepointError(
                    422,
                    "thesis_ready_step_locked",
                    f"step {parsed.step} is part of what makes this chokepoint thesis_ready:"
                    " move its status down first (status_set), then change the step",
                )
            _check_status(parsed.status, evidence)
            _check_evidence(connection, given, before.theme, session)
            return {
                "step": parsed.step,
                "status": parsed.status,
                "evidence": evidence.model_dump(mode="json"),
            }
        if isinstance(parsed, StatusSetPayload):
            if parsed.status == "killed" and not (request.reason and request.reason.strip()):
                raise ChokepointError(422, "reason_required", "a killed chokepoint needs a reason")
            if parsed.status == "thesis_ready" and not before.thesis_gate.holds:
                missing = before.thesis_gate.missing
                raise ChokepointError(
                    422,
                    "thesis_not_ready",
                    "thesis_ready needs steps a, b and d primary, a kill criterion and an open"
                    f" linked Issue; missing: {', '.join(missing)}",
                    missing=missing,
                )
        return parsed.model_dump(mode="json")


# --- the Watch's run record ----------------------------------------------------------------

_WATCH_COLUMNS = (
    "id, theme, run_date, mode, memo, counts, tool_calls, cost_usd, tokens, session_id, created_at"
)


def _watch_run(row: Any) -> WatchRun:
    return WatchRun(
        id=row.id,
        theme=row.theme,
        run_date=row.run_date,
        mode=row.mode,
        memo=row.memo,
        counts=row.counts,
        tool_calls=row.tool_calls,
        cost_usd=None if row.cost_usd is None else float(row.cost_usd),
        tokens=row.tokens,
        session_id=row.session_id,
        created_at=row.created_at,
    )


def get_watch_run(connection: Connection, run_id: uuid.UUID) -> WatchRun | None:
    row = connection.execute(
        text(f"SELECT {_WATCH_COLUMNS} FROM watch_run WHERE id = :id"),  # noqa: S608
        {"id": run_id},
    ).one_or_none()
    return None if row is None else _watch_run(row)


def list_watch_runs(
    connection: Connection, *, theme: str | None, limit: int, offset: int
) -> tuple[list[WatchRun], int]:
    """The newest first: the latest run date, then the latest written."""
    where = "(CAST(:theme AS text) IS NULL OR theme = :theme)"
    total = connection.execute(
        text(f"SELECT count(*) FROM watch_run WHERE {where}"),  # noqa: S608
        {"theme": theme},
    ).scalar_one()
    rows = connection.execute(
        text(
            f"SELECT {_WATCH_COLUMNS} FROM watch_run WHERE {where}"  # noqa: S608
            " ORDER BY run_date DESC, created_at DESC, id LIMIT :limit OFFSET :offset"
        ),
        {"theme": theme, "limit": limit, "offset": offset},
    )
    return [_watch_run(row) for row in rows], total


class WatchRuns:
    def __init__(self, engine: Engine, actor: Actor, clock: Clock = utc_now) -> None:
        self._engine = engine
        self._actor = actor
        self._clock = clock

    def create(self, request: WatchRunCreate) -> WatchRun:
        run_id = uuid.uuid4()
        with self._engine.begin() as connection:
            at = self._clock().astimezone(UTC)
            session = _check_session(connection, request.session_id, at)
            _same_theme(session, request.theme)
            calls = request.tool_calls
            if calls is None:
                calls = (
                    0
                    if request.session_id is None
                    else connection.execute(
                        text("SELECT count(*) FROM session_tool_call WHERE session_id = :id"),
                        {"id": request.session_id},
                    ).scalar_one()
                )
            connection.execute(
                text(
                    "INSERT INTO watch_run (id, theme, run_date, mode, memo, counts, tool_calls,"
                    " cost_usd, tokens, session_id, created_at) VALUES (:id, :theme, :run_date,"
                    " :mode, :memo, CAST(:counts AS jsonb), :calls, :cost, :tokens, :session, :at)"
                ),
                {
                    "id": run_id,
                    "theme": request.theme,
                    "run_date": request.run_date,
                    "mode": request.mode,
                    "memo": request.memo,
                    "counts": json.dumps(request.counts),
                    "calls": calls,
                    "cost": request.cost_usd,
                    "tokens": request.tokens,
                    "session": request.session_id,
                    "at": at,
                },
            )
            record(
                connection,
                self._actor,
                "watch_run.created",
                entity_type="watch_run",
                entity_id=str(run_id),
                new_hash=content_hash(request.model_dump(mode="json")),
            )
            created = get_watch_run(connection, run_id)
        assert created is not None
        return created
