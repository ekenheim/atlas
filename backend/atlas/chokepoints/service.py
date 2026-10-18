"""Reading the board and writing to it: every rule of an event lives here, so the routes and the
MCP tools share it."""

import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from pydantic import BaseModel, JsonValue, ValidationError
from sqlalchemy import Connection, Engine, text

from atlas.audit import Actor, content_hash, record
from atlas.chokepoints.model import (
    PAYLOADS,
    PROSPECTIVE_WINDOW,
    THESIS_STEPS,
    Chokepoint,
    ChokepointCreate,
    ChokepointDetail,
    ChokepointError,
    ChokepointEvent,
    CreatedPayload,
    EventCreate,
    EventKind,
    FieldSetPayload,
    StatusSetPayload,
    StepEvidence,
    StepSetPayload,
    WatchRun,
    WatchRunCreate,
    fold,
)
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


def get_chokepoint(
    connection: Connection, chokepoint_id: uuid.UUID, now: datetime
) -> ChokepointDetail | None:
    found = _load(connection, "id = :id", {"id": chokepoint_id}, now)
    return found[0] if found else None


def summary(detail: ChokepointDetail) -> Chokepoint:
    return Chokepoint.model_validate(detail.model_dump(exclude={"history"}))


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
        found = [
            each
            for each in found
            if (
                each.stale
                if status == "stale"
                else each.needs_review
                if status == "needs_review"
                else each.status == status
            )
        ]
    found.sort(key=lambda each: (each.last_event_at, str(each.id)), reverse=True)
    return [summary(each) for each in found[offset : offset + limit]], len(found)


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


def check_read_session(engine: Engine, session_id: uuid.UUID | None, now: datetime) -> None:
    """Refuse a read that names a session the board is closed to."""
    with engine.connect() as connection:
        _check_session(connection, session_id, now)


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
    # The same rule as the MCP tools': a Fact of a Source Version public after the session's
    # as-of time (its effective availability) is not visible to it.
    for row in found:
        if row.available_at > session.as_of:
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
    found = connection.execute(
        text("SELECT id, first_seen_at FROM lead WHERE id = ANY(:ids) ORDER BY id"),
        {"ids": list(set(ids))},
    ).all()
    _unknown("lead", "lead", ids, {row.id for row in found})
    for row in found:
        if session is not None and row.first_seen_at > session.as_of:
            raise ChokepointError(
                422,
                "created_after_as_of",
                "that lead was first seen after the session's as-of time",
                lead=str(row.id),
            )


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
