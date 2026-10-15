"""Daily closes from TradingView, for settling predictions and replays (ticket 16b).

**Not a source of anything an agent reads.** Price history is for scoring a prediction the
programme made (ticket 19) and for the early-signal replays, never for a Belief, never Evidence,
and no tool of the Atlas MCP server returns it. It is reached through one route,
`GET /api/v1/companies/{id}/price-history`, which is a pure read of what the job below stored:
no TradingView call is ever made while serving a request.

**`tradingview_prices`** (`{"company": "<slug>", "start"?: "YYYY-MM-DD", "end"?: "YYYY-MM-DD"}`;
by default the `ATLAS_TRADINGVIEW_PRICE_DAYS` days before now): one `get_ohlcv` call (daily
bars) for the company's configured `tradingview_symbol`, a `tradingview` budget kind (not
pausable) that fails at once while `ATLAS_TRADINGVIEW_ENABLED` is off. The tool has no date
range: it returns the last `count` bars counted back from now, so the job asks for the
weekdays from `start` to today (at most 5,000, the tool's ceiling; `count_asked` and
`count_capped` in the artifacts) and keeps the bars inside the window. Each bar's close is
stored in `tradingview_price_bar` by company, day and fetch time (the day is the bar's UTC
date), marked with the owner's override. The table is insert-only: a rerun that gets the close
already held for a day adds nothing, one that gets a different close (an adjusted refresh) adds
a row, and the earlier value stays. A read takes each day's latest fetch, or, with `known_by`,
the latest fetched by then, so a settlement can be reproduced as it was made. Only the close is
kept.

The call's arguments are TradingView's documented ones and the bars its documented
`{t, o, h, l, c, v}`; an answer that doesn't fit fails the job with the first 4,000 characters
in its artifacts (`unparsed_answer`; `atlas.tradingview.client`).
"""

import uuid
from datetime import date, datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, Engine, text

from atlas.audit import Actor
from atlas.jobs.queue import Artifacts, Job
from atlas.settings import Settings
from atlas.tradingview.client import MAX_BARS, CallBoundReached, trading_days_back
from atlas.tradingview.model import OWNER_OVERRIDE
from atlas.tradingview.service import (
    mcp_session,
    require_enabled,
    resolve_company,
    tradingview_client,
)

PRICE_NOTE = (
    "Daily closes for settling predictions and replays. Never Evidence and never support for a"
    " Belief."
)


class PricesPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    company: str = Field(min_length=1)  # a company slug in the universe
    start: date | None = None
    end: date | None = None


class PriceClose(BaseModel):
    day: date
    close: float
    owner_override: str


class PriceHistory(BaseModel):
    company_id: uuid.UUID
    symbol: str | None  # None: nothing stored for the company
    start: date
    end: date
    closes: list[PriceClose]  # oldest first
    note: str = PRICE_NOTE


def run_prices(settings: Settings, engine: Engine, job: Job, now: datetime) -> Artifacts:
    require_enabled(settings)
    payload = PricesPayload.model_validate(job.payload)
    actor = Actor.from_settings(settings)
    company = resolve_company(engine, settings, actor, payload.company)
    end = payload.end or now.date()
    start = payload.start or end - timedelta(days=settings.tradingview_price_days)
    if start > end:
        raise ValueError(f"start {start} is after end {end}")
    wanted = trading_days_back(start, now.date())
    closes: dict[date, float] = {}
    bounded = False
    with mcp_session(settings) as mcp:
        client = tradingview_client(mcp, settings, engine, job.id)
        try:
            for bar in client.daily_bars(company.symbol, start=start, end=end, today=now.date()):
                closes[bar.at.date()] = bar.close  # a day listed twice: the last is kept
        except CallBoundReached:
            bounded = True
        calls = client.calls
    with engine.begin() as connection:
        for day, close in closes.items():
            connection.execute(
                text(
                    "INSERT INTO tradingview_price_bar (company_id, symbol, day, close,"
                    " owner_override, job_id, fetched_at) SELECT CAST(:company AS uuid),"
                    " CAST(:symbol AS text), CAST(:day AS date), CAST(:close AS numeric),"
                    " CAST(:override AS text), CAST(:job AS uuid), CAST(:now AS timestamptz)"
                    " WHERE CAST(:close AS numeric) IS DISTINCT FROM ("
                    "SELECT close FROM tradingview_price_bar WHERE company_id = :company"
                    " AND day = :day ORDER BY fetched_at DESC LIMIT 1) ON CONFLICT DO NOTHING"
                ),
                {
                    "company": company.company_id,
                    "symbol": company.symbol,
                    "day": day,
                    "close": close,
                    "override": OWNER_OVERRIDE,
                    "job": job.id,
                    "now": now,
                },
            )
    return {
        "company_id": str(company.company_id),
        "symbol": company.symbol,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "closes": len(closes),
        "count_asked": min(wanted, MAX_BARS),
        "count_capped": wanted > MAX_BARS,
        "tool_calls": calls,
        "bounded": bounded,
        "owner_override": OWNER_OVERRIDE,
    }


def price_history(
    connection: Connection,
    *,
    company_id: uuid.UUID,
    start: date,
    end: date,
    known_by: datetime | None = None,
) -> PriceHistory:
    """The stored daily closes of the company from `start` to `end` inclusive, oldest first:
    each day's latest fetch, or the latest fetched by `known_by` if given."""
    rows = connection.execute(
        text(
            "SELECT DISTINCT ON (day) day, close, symbol, owner_override"
            " FROM tradingview_price_bar WHERE company_id = :company"
            " AND day BETWEEN :start AND :end"
            " AND (CAST(:known_by AS timestamptz) IS NULL OR fetched_at <= :known_by)"
            " ORDER BY day, fetched_at DESC"
        ),
        {"company": company_id, "start": start, "end": end, "known_by": known_by},
    ).all()
    return PriceHistory(
        company_id=company_id,
        symbol=rows[-1].symbol if rows else None,
        start=start,
        end=end,
        closes=[
            PriceClose(day=row.day, close=float(row.close), owner_override=row.owner_override)
            for row in rows
        ],
    )
