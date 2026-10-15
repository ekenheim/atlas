"""The prospective record's calls (atlas-beliefs ticket 19): made by a Belief judged `proven`, by a
Scout session escalating an archive signal to a question Issue, dated by the event that makes
them; backfilled for the Beliefs proven before; and settled by the daily `settle_calls` job at
+1, +3 and +6 months against the theme's equal-weighted universe, with TradingView off recorded
`unpriced`.

Seams: the `/api/v1` API, the `atlas` CLI (only to record the hand-written document a signal is
found in), and single worker passes at a clock the test sets. TradingView is the transport-level
fake of its MCP server over synthetic bars the test builds around the real dates of the calls it
made (a call is dated by the database's clock, never by a request); nothing live is called. The
universe is Lumentum, Coherent and Innolight of the photonics theme, whose TradingView symbols
the fake knows; Innolight has no bars, so it is left out of every benchmark.
"""

import json
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from atlas.audit import Actor
from atlas.calls.model import add_months
from atlas.calls.settle import SettleSchedule
from atlas.jobs import JobQueue, Pacing, Worker, builtin_registry
from atlas.ledger.ingest import INGEST_KIND, ingest_payload
from tests.fakes.serve import Served, serve
from tests.fakes.tradingview import ACCESS_TOKEN, FakeTradingView
from tests.harness import THEMES, Atlas, Clock

URL_EX991 = (
    "https://www.sec.gov/Archives/edgar/data/1633978/000162828026055726/lite_ex991xq4fy26.htm"
)
QUARTER = "Net revenue for the fourth quarter of fiscal year 2026 was $1.01 billion"
STATEMENT = "Lumentum's fourth-quarter fiscal 2026 net revenue was $1.01 billion."
BELIEF = "Lumentum's revenue is growing fast enough to strain its laser capacity."
SOLD_OUT = "Demand for our wafers is growing too fast, we cannot keep up, and only three suppliers make it."
UNIVERSE = ("coherent", "lumentum", "innolight")
OVERRIDE = (
    "TradingView terms (display-only) overridden by the owner for private non-commercial use"
    " (2026-09-30)"
)


def small_universe(path: Path) -> Path:
    """The photonics config cut to three companies the TradingView fake has symbols for."""
    document = yaml.safe_load(THEMES.read_text(encoding="utf-8"))
    document["companies"] = {k: v for k, v in document["companies"].items() if k in UNIVERSE}
    for theme in document["themes"].values():
        theme["companies"] = [c for c in theme["companies"] if c in UNIVERSE]
    target = path / "themes.yaml"
    target.write_text(yaml.safe_dump(document), encoding="utf-8")
    return target


def bars(closes: dict[date, float]) -> str:
    """A get_ohlcv answer of one bar a day, in the documented `{t, o, h, l, c, v}` shape."""
    return json.dumps(
        {
            "bars": [
                {
                    "t": int(datetime(day.year, day.month, day.day, 12, tzinfo=UTC).timestamp()),
                    "o": close,
                    "h": close,
                    "l": close,
                    "c": close,
                    "v": 1000,
                }
                for day, close in sorted(closes.items())
            ]
        }
    )


class Record:
    """Atlas with Lumentum's press release ingested and TradingView served."""

    def __init__(
        self, database_url: str, tmp_path: Path, fake: FakeTradingView, served: Served
    ) -> None:
        self.fake = fake
        self._fact: str | None = None
        self.atlas = Atlas(
            database_url,
            tmp_path,
            "",
            themes_config=small_universe(tmp_path),
            signal_scan_lag_seconds=0,
            tradingview_enabled=True,
            tradingview_mcp_url=f"{served.url}/mcp",
            tradingview_access_token=ACCESS_TOKEN,
            tradingview_token_file=tmp_path / "no-token-file.json",
            tradingview_rate_per_s=1.0,
        )
        self.engine = self.atlas.engine
        self.api = self.atlas.api
        self.get = self.atlas.get
        queue = JobQueue(self.engine, actor=Actor("record-test"))
        queue.enqueue(INGEST_KIND, "lumentum", ingest_payload("lumentum", ["8-K"], None))
        assert Worker(queue, builtin_registry(self.atlas.settings())).run_once() >= 1

    def post(self, path: str, body: dict[str, Any], status: int = 200) -> Any:
        response = self.api.post(path, json=body)
        assert response.status_code == status, response.text
        return response.json()

    def company(self, slug: str = "lumentum") -> str:
        return self.atlas.company(slug)["id"]

    def fact(self) -> str:
        """The one Fact every Belief of these tests cites, recorded the first time."""
        if self._fact is None:
            self._fact = self._record_fact()
        return self._fact

    def _record_fact(self) -> str:
        version = self.atlas.version(URL_EX991)["id"]
        parsed = self.atlas.parsed(version)
        start = parsed.index(QUARTER)
        recorded = self.post(
            "/api/v1/facts",
            {
                "subject_company_id": self.company(),
                "source_version_id": version,
                "quote": QUARTER,
                "span_start": start,
                "span_end": start + len(QUARTER),
                "epistemic_type": "company_claim",
                "step": "context",
                "statement": STATEMENT,
                "quantity": {"value": 1.01, "unit": "USD", "metric": "figure"},
                "period": "FY2026",
                "status": "in_effect",
            },
            status=201,
        )
        return recorded["fact"]["id"]

    def belief(
        self, step: str = "constraint", statement: str = BELIEF, companies: bool = True
    ) -> str:
        return self.post(
            "/api/v1/beliefs",
            {
                "statement": statement,
                "theme": "photonics",
                "step": step,
                "company_ids": [self.company()] if companies else [],
                "as_of": "2026-09-30T00:00:00Z",
                "actor": "claude-session",
                "citations": [
                    {
                        "ref_id": self.fact(),
                        "valence": 0.9,
                        "weight": "load_bearing",
                        "note": "the figure",
                    }
                ],
            },
            status=201,
        )["id"]

    def judge(self, belief: str, judgement: str = "proven") -> dict[str, Any]:
        return self.post(
            f"/api/v1/beliefs/{belief}/judge",
            {"actor": "owner", "judgement": judgement, "confidence": 0.8, "reason": "agreed"},
        )

    def calls(self, **params: Any) -> list[dict[str, Any]]:
        return self.get("/api/v1/calls", **params)["items"]

    def settle(self, now: datetime, key: str) -> dict[str, Any]:
        """Enqueue `settle_calls`, run worker passes at `now` until it is done, and return it."""
        settings = self.atlas.settings()
        queue = JobQueue(self.engine, pacing=Pacing.from_settings(settings))
        job = queue.enqueue("settle_calls", key, {}).job
        worker = Worker(queue, builtin_registry(settings, clock=Clock(now)))
        for _ in range(12):
            worker.run_once()
            read = self.get(f"/api/v1/jobs/{job.id}")
            if read["status"] in ("succeeded", "failed", "dead"):
                return read
        raise AssertionError("the settlement did not finish")

    def symbols_asked(self) -> list[str]:
        return [a["symbol"] for name, a in self.fake.tool_calls if name == "mcp-tv-get-ohlcv"]


@pytest.fixture
def tradingview() -> Iterator[tuple[FakeTradingView, Served]]:
    fake = FakeTradingView()
    with serve(fake.handle) as served:
        yield fake, served
        served.raise_errors()


@pytest.fixture
def record(
    database_url: str, tmp_path: Path, tradingview: tuple[FakeTradingView, Served]
) -> Iterator[Record]:
    started = Record(database_url, tmp_path, *tradingview)
    yield started
    started.engine.dispose()


def day_of(moment: str) -> date:
    return datetime.fromisoformat(moment).astimezone(UTC).date()


def noon(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, 12, tzinfo=UTC)


# --- the Belief origin ---------------------------------------------------------------------------


def test_proving_a_belief_makes_one_call_dated_the_judgement(record: Record) -> None:
    belief = record.belief()
    assert record.calls() == []  # born unproven: nothing said yet

    judged = record.judge(belief)
    (call,) = record.calls()

    assert call["origin"] == "belief"
    assert call["origin_id"] == belief
    assert call["lead_id"] is None
    assert call["theme"] == "photonics"
    assert call["claim"] == BELIEF
    assert call["direction"] == "tightening"
    assert call["made_at"] == judged["history"][-1]["at"]
    assert [(c["slug"], c["symbol"]) for c in call["companies"]] == [("lumentum", "NASDAQ:LITE")]
    assert (call["state"], call["checkpoints"], call["unpriced_reason"]) == ("open", [], None)
    made = day_of(call["made_at"])
    assert call["next_due"] == {"horizon_months": 1, "due_on": add_months(made, 1).isoformat()}
    assert "closes are used only to score" in call["note"].lower()

    # Judged again, or otherwise, it says nothing new.
    record.judge(belief)
    record.judge(belief, "unproven")
    assert len(record.calls()) == 1


def test_a_calls_direction_follows_the_belief_step_and_a_filter_selects(record: Record) -> None:
    constraint = record.belief("constraint")
    relief = record.belief("relief", "Qualified second sources will ease the laser supply.")
    capture = record.belief("capture", "Lumentum captures a growing share of the value.")
    unproven = record.belief("control", "Lumentum controls its supply.")
    for each in (constraint, relief, capture):
        record.judge(each)
    record.judge(unproven, "disproven")

    by_claim = {call["claim"]: call["direction"] for call in record.calls()}

    assert by_claim == {
        BELIEF: "tightening",
        "Qualified second sources will ease the laser supply.": "easing",
        "Lumentum captures a growing share of the value.": None,
    }
    assert len(record.calls(origin="belief", theme="photonics", state="open")) == 3
    assert record.calls(origin="hypothesis") == []
    assert record.calls(theme="robotics") == []
    assert record.calls(state="settled") == []
    assert len(record.calls(company_id=record.company())) == 3


def test_a_belief_proven_before_the_record_gets_its_call_at_its_judgement_time(
    record: Record,
) -> None:
    belief = record.belief()
    proven_at = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
    with record.engine.begin() as connection:  # as it was before the record existed
        connection.execute(
            text(
                "INSERT INTO belief_judgement (id, belief_id, judgement, confidence, actor,"
                " reason, at) VALUES (gen_random_uuid(), :belief, 'proven', 0.8, 'owner',"
                " 'agreed', :at)"
            ),
            {"belief": belief, "at": proven_at},
        )
    assert record.calls() == []

    job = record.settle(datetime(2026, 9, 2, 12, tzinfo=UTC), "backfill")

    assert job["status"] == "succeeded", job["failures"]
    assert job["artifacts"]["backfilled_calls"] == 1
    (call,) = record.calls()
    assert call["made_at"] == "2026-09-01T10:00:00Z"  # not today
    assert call["origin_id"] == belief

    again = record.settle(datetime(2026, 9, 3, 12, tzinfo=UTC), "backfill-again")
    assert again["artifacts"]["backfilled_calls"] == 0
    assert len(record.calls()) == 1
    assert record.fake.tool_calls == []  # nothing was due, so TradingView was not asked


# --- the signal origin ---------------------------------------------------------------------------


def test_escalating_an_archive_signal_to_a_question_makes_a_call_once(record: Record) -> None:
    file = record.atlas.tmp_path / "lumentum-q3.htm"
    file.write_bytes(
        f"<html><body><p>The company designs products.</p><p>{SOLD_OUT}</p></body></html>".encode()
    )
    imported = record.atlas.cli(
        "sources",
        "import",
        "--company",
        "lumentum",
        "--file",
        str(file),
        "--origin-url",
        "https://filings.example.test/lumentum/q3.htm",
        "--published-at",
        "2025-09-15T12:00:00Z",
        "--title",
        "q3",
    )
    assert imported.returncode == 0, imported.stderr
    scan = record.atlas.enqueue("signals", "scan", "--key", "scan")
    record.atlas.worker_pass()
    scanned = record.get(f"/api/v1/jobs/{scan}")
    assert scanned["status"] == "succeeded", scanned
    assert scanned["artifacts"]["hits"] == 1, scanned["artifacts"]
    (lead,) = record.get("/api/v1/leads", origin="archive_signal")["items"]
    assert lead["signal"]["quote"] == SOLD_OUT

    issue = record.post(
        "/api/v1/issues",
        {
            "title": "Is Lumentum's laser output sold out through next year?",
            "theme": "photonics",
            "kind": "question",
            "lead_id": lead["id"],
        },
        status=201,
    )

    (call,) = record.calls()
    assert call["origin"] == "signal"
    assert (call["origin_id"], call["lead_id"]) == (issue["id"], lead["id"])
    assert call["claim"] == SOLD_OUT
    assert call["direction"] is None
    assert call["made_at"] == issue["created_at"]  # now, not the document's date or a session's
    assert [(c["slug"], c["symbol"]) for c in call["companies"]] == [("lumentum", "NASDAQ:LITE")]

    # A second question from the same lead adds no call; a lead that is no signal is refused,
    # as is a lead on an Issue that is not a question.
    record.post(
        "/api/v1/issues",
        {"title": "Again?", "theme": "photonics", "kind": "question", "lead_id": lead["id"]},
        status=201,
    )
    assert len(record.calls()) == 1
    refused = record.api.post(
        "/api/v1/issues",
        json={
            "title": "x",
            "theme": "photonics",
            "kind": "question",
            "lead_id": "00000000-0000-0000-0000-000000000000",
        },
    )
    assert (refused.status_code, refused.json()["error"]["code"]) == (422, "unknown_lead")
    on_a_read = record.api.post(
        "/api/v1/issues",
        json={"title": "x", "theme": "photonics", "kind": "read", "lead_id": lead["id"]},
    )
    assert on_a_read.status_code == 422
    assert len(record.calls()) == 1


# --- settlement ----------------------------------------------------------------------------------


def checkpoints_of(call: dict[str, Any]) -> list[tuple[int, float, float | None, float | None]]:
    return [
        (c["horizon_months"], c["change"], c["benchmark_change"], c["relative_change"])
        for c in call["checkpoints"]
    ]


def test_checkpoints_are_appended_at_one_three_and_six_months_against_the_universe(
    record: Record, tradingview: tuple[FakeTradingView, Served]
) -> None:
    record.judge(record.belief())
    (call,) = record.calls()
    made = day_of(call["made_at"])
    one, three, six = (add_months(made, months) for months in (1, 3, 6))
    before = made - timedelta(days=1)
    # Lumentum: 100 -> 110 -> 121 -> 90. Coherent: 50 -> 50 -> 55 -> 45. Innolight has no bars.
    tradingview[0].ohlcv["NASDAQ:LITE"] = bars({before: 100.0, one: 110.0, three: 121.0, six: 90.0})
    tradingview[0].ohlcv["NYSE:COHR"] = bars({before: 50.0, one: 50.0, three: 55.0, six: 45.0})

    # Not due yet: nothing is called.
    early = record.settle(noon(one - timedelta(days=1)), "early")
    assert early["status"] == "succeeded", early["failures"]
    assert early["artifacts"]["checkpoints_due"] == 0
    assert tradingview[0].tool_calls == []

    first = record.settle(noon(one), "one")
    assert first["status"] == "succeeded", first["failures"]
    assert first["artifacts"]["checkpoints_appended"] == 1
    assert first["artifacts"]["tool_calls"] == 3
    assert sorted(record.symbols_asked()) == ["HKEX:3308", "NASDAQ:LITE", "NYSE:COHR"]
    (call,) = record.calls()
    assert checkpoints_of(call) == [(1, 0.1, 0.05, 0.05)]
    (checkpoint,) = call["checkpoints"]
    assert checkpoint["due_on"] == one.isoformat()
    assert checkpoint["benchmark_members"] == 2
    assert [(m["company"], m["base_close"], m["close"]) for m in checkpoint["companies"]] == [
        ("lumentum", 100.0, 110.0)
    ]
    assert sorted((m["company"], m["change"]) for m in checkpoint["benchmark"]) == [
        ("coherent", 0.0),
        ("lumentum", 0.1),
    ]
    assert (call["state"], call["next_due"]["horizon_months"]) == ("open", 3)

    # The same day again, and the day after: nothing more, nothing called.
    asked = len(tradingview[0].tool_calls)
    assert record.settle(noon(one), "one-again")["artifacts"]["checkpoints_due"] == 0
    assert len(tradingview[0].tool_calls) == asked

    third = record.settle(noon(three), "three")
    assert third["artifacts"]["checkpoints_appended"] == 1
    (call,) = record.calls()
    assert checkpoints_of(call) == [(1, 0.1, 0.05, 0.05), (3, 0.21, 0.155, 0.055)]

    sixth = record.settle(noon(six + timedelta(days=2)), "six")  # a late pass still dates it
    assert sixth["artifacts"]["checkpoints_appended"] == 1
    (call,) = record.calls()
    assert checkpoints_of(call)[2] == (6, -0.1, -0.1, 0.0)
    assert (call["state"], call["next_due"]) == ("settled", None)
    assert [c["due_on"] for c in call["checkpoints"]] == [d.isoformat() for d in (one, three, six)]
    assert len(record.calls(state="settled")) == 1
    assert record.calls(state="open") == []

    with record.engine.connect() as connection:
        owners = set(
            connection.execute(text("SELECT owner_override FROM call_checkpoint")).scalars()
        )
    assert owners == {OVERRIDE}


def test_a_close_missing_on_a_day_takes_the_last_and_a_call_waits_for_a_company_not_fetched(
    record: Record, tradingview: tuple[FakeTradingView, Served]
) -> None:
    record.judge(record.belief())
    (call,) = record.calls()
    made = day_of(call["made_at"])
    one = add_months(made, 1)
    tradingview[0].ohlcv["NASDAQ:LITE"] = bars(
        {made - timedelta(days=3): 80.0, one - timedelta(days=2): 100.0}  # nothing on the day
    )
    tradingview[0].ohlcv["NYSE:COHR"] = bars(
        {made - timedelta(days=3): 20.0, one - timedelta(days=2): 20.0}
    )

    # One call per job: Lumentum is fetched, Coherent is not, so the benchmark is incomplete.
    record.atlas.overrides["tradingview_max_calls_per_job"] = 1
    held = record.settle(noon(one), "bounded")
    assert held["status"] == "succeeded", held["failures"]
    assert held["artifacts"]["bounded"] is True
    assert held["artifacts"]["checkpoints_appended"] == 0
    assert held["artifacts"]["deferred"] == [
        {"call_id": call["id"], "horizon_months": 1, "reason": "prices_not_fetched"}
    ]
    assert record.calls()[0]["checkpoints"] == []

    record.atlas.overrides["tradingview_max_calls_per_job"] = 20
    done = record.settle(noon(one), "unbounded")
    assert done["artifacts"]["checkpoints_appended"] == 1
    assert checkpoints_of(record.calls()[0]) == [(1, 0.25, 0.125, 0.125)]


def test_a_call_that_cannot_be_priced_is_noted_once_and_nothing_fails(
    record: Record, tradingview: tuple[FakeTradingView, Served]
) -> None:
    nobody = record.belief(statement="Capacity is tight.", companies=False)
    record.judge(nobody)
    record.judge(record.belief())
    by_company = {len(c["companies"]): c for c in record.calls()}
    made = day_of(by_company[0]["made_at"])
    one = add_months(made, 1)

    # No symbol anywhere in the first call; TradingView off for the second.
    record.atlas.overrides["tradingview_enabled"] = False
    off = record.settle(noon(one), "off")
    assert off["status"] == "succeeded", off["failures"]
    assert off["artifacts"]["unpriced_noted"] == 2
    assert tradingview[0].tool_calls == []
    reasons = {len(c["companies"]): c["unpriced_reason"] for c in record.calls()}
    assert reasons == {0: "no_symbol", 1: "tradingview_disabled"}
    assert {c["state"] for c in record.calls()} == {"unpriced"}
    assert len(record.calls(state="unpriced")) == 2

    # Once: another pass notes nothing more.
    assert record.settle(noon(one), "off-again")["artifacts"]["unpriced_noted"] == 0
    with record.engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM call_unpriced")).scalar_one() == 2

    # The note is no verdict: with TradingView on, the call that has a symbol is priced.
    record.atlas.overrides["tradingview_enabled"] = True
    before = made - timedelta(days=1)
    tradingview[0].ohlcv["NASDAQ:LITE"] = bars({before: 100.0, one: 90.0})
    tradingview[0].ohlcv["NYSE:COHR"] = bars({before: 10.0, one: 10.0})
    on = record.settle(noon(one), "on")
    assert on["artifacts"]["checkpoints_appended"] == 1
    priced = {len(c["companies"]): c for c in record.calls()}
    assert checkpoints_of(priced[1]) == [(1, -0.1, -0.05, -0.05)]
    assert priced[1]["unpriced_reason"] == "tradingview_disabled"
    assert priced[1]["state"] == "open"
    assert priced[0]["checkpoints"] == []


def test_the_prospective_record_is_insert_only(
    record: Record, tradingview: tuple[FakeTradingView, Served]
) -> None:
    record.judge(record.belief())
    (call,) = record.calls()
    made = day_of(call["made_at"])
    one = add_months(made, 1)
    tradingview[0].ohlcv["NASDAQ:LITE"] = bars({made: 100.0, one: 110.0})
    tradingview[0].ohlcv["NYSE:COHR"] = bars({made: 50.0, one: 50.0})
    record.settle(noon(one), "one")
    record.settle(noon(one + timedelta(days=1)), "off")

    for statement in (
        "UPDATE call_record SET claim = 'x'",
        "DELETE FROM call_record",
        "TRUNCATE call_record CASCADE",
        "UPDATE call_company SET symbol = NULL",
        "DELETE FROM call_company",
        "UPDATE call_checkpoint SET change = 0",
        "DELETE FROM call_checkpoint",
        "TRUNCATE call_checkpoint",
    ):
        with pytest.raises(DBAPIError, match="insert-only"), record.engine.begin() as connection:
            connection.execute(text(statement))
    (still,) = record.calls()
    assert checkpoints_of(still) == [(1, 0.1, 0.05, 0.05)]


def test_the_worker_enqueues_one_settlement_a_day_from_its_time(record: Record) -> None:
    schedule = SettleSchedule(record.engine, (5, 30))

    assert schedule(datetime(2026, 10, 16, 5, 29, tzinfo=UTC)) == []
    (first,) = schedule(datetime(2026, 10, 16, 5, 30, tzinfo=UTC))
    assert (first.job.kind, first.job.idempotency_key) == (
        "settle_calls",
        "settle_calls:2026-10-16",
    )
    assert first.job.job_class == "backfill"
    assert schedule(datetime(2026, 10, 16, 23, 0, tzinfo=UTC)) == []
    (next_day,) = schedule(datetime(2026, 10, 17, 6, 0, tzinfo=UTC))
    assert next_day.job.idempotency_key == "settle_calls:2026-10-17"
