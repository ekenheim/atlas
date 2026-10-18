"""Reading the board and writing to it: every rule of an event lives here, so the routes and the
MCP tools share it."""

import json
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, JsonValue, ValidationError
from sqlalchemy import Connection, Engine, text

from atlas.audit import Actor, content_hash, record
from atlas.chokepoints.model import (
    PAYLOADS,
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
    return [fold(dict(head), by_id[head["id"]], now) for head in heads]


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
    """The latest event first. `status` is the stored status, or `stale` (the derived flag)."""
    found = _load(
        connection, "(CAST(:theme AS text) IS NULL OR theme = :theme)", {"theme": theme}, now
    )
    if status is not None:
        found = [
            each for each in found if (each.stale if status == "stale" else each.status == status)
        ]
    found.sort(key=lambda each: (each.last_event_at, str(each.id)), reverse=True)
    return [summary(each) for each in found[offset : offset + limit]], len(found)


# --- checks --------------------------------------------------------------------------------


def _check_session(connection: Connection, session_id: uuid.UUID | None) -> datetime | None:
    """The session's as-of time; the session must exist and must not be isolated (an isolated
    session, the early-call scorecard's, leaves nothing for others to find)."""
    if session_id is None:
        return None
    row = connection.execute(
        text("SELECT as_of, isolated FROM research_session WHERE id = :id"), {"id": session_id}
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
    return row.as_of


def _check_run(connection: Connection, run_id: uuid.UUID | None) -> None:
    if (
        run_id is not None
        and connection.execute(text("SELECT 1 FROM run WHERE id = :id"), {"id": run_id}).first()
        is None
    ):
        raise ChokepointError(422, "unknown_run", "no such run")


_KEYS = {"fact": "assertion_id", "lead": "id", "issue": "id"}


def _missing(connection: Connection, table: str, ids: Sequence[uuid.UUID]) -> list[str]:
    """The IDs that name no row of `table` (a Fact is its assertion's ID)."""
    wanted = set(ids)
    if not wanted:
        return []
    column = _KEYS[table]
    held = set(
        connection.execute(
            text(f"SELECT {column} FROM {table} WHERE {column} = ANY(:ids)"),  # noqa: S608
            {"ids": list(wanted)},
        ).scalars()
    )
    return sorted(str(each) for each in wanted - held)


def _check_evidence(connection: Connection, evidence: StepEvidence, as_of: datetime | None) -> None:
    for table, ids, what in (
        ("fact", evidence.fact_ids, "Fact"),
        ("lead", evidence.lead_ids, "lead"),
        ("issue", evidence.issue_ids, "Issue"),
    ):
        if missing := _missing(connection, table, ids):
            raise ChokepointError(
                422, f"unknown_{table}", f"no such {what}: {', '.join(missing)}", ids=missing
            )
    if as_of is None or not evidence.fact_ids:
        return
    # The same rule as the MCP tools': a Fact of a Source Version public after the session's
    # as-of time (its effective availability) is not visible to it.
    later = connection.execute(
        text(
            "SELECT f.assertion_id, a.available_at FROM fact f"
            " JOIN assertion s ON s.id = f.assertion_id"
            " JOIN source_version_availability a ON a.source_version_id = s.source_version_id"
            " WHERE f.assertion_id = ANY(:ids) AND a.available_at > :as_of"
            " ORDER BY a.available_at, f.assertion_id"
        ),
        {"ids": list(set(evidence.fact_ids)), "as_of": as_of},
    ).first()
    if later is not None:
        raise ChokepointError(
            422,
            "fact_available_after_as_of",
            "that Fact's document became public after the session's as-of time",
            fact=str(later.assertion_id),
            available_at=later.available_at.isoformat(),
            as_of=as_of.isoformat(),
        )


def _check_step(connection: Connection, step: StepSetPayload, as_of: datetime | None) -> None:
    evidence = step.evidence
    if step.status in ("primary", "contradicted") and not evidence.fact_ids:
        raise ChokepointError(
            422,
            "step_needs_fact",
            f"a step set to {step.status} cites at least one Fact (evidence.fact_ids)",
        )
    if step.status == "lead" and not (evidence.lead_ids or evidence.issue_ids):
        raise ChokepointError(
            422,
            "step_needs_lead",
            "a step set to lead cites a lead or an Issue (evidence.lead_ids or issue_ids)",
        )
    _check_evidence(connection, evidence, as_of)


def _check_thesis_ready(connection: Connection, state: ChokepointDetail) -> None:
    """Thesis-ready is the hand-off to a Researcher session: steps a, b and d are primary,
    a kill criterion is written and an Issue linked to it is open."""
    missing = [
        f"step_{each.step}_primary"
        for each in state.steps
        if each.step in THESIS_STEPS and each.status != "primary"
    ]
    if not state.kill_criteria:
        missing.append("kill_criteria")
    open_issues = (
        connection.execute(
            text("SELECT count(*) FROM issue WHERE id = ANY(:ids) AND status = 'active'"),
            {"ids": state.issue_ids},
        ).scalar_one()
        if state.issue_ids
        else 0
    )
    if not open_issues:
        missing.append("open_issue")
    if missing:
        raise ChokepointError(
            422,
            "thesis_not_ready",
            "thesis_ready needs steps a, b and d primary, a kill criterion and an open linked"
            f" Issue; missing: {', '.join(missing)}",
            missing=missing,
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

    def create(self, request: ChokepointCreate) -> ChokepointDetail:
        at = self._clock().astimezone(UTC)
        chokepoint_id = uuid.uuid4()
        actor = Actor(request.actor) if request.actor else self._actor
        with self._engine.begin() as connection:
            _check_session(connection, request.session_id)
            _check_run(connection, request.run_id)
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
        actor = Actor(request.actor) if request.actor else self._actor
        with self._engine.begin() as connection:
            locked = connection.execute(
                text("SELECT 1 FROM chokepoint WHERE id = :id FOR UPDATE"), {"id": chokepoint_id}
            ).first()
            if locked is None:
                return None
            as_of = _check_session(connection, request.session_id)
            _check_run(connection, request.run_id)
            before = get_chokepoint(connection, chokepoint_id, at)
            assert before is not None
            payload = self._validated(connection, before, request, as_of)
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
        as_of: datetime | None,
    ) -> dict[str, Any]:
        """The event's payload as it is stored, once the kind's rules hold."""
        parsed = _parse(PAYLOADS[request.kind], request.payload, request.kind)
        if isinstance(parsed, FieldSetPayload):
            if parsed.issue_ids is not None and (
                missing := _missing(connection, "issue", parsed.issue_ids)
            ):
                raise ChokepointError(
                    422, "unknown_issue", f"no such Issue: {', '.join(missing)}", ids=missing
                )
            return parsed.model_dump(mode="json", exclude_unset=True)
        if isinstance(parsed, StepSetPayload):
            _check_step(connection, parsed, as_of)
        elif isinstance(parsed, StatusSetPayload):
            if parsed.status == "killed" and not (request.reason and request.reason.strip()):
                raise ChokepointError(422, "reason_required", "a killed chokepoint needs a reason")
            if parsed.status == "thesis_ready":
                _check_thesis_ready(connection, before)
        return parsed.model_dump(mode="json")


# --- the Watch's run record ----------------------------------------------------------------

_WATCH_COLUMNS = "id, theme, run_date, mode, memo, counts, tool_calls, session_id, created_at"


def _watch_run(row: Any) -> WatchRun:
    return WatchRun(
        id=row.id,
        theme=row.theme,
        run_date=row.run_date,
        mode=row.mode,
        memo=row.memo,
        counts=row.counts,
        tool_calls=row.tool_calls,
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
            _check_session(connection, request.session_id)
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
                    " session_id, created_at) VALUES (:id, :theme, :run_date, :mode, :memo,"
                    " CAST(:counts AS jsonb), :calls, :session, :at)"
                ),
                {
                    "id": run_id,
                    "theme": request.theme,
                    "run_date": request.run_date,
                    "mode": request.mode,
                    "memo": request.memo,
                    "counts": json.dumps(request.counts),
                    "calls": calls,
                    "session": request.session_id,
                    "at": self._clock().astimezone(UTC),
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
