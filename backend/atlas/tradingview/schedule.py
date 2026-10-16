"""The `tradingview_calendar` job: companies' reporting dates as Tier C leads (ticket 16b).

Like the other TradingView jobs it runs only with `ATLAS_TRADINGVIEW_ENABLED=true` (off: it
fails at once, calling nothing), is a `tradingview` budget kind (not pausable) and makes at
most `ATLAS_TRADINGVIEW_MAX_CALLS_PER_JOB` tool calls, each recorded in `tradingview_request`.

`{"company": "<slug>"}` or `{"companies": ["<slug>", ...]}`: for each company's configured
`tradingview_symbol`, the earnings calendar between `ATLAS_TRADINGVIEW_CALENDAR_PAST_DAYS`
before now and `ATLAS_TRADINGVIEW_CALENDAR_AHEAD_DAYS` after it, as `get_earnings_calendar`
documents its arguments (`symbols[]`, `date_from`, `date_to`; ticket 16c). One call carries
up to `ATLAS_TRADINGVIEW_CALENDAR_BATCH` (20) companies' symbols, each row of the answer going
to the company whose symbol it names; a symbol the answer leaves out (no data) is no error.

The answer's shape was confirmed from the first live call (2026-10-16, ticket 16d): per symbol
one row `{symbol, fiscal_period_end, release_date, release_next_date, next_date_confirmed,
...}` holding two events (`atlas.tradingview.client.CalendarItem`): the next report (date
`release_next_date`, `confirmed` or `scheduled`, for the quarter ending `fiscal_period_end`)
and the most recent one (date `release_date`, `reported`, for the quarter ending the month end
three months before `fiscal_period_end`: derived, recorded as `period_basis`
`derived_from_next`). Atlas keeps the symbol, the two dates, the confirmed flag and the period
end, and nothing else of a row: not its price, name, description or flags, and never a
consensus or estimate (the client's model has no field for them).

Each event is a `tradingview_calendar` lead (`atlas.discovery.leads.store_calendar_event`),
identified by the symbol and the period's end day (`NASDAQ:LITE:2026-09-30`): a rerun that
sees the same date and status changes nothing, a moved date or a new status adds an observation
to the same lead, and a scheduled report that happens is named by the next answer as the recent
one with the same period end, so it gains a `reported` observation instead of a second lead.
The lead's title says which results are due; its date, status and period are in the lead's
`calendar`, and the owner's override is recorded on it. A lead says when to look, never what a
company said: it is not Evidence, no Claim comes of it.

An answer that doesn't fit fails the job with its first 4,000 characters in the artifacts
(`unparsed_answer`; `atlas.tradingview.client`); an event with no usable date is skipped, not
the row or the job (`skipped_events` in the artifacts).
"""

from datetime import datetime, timedelta
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator
from sqlalchemy import Connection, Engine

from atlas.audit import Actor
from atlas.discovery.leads import store_calendar_event
from atlas.jobs.queue import Artifacts, Job
from atlas.settings import Settings
from atlas.tradingview.client import CalendarItem, CallBoundReached
from atlas.tradingview.model import OWNER_OVERRIDE, calendar_url
from atlas.tradingview.service import (
    SymbolCompany,
    mcp_session,
    require_enabled,
    resolve_company,
    tradingview_client,
)


class CalendarPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    company: str | None = Field(default=None, min_length=1)  # a company slug in the universe
    companies: list[str] | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _one_way(self) -> Self:
        if (self.company is None) == (self.companies is None):
            raise ValueError('name the companies one way: "company" or "companies"')
        return self

    @property
    def slugs(self) -> list[str]:
        named = self.companies if self.companies is not None else [self.company or ""]
        return list(dict.fromkeys(named))


def event_key(item: CalendarItem) -> str:
    """What identifies a reporting date across runs, whatever the date or the status: the symbol
    and the day its quarter ends."""
    return f"{item.symbol}:{item.period_end.isoformat()}"


def run_calendar(settings: Settings, engine: Engine, job: Job, now: datetime) -> Artifacts:
    require_enabled(settings)
    payload = CalendarPayload.model_validate(job.payload)
    actor = Actor.from_settings(settings)
    companies = [resolve_company(engine, settings, actor, slug) for slug in payload.slugs]
    items: dict[str, dict[str, CalendarItem]] = {c.slug: {} for c in companies}
    unattributed = 0
    asked: set[str] = set()
    bounded = False
    size = settings.tradingview_calendar_batch
    with mcp_session(settings) as mcp:
        client = tradingview_client(mcp, settings, engine, job.id)
        try:
            for first in range(0, len(companies), size):
                group = companies[first : first + size]
                by_symbol = {c.symbol: c for c in group}
                answer = client.calendar(
                    list(by_symbol),
                    start=now - timedelta(days=settings.tradingview_calendar_past_days),
                    end=now + timedelta(days=settings.tradingview_calendar_ahead_days),
                )
                asked.update(c.slug for c in group)
                for item in answer:
                    owner = by_symbol.get(item.symbol)
                    if owner is None:
                        unattributed += 1
                        continue
                    items[owner.slug][event_key(item)] = item  # a date listed twice: last kept
        except CallBoundReached:
            bounded = True
        calls = client.calls
        skipped = client.calendar_events_skipped
    summaries: list[dict[str, JsonValue]] = []
    listed = created = 0
    with engine.begin() as connection:
        for company in companies:
            new_leads = sum(
                _store(connection, company, key, item, job, now)
                for key, item in items[company.slug].items()
            )
            listed += len(items[company.slug])
            created += new_leads
            summaries.append(
                {
                    "slug": company.slug,
                    "company_id": str(company.company_id),
                    "symbol": company.symbol,
                    "listed": len(items[company.slug]),
                    "new_leads": new_leads,
                }
            )
    artifacts: Artifacts = {
        "events": {
            "listed": listed,
            "new_leads": created,
        },
        "companies": list[JsonValue](summaries),
        "unattributed": unattributed,
        "skipped_events": skipped,
        "not_asked": [c.slug for c in companies if c.slug not in asked],
        "tool_calls": calls,
        "bounded": bounded,
        "owner_override": OWNER_OVERRIDE,
    }
    if len(companies) == 1:
        artifacts["company_id"] = str(companies[0].company_id)
        artifacts["symbol"] = companies[0].symbol
    return artifacts


def _store(
    connection: Connection,
    company: SymbolCompany,
    key: str,
    item: CalendarItem,
    job: Job,
    now: datetime,
) -> int:
    title = (
        f"{company.config.display_name} results,"
        f" quarter ending {item.period_end.day} {item.period_end:%b %Y}"
    )
    created = store_calendar_event(
        connection,
        url=calendar_url(company.symbol, item.period_end),
        title=title,
        event_key=key,
        company_id=company.company_id,
        symbol=company.symbol,
        themes=company.themes,
        period_end=item.period_end,
        period_basis=item.period_basis,
        event_at=item.event_at,
        status=item.status,
        owner_override=OWNER_OVERRIDE,
        job_id=job.id,
        now=now,
    )
    return int(bool(created))
