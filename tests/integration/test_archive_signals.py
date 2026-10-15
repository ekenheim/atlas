"""Archive bottleneck signals as leads (atlas-beliefs ticket 18): the nightly `scan_signals` job,
`GET /api/v1/leads?origin=archive_signal` and the Atlas MCP tool `signal_leads`.

Seams: the `atlas` CLI records hand-written documents (`sources import`) and enqueues the jobs,
single worker passes run them (with the worker's schedule on a clock the test sets), and
everything is observed through `/api/v1` and `/mcp`. No model or network is involved: the scan
is the scorer of `configs/discovery/signals.yaml` over the archived parses. The documents are
written for these tests; their scores are worked out by hand from the config (family weight times
the phrase's factor, plus 1.0 for two families in a paragraph and 0.75 for a figure).
"""

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from atlas.api.app import create_app
from atlas.jobs import JobQueue, Pacing, Worker, builtin_registry, builtin_schedules
from tests.harness import Atlas, Clock

GROWING = (
    "Demand for our wafers is growing too fast, we cannot keep up, and only three suppliers"
    " make it."
)
BACKLOG = "We ended the quarter with a backlog of more than $10 million."
SOLD_OUT = "Our lasers are sold out through next year."
LEAD_TIMES = "Extended lead times of 52 weeks are now common."
OTHER_SENSE = "Management cleared the backlog of unresolved staff comments."
HEDGED = "Demand may exceed our supply."
FILLER = (
    "The company designs and manufactures products for customers in many markets and describes"
    " its business, its employees and its facilities in the sections of this report."
)

# Coherent, public 31 July 2025: two strong sentences, one that is not a signal.
COHERENT_Q2 = (FILLER, f"{GROWING} {OTHER_SENSE}", BACKLOG, HEDGED)
# Lumentum, public 15 September 2025.
LUMENTUM_Q3 = (FILLER, SOLD_OUT)
# Coherent again, public 30 October 2025: the July statement repeated, and one new one.
COHERENT_Q3 = (FILLER, GROWING, LEAD_TIMES)

JULY = "2025-07-31T20:00:00Z"
SEPTEMBER = "2025-09-15T12:00:00Z"
OCTOBER = "2025-10-30T20:00:00Z"
AUGUST_31 = "2025-08-31T00:00:00Z"
NOW = datetime(2026, 10, 16, 3, 30, tzinfo=UTC)


def html(*paragraphs: str) -> bytes:
    body = "".join(f"<p>{paragraph}</p>" for paragraph in paragraphs)
    return f"<html><body>{body}</body></html>".encode()


@pytest.fixture
def atlas(database_url: str, tmp_path: Path) -> Iterator[Atlas]:
    # No Hindsight: nothing is retained, so a worker pass runs the scan alone.
    harness = Atlas(database_url, tmp_path, "", signal_scan_lag_seconds=0)
    seeded = harness.cli("companies", "seed")
    assert seeded.returncode == 0, seeded.stderr
    yield harness
    harness.engine.dispose()


def import_html(atlas: Atlas, company: str, name: str, published: str, *paragraphs: str) -> str:
    file = atlas.tmp_path / f"{name}.htm"
    file.write_bytes(html(*paragraphs))
    result = atlas.cli(
        "sources",
        "import",
        "--company",
        company,
        "--file",
        str(file),
        "--origin-url",
        f"https://filings.example.test/{company}/{name}.htm",
        "--published-at",
        published,
        "--title",
        name,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)["source_version_id"]


def scan(atlas: Atlas, key: str, *args: str) -> dict[str, Any]:
    """`atlas signals scan`, one worker pass, and the job."""
    job_id = atlas.enqueue("signals", "scan", "--key", key, *args)
    atlas.worker_pass()
    job = atlas.get(f"/api/v1/jobs/{job_id}")
    assert job["status"] == "succeeded", job["failures"]
    return job


def signals(atlas: Atlas, **params: Any) -> list[dict[str, Any]]:
    return atlas.get("/api/v1/leads", origin="archive_signal", **params)["items"]


def quoted(items: list[dict[str, Any]]) -> list[tuple[str, str, float]]:
    return [
        (each["signal"]["company"], each["signal"]["quote"], each["signal"]["score"])
        for each in items
    ]


@pytest.fixture
def archive(atlas: Atlas) -> dict[str, str]:
    return {
        "coherent_q2": import_html(atlas, "coherent", "coherent-q2", JULY, *COHERENT_Q2),
        "lumentum_q3": import_html(atlas, "lumentum", "lumentum-q3", SEPTEMBER, *LUMENTUM_Q3),
        "coherent_q3": import_html(atlas, "coherent", "coherent-q3", OCTOBER, *COHERENT_Q3),
    }


# --- the scan ----------------------------------------------------------------------------------


def test_a_scan_stores_the_hits_once_ranked_with_their_spans(
    atlas: Atlas, archive: dict[str, str]
) -> None:
    job = scan(atlas, "first")

    assert {
        key: job["artifacts"][key]
        for key in ("mode", "versions_scanned", "hits", "stored", "repeats", "already")
    } == {
        "mode": "since_last",
        "versions_scanned": 3,
        "hits": 5,  # 2 + 1 + 2 (a hedged sentence under the threshold is no hit)
        "stored": 4,
        "repeats": 1,  # the October filing repeats July's sentence word for word
        "already": 0,
    }
    leads = signals(atlas)
    assert quoted(leads) == [
        ("coherent", GROWING, 5.5),  # 2.5 + 2.0 + 1.0
        ("lumentum", SOLD_OUT, 4.2),  # 2.0 + 1.2 + 1.0
        ("coherent", LEAD_TIMES, 2.25),  # 1.5 + 0.75; level with the next, the later document first
        ("coherent", BACKLOG, 2.25),
    ]
    for lead in leads:
        signal = lead["signal"]
        parsed = atlas.parsed(signal["source_version_id"])
        assert parsed[signal["char_start"] : signal["char_end"]] == signal["quote"]
        assert (lead["tier"], lead["origin"], lead["snippet"]) == (
            "C",
            "archive_signal",
            signal["quote"],
        )
    top = leads[0]["signal"]
    assert top["source_version_id"] == archive["coherent_q2"]
    assert top["families"] == ["few_suppliers", "demand_beyond_supply"]
    assert top["factors"] == {"families": 4.5, "cooccurrence": 1.0}
    assert (top["speaker"], top["speaker_kind"]) == (None, None)
    assert top["available_at"].startswith("2025-07-31T20:00:00")


def test_a_second_scan_stores_nothing_twice(atlas: Atlas, archive: dict[str, str]) -> None:
    scan(atlas, "first")
    before = quoted(signals(atlas))

    nothing_new = scan(atlas, "second")
    again = scan(atlas, "third", "--since", "2025-01-01T00:00:00Z")

    assert nothing_new["artifacts"]["versions_selected"] == 0
    assert (again["artifacts"]["versions_scanned"], again["artifacts"]["stored"]) == (3, 0)
    assert again["artifacts"]["already"] == 4  # and the October repeat is a repeat again
    assert again["artifacts"]["mode"] == "since"
    assert quoted(signals(atlas)) == before
    with atlas.engine.connect() as connection:
        runs = connection.execute(
            text("SELECT mode, versions_scanned, stored FROM signal_scan ORDER BY scanned_at")
        ).all()
    assert [tuple(row) for row in runs] == [
        ("since_last", 3, 4),
        ("since_last", 0, 0),
        ("since", 3, 0),
    ]


def test_a_backfill_ingested_newest_first_keeps_the_sentence_in_the_oldest_document(
    atlas: Atlas,
) -> None:
    # Ingested October first, then July: the scan goes by public date, so the repeat is October's.
    import_html(atlas, "coherent", "coherent-q3", OCTOBER, *COHERENT_Q3)
    import_html(atlas, "coherent", "coherent-q2", JULY, *COHERENT_Q2)

    job = scan(atlas, "backfill")

    assert (job["artifacts"]["stored"], job["artifacts"]["repeats"]) == (3, 1)
    kept = [
        (each["signal"]["quote"], each["signal"]["available_at"][:10]) for each in signals(atlas)
    ]
    assert (GROWING, "2025-07-31") in kept
    assert (GROWING, "2025-10-30") not in kept


def test_the_next_scan_reads_only_what_was_ingested_since(
    atlas: Atlas, archive: dict[str, str]
) -> None:
    scan(atlas, "first")
    later = import_html(
        atlas,
        "lumentum",
        "lumentum-q4",
        "2025-12-01T12:00:00Z",
        FILLER,
        "We are doubling our capacity.",
    )

    job = scan(atlas, "second")

    assert (job["artifacts"]["versions_selected"], job["artifacts"]["stored"]) == (1, 1)
    leads = signals(atlas, company_id=atlas.company("lumentum")["id"])
    assert [(each["signal"]["quote"], each["signal"]["source_version_id"]) for each in leads] == [
        (SOLD_OUT, archive["lumentum_q3"]),
        ("We are doubling our capacity.", later),
    ]


def test_a_version_ingested_inside_the_lag_is_left_for_the_next_scan(
    atlas: Atlas, archive: dict[str, str]
) -> None:
    atlas.overrides["signal_scan_lag_seconds"] = 600

    job = scan(atlas, "too-soon")

    assert (job["artifacts"]["versions_selected"], job["artifacts"]["stored"]) == (0, 0)
    assert signals(atlas) == []

    atlas.overrides["signal_scan_lag_seconds"] = 0
    assert scan(atlas, "now")["artifacts"]["versions_selected"] == 3


def test_a_company_or_a_version_can_be_scanned_alone(atlas: Atlas, archive: dict[str, str]) -> None:
    only = scan(atlas, "one", "--version", archive["lumentum_q3"])
    company = scan(atlas, "two", "--company", "coherent")

    assert (only["artifacts"]["mode"], only["artifacts"]["stored"]) == ("versions", 1)
    assert (company["artifacts"]["mode"], company["artifacts"]["stored"]) == ("since", 3)
    # The July sentence is Coherent's first, so the October one is the repeat.
    assert company["artifacts"]["repeats"] == 1
    assert {each["signal"]["company"] for each in signals(atlas)} == {"coherent", "lumentum"}


# --- reading the leads -------------------------------------------------------------------------


def test_the_as_of_bound_is_the_documents_not_the_scans(
    atlas: Atlas, archive: dict[str, str]
) -> None:
    scan(atlas, "first")  # run today, over documents public in 2025

    by_august = signals(atlas, known_by=AUGUST_31)
    by_september = signals(atlas, known_by="2025-09-30T00:00:00Z")
    everything = signals(atlas)
    since_september = signals(atlas, available_from="2025-09-01T00:00:00Z")

    assert quoted(by_august) == [("coherent", GROWING, 5.5), ("coherent", BACKLOG, 2.25)]
    assert quoted(by_september) == [
        ("coherent", GROWING, 5.5),
        ("lumentum", SOLD_OUT, 4.2),
        ("coherent", BACKLOG, 2.25),
    ]
    assert [each["signal"]["score"] for each in everything] == [5.5, 4.2, 2.25, 2.25]
    assert quoted(since_september) == [("lumentum", SOLD_OUT, 4.2), ("coherent", LEAD_TIMES, 2.25)]
    page = atlas.get("/api/v1/leads", origin="archive_signal", known_by=AUGUST_31, limit=1)
    assert (page["total"], len(page["items"])) == (2, 1)


def test_leads_filter_by_theme_and_company_and_are_not_other_origins(
    atlas: Atlas, archive: dict[str, str]
) -> None:
    scan(atlas, "first")
    coherent = atlas.company("coherent")["id"]

    photonics = signals(atlas, theme="photonics")
    nothing = signals(atlas, theme="no-such-theme")
    by_company = signals(atlas, company_id=coherent)
    unfiltered = atlas.get("/api/v1/leads")

    assert len(photonics) == 4
    assert nothing == []
    assert {each["signal"]["company"] for each in by_company} == {"coherent"}
    assert {each["theme"] for each in photonics} == {"photonics"}
    assert unfiltered["total"] == 4  # the lead list as a whole includes them
    assert atlas.get("/api/v1/leads", origin="searxng")["total"] == 0


def test_a_sentence_with_no_cue_or_a_hedged_one_is_not_a_lead(
    atlas: Atlas, archive: dict[str, str]
) -> None:
    scan(atlas, "first")

    stored = " ".join(each["signal"]["quote"] for each in signals(atlas))

    assert OTHER_SENSE not in stored
    assert HEDGED not in stored  # 2.0 x 0.5 for "may": under the 1.5 threshold
    assert FILLER not in stored


# --- the worker's schedule -----------------------------------------------------------------------


class Scheduled(Atlas):
    """The harness with the worker's schedules on a clock the test sets."""

    def __init__(self, database_url: str, tmp_path: Path, hindsight: str, clock: Clock) -> None:
        super().__init__(
            database_url,
            tmp_path,
            hindsight,
            mental_model_refresh_at="",
            consolidate_at="",
            reconcile_at="",
            signal_scan_at="03:00",
            signal_scan_lag_seconds=0,
        )
        self.clock = clock
        self.api = TestClient(create_app(self.settings(), clock=clock))

    def scheduled_pass(self) -> int:
        settings = self.settings()
        queue = JobQueue(self.engine, pacing=Pacing.from_settings(settings), clock=self.clock)
        return Worker(
            queue,
            builtin_registry(settings, clock=self.clock),
            schedules=builtin_schedules(settings, self.engine),
        ).run_once()


def test_the_worker_scans_once_a_day_from_signal_scan_at_in_the_backfill_class(
    database_url: str, tmp_path: Path
) -> None:
    clock = Clock(datetime(2026, 10, 16, 2, 0, tzinfo=UTC))
    scheduled = Scheduled(database_url, tmp_path, "", clock)
    try:
        assert scheduled.scheduled_pass() == 0  # before ATLAS_SIGNAL_SCAN_AT
        clock.advance(hours=1, minutes=5)
        assert scheduled.scheduled_pass() == 1
        clock.advance(hours=5)
        assert scheduled.scheduled_pass() == 0  # one a day
        clock.advance(days=1)
        assert scheduled.scheduled_pass() == 1

        with scheduled.engine.connect() as connection:
            jobs = connection.execute(
                text(
                    "SELECT idempotency_key, job_class, status FROM job"
                    " WHERE kind = 'scan_signals' ORDER BY created_at"
                )
            ).all()
        assert [tuple(row) for row in jobs] == [
            ("scan_signals:2026-10-16", "backfill", "succeeded"),
            ("scan_signals:2026-10-17", "backfill", "succeeded"),
        ]
        scheduled.overrides["signal_scan_at"] = ""  # empty: never
        clock.advance(days=1)
        assert scheduled.scheduled_pass() == 0
    finally:
        scheduled.engine.dispose()


# --- the MCP tool ------------------------------------------------------------------------------


class Agent:
    """The Atlas MCP server over the harness's API."""

    def __init__(self, atlas: Atlas) -> None:
        self.atlas = atlas
        self.requests = 0

    def call(self, tool: str, **arguments: Any) -> tuple[bool, dict[str, Any]]:
        self.requests += 1
        response = self.atlas.api.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": self.requests,
                "method": "tools/call",
                "params": {"name": tool, "arguments": arguments},
            },
        )
        assert response.status_code == 200, response.text
        result = response.json()["result"]
        return result["isError"], json.loads(result["content"][0]["text"])

    def ok(self, tool: str, **arguments: Any) -> dict[str, Any]:
        is_error, value = self.call(tool, **arguments)
        assert not is_error, value
        return value

    def session(self, as_of: str) -> str:
        return self.ok("open_session", question="What is scarce?", as_of=as_of)["session_id"]


def test_signal_leads_lists_the_ranked_leads_public_by_the_sessions_time(
    atlas: Atlas, archive: dict[str, str]
) -> None:
    scan(atlas, "first")
    agent = Agent(atlas)
    early = agent.session(AUGUST_31)
    late = agent.session("2026-01-01T00:00:00Z")

    by_august = agent.ok("signal_leads", session_id=early)
    by_new_year = agent.ok("signal_leads", session_id=late)
    since = agent.ok("signal_leads", session_id=late, since="2025-09-01T00:00:00Z")
    one = agent.ok("signal_leads", session_id=late, limit=1)

    assert [(each["company"], each["quote"], each["score"]) for each in by_august["leads"]] == [
        ("coherent", GROWING, 5.5),
        ("coherent", BACKLOG, 2.25),
    ]
    assert by_august["total"] == 2
    assert [each["score"] for each in by_new_year["leads"]] == [5.5, 4.2, 2.25, 2.25]
    assert [each["quote"] for each in since["leads"]] == [SOLD_OUT, LEAD_TIMES]
    assert [each["quote"] for each in one["leads"]] == [GROWING]
    assert one["total"] == 4
    first = by_august["leads"][0]
    assert first["version_id"] == archive["coherent_q2"]
    assert first["tier"] == "C"
    assert first["families"] == ["few_suppliers", "demand_beyond_supply"]
    assert first["public_at"].startswith("2025-07-31T20:00:00")
    assert "never a Fact" in by_august["note"]
    parsed = atlas.parsed(first["version_id"])
    assert parsed[first["char_start"] : first["char_end"]] == GROWING


def test_signal_leads_needs_a_session_and_takes_no_as_of(atlas: Atlas) -> None:
    agent = Agent(atlas)
    session = agent.session(AUGUST_31)

    is_error, refused = agent.call("signal_leads")
    is_extra, extra = agent.call("signal_leads", session_id=session, as_of="2030-01-01T00:00:00Z")

    assert (is_error, refused) == (
        True,
        {"refused": "invalid_arguments", "message": "session_id: Field required"},
    )
    assert (is_extra, extra) == (
        True,
        {"refused": "invalid_arguments", "message": "as_of: Extra inputs are not permitted"},
    )


# --- one document's share of the ranked read (ticket 27) -------------------------------------

TIGHT = "We believe supply is very tight."
TWO_COMPANIES = "Only two companies make this wafer at volume."
FULL_CAPACITY = "The fab is running at full capacity."


def test_a_documents_hits_past_the_cap_come_after_the_others_in_the_ranked_read(
    atlas: Atlas,
) -> None:
    # Lumentum's call has five hits: 4.2, 2.25, 2.0, 1.6 and 1.5. Coherent's has one of 1.5.
    big = import_html(
        atlas,
        "lumentum",
        "lumentum-big",
        JULY,
        FILLER,
        SOLD_OUT,
        BACKLOG,
        TWO_COMPANIES,
        TIGHT,
        FULL_CAPACITY,
    )
    small = import_html(atlas, "coherent", "coherent-small", SEPTEMBER, FILLER, FULL_CAPACITY)
    scan(atlas, "first")

    ranked = signals(atlas)
    first_four = signals(atlas, limit=4)
    later_page = atlas.get("/api/v1/leads", origin="archive_signal", limit=2, offset=4)

    # Stored as the scorer scores them; read with at most 3 of one document among the first.
    assert [(each["signal"]["source_version_id"], each["signal"]["score"]) for each in ranked] == [
        (big, 4.2),
        (big, 2.25),
        (big, 2.0),
        (small, 1.5),  # level with the big call's 1.5, the later document first
        (big, 1.6),
        (big, 1.5),
    ]
    assert [each["signal"]["score"] for each in first_four] == [4.2, 2.25, 2.0, 1.5]
    assert [each["signal"]["score"] for each in later_page["items"]] == [1.6, 1.5]
    assert later_page["total"] == 6  # nothing is dropped, only reordered
    with atlas.engine.connect() as connection:
        stored = connection.execute(text("SELECT count(*) FROM archive_signal")).scalar_one()
    assert stored == 6


def test_signal_leads_reads_the_capped_ranking(atlas: Atlas) -> None:
    import_html(
        atlas,
        "lumentum",
        "lumentum-big",
        JULY,
        FILLER,
        SOLD_OUT,
        BACKLOG,
        TWO_COMPANIES,
        TIGHT,
        FULL_CAPACITY,
    )
    import_html(atlas, "coherent", "coherent-small", SEPTEMBER, FILLER, FULL_CAPACITY)
    scan(atlas, "first")
    agent = Agent(atlas)
    session = agent.session("2026-01-01T00:00:00Z")

    leads = agent.ok("signal_leads", session_id=session, limit=4)["leads"]

    assert [(each["company"], each["score"]) for each in leads] == [
        ("lumentum", 4.2),
        ("lumentum", 2.25),
        ("lumentum", 2.0),
        ("coherent", 1.5),
    ]
