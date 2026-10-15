"""The `settle_calls` job: the checkpoints of the prospective record (atlas-beliefs ticket 19;
`docs/decisions.md`, "The prospective record").

A call (`call_record`) falls due at +1, +3 and +6 calendar months from the day it was made. The
daily job appends, for each call and horizon that has fallen due and has no row, one
`call_checkpoint`: what each of the call's companies' close did from the call date to the due
day, what the theme's equal-weighted universe did over the same days, and the difference, so a
call is read against its peers. Nothing is ever rewritten: a checkpoint, once appended, stays
as it was, whatever TradingView later restates.

- **No LLM.** The job's only outside call is TradingView's daily bars, through the existing
  price service (`atlas.tradingview.prices`): one `get_ohlcv` call per company, paced, held to
  the cross-process cap and to `ATLAS_TRADINGVIEW_MAX_CALLS_PER_JOB`, recorded in
  `tradingview_request`, the closes stored in the insert-only `tradingview_price_bar` marked
  with the owner's override. It is a `tradingview` budget kind. Most days nothing is due and
  nothing is called. Closes are used here only to score a call; they are never a Belief's
  evidence.
- **Backfill first.** Each pass first gives the Beliefs proven before this existed their call,
  dated their first `proven` judgement (never today).
- **The arithmetic** (`atlas.calls.model`): the close of a day is that day's or the last one
  before it (at most seven days back); a company with no such close at either end is left out;
  the call's change and the benchmark's are equal-weighted means of the companies' changes,
  rounded to six places; the benchmark's members are the theme's researched companies with a
  TradingView symbol, the call's own companies among them. Each row keeps the closes it used.
- **Deferred, not failed.** A checkpoint waits when a company it needs could not be fetched
  (the job's call bound was reached) or when no company of the call has a close at both ends;
  the next pass tries again and the artifacts list what waited.
- **Unpriced.** A call none of whose companies has a TradingView symbol records `unpriced`
  (`no_symbol`) once; with TradingView off, a call whose checkpoint has fallen due records it
  (`tradingview_disabled`) once and the job succeeds having called nothing. The note is not a
  verdict: a later pass that can price the call (TradingView on, a symbol added to the config)
  still appends its checkpoints, since the closes are history.
"""

import json
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Connection, Engine, text

from atlas.audit import Actor, content_hash, record
from atlas.calls.model import (
    HORIZONS,
    MAX_STALE_DAYS,
    Close,
    Move,
    UnpricedReason,
    due_on,
    move,
    outcome,
)
from atlas.calls.record import backfill_belief_calls
from atlas.companies import extend_universe, load_universe
from atlas.db import create_engine
from atlas.jobs.handlers import HandlerRegistry, Schedule
from atlas.jobs.pacing import Clock, utc_now
from atlas.jobs.queue import Artifacts, Enqueued, Job, JobQueue
from atlas.settings import Settings
from atlas.tradingview.client import CallBoundReached
from atlas.tradingview.model import OWNER_OVERRIDE
from atlas.tradingview.prices import price_history, store_closes
from atlas.tradingview.service import (
    TradingViewNotConfigured,
    mcp_session,
    resolve_company,
    tradingview_client,
)

SETTLE_KIND = "settle_calls"
# Closes are fetched from this many days before the earliest call, so the call date's own
# close (or the last before it) is among them.
LEAD_DAYS = MAX_STALE_DAYS + 3


class SettlePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def settle_key(day: str) -> str:
    return f"{SETTLE_KIND}:{day}"


def enqueue_settle(
    queue: JobQueue, key: str, *, job_class: Literal["interactive", "backfill"] = "backfill"
) -> Enqueued:
    """Ask for a settlement pass (idempotent per key). Backfill class by default."""
    return queue.enqueue(SETTLE_KIND, key, {}, job_class=job_class)


@dataclass
class Member:
    company_id: uuid.UUID
    slug: str
    symbol: str


@dataclass
class Pending:
    id: uuid.UUID
    theme: str
    made_at: datetime
    companies: list[Member]  # those with a symbol
    unsymbolled: int
    horizons: list[tuple[int, date]] = field(default_factory=list[tuple[int, date]])


def pending_calls(connection: Connection, today: date) -> list[Pending]:
    """The calls with a checkpoint fallen due and not yet appended, oldest first."""
    calls = connection.execute(
        text(
            "SELECT c.id, c.theme, c.made_at FROM call_record c"
            " WHERE (SELECT count(*) FROM call_checkpoint k WHERE k.call_id = c.id) < :all"
            " ORDER BY c.made_at, c.id"
        ),
        {"all": len(HORIZONS)},
    ).all()
    done: dict[uuid.UUID, set[int]] = defaultdict(set)
    for row in connection.execute(text("SELECT call_id, horizon_months FROM call_checkpoint")):
        done[row.call_id].add(row.horizon_months)
    members: dict[uuid.UUID, list[Member]] = defaultdict(list)
    unsymbolled: dict[uuid.UUID, int] = defaultdict(int)
    for row in connection.execute(
        text(
            "SELECT cc.call_id, cc.company_id, cc.symbol, c.slug FROM call_company cc"
            " JOIN company c ON c.id = cc.company_id ORDER BY c.slug"
        )
    ):
        if row.symbol:
            members[row.call_id].append(Member(row.company_id, row.slug, row.symbol))
        else:
            unsymbolled[row.call_id] += 1
    pending: list[Pending] = []
    for call in calls:
        due = [
            (months, day)
            for months in HORIZONS
            if months not in done[call.id] and (day := due_on(call.made_at, months)) <= today
        ]
        if due:
            pending.append(
                Pending(
                    call.id, call.theme, call.made_at, members[call.id], unsymbolled[call.id], due
                )
            )
    return pending


def _note_unpriced(
    connection: Connection,
    actor: Actor,
    call_id: uuid.UUID,
    reason: UnpricedReason,
    job_id: uuid.UUID,
    now: datetime,
) -> bool:
    noted = connection.execute(
        text(
            "INSERT INTO call_unpriced (call_id, reason, job_id, recorded_at)"
            " VALUES (:call, :reason, :job, :now) ON CONFLICT DO NOTHING RETURNING call_id"
        ),
        {"call": call_id, "reason": reason, "job": job_id, "now": now},
    ).scalar_one_or_none()
    if noted is None:
        return False
    record(
        connection,
        actor,
        "call.unpriced",
        entity_type="call",
        entity_id=str(call_id),
        new_hash=content_hash({"reason": reason}),
    )
    return True


def _json_moves(moves: list[Move]) -> str:
    return json.dumps(
        [
            {
                "company": each.key,
                "symbol": each.symbol,
                "base_day": each.base_day.isoformat(),
                "base_close": each.base_close,
                "day": each.day.isoformat(),
                "close": each.close,
                "change": round(each.change, 6),
            }
            for each in moves
        ]
    )


def run_settle(settings: Settings, engine: Engine, job: Job, now: datetime) -> Artifacts:
    actor = Actor.from_settings(settings)
    today = now.astimezone(UTC).date()
    with engine.begin() as connection:
        backfilled = backfill_belief_calls(connection, actor, settings.themes_config)
    with engine.connect() as connection:
        pending = pending_calls(connection, today)
        owed = _price_predictions_due(connection, today) if settings.tradingview_enabled else []
    artifacts: Artifacts = {
        "backfilled_calls": len(backfilled),
        "calls_due": len(pending),
        "checkpoints_due": sum(len(each.horizons) for each in pending),
        "owner_override": OWNER_OVERRIDE,
    }
    if not pending and not owed:
        return artifacts

    # Calls that cannot be priced: noted once, and (with TradingView off) not tried.
    unpriced = 0
    priceable: list[Pending] = []
    with engine.begin() as connection:
        for each in pending:
            reason: UnpricedReason | None = None
            if not each.companies:
                reason = "no_symbol"
            elif not settings.tradingview_enabled:
                reason = "tradingview_disabled"
            if reason is None:
                priceable.append(each)
            elif _note_unpriced(connection, actor, each.id, reason, job.id, now):
                unpriced += 1
    artifacts["unpriced_noted"] = unpriced
    if not priceable and not owed:
        artifacts["tool_calls"] = 0
        return artifacts

    benchmark = _benchmarks(settings, engine, actor, {each.theme for each in priceable})
    wanted: dict[uuid.UUID, Member] = {}
    for each in priceable:  # the calls' own companies first, then the benchmarks'
        for member in each.companies:
            wanted.setdefault(member.company_id, member)
    for members in benchmark.values():
        for member in members:
            wanted.setdefault(member.company_id, member)
    # Companies a price prediction whose deadline has passed is settled by: their closes are
    # stored too, so that settling it reads a stored close (it never calls TradingView).
    firsts = [each.made_at.astimezone(UTC).date() for each in priceable]
    for deadline, slug in owed:
        firsts.append(deadline)
        try:
            company = resolve_company(engine, settings, actor, slug)
        except TradingViewNotConfigured:
            continue
        wanted.setdefault(company.company_id, Member(company.company_id, slug, company.symbol))
    start = min(firsts) - timedelta(days=LEAD_DAYS)
    fetched: set[uuid.UUID] = set()
    bounded = False
    with mcp_session(settings) as mcp:
        client = tradingview_client(mcp, settings, engine, job.id)
        try:
            for member in wanted.values():
                bars = client.daily_bars(member.symbol, start=start, end=today, today=today)
                closes = {bar.at.date(): bar.close for bar in bars}
                store_closes(engine, member.company_id, member.symbol, closes, job.id, now)
                fetched.add(member.company_id)
        except CallBoundReached:
            bounded = True
        calls = client.calls

    appended = 0
    deferred: list[dict[str, str | int]] = []
    with engine.begin() as connection:
        history = {
            company_id: [
                Close(each.day, each.close)
                for each in price_history(
                    connection, company_id=company_id, start=start, end=today
                ).closes
            ]
            for company_id in fetched
        }
        for each in priceable:
            needed = {m.company_id for m in each.companies} | {
                m.company_id for m in benchmark.get(each.theme, [])
            }
            made_on = each.made_at.astimezone(UTC).date()
            for months, due in each.horizons:
                label: dict[str, str | int] = {"call_id": str(each.id), "horizon_months": months}
                if not needed <= fetched:
                    deferred.append(label | {"reason": "prices_not_fetched"})
                    continue
                moves = _moves(each.companies, history, made_on, due)
                bench = _moves(benchmark.get(each.theme, []), history, made_on, due)
                result = outcome(moves, bench)
                if result is None:
                    deferred.append(label | {"reason": "no_closes"})
                    continue
                inserted = connection.execute(
                    text(
                        "INSERT INTO call_checkpoint (id, call_id, horizon_months, due_on, change,"
                        " benchmark_change, relative_change, benchmark_members, companies,"
                        " benchmark, owner_override, job_id, settled_at) VALUES (:id, :call,"
                        " :months, :due, :change, :bench, :relative, :members,"
                        " CAST(:companies AS jsonb), CAST(:benchmark AS jsonb), :override, :job,"
                        " :now) ON CONFLICT DO NOTHING RETURNING id"
                    ),
                    {
                        "id": uuid.uuid4(),
                        "call": each.id,
                        "months": months,
                        "due": due,
                        "change": result.change,
                        "bench": result.benchmark_change,
                        "relative": result.relative_change,
                        "members": len(result.benchmark),
                        "companies": _json_moves(result.companies),
                        "benchmark": _json_moves(result.benchmark),
                        "override": OWNER_OVERRIDE,
                        "job": job.id,
                        "now": now,
                    },
                ).scalar_one_or_none()
                if inserted is None:
                    continue
                appended += 1
                record(
                    connection,
                    actor,
                    "call.checkpoint_appended",
                    entity_type="call",
                    entity_id=str(each.id),
                    new_hash=content_hash(
                        {
                            "horizon_months": months,
                            "due_on": due,
                            "change": result.change,
                            "benchmark_change": result.benchmark_change,
                            "relative_change": result.relative_change,
                        }
                    ),
                )
    artifacts.update(
        {
            "checkpoints_appended": appended,
            "deferred": [dict(each) for each in deferred],  # pyright: ignore[reportAssignmentType]
            "companies_fetched": len(fetched),
            "tool_calls": calls,
            "bounded": bounded,
        }
    )
    return artifacts


def _price_predictions_due(connection: Connection, today: date) -> list[tuple[date, str]]:
    """The deadline and company slug of each unsettled price prediction whose deadline has come."""
    return [
        (row.deadline, row.slug)
        for row in connection.execute(
            text(
                "SELECT p.deadline, c.slug FROM prediction p JOIN company c ON c.id = p.company_id"
                " WHERE p.source_kind = 'price' AND p.deadline <= :today AND NOT EXISTS"
                " (SELECT FROM prediction_settlement s WHERE s.prediction_id = p.id)"
                " ORDER BY p.deadline"
            ),
            {"today": today},
        )
    ]


def _moves(
    members: list[Member], history: dict[uuid.UUID, list[Close]], made_on: date, due: date
) -> list[Move]:
    found: list[Move] = []
    for member in members:
        one = move(member.slug, member.symbol, history.get(member.company_id, []), made_on, due)
        if one is not None:
            found.append(one)
    return found


def _benchmarks(
    settings: Settings, engine: Engine, actor: Actor, themes: set[str]
) -> dict[str, list[Member]]:
    """Each theme's benchmark members: its researched companies that have a TradingView symbol
    (the universe as configured, with the committed Candidates)."""
    with engine.connect() as connection:
        universe = extend_universe(connection, load_universe(settings.themes_config))
    members: dict[str, list[Member]] = {}
    for theme in sorted(themes):
        config = universe.themes.get(theme)
        found: list[Member] = []
        for slug in config.companies if config else ():
            if universe.companies[slug].tradingview_symbol is None:
                continue
            company = resolve_company(engine, settings, actor, slug)
            found.append(Member(company.company_id, slug, company.symbol))
        members[theme] = found
    return members


def register_settle_handlers(
    registry: HandlerRegistry, settings: Settings, clock: Clock = utc_now
) -> None:
    def settle(job: Job) -> Artifacts:
        SettlePayload.model_validate(job.payload)
        engine = create_engine(settings)
        try:
            return run_settle(settings, engine, job, clock())
        finally:
            engine.dispose()

    # Not pausable (it calls no LLM and no Hindsight) and, unlike the other TradingView kinds,
    # not failed at once while TradingView is off: it records the calls unpriced instead.
    registry.register(SETTLE_KIND, settle)


class SettleSchedule:
    """Enqueues the day's settlement from `at` (UTC), once a day, backfill class."""

    def __init__(self, engine: Engine, at: tuple[int, int]) -> None:
        self._engine = engine
        self._at = at
        self._done: str | None = None

    def __call__(self, now: datetime) -> list[Enqueued]:
        moment = now.astimezone(UTC)
        day = moment.date().isoformat()
        if self._done == day or (moment.hour, moment.minute) < self._at:
            return []
        enqueued = enqueue_settle(JobQueue(self._engine), settle_key(day))
        self._done = day
        return [enqueued]


def settle_schedules(settings: Settings, engine: Engine) -> list[Schedule]:
    """The daily settlement (none with an empty `ATLAS_SETTLE_CALLS_AT`)."""
    if not settings.settle_calls_at:
        return []
    hour, minute = (int(part) for part in settings.settle_calls_at.split(":"))
    return [SettleSchedule(engine, (hour, minute))]
