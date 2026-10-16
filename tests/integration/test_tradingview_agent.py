"""TradingView for the agents, under the owner's override (atlas-beliefs ticket 16b): the earnings
calendar as Tier C leads, the Atlas MCP tool that projects them, and daily closes for settling
predictions and replays.

Seams: single worker passes run the jobs (enqueued through the queue, with an application clock
the test sets), and everything is observed through `/api/v1` and `/mcp` and the requests the
TradingView fake received. TradingView is the transport-level fake of its MCP server
(`tests/fakes/tradingview.py`) over synthetic fixtures in the confirmed calendar shape (ticket
16d) and the assumed `get_ohlcv` shape; nothing live is called.
"""

import json
import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from atlas.db import create_engine
from atlas.discovery.leads import store_headline
from atlas.jobs import JobQueue, Pacing, Worker, builtin_registry
from atlas.sources import TokenBucket
from atlas.tradingview import service
from atlas.tradingview.service import mcp_session, tradingview_client
from tests.fakes.serve import Served, serve
from tests.fakes.tradingview import ACCESS_TOKEN, FakeTradingView
from tests.harness import Atlas, Clock

OVERRIDE = (
    "TradingView terms (display-only) overridden by the owner for private non-commercial use"
    " (2026-09-30)"
)
NOW = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
CALENDAR_URL = "https://mcp.tradingview.com/calendar/NASDAQ%3ALITE/{key}"
# A calendar lead is keyed by its symbol and the day its quarter ends: the most recent report's
# quarter (derived), the next report's, and the quarter after it.
RECENT, NEXT, LATER = (f"NASDAQ:LITE:{day}" for day in ("2026-06-30", "2026-09-30", "2026-12-31"))


@pytest.fixture
def tradingview() -> Iterator[tuple[FakeTradingView, Served]]:
    fake = FakeTradingView()
    with serve(fake.handle) as served:
        yield fake, served
        served.raise_errors()


def enabled(served: Served, tmp_path: Path, **overrides: Any) -> dict[str, Any]:
    """TradingView on, reached with the access-token setting (the cluster proxy's way), so no
    token file is written."""
    return {
        "tradingview_enabled": True,
        "tradingview_mcp_url": f"{served.url}/mcp",
        "tradingview_access_token": ACCESS_TOKEN,
        "tradingview_token_file": tmp_path / "no-token-file.json",
        "tradingview_rate_per_s": 1.0,
    } | overrides


class Agent:
    """A migrated database with TradingView on, the jobs run at a clock the test sets, and
    the API and the MCP server over them."""

    def __init__(self, atlas: Atlas) -> None:
        self.atlas = atlas
        self.clock = Clock(NOW)
        self.requests = 0

    def run(self, kind: str, key: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Enqueue the job, run one worker pass at the clock's time and return the job."""
        settings = self.atlas.settings()
        queue = JobQueue(self.atlas.engine, pacing=Pacing.from_settings(settings))
        job = queue.enqueue(kind, key, payload or {"company": "lumentum"}).job
        Worker(queue, builtin_registry(settings, clock=self.clock)).run_once()
        return self.atlas.get(f"/api/v1/jobs/{job.id}")

    def leads(self, **params: Any) -> list[dict[str, Any]]:
        return self.atlas.get("/api/v1/leads", origin="tradingview_calendar", **params)["items"]

    # --- the Atlas MCP server ---

    def rpc(self, method: str, params: dict[str, Any] | None = None) -> Any:
        self.requests += 1
        return self.atlas.api.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": self.requests, "method": method, "params": params or {}},
        )

    def call(self, tool: str, **arguments: Any) -> tuple[bool, dict[str, Any]]:
        response = self.rpc("tools/call", {"name": tool, "arguments": arguments})
        assert response.status_code == 200, response.text
        result = response.json()["result"]
        return result["isError"], json.loads(result["content"][0]["text"])

    def ok(self, tool: str, **arguments: Any) -> dict[str, Any]:
        is_error, value = self.call(tool, **arguments)
        assert not is_error, value
        return value

    def session(self, as_of: str) -> str:
        opened = self.ok("open_session", question="Who reports when?", as_of=as_of)
        return opened["session_id"]

    def tool_calls(self, session: str) -> list[tuple[str, str]]:
        with self.atlas.engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT tool, outcome FROM session_tool_call WHERE session_id = :id"
                    " ORDER BY created_at, id"
                ),
                {"id": session},
            ).all()
        return [(row.tool, row.outcome) for row in rows]


@pytest.fixture
def agent(
    database_url: str, tmp_path: Path, tradingview: tuple[FakeTradingView, Served]
) -> Iterator[Agent]:
    atlas = Atlas(database_url, tmp_path, "http://127.0.0.1:9", **enabled(tradingview[1], tmp_path))
    yield Agent(atlas)
    atlas.engine.dispose()


def events(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """The calendar leads by the event key they are deduplicated by."""
    return {item["calendar"]["event_key"]: item for item in items}


# --- the calendar job ---------------------------------------------------------------------------


def test_off_by_default_neither_job_calls_tradingview(
    database_url: str, tmp_path: Path, tradingview: tuple[FakeTradingView, Served]
) -> None:
    atlas = Atlas(database_url, tmp_path, "http://127.0.0.1:9")
    off = Agent(atlas)

    calendar = off.run("tradingview_calendar", "off")
    prices = off.run("tradingview_prices", "off")

    for job in (calendar, prices):
        assert job["status"] != "succeeded"
        assert "ATLAS_TRADINGVIEW_ENABLED=false" in job["failures"][0]["error"]
    assert tradingview[0].calls == []
    assert off.leads() == []
    atlas.engine.dispose()


def test_the_calendar_becomes_tier_c_leads_marked_with_the_override(
    agent: Agent, tradingview: tuple[FakeTradingView, Served]
) -> None:
    job = agent.run("tradingview_calendar", "lite")

    assert job["status"] == "succeeded", job["failures"]
    artifacts = job["artifacts"]
    assert artifacts["events"] == {"listed": 2, "new_leads": 2}  # the recent report and the next
    assert (artifacts["tool_calls"], artifacts["bounded"], artifacts["skipped_events"]) == (
        1,
        False,
        0,
    )
    assert artifacts["owner_override"] == OVERRIDE
    assert tradingview[0].tool_calls == [
        (
            "mcp-tv-get-earnings-calendar",
            {
                "symbols": ["NASDAQ:LITE"],
                "date_from": "2026-04-17",  # 120 days before the clock
                "date_to": "2027-02-11",  # 180 days after it
            },
        )
    ]

    leads = agent.leads(theme="photonics")
    assert len(leads) == 2
    next_report = events(leads)[NEXT]
    lumentum = agent.atlas.company("lumentum")["id"]
    assert {
        k: next_report[k] for k in ("tier", "origin", "snippet", "query", "theme", "engines")
    } == {
        "tier": "C",
        "origin": "tradingview_calendar",
        "snippet": "",
        "query": None,
        "theme": "photonics",
        "engines": ["tradingview"],
    }
    assert next_report["url"] == CALENDAR_URL.format(key="NASDAQ%3ALITE%3A2026-09-30")
    assert next_report["title"] == "Lumentum results, quarter ending 30 Sep 2026"
    assert next_report["calendar"] == {
        "company_id": lumentum,
        "symbol": "NASDAQ:LITE",
        "event_key": NEXT,
        "event_at": "2026-11-05T00:00:00Z",
        "status": "scheduled",  # next_date_confirmed is false
        "period_end": "2026-09-30",
        "period_basis": "stated",
        "observed_at": "2026-08-15T12:00:00Z",
        "owner_override": OVERRIDE,
    }
    # The most recent report: its quarter is the month end three months before the next one's,
    # recorded as derived.
    recent = events(leads)[RECENT]
    assert recent["title"] == "Lumentum results, quarter ending 30 Jun 2026"
    assert {
        k: recent["calendar"][k] for k in ("event_at", "status", "period_end", "period_basis")
    } == {
        "event_at": "2026-08-11T00:00:00Z",
        "status": "reported",
        "period_end": "2026-06-30",
        "period_basis": "derived_from_next",
    }
    assert agent.leads(theme="other-theme") == []

    # A calendar date is a lead like the others: the plain list shows a news headline beside
    # it (and by theme), and only the calendar's has a `calendar`.
    with agent.atlas.engine.begin() as connection:
        store_headline(
            connection,
            url="https://www.tradingview.com/news/example/",
            title="A headline",
            published_at=NOW,
            headline_id="h-1",
            company_id=uuid.UUID(lumentum),
            symbol="NASDAQ:LITE",
            themes=["photonics"],
            publisher=None,
            publisher_url=None,
            related_symbols=[],
            urgency=None,
            owner_override=OVERRIDE,
            job_id=None,
        )
    everything = agent.atlas.get("/api/v1/leads", theme="photonics")
    assert everything["total"] == 3
    assert {lead["origin"]: lead["calendar"] is None for lead in everything["items"]} == {
        "tradingview_calendar": False,
        "tradingview_news": True,
    }
    news = agent.atlas.get("/api/v1/leads", origin="tradingview_news")["items"]
    assert [lead["headline"]["headline_id"] for lead in news] == ["h-1"]
    assert agent.atlas.get("/api/v1/leads", theme="other-theme")["total"] == 0


def test_a_rerun_dedupes_and_a_moved_date_is_a_new_observation_of_the_same_lead(
    agent: Agent, tradingview: tuple[FakeTradingView, Served]
) -> None:
    agent.run("tradingview_calendar", "first")
    again = agent.run("tradingview_calendar", "second")
    assert again["artifacts"]["events"] == {"listed": 2, "new_leads": 0}
    assert len(agent.leads()) == 2
    assert _observations(agent) == 2  # the same dates change nothing

    tradingview[0].calendar = "-moved"
    agent.clock.advance(days=7)
    moved = agent.run("tradingview_calendar", "third")

    assert moved["artifacts"]["events"] == {"listed": 2, "new_leads": 0}
    assert len(agent.leads()) == 2  # the same leads, not new ones
    assert _observations(agent) == 3  # the recent report is as it was; the next one moved
    now = events(agent.leads())[NEXT]["calendar"]
    assert (now["event_at"], now["status"], now["observed_at"]) == (
        "2026-11-12T00:00:00Z",
        "confirmed",
        "2026-08-22T12:00:00Z",
    )
    # As Atlas knew it a day after the first run, the date had not moved.
    then = events(agent.leads(known_by="2026-08-16T00:00:00Z"))[NEXT]["calendar"]
    assert (then["event_at"], then["status"]) == ("2026-11-05T00:00:00Z", "scheduled")


def test_a_report_that_happens_stays_one_lead_with_a_reported_observation(
    agent: Agent, tradingview: tuple[FakeTradingView, Served]
) -> None:
    agent.run("tradingview_calendar", "first")  # 15 Aug: the next report is 5 Nov, scheduled
    tradingview[0].calendar = "-moved"
    agent.clock.advance(days=7)
    agent.run("tradingview_calendar", "moved")  # 22 Aug: moved to 12 Nov, confirmed
    assert len(agent.leads()) == 2

    # 6 Nov: the report happened (on 5 Nov, as the answer's `release_date` now says) and the
    # next quarter's is listed. The quarter that was the next one is now the recent one.
    tradingview[0].calendar = "-reported"
    agent.clock.advance(days=76)
    after = agent.run("tradingview_calendar", "reported")

    assert after["status"] == "succeeded", after["failures"]
    assert after["artifacts"]["events"] == {"listed": 2, "new_leads": 1}  # only the new quarter
    leads = agent.leads()
    assert sorted(each["calendar"]["event_key"] for each in leads) == [RECENT, NEXT, LATER]
    assert [e for e in events(leads) if e.endswith("2026-09-30")] == [NEXT]  # no second lead
    reported = events(leads)[NEXT]["calendar"]
    assert {k: reported[k] for k in ("event_at", "status", "period_end", "period_basis")} == {
        "event_at": "2026-11-05T00:00:00Z",
        "status": "reported",
        "period_end": "2026-09-30",
        "period_basis": "derived_from_next",
    }
    assert reported["observed_at"] == "2026-11-06T12:00:00Z"
    assert events(leads)[LATER]["calendar"]["status"] == "scheduled"
    assert events(leads)[RECENT]["calendar"]["status"] == "reported"  # no longer listed: kept
    assert _observations(agent) == 5  # 2 + the move + the report + the new quarter
    # Insert-only history: the same lead, as Atlas knew it on 23 Aug, was confirmed for 12 Nov.
    was = events(agent.leads(known_by="2026-08-23T00:00:00Z"))[NEXT]["calendar"]
    assert (was["event_at"], was["status"], was["period_basis"]) == (
        "2026-11-12T00:00:00Z",
        "confirmed",
        "stated",
    )


def test_two_companies_on_one_fiscal_calendar_keep_a_lead_each(
    agent: Agent, tradingview: tuple[FakeTradingView, Served]
) -> None:
    tradingview[0].calendar = "-both"  # both answer a report for the quarter ending 30 Sep 2026
    lumentum = agent.run("tradingview_calendar", "lite", {"company": "lumentum"})
    innolight = agent.run("tradingview_calendar", "innolight", {"company": "innolight"})

    assert (lumentum["status"], innolight["status"]) == ("succeeded", "succeeded"), (
        lumentum["failures"],
        innolight["failures"],
    )
    leads = agent.leads()
    assert len(leads) == 4
    assert {each["calendar"]["event_key"] for each in leads} == {
        RECENT,
        NEXT,
        "HKEX:3308:2026-06-30",
        "HKEX:3308:2026-09-30",
    }
    next_reports = [each for each in leads if each["calendar"]["period_end"] == "2026-09-30"]
    by_company = {each["calendar"]["company_id"]: each for each in next_reports}
    assert set(by_company) == {
        agent.atlas.company("lumentum")["id"],
        agent.atlas.company("innolight")["id"],
    }
    assert {each["calendar"]["symbol"] for each in next_reports} == {"NASDAQ:LITE", "HKEX:3308"}
    assert _observations(agent) == 4
    # A rerun finds both again and adds nothing.
    agent.run("tradingview_calendar", "lite-again", {"company": "lumentum"})
    assert len(agent.leads()) == 4
    assert _observations(agent) == 4


def test_the_calendar_and_price_tables_are_insert_only(agent: Agent) -> None:
    agent.run("tradingview_calendar", "lite")
    agent.run(
        "tradingview_prices",
        "july",
        {"company": "lumentum", "start": "2026-07-01", "end": "2026-07-31"},
    )
    updates = {
        "tradingview_calendar_event": "UPDATE tradingview_calendar_event SET fiscal_period = 'x'",
        "tradingview_calendar_observation": (
            "UPDATE tradingview_calendar_observation SET status = 'x'"
        ),
        "tradingview_price_bar": "UPDATE tradingview_price_bar SET close = 1",
    }
    for table, update in updates.items():
        # (the event table's foreign key makes Postgres truncate it only with its observations)
        truncate = "TRUNCATE " + ", ".join(
            dict.fromkeys([table, "tradingview_calendar_observation"])
        )
        for sql in (update, f"DELETE FROM {table}", truncate):
            with (
                pytest.raises(DBAPIError, match="insert-only"),
                agent.atlas.engine.begin() as connection,
            ):
                connection.execute(text(sql))


def _observations(agent: Agent) -> int:
    with agent.atlas.engine.connect() as connection:
        return connection.execute(
            text("SELECT count(*) FROM tradingview_calendar_observation")
        ).scalar_one()


def test_the_leads_filter_by_origin_known_by_and_event_window(agent: Agent) -> None:
    agent.run("tradingview_calendar", "lite")

    assert len(agent.leads(known_by="2026-08-15T12:00:00Z")) == 2
    assert agent.leads(known_by="2026-08-15T11:59:59Z") == []
    window = agent.leads(event_from="2026-08-01T00:00:00Z", event_to="2026-12-31T00:00:00Z")
    assert [item["calendar"]["event_key"] for item in window] == [RECENT, NEXT]  # soonest first
    only_recent = agent.leads(event_from="2026-08-01T00:00:00Z", event_to="2026-09-01T00:00:00Z")
    assert [item["calendar"]["event_key"] for item in only_recent] == [RECENT]
    assert agent.atlas.get("/api/v1/leads", origin="searxng")["items"] == []


def test_the_calendar_job_counts_in_the_tradingview_budget(
    database_url: str, tmp_path: Path, tradingview: tuple[FakeTradingView, Served]
) -> None:
    atlas = Atlas(
        database_url,
        tmp_path,
        "http://127.0.0.1:9",
        **enabled(tradingview[1], tmp_path, tradingview_budget_requests=1),
    )
    spent = Agent(atlas)

    first = spent.run("tradingview_calendar", "one")
    second = spent.run("tradingview_calendar", "two")

    assert first["status"] == "succeeded"
    assert second["status"] == "queued"  # the window's one request is spent: held
    queue = atlas.get("/api/v1/queue")
    (budget,) = [b for b in queue["budgets"] if b["provider"] == "tradingview"]
    assert (budget["unit"], budget["used"], budget["budget"]) == ("requests", 1, 1)
    assert "tradingview_calendar" in budget["kinds"]
    assert len(tradingview[0].tool_calls) == 1
    atlas.engine.dispose()


def test_the_calendar_job_is_bounded_per_job(
    agent: Agent, tradingview: tuple[FakeTradingView, Served]
) -> None:
    agent.atlas.overrides |= {"tradingview_max_calls_per_job": 1}
    job = agent.run("tradingview_calendar", "bounded")
    assert job["artifacts"]["tool_calls"] == 1
    with agent.atlas.engine.connect() as connection:
        recorded = connection.execute(text("SELECT tool, outcome FROM tradingview_request")).all()
    assert [(r.tool, r.outcome) for r in recorded] == [("mcp-tv-get-earnings-calendar", "ok")]


# --- the Atlas MCP tool -------------------------------------------------------------------------


def test_upcoming_reports_lists_the_theme_s_dates_around_the_session_s_as_of_time(
    agent: Agent,
) -> None:
    agent.run("tradingview_calendar", "lite")
    session = agent.session("2026-08-15T12:00:00Z")

    near = agent.ok("upcoming_reports", session_id=session)  # 30 days either side
    wide = agent.ok("upcoming_reports", session_id=session, window_days=100)
    assert [r["period_end"] for r in near["reports"]] == ["2026-06-30"]  # the recent report
    assert [(r["period_end"], r["period_basis"], r["status"]) for r in wide["reports"]] == [
        ("2026-06-30", "derived_from_next", "reported"),
        ("2026-09-30", "stated", "scheduled"),  # 5 Nov is 81 days on
    ]
    report = wide["reports"][1]
    assert {k: report[k] for k in ("company", "symbol", "event_at", "status", "tier")} == {
        "company": "lumentum",
        "symbol": "NASDAQ:LITE",
        "event_at": "2026-11-05T00:00:00Z",
        "status": "scheduled",
        "tier": "C",
    }
    assert report["title"] == "Lumentum results, quarter ending 30 Sep 2026"
    assert report["days_from_as_of"] == 81.5
    assert wide["reports"][0]["days_from_as_of"] == -4.5  # reported the Tuesday before
    assert (wide["theme"], wide["as_of"], wide["window_days"]) == (
        "photonics",
        "2026-08-15T12:00:00Z",
        100,
    )
    assert "never what it says" in wide["note"] and "Not Evidence" in wide["note"]
    assert agent.ok("upcoming_reports", session_id=session, theme="other-theme")["reports"] == []
    assert agent.tool_calls(session) == [
        ("open_session", "ok"),
        ("upcoming_reports", "ok"),
        ("upcoming_reports", "ok"),
        ("upcoming_reports", "ok"),
    ]


def test_upcoming_reports_never_shows_what_atlas_stored_after_the_as_of_time(
    agent: Agent, tradingview: tuple[FakeTradingView, Served]
) -> None:
    agent.run("tradingview_calendar", "first")  # stored at 15 Aug 12:00
    tradingview[0].calendar = "-moved"
    agent.clock.advance(days=7)
    agent.run("tradingview_calendar", "second")  # the next date moves, stored at 22 Aug 12:00
    before_storing = agent.session("2026-08-10T00:00:00Z")
    after_the_first = agent.session("2026-08-16T00:00:00Z")
    after_the_move = agent.session("2026-08-23T00:00:00Z")

    # 11 Aug is inside this window, but Atlas had stored nothing yet.
    empty = agent.ok("upcoming_reports", session_id=before_storing, window_days=100)
    assert empty["reports"] == []

    early = agent.ok("upcoming_reports", session_id=after_the_first, window_days=100)
    assert [(r["period_end"], r["event_at"], r["status"]) for r in early["reports"]] == [
        ("2026-06-30", "2026-08-11T00:00:00Z", "reported"),
        ("2026-09-30", "2026-11-05T00:00:00Z", "scheduled"),  # the date as Atlas knew it then
    ]
    late = agent.ok("upcoming_reports", session_id=after_the_move, window_days=100)
    assert [(r["period_end"], r["event_at"], r["status"]) for r in late["reports"]] == [
        ("2026-06-30", "2026-08-11T00:00:00Z", "reported"),
        ("2026-09-30", "2026-11-12T00:00:00Z", "confirmed"),
    ]
    assert late["reports"][1]["known_since"] == "2026-08-22T12:00:00Z"


def test_the_tool_is_typed_takes_no_as_of_and_price_history_is_not_a_tool(agent: Agent) -> None:
    listed = agent.rpc("tools/list").json()["result"]["tools"]
    (tool,) = [each for each in listed if each["name"] == "upcoming_reports"]
    schema = tool["inputSchema"]
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == {"session_id", "theme", "window_days"}
    assert schema["required"] == ["session_id"]
    assert not [each["name"] for each in listed if "price" in each["name"]]
    session = agent.session("2026-08-15T12:00:00Z")

    is_error, refused = agent.call("upcoming_reports", session_id=session, as_of="2030-01-01")
    assert is_error and refused["refused"] == "invalid_arguments"
    is_error, refused = agent.call("upcoming_reports", session_id=session, window_days=0)
    assert is_error and refused["refused"] == "invalid_arguments"
    is_error, refused = agent.call("upcoming_reports", session_id=str(uuid.uuid4()))
    assert is_error and refused["refused"] == "unknown_session"
    assert agent.tool_calls(session) == [
        ("open_session", "ok"),
        ("upcoming_reports", "refused"),
        ("upcoming_reports", "refused"),
    ]


# --- price history ------------------------------------------------------------------------------


def test_daily_closes_are_stored_by_a_job_and_read_by_a_route_that_calls_nothing(
    agent: Agent, tradingview: tuple[FakeTradingView, Served]
) -> None:
    payload = {"company": "lumentum", "start": "2026-07-01", "end": "2026-07-31"}
    job = agent.run("tradingview_prices", "july", payload)

    assert job["status"] == "succeeded", job["failures"]
    assert (job["artifacts"]["closes"], job["artifacts"]["tool_calls"]) == (3, 1)
    assert tradingview[0].tool_calls == [
        (
            "mcp-tv-get-ohlcv",
            {
                "symbol": "NASDAQ:LITE",
                "interval": "1D",
                # The count runs back from the clock (Sat 15 Aug), not from `end`: the 33
                # weekdays from Wed 1 Jul to it, so the window's first day is surely reached.
                "count": 33,
            },
        )
    ]
    lumentum = agent.atlas.company("lumentum")["id"]

    history = agent.atlas.get(
        f"/api/v1/companies/{lumentum}/price-history", start="2026-07-01", end="2026-07-31"
    )

    assert history["symbol"] == "NASDAQ:LITE"
    assert history["closes"] == [
        {"day": "2026-07-01", "close": 103.25, "owner_override": OVERRIDE},
        {"day": "2026-07-02", "close": 105.5, "owner_override": OVERRIDE},
        {"day": "2026-07-06", "close": 102.0, "owner_override": OVERRIDE},
    ]
    assert "Never Evidence" in history["note"]
    narrower = agent.atlas.get(
        f"/api/v1/companies/{lumentum}/price-history", start="2026-07-02", end="2026-07-05"
    )
    assert [c["day"] for c in narrower["closes"]] == ["2026-07-02"]
    assert len(tradingview[0].tool_calls) == 1  # reading calls TradingView never

    # A rerun with the same closes adds nothing.
    agent.run("tradingview_prices", "july-again", payload)
    again = agent.atlas.get(
        f"/api/v1/companies/{lumentum}/price-history", start="2026-07-01", end="2026-07-31"
    )
    assert again["closes"] == history["closes"]
    assert _price_rows(agent) == 3

    # An adjusted refresh is a new row; the earlier close stays and a read `known_by` before
    # the refresh still gives it.
    tradingview[0].prices = "-adjusted"
    agent.clock.advance(days=7)
    agent.run("tradingview_prices", "july-adjusted", payload)
    path = f"/api/v1/companies/{lumentum}/price-history"
    latest = agent.atlas.get(path, start="2026-07-01", end="2026-07-31")
    assert [(c["day"], c["close"]) for c in latest["closes"]] == [
        ("2026-07-01", 102.25),
        ("2026-07-02", 105.5),
        ("2026-07-06", 102.0),
    ]
    assert _price_rows(agent) == 4
    then = agent.atlas.get(
        path, start="2026-07-01", end="2026-07-31", known_by="2026-08-16T00:00:00Z"
    )
    assert then["closes"] == history["closes"]
    # No tool of the Atlas MCP server returns prices.
    listed = agent.rpc("tools/list").json()["result"]["tools"]
    assert all("price" not in each["name"] for each in listed)


def _price_rows(agent: Agent) -> int:
    with agent.atlas.engine.connect() as connection:
        return connection.execute(text("SELECT count(*) FROM tradingview_price_bar")).scalar_one()


def test_the_price_route_with_nothing_stored_and_bad_requests(agent: Agent) -> None:
    payload = {"company": "lumentum", "start": "2026-07-01", "end": "2026-07-31"}
    assert agent.run("tradingview_prices", "july", payload)["status"] == "succeeded"
    path = f"/api/v1/companies/{agent.atlas.company('lumentum')['id']}/price-history"

    empty = agent.atlas.get(path, start="2026-01-01", end="2026-01-31")
    assert (empty["symbol"], empty["closes"]) == (None, [])
    backwards = agent.atlas.api.get(path, params={"start": "2026-08-01", "end": "2026-07-01"})
    assert backwards.status_code == 422
    assert backwards.json()["error"]["code"] == "invalid_range"
    unknown = agent.atlas.api.get(f"/api/v1/companies/{uuid.uuid4()}/price-history")
    assert unknown.status_code == 404


# --- the calls as TradingView documents them (ticket 16c) ---------------------------------------

CALENDAR_TOOL = "mcp-tv-get-earnings-calendar"
OHLCV_TOOL = "mcp-tv-get-ohlcv"
WINDOW = {"date_from": "2026-04-17", "date_to": "2027-02-11"}  # 120 days back, 180 ahead of NOW


def test_the_calendar_batches_the_companies_into_calls_of_several_symbols(
    agent: Agent, tradingview: tuple[FakeTradingView, Served]
) -> None:
    tradingview[0].calendar = "-both"  # a report each for Lumentum and Innolight, both quarters
    both = {"companies": ["lumentum", "innolight"]}

    first = agent.run("tradingview_calendar", "both", both)

    assert first["status"] == "succeeded", first["failures"]
    assert tradingview[0].tool_calls == [
        (CALENDAR_TOOL, {"symbols": ["NASDAQ:LITE", "HKEX:3308"]} | WINDOW)
    ]
    artifacts = first["artifacts"]
    assert (artifacts["tool_calls"], artifacts["events"]) == (1, {"listed": 4, "new_leads": 4})
    assert [(c["slug"], c["symbol"], c["listed"]) for c in artifacts["companies"]] == [
        ("lumentum", "NASDAQ:LITE", 2),
        ("innolight", "HKEX:3308", 2),
    ]
    leads = agent.leads()
    assert {each["calendar"]["symbol"] for each in leads} == {"NASDAQ:LITE", "HKEX:3308"}
    assert {
        (each["calendar"]["symbol"], each["calendar"]["event_at"])
        for each in leads
        if each["calendar"]["period_basis"] == "stated"
    } == {
        ("NASDAQ:LITE", "2026-11-05T00:00:00Z"),
        ("HKEX:3308", "2026-11-07T00:00:00Z"),
    }

    # A batch size of one makes a call a company; the dates are the same, so nothing is new.
    agent.atlas.overrides |= {"tradingview_calendar_batch": 1}
    again = agent.run("tradingview_calendar", "one-each", both)

    assert again["artifacts"]["events"] == {"listed": 4, "new_leads": 0}
    assert again["artifacts"]["tool_calls"] == 2
    assert tradingview[0].tool_calls[1:] == [
        (CALENDAR_TOOL, {"symbols": ["NASDAQ:LITE"]} | WINDOW),
        (CALENDAR_TOOL, {"symbols": ["HKEX:3308"]} | WINDOW),
    ]
    assert len(agent.leads()) == 4


def test_a_symbol_the_answer_leaves_out_is_no_failure(
    agent: Agent, tradingview: tuple[FakeTradingView, Served]
) -> None:
    # Innolight's default answer has no row (as for IQE, Soitec and Innolight on 2026-10-16).
    job = agent.run("tradingview_calendar", "absent", {"companies": ["lumentum", "innolight"]})

    assert job["status"] == "succeeded", job["failures"]
    assert job["artifacts"]["events"] == {"listed": 2, "new_leads": 2}
    assert [(c["slug"], c["listed"]) for c in job["artifacts"]["companies"]] == [
        ("lumentum", 2),
        ("innolight", 0),
    ]
    assert job["artifacts"]["unattributed"] == 0
    assert {each["calendar"]["symbol"] for each in agent.leads()} == {"NASDAQ:LITE"}
    alone = agent.run("tradingview_calendar", "alone", {"company": "innolight"})
    assert alone["status"] == "succeeded", alone["failures"]  # an empty answer is not a failure
    assert alone["artifacts"]["events"] == {"listed": 0, "new_leads": 0}


def test_a_calendar_job_names_its_companies_one_way(
    agent: Agent, tradingview: tuple[FakeTradingView, Served]
) -> None:
    cases: list[tuple[str, dict[str, Any]]] = [
        ("both-ways", {"company": "lumentum", "companies": ["innolight"]}),
        ("neither", {"theme": "photonics"}),
        ("empty", {"companies": []}),
    ]
    for key, payload in cases:
        job = agent.run("tradingview_calendar", key, payload)
        assert job["status"] != "succeeded", key
    assert tradingview[0].calls == []


def test_the_price_and_consensus_in_the_calendar_answer_are_stored_nowhere(
    agent: Agent, tradingview: tuple[FakeTradingView, Served]
) -> None:
    tradingview[0].calendar = "-noisy"  # a distinctive close, a name and made-up estimates
    job = agent.run("tradingview_calendar", "lite")

    assert job["status"] == "succeeded", job["failures"]
    assert job["artifacts"]["events"] == {"listed": 2, "new_leads": 2}
    stored = [json.dumps(job["artifacts"]), json.dumps(agent.leads(), default=str)]
    with agent.atlas.engine.connect() as connection:
        for table in ("lead", "tradingview_calendar_event", "tradingview_calendar_observation"):
            stored += connection.execute(text(f"SELECT t::text FROM {table} t")).scalars().all()
    assert len(stored) > 6  # two events in each of three tables, and the two JSONs
    everything = "\n".join(stored).lower()
    forbidden = (
        "close",
        "987.65",
        "eps_estimate",
        "revenue_estimate",
        "eps_surprise",
        "4.321",
        "7654321000",
        "release_next_time_flag",
        "publication_type_next_fq",
        "release_next_at",
        "description",
        "synthetic",  # the answer's name and description: nothing of a row but dates is kept
    )
    for name in forbidden:
        assert name not in everything, name
    # What is kept, to show the check looks at the rows it should.
    assert "2026-11-05" in everything and "derived_from_next" in everything


def test_a_calendar_answer_that_does_not_fit_is_kept_for_the_lead_and_nothing_is_stored(
    agent: Agent, tradingview: tuple[FakeTradingView, Served]
) -> None:
    tradingview[0].raw[CALENDAR_TOOL] = json.dumps(
        {
            "success": True,
            "data": {
                "count": 1,
                "rows": [
                    {
                        "symbol": "NASDAQ:LITE",
                        "release_date": "2026-08-11",
                        "close": 111.11,
                        "eps_estimate_next_fq": 4.321,
                    }
                ],
            },
        }
    )

    job = agent.run("tradingview_calendar", "odd")

    # Failed, not retried (the shape would not change), and the answer is in the artifacts as
    # a skeleton: values only under identifying keys, the estimate key taken out.
    assert job["status"] == "failed"
    assert job["attempts"] == 1
    assert job["artifacts"] == {
        "status": "unexpected_answer",
        "tool": CALENDAR_TOOL,
        "unparsed_answer": (
            '{"success": "<bool>", "data": {"count": "<int>", "rows": [{"symbol": "NASDAQ:LITE",'
            ' "release_date": "2026-08-11", "close": "<float>"}]}}'
        ),
    }
    assert "unexpected answer" in job["failures"][0]["error"]
    assert agent.leads() == []
    assert len(tradingview[0].tool_calls) == 1


def test_an_answer_without_data_earnings_fails_with_unparsed_answer_never_an_empty_calendar(
    agent: Agent, tradingview: tuple[FakeTradingView, Served]
) -> None:
    answers: dict[str, dict[str, Any]] = {
        "old-guess": {"items": [{"symbol": "NASDAQ:LITE", "date": 1793912400}], "total": 1},
        "no-earnings": {"success": True, "data": {"count": 0, "from": "a", "to": "b"}},
        "no-data": {"success": True, "earnings": []},
        "no-symbol": {"data": {"earnings": [{"release_next_date": "2026-11-05"}]}},
    }
    for key, answer in answers.items():
        tradingview[0].raw[CALENDAR_TOOL] = json.dumps(answer)

        job = agent.run("tradingview_calendar", key)

        assert job["status"] == "failed", key
        assert job["attempts"] == 1, key
        assert job["artifacts"]["status"] == "unexpected_answer", key
        assert job["artifacts"]["unparsed_answer"], key
    assert agent.leads() == []


def test_an_event_with_no_usable_date_is_skipped_not_the_row_or_the_job(
    agent: Agent, tradingview: tuple[FakeTradingView, Served]
) -> None:
    def row(symbol: str, **fields: Any) -> dict[str, Any]:
        return {"symbol": symbol, "fiscal_period_end": "2026-09-30"} | fields

    tradingview[0].raw[CALENDAR_TOOL] = json.dumps(
        {
            "success": True,
            "data": {
                "earnings": [
                    # the recent date is unusable, the next one is fine: one event, no failure
                    row("NASDAQ:LITE", release_date="soon", release_next_date="2026-11-05"),
                    # no period end: neither event has a period to be identified by
                    {
                        "symbol": "HKEX:3308",
                        "release_date": "2026-08-25",
                        "release_next_date": "2026-11-07",
                    },
                ]
            },
        }
    )

    job = agent.run("tradingview_calendar", "partial", {"companies": ["lumentum", "innolight"]})

    assert job["status"] == "succeeded", job["failures"]
    assert job["artifacts"]["skipped_events"] == 3
    assert job["artifacts"]["events"] == {"listed": 1, "new_leads": 1}
    (lead,) = agent.leads()
    assert lead["calendar"]["event_key"] == NEXT
    assert lead["calendar"]["event_at"] == "2026-11-05T00:00:00Z"


def test_the_recent_report_s_quarter_is_the_month_end_three_months_before_the_next_one(
    agent: Agent, tradingview: tuple[FakeTradingView, Served]
) -> None:
    cases = {  # fiscal_period_end of the next report -> the derived period end of the recent one
        "2026-10-31": "2026-07-31",  # MRVL's and CIEN's own fiscal quarters
        "2026-05-31": "2026-02-28",  # a shorter month
        "2028-05-31": "2028-02-29",  # a leap year
        "2027-02-28": "2026-11-30",  # across the year end
        "2026-12-31": "2026-09-30",
    }
    for end, derived in cases.items():
        tradingview[0].raw[CALENDAR_TOOL] = json.dumps(
            {
                "data": {
                    "earnings": [
                        {
                            "symbol": "NASDAQ:LITE",
                            "fiscal_period_end": end,
                            "release_date": "2026-08-11",
                            "release_next_date": "2026-11-05",
                        }
                    ]
                }
            }
        )
        agent.run("tradingview_calendar", f"quarter-{end}")
        found = {
            each["calendar"]["period_end"]: each["calendar"]["period_basis"]
            for each in agent.leads()
        }
        assert found[end] == "stated", end
        assert found[derived] == "derived_from_next", end


def test_an_answer_that_is_not_json_is_kept_too(
    agent: Agent, tradingview: tuple[FakeTradingView, Served]
) -> None:
    tradingview[0].raw[CALENDAR_TOOL] = "No earnings data for this symbol."

    job = agent.run("tradingview_calendar", "prose")

    assert job["status"] == "failed"
    assert job["artifacts"] == {
        "status": "unexpected_answer",
        "tool": CALENDAR_TOOL,
        "unparsed_answer": "No earnings data for this symbol.",
    }


def test_a_calendar_answer_under_another_wrapper_key_fails_and_is_not_an_empty_calendar(
    agent: Agent, tradingview: tuple[FakeTradingView, Served]
) -> None:
    tradingview[0].raw[CALENDAR_TOOL] = json.dumps(
        {
            "rows": [{"symbol": "NASDAQ:LITE", "earnings_release_next_date": 1793912400}],
            "totalCount": 1,
        }
    )

    job = agent.run("tradingview_calendar", "rows")

    assert job["status"] == "failed"
    assert job["attempts"] == 1
    assert job["artifacts"]["status"] == "unexpected_answer"
    assert job["artifacts"]["tool"] == CALENDAR_TOOL
    # The shape is kept for the lead (the wrapper key, the field names, the symbol), no date.
    assert '"rows"' in job["artifacts"]["unparsed_answer"]
    assert "NASDAQ:LITE" in job["artifacts"]["unparsed_answer"]
    assert agent.leads() == []


def test_a_calendar_that_names_none_of_the_symbols_asked_fails_instead_of_listing_nothing(
    agent: Agent, tradingview: tuple[FakeTradingView, Served]
) -> None:
    tradingview[0].raw[CALENDAR_TOOL] = json.dumps(
        {
            "data": {
                "earnings": [
                    {
                        "symbol": "LITE",
                        "fiscal_period_end": "2026-09-30",
                        "release_date": "2026-08-11",
                    }
                ]
            }
        }
    )

    job = agent.run("tradingview_calendar", "other-form")

    assert job["status"] == "failed"
    assert "no row names a symbol asked for" in job["failures"][0]["error"]
    assert job["artifacts"]["unparsed_answer"] == (
        '{"data": {"earnings": [{"symbol": "LITE", "fiscal_period_end": "2026-09-30",'
        ' "release_date": "2026-08-11"}]}}'
    )
    assert agent.leads() == []


def test_consensus_in_a_failed_calendar_answer_is_kept_in_neither_columns_nor_prose(
    agent: Agent, tradingview: tuple[FakeTradingView, Served]
) -> None:
    tradingview[0].raw[CALENDAR_TOOL] = json.dumps(
        {
            "fields": ["symbol", "eps_forecast", "next_report"],
            "rows": [["NASDAQ:LITE", 1.2345, 1793912400]],
            "steps": 3,
            "notes": "consensus 9.8765",
        }
    )
    columns = agent.run("tradingview_calendar", "columns")
    tradingview[0].raw[CALENDAR_TOOL] = (
        "Lumentum EPS estimate 7.7777\nNext report 2026-11-05\nRevenue forecast 8.8888 bn"
    )
    prose = agent.run("tradingview_calendar", "prose")

    for job in (columns, prose):
        assert job["status"] == "failed"
    kept = columns["artifacts"]["unparsed_answer"]
    for consensus in ("1.2345", "eps_forecast", "9.8765", "1793912400"):
        assert consensus not in kept
    assert '"fields": ["symbol", "next_report"]' in kept  # the layout can still be fitted
    assert '"steps": "<int>"' in kept  # `eps` inside a word is not consensus
    assert prose["artifacts"]["unparsed_answer"] == "Next report 2026-11-05"


def test_a_price_answer_under_another_wrapper_or_in_columns_fails_and_stores_nothing(
    agent: Agent, tradingview: tuple[FakeTradingView, Served]
) -> None:
    answers: dict[str, dict[str, Any]] = {
        "data": {"summary": {"count": 3}, "data": [{"t": 1782864000, "c": 105.5}]},
        "columns": {"t": [1782864000, 1782950400], "c": [105.5, 106.0]},
    }
    for key, answer in answers.items():
        tradingview[0].raw[OHLCV_TOOL] = json.dumps(answer)

        job = agent.run("tradingview_prices", key, {"company": "lumentum"})

        assert job["status"] == "failed", key
        assert job["attempts"] == 1
        assert job["artifacts"]["status"] == "unexpected_answer"
        assert job["artifacts"]["tool"] == OHLCV_TOOL
        assert _price_rows(agent) == 0


def test_the_price_job_asks_for_the_count_to_its_start_and_keeps_the_window(
    agent: Agent, tradingview: tuple[FakeTradingView, Served]
) -> None:
    # The fixture answers with five bars (30 Jun, 1, 2 and 6 Jul, 3 Aug), as a count-bounded
    # answer would not be cut to the window.
    job = agent.run(
        "tradingview_prices",
        "narrow",
        {"company": "lumentum", "start": "2026-07-02", "end": "2026-07-05"},
    )

    assert job["status"] == "succeeded", job["failures"]
    assert job["artifacts"]["closes"] == 1
    assert tradingview[0].tool_calls == [
        (
            OHLCV_TOOL,
            {"symbol": "NASDAQ:LITE", "interval": "1D", "count": 32},
        )  # Thu 2 Jul..Sat 15 Aug
    ]
    history = agent.atlas.get(
        f"/api/v1/companies/{agent.atlas.company('lumentum')['id']}/price-history",
        start="2026-06-01",
        end="2026-08-31",
    )
    assert [(c["day"], c["close"]) for c in history["closes"]] == [("2026-07-02", 105.5)]


def test_the_price_count_is_capped_at_what_the_tool_allows(
    agent: Agent, tradingview: tuple[FakeTradingView, Served]
) -> None:
    job = agent.run(
        "tradingview_prices",
        "old",
        {"company": "lumentum", "start": "2000-01-03", "end": "2000-12-29"},
    )

    assert job["status"] == "succeeded", job["failures"]
    assert tradingview[0].tool_calls == [
        (OHLCV_TOOL, {"symbol": "NASDAQ:LITE", "interval": "1D", "count": 5000})
    ]
    assert job["artifacts"]["closes"] == 0
    assert job["artifacts"]["count_capped"] is True


def test_a_price_answer_that_does_not_fit_is_kept_cut_to_4000_characters(
    agent: Agent, tradingview: tuple[FakeTradingView, Served]
) -> None:
    tradingview[0].raw[OHLCV_TOOL] = json.dumps(
        {"bars": [{"t": "yesterday", "c": 1}], "padding": "x" * 5000}
    )

    job = agent.run("tradingview_prices", "odd", {"company": "lumentum"})

    assert job["status"] == "failed"
    kept = job["artifacts"]["unparsed_answer"]
    assert len(kept) == 4000
    assert kept.startswith('{"bars": [{"t": "yesterday", "c": 1}], "padding": "xxxx')
    assert _price_rows(agent) == 0


# --- one cap on TradingView's calls across processes --------------------------------------------


@pytest.fixture
def unpaced(monkeypatch: pytest.MonkeyPatch) -> None:
    """The per-process pacing (a request a second) out of the way, so that what the tests time
    is the cap's wait alone."""
    monkeypatch.setattr(service, "_LIMITERS", {1.0: TokenBucket(rate_per_s=1000)})


def _age_requests(agent: Agent, seconds: int) -> float:
    """Make every recorded call `seconds` old (by the database's clock); the monotonic time it
    was done at."""
    with agent.atlas.engine.begin() as connection:
        connection.execute(
            text("UPDATE tradingview_request SET called_at = now() - make_interval(secs => :s)"),
            {"s": seconds},
        )
    return time.monotonic()


def _one_call(settings: Any, engine: Any) -> None:
    with mcp_session(settings) as mcp:
        client = tradingview_client(mcp, settings, engine, None)
        client.calendar(["NASDAQ:LITE"], start=NOW, end=NOW)


def _arrivals(fake: FakeTradingView) -> list[float]:
    """When each tool call reached the fake (the monotonic clock)."""
    return [
        fake.times[i]
        for i, call in enumerate(fake.calls)
        if call.url.path == "/mcp" and b'"tools/call"' in call.content
    ]


def test_two_clients_on_one_database_share_the_cap_on_calls_in_the_last_minute(
    database_url: str,
    tmp_path: Path,
    tradingview: tuple[FakeTradingView, Served],
    unpaced: None,
) -> None:
    fake, served = tradingview
    atlas = Atlas(database_url, tmp_path, "http://127.0.0.1:9", **enabled(served, tmp_path))
    atlas.overrides |= {"tradingview_max_per_minute": 2}
    agent = Agent(atlas)
    settings = atlas.settings()
    other_process = create_engine(settings)
    try:
        _one_call(settings, atlas.engine)
        _one_call(settings, other_process)  # a second process's call: the minute holds two
        assert len(_arrivals(fake)) == 2

        # Both are 58 s old: a third must wait for them to leave the minute (2 s).
        aged = _age_requests(agent, 58)
        _one_call(settings, other_process)

        assert len(_arrivals(fake)) == 3
        assert _arrivals(fake)[2] - aged >= 1.8

        # Three calls in the minute (two 58 s old, one 1 s old) and a cap of two: the fourth
        # waits for the second newest to age out (2 s), not for the newest (59 s).
        aged = _age_requests(agent, 58)
        with atlas.engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE tradingview_request SET called_at = now() - interval '1 second'"
                    " WHERE id = (SELECT id FROM tradingview_request ORDER BY id LIMIT 1)"
                )
            )
        _one_call(settings, atlas.engine)
        waited = _arrivals(fake)[3] - aged
        assert 1.8 <= waited < 20  # the 58 s old call ages out in 2 s; the 1 s old one in 59
    finally:
        other_process.dispose()
        atlas.engine.dispose()


def test_calls_older_than_a_minute_do_not_count_and_every_job_is_counted(
    database_url: str,
    tmp_path: Path,
    tradingview: tuple[FakeTradingView, Served],
    unpaced: None,
) -> None:
    fake, served = tradingview
    atlas = Atlas(database_url, tmp_path, "http://127.0.0.1:9", **enabled(served, tmp_path))
    atlas.overrides |= {"tradingview_max_per_minute": 1}
    agent = Agent(atlas)
    try:
        assert agent.run("tradingview_calendar", "first")["status"] == "succeeded"
        started = time.monotonic()
        _age_requests(agent, 61)  # out of the minute: the cap is not reached
        assert agent.run("tradingview_calendar", "second")["status"] == "succeeded"
        assert _arrivals(fake)[1] - started < 20  # not held for a minute

        # The second job's call is in the minute, and the cap is one: the next job waits.
        aged = _age_requests(agent, 59)
        third = agent.run("tradingview_prices", "third", {"company": "lumentum"})
        assert third["status"] == "succeeded", third["failures"]
        assert _arrivals(fake)[2] - aged >= 0.8
    finally:
        atlas.engine.dispose()
