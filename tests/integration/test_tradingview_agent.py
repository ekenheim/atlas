"""TradingView for the agents, under the owner's override (atlas-beliefs ticket 16b): the earnings
calendar as Tier C leads, the Atlas MCP tool that projects them, and daily closes for settling
predictions and replays.

Seams: single worker passes run the jobs (enqueued through the queue, with an application clock
the test sets), and everything is observed through `/api/v1` and `/mcp` and the requests the
TradingView fake received. TradingView is the transport-level fake of its MCP server
(`tests/fakes/tradingview.py`) over synthetic fixtures in the assumed calendar and `get_ohlcv`
shapes; nothing live is called.
"""

import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from atlas.discovery.leads import store_headline
from atlas.jobs import JobQueue, Pacing, Worker, builtin_registry
from tests.fakes.serve import Served, serve
from tests.fakes.tradingview import ACCESS_TOKEN, FakeTradingView
from tests.harness import Atlas, Clock

OVERRIDE = (
    "TradingView terms (display-only) overridden by the owner for private non-commercial use"
    " (2026-09-30)"
)
NOW = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
CALENDAR_URL = "https://mcp.tradingview.com/calendar/NASDAQ%3ALITE/{key}"
Q4, Q1, Q2 = "syn-cal-2026-q4", "syn-cal-2027-q1", "syn-cal-2027-q2"


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
    assert artifacts["events"] == {"listed": 3, "new_leads": 3}
    assert (artifacts["tool_calls"], artifacts["bounded"]) == (1, False)
    assert artifacts["owner_override"] == OVERRIDE
    assert tradingview[0].tool_calls == [
        (
            "mcp-tv-get-earnings-calendar",
            {
                "symbol": "NASDAQ:LITE",
                "start_date": "2026-04-17T12:00:00Z",  # 120 days before the clock
                "end_date": "2027-02-11T12:00:00Z",  # 180 days after it
            },
        )
    ]

    leads = agent.leads(theme="photonics")
    assert len(leads) == 3
    first = events(leads)[Q1]
    lumentum = agent.atlas.company("lumentum")["id"]
    assert {k: first[k] for k in ("tier", "origin", "snippet", "query", "theme", "engines")} == {
        "tier": "C",
        "origin": "tradingview_calendar",
        "snippet": "",
        "query": None,
        "theme": "photonics",
        "engines": ["tradingview"],
    }
    assert first["url"] == CALENDAR_URL.format(key=Q1)
    assert first["title"] == "SYNTHETIC Q1 FY2027 results"
    assert first["calendar"] == {
        "company_id": lumentum,
        "symbol": "NASDAQ:LITE",
        "event_key": Q1,
        "event_at": "2026-11-05T21:00:00Z",
        "status": "scheduled",
        "fiscal_period": "Q1",
        "fiscal_year": "2027",
        "observed_at": "2026-08-15T12:00:00Z",
        "owner_override": OVERRIDE,
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
    assert everything["total"] == 4
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
    assert again["artifacts"]["events"] == {"listed": 3, "new_leads": 0}
    assert len(agent.leads()) == 3
    assert _observations(agent) == 3  # the same dates change nothing

    tradingview[0].calendar = "-moved"
    agent.clock.advance(days=7)
    moved = agent.run("tradingview_calendar", "third")

    assert moved["artifacts"]["events"] == {"listed": 1, "new_leads": 0}
    assert len(agent.leads()) == 3  # the same lead, not a second one
    assert _observations(agent) == 4
    now = events(agent.leads())[Q1]["calendar"]
    assert (now["event_at"], now["status"], now["observed_at"]) == (
        "2026-11-12T21:00:00Z",
        "confirmed",
        "2026-08-22T12:00:00Z",
    )
    # As Atlas knew it a day after the first run, the date had not moved.
    then = events(agent.leads(known_by="2026-08-16T00:00:00Z"))[Q1]["calendar"]
    assert (then["event_at"], then["status"]) == ("2026-11-05T21:00:00Z", "scheduled")


def test_two_companies_on_one_fiscal_calendar_keep_a_lead_each_without_event_ids(
    agent: Agent, tradingview: tuple[FakeTradingView, Served]
) -> None:
    tradingview[0].calendar = "-noid"  # no event ID: both are keyed by their fiscal period
    lumentum = agent.run("tradingview_calendar", "lite", {"company": "lumentum"})
    innolight = agent.run("tradingview_calendar", "innolight", {"company": "innolight"})

    assert (lumentum["status"], innolight["status"]) == ("succeeded", "succeeded"), (
        lumentum["failures"],
        innolight["failures"],
    )
    leads = agent.leads()
    assert len(leads) == 2
    assert {each["calendar"]["event_key"] for each in leads} == {"fy2027-Q1"}
    by_company = {each["calendar"]["company_id"]: each for each in leads}
    assert set(by_company) == {
        agent.atlas.company("lumentum")["id"],
        agent.atlas.company("innolight")["id"],
    }
    assert {each["calendar"]["symbol"] for each in leads} == {"NASDAQ:LITE", "HKEX:3308"}
    assert _observations(agent) == 2
    # A rerun finds both again and adds nothing.
    agent.run("tradingview_calendar", "lite-again", {"company": "lumentum"})
    assert len(agent.leads()) == 2
    assert _observations(agent) == 2


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

    assert len(agent.leads(known_by="2026-08-15T12:00:00Z")) == 3
    assert agent.leads(known_by="2026-08-15T11:59:59Z") == []
    window = agent.leads(event_from="2026-08-01T00:00:00Z", event_to="2026-12-31T00:00:00Z")
    assert [item["calendar"]["event_key"] for item in window] == [Q4, Q1]  # soonest first
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
    assert [r["fiscal_period"] for r in near["reports"]] == ["Q4"]
    assert [(r["fiscal_period"], r["fiscal_year"]) for r in wide["reports"]] == [
        ("Q4", "2026"),
        ("Q1", "2027"),  # 5 Nov is 82 days on; 4 Feb 2027 is not within 100
    ]
    report = wide["reports"][1]
    assert {k: report[k] for k in ("company", "symbol", "event_at", "status", "tier")} == {
        "company": "lumentum",
        "symbol": "NASDAQ:LITE",
        "event_at": "2026-11-05T21:00:00Z",
        "status": "scheduled",
        "tier": "C",
    }
    assert report["days_from_as_of"] == 82.4
    assert wide["reports"][0]["days_from_as_of"] == -3.6  # reported the Tuesday before
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
    agent.run("tradingview_calendar", "second")  # the Q1 date moves, stored at 22 Aug 12:00
    before_storing = agent.session("2026-08-10T00:00:00Z")
    after_the_first = agent.session("2026-08-16T00:00:00Z")
    after_the_move = agent.session("2026-08-23T00:00:00Z")

    # 11 Aug is inside this window, but Atlas had stored nothing yet.
    empty = agent.ok("upcoming_reports", session_id=before_storing, window_days=100)
    assert empty["reports"] == []

    early = agent.ok("upcoming_reports", session_id=after_the_first, window_days=100)
    assert [(r["fiscal_period"], r["event_at"], r["status"]) for r in early["reports"]] == [
        ("Q4", "2026-08-11T20:30:00Z", "reported"),
        ("Q1", "2026-11-05T21:00:00Z", "scheduled"),  # the date as Atlas knew it then
    ]
    late = agent.ok("upcoming_reports", session_id=after_the_move, window_days=100)
    assert [(r["fiscal_period"], r["event_at"], r["status"]) for r in late["reports"]] == [
        ("Q4", "2026-08-11T20:30:00Z", "reported"),
        ("Q1", "2026-11-12T21:00:00Z", "confirmed"),
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
                "start_date": "2026-07-01T00:00:00Z",
                "end_date": "2026-07-31T23:59:59Z",
                "interval": "1D",
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
