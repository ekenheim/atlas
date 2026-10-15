"""The `tradingview_calendar` job: a company's reporting dates as Tier C leads (ticket 16b).

Like the other TradingView jobs it runs only with `ATLAS_TRADINGVIEW_ENABLED=true` (off: it
fails at once, calling nothing), is a `tradingview` budget kind (not pausable) and makes at
most `ATLAS_TRADINGVIEW_MAX_CALLS_PER_JOB` tool calls, here one, recorded in
`tradingview_request`.

`{"company": "<slug>"}`: for the company's configured `tradingview_symbol`, the earnings
calendar between `ATLAS_TRADINGVIEW_CALENDAR_PAST_DAYS` before now and
`ATLAS_TRADINGVIEW_CALENDAR_AHEAD_DAYS` after it. Each listed reporting date is a
`tradingview_calendar` lead (`atlas.discovery.leads.store_calendar_event`): one per event, keyed
by TradingView's event ID, else the fiscal year and period, else the day; a rerun that sees
the same date changes nothing and one that sees a moved date or a new status adds an
observation to the same lead. The lead's title says which results are due; its date, status
and period are in the lead's `calendar`, and the owner's override is recorded on it. A lead
says when to look, never what a company said: it is not Evidence, no Claim comes of it.

The calendar tool's name and answer shape are unconfirmed (`atlas.tradingview.client`).
"""

from datetime import datetime, timedelta

from sqlalchemy import Engine

from atlas.audit import Actor
from atlas.discovery.leads import store_calendar_event
from atlas.jobs.queue import Artifacts, Job
from atlas.settings import Settings
from atlas.tradingview.client import CalendarItem, CallBoundReached, TradingViewClient
from atlas.tradingview.model import OWNER_OVERRIDE, calendar_url
from atlas.tradingview.service import (
    CompanyPayload,
    call_recorder,
    mcp_session,
    require_enabled,
    resolve_company,
)


def event_key(item: CalendarItem) -> str:
    """What identifies a reporting date across runs, whatever the date: TradingView's event ID,
    else the fiscal period, else the day itself."""
    if item.id:
        return item.id
    if item.fiscal_year and item.fiscal_period:
        return f"fy{item.fiscal_year}-{item.fiscal_period}"
    return item.event_at.date().isoformat()


def run_calendar(settings: Settings, engine: Engine, job: Job, now: datetime) -> Artifacts:
    require_enabled(settings)
    payload = CompanyPayload.model_validate(job.payload)
    actor = Actor.from_settings(settings)
    company = resolve_company(engine, settings, actor, payload.company)
    items: dict[str, CalendarItem] = {}
    new_leads = 0
    bounded = False
    with mcp_session(settings) as mcp:
        client = TradingViewClient(
            mcp,
            max_calls=settings.tradingview_max_calls_per_job,
            on_call=call_recorder(engine, job.id),
        )
        try:
            for item in client.calendar(
                company.symbol,
                start=now - timedelta(days=settings.tradingview_calendar_past_days),
                end=now + timedelta(days=settings.tradingview_calendar_ahead_days),
            ):
                items[event_key(item)] = item  # a date listed twice: the last is kept
        except CallBoundReached:
            bounded = True
        calls = client.calls
    with engine.begin() as connection:
        for key, item in items.items():
            period = " ".join(
                part
                for part in (
                    item.fiscal_period,
                    f"FY{item.fiscal_year}" if item.fiscal_year else None,
                )
                if part
            )
            title = item.title or f"{company.config.display_name} results {period}".strip()
            created = store_calendar_event(
                connection,
                url=calendar_url(company.symbol, key),
                title=title,
                event_key=key,
                company_id=company.company_id,
                symbol=company.symbol,
                themes=company.themes,
                fiscal_period=item.fiscal_period,
                fiscal_year=item.fiscal_year,
                event_at=item.event_at,
                status=item.status,
                owner_override=OWNER_OVERRIDE,
                job_id=job.id,
                now=now,
            )
            new_leads += bool(created)
    return {
        "company_id": str(company.company_id),
        "symbol": company.symbol,
        "events": {"listed": len(items), "new_leads": new_leads},
        "tool_calls": calls,
        "bounded": bounded,
        "owner_override": OWNER_OVERRIDE,
    }
