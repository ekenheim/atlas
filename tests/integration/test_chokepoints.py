"""The Chokepoint Watch's board and run record (Chokepoint Watch ticket W1).

Seam: the `/api/v1` API on a fresh database holding Lumentum's recorded Q4 FY26 press release
(a Fact to cite is quoted from it, public on 11 August 2026, as in `test_sessions`), with a
controllable application clock so that a chokepoint can go stale. A lead is inserted by SQL
(the discovery that finds one is not under test); an Issue comes from `POST /issues`. The
insert-only tables are attacked through the engine.
"""

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.exc import DBAPIError

from atlas.api.app import create_app
from atlas.audit import Actor
from atlas.jobs import JobQueue, Worker, builtin_registry
from atlas.ledger.ingest import INGEST_KIND, ingest_payload
from tests.harness import EDGAR_FIXTURES, THEMES, Clock, at, make_settings

URL_EX991 = (
    "https://www.sec.gov/Archives/edgar/data/1633978/000162828026055726/lite_ex991xq4fy26.htm"
)
ACTOR = "board-test-owner"
REVENUE_QUOTE = "Net revenue for the fourth quarter of fiscal year 2026 was $1.01 billion"
REVENUE_SPAN = (1604, 1676)
THEME = "photonics"
NO_SUCH_ID = "00000000-0000-0000-0000-000000000000"
# The press release became public on 11 August; the board is prospective, so a test that needs a
# session of that day sets the application clock there.
BEFORE_RELEASE = "2026-08-01T12:00:00+00:00"
AFTER_RELEASE = "2026-08-12T12:00:00+00:00"
START = "2026-10-18T09:00:00+00:00"
CONSTRAINT = "Indium phosphide substrates for 1.6T lasers"
LAYER = "materials"


class Board:
    def __init__(self, database_url: str, tmp_path: Path) -> None:
        archive = tmp_path / "archive"
        archive.mkdir(exist_ok=True)
        self.engine = create_engine(database_url)
        self.clock = Clock(at(START))
        settings = make_settings(
            archive,
            database_url=database_url,
            actor=ACTOR,
            themes_config=THEMES,
            sec_fixtures_dir=EDGAR_FIXTURES,
        )
        self.api = TestClient(create_app(settings, clock=self.clock))
        queue = JobQueue(self.engine, actor=Actor(ACTOR))
        queue.enqueue(INGEST_KIND, "lumentum", ingest_payload("lumentum", ["8-K"], None))
        assert Worker(queue, builtin_registry(settings)).run_once() == 1

    # --- reads and setup ---

    def get(self, path: str, **params: Any) -> Any:
        response = self.api.get(path, params=params)
        assert response.status_code == 200, response.text
        return response.json()

    def company_id(self) -> str:
        return next(
            c["id"] for c in self.get("/api/v1/companies")["items"] if c["slug"] == "lumentum"
        )

    def fact(self, session_id: str | None = None) -> str:
        company = self.company_id()
        documents = self.get(f"/api/v1/companies/{company}/sources", limit=100)["items"]
        version = next(d["latest_version_id"] for d in documents if d["canonical_url"] == URL_EX991)
        start, end = REVENUE_SPAN
        response = self.api.post(
            "/api/v1/facts",
            json={
                "subject_company_id": company,
                "source_version_id": version,
                "quote": REVENUE_QUOTE,
                "span_start": start,
                "span_end": end,
                "epistemic_type": "company_claim",
                "step": "context",
                "statement": "Lumentum's fourth-quarter fiscal 2026 net revenue was $1.01 billion.",
                "quantity": {"value": 1.01, "unit": "USD billion", "metric": "net revenue"},
                "period": "Q4 FY2026",
                "status": "in_effect",
                "session_id": session_id,
            },
        )
        assert response.status_code == 201, response.text
        return response.json()["fact"]["id"]

    def lead(
        self,
        first_seen_at: str | None = None,
        *,
        title: str = "InP wafer lead times",
        published: str | None = None,
    ) -> str:
        with self.engine.begin() as connection:
            return str(
                connection.execute(
                    text(
                        "INSERT INTO lead (id, canonical_url, url, title, snippet, engines,"
                        " origin, first_seen_at, published_date) VALUES (gen_random_uuid(),"
                        " 'https://example.test/' || gen_random_uuid(),"
                        " 'https://example.test/a', :title, 'lead times',"
                        " '{}', 'tradingview_news', COALESCE(CAST(:seen AS timestamptz), now()),"
                        " CAST(:published AS date)) RETURNING id"
                    ),
                    {"seen": first_seen_at, "title": title, "published": published},
                ).scalar_one()
            )

    def issue(self, title: str = "Is InP the constraint?", theme: str = THEME, **extra: Any) -> str:
        response = self.api.post(
            "/api/v1/issues", json={"title": title, "theme": theme, "kind": "question", **extra}
        )
        assert response.status_code == 201, response.text
        return response.json()["id"]

    def session(self, as_of: str | None = None, **extra: Any) -> str:
        """Open a session; by default as of the application clock's now."""
        as_of = as_of or self.clock.now.isoformat()
        response = self.api.post(
            "/api/v1/sessions",
            json={
                "question": "Where is the next bottleneck?",
                "theme": THEME,
                "seed_company_ids": [],
                "as_of": as_of,
                "model": "claude-fable-5-1",
                "actor": "claude-session",
                **extra,
            },
        )
        assert response.status_code == 201, response.text
        return response.json()["id"]

    # --- the board ---

    def create(self, **overrides: Any) -> dict[str, Any]:
        response = self.api.post(
            "/api/v1/chokepoints",
            json={"theme": THEME, "constraint": CONSTRAINT, "layer": LAYER} | overrides,
        )
        assert response.status_code == 201, response.text
        return response.json()

    def event(self, chokepoint: str, kind: str, payload: dict[str, Any], **extra: Any) -> Any:
        return self.api.post(
            f"/api/v1/chokepoints/{chokepoint}/events",
            json={"kind": kind, "payload": payload} | extra,
        )

    def ok(self, chokepoint: str, kind: str, payload: dict[str, Any], **extra: Any) -> Any:
        response = self.event(chokepoint, kind, payload, **extra)
        assert response.status_code == 201, response.text
        return response.json()

    def step(self, status: str, step: str = "a", **evidence: list[str]) -> dict[str, Any]:
        return {"step": step, "status": status, "evidence": evidence}

    def refused(self, response: Any, status: int, code: str) -> dict[str, Any]:
        assert response.status_code == status, response.text
        error = response.json()["error"]
        assert error["code"] == code, error
        return error

    def events(self, chokepoint: str) -> int:
        return self.get(f"/api/v1/chokepoints/{chokepoint}")["event_count"]

    def actions(self, entity_id: str) -> list[str]:
        with self.engine.connect() as connection:
            return list(
                connection.execute(
                    text("SELECT action FROM audit_event WHERE entity_id = :id ORDER BY id"),
                    {"id": entity_id},
                ).scalars()
            )


@pytest.fixture
def board(database_url: str, tmp_path: Path) -> Iterator[Board]:
    harness = Board(database_url, tmp_path)
    yield harness
    harness.engine.dispose()


# --- the lifecycle ---


def test_a_chokepoint_is_born_a_lead_and_every_change_is_an_event_in_its_history(
    board: Board,
) -> None:
    created = board.create(
        holders=[{"name": "AXT Inc", "slug": "axt", "cik": "1051627"}, {"name": "Sumitomo"}]
    )
    chokepoint = created["id"]
    assert (created["status"], created["stale"], created["event_count"]) == ("lead", False, 1)
    assert [step["status"] for step in created["steps"]] == ["unexamined"] * 6
    assert [step["step"] for step in created["steps"]] == list("abcdef")
    assert (created["constraint"], created["layer"], created["theme"]) == (CONSTRAINT, LAYER, THEME)
    assert created["holders"] == [
        {"name": "AXT Inc", "slug": "axt", "cik": "1051627", "company_id": None},
        {"name": "Sumitomo", "slug": None, "cik": None, "company_id": None},
    ]
    assert [event["kind"] for event in created["history"]] == ["created"]
    assert created["history"][0]["actor"] == ACTOR

    fact, lead, issue = board.fact(), board.lead(), board.issue()
    board.clock.advance(hours=1)
    board.ok(
        chokepoint,
        "field_set",
        {
            "relief_horizon": {"horizon": "2028", "basis": "announced capacity adds"},
            "crowding": "early",
            "kill_criteria": ["a second qualified substrate vendor ships volume"],
            "issue_ids": [issue],
            "holders": [{"name": "AXT Inc", "slug": "axt"}],
        },
        reason="first pass",
    )
    board.clock.advance(hours=1)
    board.ok(chokepoint, "step_set", board.step("lead", "a", lead_ids=[lead]))
    board.ok(chokepoint, "step_set", board.step("lead", "b", issue_ids=[issue]))
    board.clock.advance(hours=1)
    board.ok(chokepoint, "step_set", board.step("primary", "a", fact_ids=[fact]))
    board.ok(chokepoint, "status_set", {"status": "candidate"}, reason="a is primary")
    board.ok(chokepoint, "note", {"text": "watch the Q1 call"})

    read = board.get(f"/api/v1/chokepoints/{chokepoint}")
    assert read["status"] == "candidate"
    assert read["status_reason"] == "a is primary"
    assert read["event_count"] == 7
    assert [event["kind"] for event in read["history"]] == [
        "created",
        "field_set",
        "step_set",
        "step_set",
        "step_set",
        "status_set",
        "note",
    ]
    steps = {step["step"]: step for step in read["steps"]}
    assert steps["a"]["status"] == "primary"  # the latest event for the step wins
    assert steps["a"]["evidence"]["fact_ids"] == [fact]
    assert steps["b"]["status"] == "lead" and steps["b"]["evidence"]["issue_ids"] == [issue]
    assert steps["c"]["status"] == "unexamined" and steps["c"]["set_at"] is None
    assert read["holders"] == [
        {"name": "AXT Inc", "slug": "axt", "cik": None, "company_id": None}
    ]  # replaced
    assert read["crowding"] == "early"
    assert read["relief_horizon"] == {"horizon": "2028", "basis": "announced capacity adds"}
    assert read["kill_criteria"] == ["a second qualified substrate vendor ships volume"]
    assert read["issue_ids"] == [issue]
    assert read["constraint"] == CONSTRAINT  # a field no event set again keeps its value
    assert read["history"][1]["reason"] == "first pass"
    assert read["last_event_at"] == read["history"][-1]["at"]
    assert board.actions(chokepoint) == ["chokepoint.created"] + ["chokepoint.updated"] * 6


def test_a_field_set_can_clear_the_relief_horizon_and_the_crowding(board: Board) -> None:
    chokepoint = board.create()["id"]
    board.ok(
        chokepoint,
        "field_set",
        {"crowding": "consensus", "relief_horizon": {"horizon": "2027", "basis": "a filing"}},
    )
    cleared = board.ok(chokepoint, "field_set", {"crowding": None, "relief_horizon": None})

    assert (cleared["crowding"], cleared["relief_horizon"]) == (None, None)
    for crowding in ("early", "emerging", "consensus"):
        assert board.ok(chokepoint, "field_set", {"crowding": crowding})["crowding"] == crowding


def test_the_board_lists_the_latest_event_first_and_filters_by_theme_and_status(
    board: Board,
) -> None:
    first = board.create()["id"]
    board.clock.advance(minutes=1)
    second = board.create(constraint="Cryogenic pumps", layer="equipment")["id"]
    board.clock.advance(minutes=1)
    other = board.create(theme="robotics", constraint="Harmonic reducers", layer="parts")["id"]
    board.clock.advance(minutes=1)
    board.ok(first, "note", {"text": "touched"})
    board.clock.advance(minutes=1)
    board.ok(second, "status_set", {"status": "killed"}, reason="a second source is shipping")

    assert [item["id"] for item in board.get("/api/v1/chokepoints")["items"]] == [
        second,
        first,
        other,
    ]
    listed = board.get("/api/v1/chokepoints", theme=THEME)
    assert listed["total"] == 2
    assert [item["id"] for item in listed["items"]] == [second, first]
    assert all("history" not in item for item in listed["items"])
    assert [i["id"] for i in board.get("/api/v1/chokepoints", theme="robotics")["items"]] == [other]
    killed = board.get("/api/v1/chokepoints", status="killed")["items"]
    assert [item["id"] for item in killed] == [second]  # a killed chokepoint stays listed
    assert board.get("/api/v1/chokepoints", status="lead")["total"] == 2
    assert board.get("/api/v1/chokepoints", status="thesis_ready")["total"] == 0
    assert board.api.get("/api/v1/chokepoints", params={"status": "nonsense"}).status_code == 422


def test_the_board_orders_by_the_latest_event(board: Board) -> None:
    older = board.create()["id"]
    board.clock.advance(hours=1)
    newer = board.create(constraint="Cryogenic pumps", layer="equipment")["id"]
    assert [i["id"] for i in board.get("/api/v1/chokepoints")["items"]] == [newer, older]

    board.clock.advance(hours=1)
    board.ok(older, "note", {"text": "back on top"})

    assert [i["id"] for i in board.get("/api/v1/chokepoints")["items"]] == [older, newer]
    assert board.get("/api/v1/chokepoints", limit=1)["items"][0]["id"] == older
    assert board.get("/api/v1/chokepoints", limit=1, offset=1)["items"][0]["id"] == newer


def test_an_unknown_chokepoint_is_not_found(board: Board) -> None:
    assert board.api.get(f"/api/v1/chokepoints/{NO_SUCH_ID}").status_code == 404
    response = board.event(NO_SUCH_ID, "note", {"text": "x"})
    board.refused(response, 404, "not_found")


# --- the validation ---


def test_a_primary_or_contradicted_step_cites_a_fact_and_a_lead_step_a_lead_or_an_issue(
    board: Board,
) -> None:
    chokepoint = board.create()["id"]
    lead, issue = board.lead(), board.issue()

    for status in ("primary", "contradicted"):
        board.refused(
            board.event(chokepoint, "step_set", board.step(status, lead_ids=[lead])),
            422,
            "step_needs_fact",
        )
        board.refused(
            board.event(chokepoint, "step_set", board.step(status)), 422, "step_needs_fact"
        )
    board.refused(
        board.event(chokepoint, "step_set", board.step("lead", fact_ids=[board.fact()])),
        422,
        "step_needs_lead",
    )
    board.refused(board.event(chokepoint, "step_set", board.step("lead")), 422, "step_needs_lead")
    assert board.events(chokepoint) == 1  # none of them wrote an event

    fact = board.fact()
    for status, evidence in (
        ("contradicted", {"fact_ids": [fact]}),
        ("lead", {"lead_ids": [lead]}),
        ("lead", {"issue_ids": [issue]}),
        ("unexamined", {}),
    ):
        stored = board.ok(chokepoint, "step_set", board.step(status, "a", **evidence))
        assert stored["steps"][0]["status"] == status


def test_what_a_step_cites_must_exist(board: Board) -> None:
    chokepoint = board.create()["id"]

    board.refused(
        board.event(chokepoint, "step_set", board.step("primary", fact_ids=[NO_SUCH_ID])),
        422,
        "unknown_fact",
    )
    board.refused(
        board.event(chokepoint, "step_set", board.step("lead", lead_ids=[NO_SUCH_ID])),
        422,
        "unknown_lead",
    )
    board.refused(
        board.event(chokepoint, "step_set", board.step("lead", issue_ids=[NO_SUCH_ID])),
        422,
        "unknown_issue",
    )
    board.refused(
        board.event(chokepoint, "field_set", {"issue_ids": [NO_SUCH_ID]}), 422, "unknown_issue"
    )
    assert board.events(chokepoint) == 1


def test_a_killed_chokepoint_needs_a_reason_and_stays_on_the_board(board: Board) -> None:
    chokepoint = board.create()["id"]

    board.refused(
        board.event(chokepoint, "status_set", {"status": "killed"}), 422, "reason_required"
    )
    board.refused(
        board.event(chokepoint, "status_set", {"status": "killed"}, reason="  "),
        422,
        "reason_required",
    )
    killed = board.ok(chokepoint, "status_set", {"status": "killed"}, reason="relief came early")

    assert (killed["status"], killed["status_reason"]) == ("killed", "relief came early")
    assert board.get("/api/v1/chokepoints", theme=THEME, status="killed")["total"] == 1
    assert board.get(f"/api/v1/chokepoints/{chokepoint}")["event_count"] == 2  # nothing deleted


@pytest.mark.parametrize(
    ("kind", "payload"),
    [
        ("field_set", {}),
        ("field_set", {"crowding": "hot"}),
        ("field_set", {"constraint": None}),
        ("field_set", {"constraint": "   "}),
        ("field_set", {"kill_criteria": [" "]}),
        ("field_set", {"kill_criteria": None}),
        ("field_set", {"relief_horizon": {"horizon": "2028"}}),
        ("field_set", {"holders": [{"name": "X", "cik": "not-a-cik"}]}),
        ("field_set", {"holders": [{"slug": "axt"}]}),
        ("field_set", {"stale": True}),
        ("step_set", {"step": "g", "status": "lead"}),
        ("step_set", {"step": "a", "status": "proven"}),
        ("step_set", {"status": "lead"}),
        ("status_set", {"status": "stale"}),
        ("status_set", {"status": "proven"}),
        ("status_set", {}),
        ("note", {"text": ""}),
        ("note", {"body": "x"}),
    ],
)
def test_a_payload_that_does_not_fit_its_kind_is_refused(
    board: Board, kind: str, payload: dict[str, Any]
) -> None:
    chokepoint = board.create()["id"]

    board.refused(board.event(chokepoint, kind, payload), 422, "invalid_payload")

    assert board.events(chokepoint) == 1
    assert board.actions(chokepoint) == ["chokepoint.created"]


def test_the_created_kind_is_not_written_by_hand_and_a_creation_is_checked(board: Board) -> None:
    chokepoint = board.create()["id"]

    assert board.event(chokepoint, "created", {}).status_code == 422
    assert board.event(chokepoint, "closed", {}).status_code == 422
    for bad in ({"constraint": ""}, {"layer": " "}, {"theme": ""}, {"holders": [{"name": ""}]}):
        response = board.api.post(
            "/api/v1/chokepoints",
            json={"theme": THEME, "constraint": CONSTRAINT, "layer": LAYER} | bad,
        )
        assert response.status_code == 422, bad
    assert board.get("/api/v1/chokepoints")["total"] == 1


def test_a_holder_may_be_outside_the_universe(board: Board) -> None:
    created = board.create(
        holders=[{"name": "Unlisted Wafer Co", "cik": "42"}, {"name": "Made-up GmbH"}]
    )

    assert [holder["slug"] for holder in created["holders"]] == [None, None]
    assert created["holders"][0]["cik"] == "42"
    updated = board.ok(
        created["id"], "field_set", {"holders": [{"name": "Somebody", "slug": "not-in-universe"}]}
    )
    assert updated["holders"] == [
        {"name": "Somebody", "slug": "not-in-universe", "cik": None, "company_id": None}
    ]


def test_a_fact_must_have_been_public_by_the_sessions_as_of_time(board: Board) -> None:
    board.clock.now = at(BEFORE_RELEASE)
    chokepoint = board.create()["id"]
    fact = board.fact()
    early = board.session()
    primary = board.step("primary", fact_ids=[fact])

    refusal = board.refused(
        board.event(chokepoint, "step_set", primary, session_id=early),
        422,
        "fact_available_after_as_of",
    )
    assert refusal["detail"]["fact"] == fact
    assert board.events(chokepoint) == 1

    board.clock.now = at(AFTER_RELEASE)
    later = board.session()
    stored = board.ok(chokepoint, "step_set", primary, session_id=later)
    assert stored["history"][-1]["session_id"] == later
    other = board.create()["id"]
    assert board.ok(other, "step_set", primary)["steps"][0]["status"] == "primary"  # no session


def test_a_session_must_exist_and_an_isolated_one_has_no_board(board: Board) -> None:
    chokepoint = board.create()["id"]
    isolated = board.session(isolated=True)

    board.refused(
        board.event(chokepoint, "note", {"text": "x"}, session_id=NO_SUCH_ID),
        422,
        "unknown_session",
    )
    board.refused(
        board.event(chokepoint, "note", {"text": "x"}, session_id=isolated), 422, "isolated_session"
    )
    response = board.api.post(
        "/api/v1/chokepoints",
        json={"theme": THEME, "constraint": CONSTRAINT, "layer": LAYER, "session_id": isolated},
    )
    board.refused(response, 422, "isolated_session")
    response = board.api.post(
        "/api/v1/chokepoints",
        json={"theme": THEME, "constraint": CONSTRAINT, "layer": LAYER, "run_id": NO_SUCH_ID},
    )
    board.refused(response, 422, "unknown_run")
    assert board.get("/api/v1/chokepoints")["total"] == 1


def test_a_session_that_creates_a_chokepoint_is_recorded_on_it(board: Board) -> None:
    session = board.session()

    created = board.create(session_id=session, actor="watch-agent")

    assert created["created_by_session"] == session
    assert created["history"][0]["session_id"] == session
    assert created["history"][0]["actor"] == "watch-agent"
    assert board.actions(created["id"]) == ["chokepoint.created"]


# --- thesis ready ---


def test_thesis_ready_needs_steps_a_b_and_d_primary_a_kill_criterion_and_an_open_issue(
    board: Board,
) -> None:
    chokepoint = board.create()["id"]
    fact = board.fact()

    def missing() -> list[str]:
        error = board.refused(
            board.event(chokepoint, "status_set", {"status": "thesis_ready"}),
            422,
            "thesis_not_ready",
        )
        return error["detail"]["missing"]

    assert missing() == [
        "step_a_primary",
        "step_b_primary",
        "step_d_primary",
        "kill_criteria",
        "open_issue",
    ]
    for step in ("a", "b"):
        board.ok(chokepoint, "step_set", board.step("primary", step, fact_ids=[fact]))
    board.ok(chokepoint, "step_set", board.step("lead", "d", lead_ids=[board.lead()]))
    assert missing() == ["step_d_primary", "kill_criteria", "open_issue"]  # a lead is not enough
    board.ok(chokepoint, "step_set", board.step("primary", "d", fact_ids=[fact]))
    board.ok(chokepoint, "field_set", {"kill_criteria": ["a second source ships"]})
    assert missing() == ["open_issue"]

    issue = board.issue()
    board.ok(chokepoint, "field_set", {"issue_ids": [issue]})
    assert (
        board.ok(chokepoint, "status_set", {"status": "thesis_ready"})["status"] == "thesis_ready"
    )
    assert board.get("/api/v1/chokepoints", status="thesis_ready")["total"] == 1


def test_a_linked_issue_must_be_open_for_thesis_ready(board: Board) -> None:
    chokepoint = board.create()["id"]
    fact, issue = board.fact(), board.issue()
    for step in ("a", "b", "d"):
        board.ok(chokepoint, "step_set", board.step("primary", step, fact_ids=[fact]))
    board.ok(chokepoint, "field_set", {"kill_criteria": ["x"], "issue_ids": [issue]})
    assert board.api.post(f"/api/v1/issues/{issue}/complete").status_code == 200

    error = board.refused(
        board.event(chokepoint, "status_set", {"status": "thesis_ready"}), 422, "thesis_not_ready"
    )
    assert error["detail"]["missing"] == ["open_issue"]

    board.ok(chokepoint, "field_set", {"issue_ids": [issue, board.issue("Another")]})
    assert (
        board.ok(chokepoint, "status_set", {"status": "thesis_ready"})["status"] == "thesis_ready"
    )


# --- stale is derived ---


def test_a_chokepoint_with_no_field_or_step_event_for_56_days_reads_stale(board: Board) -> None:
    chokepoint = board.create()["id"]

    board.clock.advance(days=55, hours=23)
    assert board.get(f"/api/v1/chokepoints/{chokepoint}")["stale"] is False
    assert board.get("/api/v1/chokepoints", status="stale")["total"] == 0

    board.clock.advance(hours=1)
    read = board.get(f"/api/v1/chokepoints/{chokepoint}")
    assert (read["stale"], read["status"]) == (True, "lead")  # derived, not stored
    assert [i["id"] for i in board.get("/api/v1/chokepoints", status="stale")["items"]] == [
        chokepoint
    ]
    assert board.get("/api/v1/chokepoints", status="lead")["total"] == 1
    assert board.get("/api/v1/chokepoints")["items"][0]["stale"] is True

    # A note and a status change are not evidence of anything: they do not end it.
    board.ok(chokepoint, "note", {"text": "still watching"})
    board.ok(chokepoint, "status_set", {"status": "candidate"})
    read = board.get(f"/api/v1/chokepoints/{chokepoint}")
    assert read["stale"] is True and read["last_event_at"] > read["last_evidence_at"]
    board.ok(chokepoint, "field_set", {"crowding": "early"})  # a field_set does
    assert board.get(f"/api/v1/chokepoints/{chokepoint}")["stale"] is False
    board.clock.advance(days=56)
    assert board.get(f"/api/v1/chokepoints/{chokepoint}")["stale"] is True
    board.ok(chokepoint, "step_set", board.step("lead", "a", issue_ids=[board.issue()]))  # a step
    assert board.get(f"/api/v1/chokepoints/{chokepoint}")["stale"] is False
    with board.engine.connect() as connection:  # nothing was stored for it
        statuses = connection.execute(
            text("SELECT DISTINCT payload FROM chokepoint_event WHERE kind = 'status_set'")
        ).all()
    assert [row[0] for row in statuses] == [{"status": "candidate"}]  # never "stale"


def test_a_killed_chokepoint_is_never_stale(board: Board) -> None:
    chokepoint = board.create()["id"]
    board.ok(chokepoint, "status_set", {"status": "killed"}, reason="gone")

    board.clock.advance(days=400)

    assert board.get(f"/api/v1/chokepoints/{chokepoint}")["stale"] is False


# --- insert-only ---


@pytest.mark.parametrize(
    ("table", "column", "value"),
    [
        ("chokepoint_event", "reason", "'rewritten'"),
        ("chokepoint", "theme", "'other'"),
        ("watch_run", "memo", "'rewritten'"),
    ],
)
def test_the_board_and_the_run_record_cannot_be_changed_or_deleted(
    board: Board, table: str, column: str, value: str
) -> None:
    chokepoint = board.create()["id"]
    board.ok(chokepoint, "note", {"text": "x"})
    board.api.post(
        "/api/v1/watch-runs",
        json={"theme": THEME, "run_date": "2026-10-18", "mode": "delta", "memo": "# quiet week"},
    )

    for statement in (f"UPDATE {table} SET {column} = {value}", f"DELETE FROM {table}"):
        with pytest.raises(DBAPIError), board.engine.begin() as connection:
            connection.execute(text(statement))
    with board.engine.connect() as connection:
        assert connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() >= 1


# --- the watch runs ---


def test_a_watch_run_is_recorded_listed_newest_first_and_read(board: Board) -> None:
    session = board.session()

    first = board.api.post(
        "/api/v1/watch-runs",
        json={
            "theme": THEME,
            "run_date": "2026-10-10",
            "mode": "architect",
            "memo": "# Architect\n\nDecomposed the industry.",
            "counts": {"discovered": 3, "rejected": 1},
            "tool_calls": 58,
            "session_id": session,
        },
    )
    assert first.status_code == 201, first.text
    board.clock.advance(days=7)
    second = board.api.post(
        "/api/v1/watch-runs",
        json={"theme": THEME, "run_date": "2026-10-17", "mode": "delta", "memo": "A quiet week."},
    )
    other = board.api.post(
        "/api/v1/watch-runs",
        json={"theme": "robotics", "run_date": "2026-10-18", "mode": "delta", "memo": "Robots."},
    )
    assert second.status_code == other.status_code == 201

    created = first.json()
    assert created["mode"] == "architect" and created["run_date"] == "2026-10-10"
    assert created["counts"] == {"discovered": 3, "rejected": 1}
    assert (created["tool_calls"], created["session_id"]) == (58, session)
    assert second.json()["counts"] == {} and second.json()["tool_calls"] == 0
    listed = board.get("/api/v1/watch-runs", theme=THEME)
    assert listed["total"] == 2
    assert [run["id"] for run in listed["items"]] == [second.json()["id"], created["id"]]
    assert board.get("/api/v1/watch-runs", limit=1)["items"][0]["id"] == other.json()["id"]
    assert board.get("/api/v1/watch-runs", theme="solar")["total"] == 0
    assert board.get(f"/api/v1/watch-runs/{created['id']}") == created
    assert board.api.get(f"/api/v1/watch-runs/{NO_SUCH_ID}").status_code == 404
    assert board.actions(created["id"]) == ["watch_run.created"]


def test_a_watch_run_without_a_tool_call_count_takes_its_sessions(board: Board) -> None:
    session = board.session()
    with board.engine.begin() as connection:
        for _ in range(3):
            connection.execute(
                text(
                    "INSERT INTO session_tool_call (id, session_id, tool, arguments, outcome)"
                    " VALUES (gen_random_uuid(), :s, 'board', '{}', 'ok')"
                ),
                {"s": session},
            )

    response = board.api.post(
        "/api/v1/watch-runs",
        json={
            "theme": THEME,
            "run_date": "2026-10-18",
            "mode": "delta",
            "memo": "m",
            "session_id": session,
        },
    )

    assert response.json()["tool_calls"] == 3


@pytest.mark.parametrize(
    "bad",
    [
        {"mode": "weekly"},
        {"memo": ""},
        {"memo": "  "},
        {"theme": ""},
        {"run_date": "yesterday"},
        {"tool_calls": -1},
        {"extra": 1},
    ],
)
def test_a_malformed_watch_run_is_refused(board: Board, bad: dict[str, Any]) -> None:
    body = {"theme": THEME, "run_date": "2026-10-18", "mode": "delta", "memo": "m"} | bad

    assert board.api.post("/api/v1/watch-runs", json=body).status_code == 422
    assert board.get("/api/v1/watch-runs")["total"] == 0


def test_an_isolated_session_writes_no_watch_run(board: Board) -> None:
    response = board.api.post(
        "/api/v1/watch-runs",
        json={
            "theme": THEME,
            "run_date": "2026-10-18",
            "mode": "delta",
            "memo": "m",
            "session_id": board.session(isolated=True),
        },
    )

    board.refused(response, 422, "isolated_session")


# --- review round: the gate, names, appends, the session's bounds ---


def ready(board: Board, chokepoint: str) -> tuple[str, str]:
    """Make the chokepoint's gate hold; the Fact and the open Issue it rests on."""
    fact, issue = board.fact(), board.issue()
    for step in ("a", "b", "d"):
        board.ok(chokepoint, "step_set", board.step("primary", step, fact_ids=[fact]))
    board.ok(chokepoint, "field_set", {"kill_criteria": ["x"], "issue_ids": [issue]})
    return fact, issue


def test_the_read_says_whether_the_thesis_gate_holds_and_names_the_steps(board: Board) -> None:
    chokepoint = board.create()["id"]

    read = board.get(f"/api/v1/chokepoints/{chokepoint}")
    assert read["thesis_gate"] == {
        "holds": False,
        "missing": [
            "step_a_primary",
            "step_b_primary",
            "step_d_primary",
            "kill_criteria",
            "open_issue",
        ],
    }
    assert read["needs_review"] is False
    assert [step["name"] for step in read["steps"]] == [
        "constraint",
        "demand_vs_supply",
        "relief",
        "control",
        "capture",
        "invalidation",
    ]
    ready(board, chokepoint)
    assert board.get(f"/api/v1/chokepoints/{chokepoint}")["thesis_gate"] == {
        "holds": True,
        "missing": [],
    }


def test_a_thesis_ready_chokepoint_whose_gate_stops_holding_needs_review(board: Board) -> None:
    chokepoint = board.create()["id"]
    _, issue = ready(board, chokepoint)
    board.ok(chokepoint, "status_set", {"status": "thesis_ready"})
    assert board.get("/api/v1/chokepoints", status="needs_review")["total"] == 0

    # The Issue is closed under it: the status stands, flagged.
    assert board.api.post(f"/api/v1/issues/{issue}/complete").status_code == 200
    read = board.get(f"/api/v1/chokepoints/{chokepoint}")
    assert (read["status"], read["needs_review"]) == ("thesis_ready", True)
    assert read["thesis_gate"] == {"holds": False, "missing": ["open_issue"]}
    flagged = board.get("/api/v1/chokepoints", status="needs_review")["items"]
    assert [item["id"] for item in flagged] == [chokepoint]
    assert board.get("/api/v1/chokepoints", status="thesis_ready")["total"] == 1


def test_steps_a_b_d_of_a_thesis_ready_chokepoint_stay_primary_until_the_status_moves_down(
    board: Board,
) -> None:
    chokepoint = board.create()["id"]
    fact, _ = ready(board, chokepoint)
    board.ok(chokepoint, "status_set", {"status": "thesis_ready"})
    before = board.events(chokepoint)

    for step in ("a", "b", "d"):
        for status in ("contradicted", "unexamined"):
            board.refused(
                board.event(chokepoint, "step_set", board.step(status, step, fact_ids=[fact])),
                422,
                "thesis_ready_step_locked",
            )
    assert board.events(chokepoint) == before
    # Other steps, and a primary step with other Facts, are free; so is a move down first.
    board.ok(chokepoint, "step_set", board.step("contradicted", "c", fact_ids=[fact]))
    board.ok(chokepoint, "step_set", board.step("primary", "a", fact_ids=[board.fact()]))
    board.ok(chokepoint, "status_set", {"status": "candidate"})
    moved = board.ok(chokepoint, "step_set", board.step("contradicted", "a", fact_ids=[fact]))
    assert moved["steps"][0]["status"] == "contradicted"
    assert moved["status"] == "candidate"


def test_a_step_is_named_by_letter_or_by_name(board: Board) -> None:
    chokepoint = board.create()["id"]
    issue = board.issue()
    names = ["constraint", "demand_vs_supply", "relief", "control", "capture", "invalidation"]

    stored: dict[str, Any] = {}
    for name in names:
        stored = board.ok(
            chokepoint,
            "step_set",
            {"step": name, "status": "lead", "evidence": {"issue_ids": [issue]}},
        )
    assert [each["status"] for each in stored["steps"]] == ["lead"] * 6
    assert stored["history"][-1]["payload"]["step"] == "f"  # stored by letter
    for bad in ("g", "moat"):
        board.refused(
            board.event(chokepoint, "step_set", {"step": bad, "status": "lead"}),
            422,
            "invalid_payload",
        )


def test_a_list_replaces_the_whole_list_and_an_add_appends(board: Board) -> None:
    chokepoint = board.create()["id"]
    one, two, three = board.issue("one"), board.issue("two"), board.issue("three")
    fact, other_fact, lead = board.fact(), board.fact(), board.lead()

    board.ok(chokepoint, "field_set", {"issue_ids": [one], "kill_criteria": ["a", "b"]})
    board.ok(chokepoint, "field_set", {"add_issue_ids": [two, one]})
    appended = board.ok(chokepoint, "field_set", {"add_issue_ids": [three]})
    assert appended["issue_ids"] == [one, two, three]  # no repeats, in order
    replaced = board.ok(chokepoint, "field_set", {"issue_ids": [three], "kill_criteria": ["c"]})
    assert (replaced["issue_ids"], replaced["kill_criteria"]) == ([three], ["c"])
    board.refused(
        board.event(chokepoint, "field_set", {"issue_ids": [one], "add_issue_ids": [two]}),
        422,
        "invalid_payload",
    )
    unknown = board.event(chokepoint, "field_set", {"add_issue_ids": [NO_SUCH_ID]})
    board.refused(unknown, 422, "unknown_issue")

    board.ok(chokepoint, "step_set", board.step("primary", "a", fact_ids=[fact]))
    added = board.ok(
        chokepoint,
        "step_set",
        {
            "step": "a",
            "status": "primary",
            "add_evidence": {"fact_ids": [other_fact, fact], "lead_ids": [lead]},
        },
    )
    assert added["steps"][0]["evidence"] == {
        "fact_ids": [fact, other_fact],
        "lead_ids": [lead],
        "issue_ids": [],
    }
    swapped = board.ok(chokepoint, "step_set", board.step("primary", "a", fact_ids=[other_fact]))
    assert swapped["steps"][0]["evidence"]["fact_ids"] == [other_fact]
    assert swapped["steps"][0]["evidence"]["lead_ids"] == []  # evidence replaced the lot
    # What an add leaves a step with must still satisfy its status; replace and add don't mix.
    only_a_lead = {"step": "b", "status": "primary", "add_evidence": {"lead_ids": [lead]}}
    board.refused(board.event(chokepoint, "step_set", only_a_lead), 422, "step_needs_fact")
    both = {
        "step": "b",
        "status": "primary",
        "evidence": {"fact_ids": [fact]},
        "add_evidence": {"fact_ids": [fact]},
    }
    board.refused(board.event(chokepoint, "step_set", both), 422, "invalid_payload")


def test_a_fact_an_isolated_session_recorded_is_not_citable(board: Board) -> None:
    chokepoint = board.create()["id"]
    fact = board.fact(board.session(isolated=True))

    board.refused(
        board.event(chokepoint, "step_set", board.step("primary", fact_ids=[fact])),
        422,
        "fact_not_in_session",
    )
    assert board.events(chokepoint) == 1


def test_the_board_is_prospective_a_session_older_than_36_hours_is_refused(board: Board) -> None:
    chokepoint = board.create()["id"]
    replay = board.session((board.clock.now - timedelta(hours=37)).isoformat())
    fresh = board.session((board.clock.now - timedelta(hours=35)).isoformat())
    note = {"text": "x"}
    run = {"theme": THEME, "run_date": "2026-10-17", "mode": "delta", "memo": "m"}
    new = {"theme": THEME, "constraint": CONSTRAINT, "layer": LAYER}

    board.refused(board.event(chokepoint, "note", note, session_id=replay), 422, "not_prospective")
    posted = board.api.post("/api/v1/chokepoints", json=new | {"session_id": replay})
    board.refused(posted, 422, "not_prospective")
    posted = board.api.post("/api/v1/watch-runs", json=run | {"session_id": replay})
    board.refused(posted, 422, "not_prospective")
    for path in ("/api/v1/chokepoints", f"/api/v1/chokepoints/{chokepoint}", "/api/v1/watch-runs"):
        board.refused(board.api.get(path, params={"session_id": replay}), 422, "not_prospective")
        assert board.api.get(path, params={"session_id": fresh}).status_code == 200
    assert board.ok(chokepoint, "note", note, session_id=fresh)["event_count"] == 2


def test_a_closed_session_is_refused_on_the_routes(board: Board) -> None:
    chokepoint = board.create()["id"]
    session = board.session()
    assert board.api.post(f"/api/v1/sessions/{session}/close", json={}).status_code == 200

    sent = board.event(chokepoint, "note", {"text": "x"}, session_id=session)
    board.refused(sent, 422, "session_closed")
    read = board.api.get("/api/v1/chokepoints", params={"session_id": session})
    board.refused(read, 422, "session_closed")


def test_a_session_writes_only_to_its_own_theme_and_cites_only_that_themes_issues(
    board: Board,
) -> None:
    chokepoint = board.create()["id"]
    robotics, session = board.session(theme="robotics"), board.session()
    new = {"theme": THEME, "constraint": CONSTRAINT, "layer": LAYER}

    sent = board.event(chokepoint, "note", {"text": "x"}, session_id=robotics)
    board.refused(sent, 422, "other_theme")
    posted = board.api.post("/api/v1/chokepoints", json=new | {"session_id": robotics})
    board.refused(posted, 422, "other_theme")
    foreign = board.issue("Robots", theme="robotics")
    sent = board.event(chokepoint, "field_set", {"issue_ids": [foreign]}, session_id=session)
    board.refused(sent, 422, "other_theme")
    # With no session too: an Issue of another theme is not linked to this one's chokepoint.
    sent = board.event(chokepoint, "step_set", board.step("lead", issue_ids=[foreign]))
    board.refused(sent, 422, "other_theme")
    assert board.events(chokepoint) == 1


def test_a_session_cites_only_what_existed_by_its_as_of_time_unless_it_made_it(
    board: Board,
) -> None:
    board.clock.now = at("2026-01-05T00:00:00+00:00")  # before any Issue the database stamps now
    chokepoint = board.create()["id"]
    session = board.session()
    soon = (board.clock.now + timedelta(hours=1)).isoformat()
    future_lead = board.lead(first_seen_at=soon)
    # An Issue is stamped by the database's clock, which is after the session's as-of time.
    elsewhere = board.issue("Opened by nobody's session")
    own = board.issue("Opened by this session", produced_by=session)

    sent = board.event(
        chokepoint, "step_set", board.step("lead", lead_ids=[future_lead]), session_id=session
    )
    board.refused(sent, 422, "created_after_as_of")
    sent = board.event(chokepoint, "field_set", {"issue_ids": [elsewhere]}, session_id=session)
    board.refused(sent, 422, "created_after_as_of")
    linked = board.ok(chokepoint, "field_set", {"add_issue_ids": [own]}, session_id=session)
    assert linked["issue_ids"] == [own]
    past_lead = board.lead(first_seen_at=(board.clock.now - timedelta(hours=1)).isoformat())
    board.ok(chokepoint, "step_set", board.step("lead", lead_ids=[past_lead]), session_id=session)


def test_a_sessions_actor_is_the_events_unless_one_is_given(board: Board) -> None:
    session = board.session()

    created = board.create(session_id=session)
    assert created["history"][0]["actor"] == "claude-session"
    noted = board.ok(created["id"], "note", {"text": "x"}, session_id=session)
    assert noted["history"][-1]["actor"] == "claude-session"
    named = board.ok(created["id"], "note", {"text": "y"}, session_id=session, actor="someone")
    assert named["history"][-1]["actor"] == "someone"
    assert board.ok(created["id"], "note", {"text": "z"})["history"][-1]["actor"] == ACTOR


@pytest.mark.parametrize(
    "theme", ["Photonics", "1photonics", "a", "has space", "x" * 42, "under_score", ""]
)
def test_a_theme_is_a_slug(board: Board, theme: str) -> None:
    created = board.api.post(
        "/api/v1/chokepoints", json={"theme": theme, "constraint": CONSTRAINT, "layer": LAYER}
    )
    run = {"run_date": "2026-10-18", "mode": "delta", "memo": "m"}
    posted = board.api.post("/api/v1/watch-runs", json={"theme": theme} | run)

    assert (created.status_code, posted.status_code) == (422, 422)
    inserts = (  # and the database says so too
        "INSERT INTO chokepoint (id, theme, created_at) VALUES (gen_random_uuid(), :t, now())",
        "INSERT INTO watch_run (id, theme, run_date, mode, memo, created_at)"
        " VALUES (gen_random_uuid(), :t, '2026-10-18', 'delta', 'm', now())",
    )
    for insert in inserts:
        with pytest.raises(DBAPIError), board.engine.begin() as connection:
            connection.execute(text(insert), {"t": theme})


def test_a_watch_run_keeps_its_cost_and_tokens(board: Board) -> None:
    run = {"theme": THEME, "run_date": "2026-10-18", "mode": "delta", "memo": "m"}
    created = board.api.post("/api/v1/watch-runs", json=run | {"cost_usd": 1.25, "tokens": 480_000})
    plain = board.api.post("/api/v1/watch-runs", json=run)

    assert (created.json()["cost_usd"], created.json()["tokens"]) == (1.25, 480_000)
    assert (plain.json()["cost_usd"], plain.json()["tokens"]) == (None, None)
    assert board.get(f"/api/v1/watch-runs/{created.json()['id']}")["cost_usd"] == 1.25
    for bad in ({"cost_usd": -1}, {"tokens": -1}):
        assert board.api.post("/api/v1/watch-runs", json=run | bad).status_code == 422


def test_the_tables_refuse_truncate(board: Board) -> None:
    board.create()
    run = {"theme": THEME, "run_date": "2026-10-18", "mode": "delta", "memo": "m"}
    board.api.post("/api/v1/watch-runs", json=run)

    for table in ("chokepoint_event", "chokepoint", "watch_run"):
        with pytest.raises(DBAPIError), board.engine.begin() as connection:
            connection.execute(text(f"TRUNCATE {table} CASCADE"))


# --- the reads for the owner's pages (W8) ---


def count_statements(board: Board, path: str) -> int:
    """How many SQL statements one GET of the path runs."""
    seen: list[str] = []

    def record(*args: Any) -> None:
        seen.append(args[2])

    event.listen(Engine, "before_cursor_execute", record)
    try:
        board.get(path)
    finally:
        event.remove(Engine, "before_cursor_execute", record)
    return len(seen)


def test_a_read_resolves_every_fact_lead_and_issue_the_current_state_cites(board: Board) -> None:
    company = next(c for c in board.get("/api/v1/companies")["items"] if c["slug"] == "lumentum")
    fact, lead, issue = board.fact(), board.lead(published="2026-09-01"), board.issue()
    linked = board.issue("Who else makes InP?")
    chokepoint = board.create()["id"]
    board.ok(chokepoint, "field_set", {"issue_ids": [linked]})
    board.ok(chokepoint, "step_set", board.step("primary", "a", fact_ids=[fact]))
    board.ok(chokepoint, "step_set", board.step("primary", "b", fact_ids=[fact]))  # the same Fact
    board.ok(chokepoint, "step_set", board.step("lead", "c", lead_ids=[lead], issue_ids=[issue]))
    board.ok(chokepoint, "step_set", board.step("lead", "d", issue_ids=[linked]))  # linked too
    version = board.get(f"/api/v1/facts/{fact}")["assertion"]["source_version_id"]
    documents = board.get(f"/api/v1/companies/{company['id']}/sources", limit=100)["items"]
    title = next(d["title"] for d in documents if d["latest_version_id"] == version)

    read = board.get(f"/api/v1/chokepoints/{chokepoint}")

    # The step evidence and the linked Issues stay as they were: ids.
    assert [step["evidence"]["fact_ids"] for step in read["steps"][:2]] == [[fact], [fact]]
    assert read["issue_ids"] == [linked]
    # Each cited Fact once, with what the page shows.
    assert read["facts"] == [
        {
            "id": fact,
            "assertion_id": fact,
            "statement": "Lumentum's fourth-quarter fiscal 2026 net revenue was $1.01 billion.",
            "quote": REVENUE_QUOTE,
            "company_name": company["display_name"],
            "document_title": title,
            "available_at": read["facts"][0]["available_at"],
            "source_version_id": version,
        }
    ]
    assert read["facts"][0]["available_at"].startswith("2026-08-11")
    assert read["leads"] == [
        {
            "id": lead,
            "title": "InP wafer lead times",
            "url": "https://example.test/a",
            "origin": "tradingview_news",
            "published_at": "2026-09-01",
        }
    ]
    # The Issues: those the steps cite and those linked, once each.
    assert {each["id"]: each for each in read["issues"]} == {
        issue: {"id": issue, "title": "Is InP the constraint?", "status": "active"},
        linked: {"id": linked, "title": "Who else makes InP?", "status": "active"},
    }
    assert len(read["issues"]) == 2
    # The board's list stays light: no resolved evidence.
    (listed,) = board.get("/api/v1/chokepoints")["items"]
    assert not {"facts", "leads", "issues", "history"} & set(listed)


def test_evidence_is_resolved_in_a_fixed_number_of_queries(board: Board) -> None:
    few = board.create()["id"]
    board.ok(few, "step_set", board.step("primary", "a", fact_ids=[board.fact()]))
    many = board.create(constraint="Cryogenic pumps", layer="equipment")["id"]
    for step in "abc":
        board.ok(many, "step_set", board.step("primary", step, fact_ids=[board.fact()]))
    for step in "def":
        board.ok(
            many,
            "step_set",
            board.step("lead", step, lead_ids=[board.lead()], issue_ids=[board.issue()]),
        )

    one = count_statements(board, f"/api/v1/chokepoints/{few}")
    lots = count_statements(board, f"/api/v1/chokepoints/{many}")

    assert one > 0 and lots == one + 2  # the leads and the Issues each cost one more statement
    assert len(board.get(f"/api/v1/chokepoints/{many}")["facts"]) == 3


def test_a_chokepoint_with_no_evidence_reads_empty_lists(board: Board) -> None:
    read = board.get(f"/api/v1/chokepoints/{board.create()['id']}")

    assert (read["facts"], read["leads"], read["issues"]) == ([], [], [])


def test_a_holder_gains_the_company_id_its_slug_or_cik_resolves_to(board: Board) -> None:
    lumentum = board.company_id()
    created = board.create(
        holders=[
            {"name": "Lumentum Holdings", "slug": "lumentum"},
            {"name": "Lumentum by CIK", "cik": "1633978"},  # 0001633978, unpadded
            {"name": "A slug that names nobody", "slug": "no-such-company", "cik": "1633978"},
            {"name": "Sumitomo Electric"},
            {"name": "Unknown", "slug": "no-such-company", "cik": "9999999999"},
        ]
    )

    expected = [
        {"name": "Lumentum Holdings", "slug": "lumentum", "cik": None, "company_id": lumentum},
        {"name": "Lumentum by CIK", "slug": None, "cik": "1633978", "company_id": lumentum},
        {
            "name": "A slug that names nobody",
            "slug": "no-such-company",
            "cik": "1633978",
            "company_id": lumentum,
        },
        {"name": "Sumitomo Electric", "slug": None, "cik": None, "company_id": None},
        {"name": "Unknown", "slug": "no-such-company", "cik": "9999999999", "company_id": None},
    ]
    assert created["holders"] == expected
    assert board.get(f"/api/v1/chokepoints/{created['id']}")["holders"] == expected
    (listed,) = board.get("/api/v1/chokepoints")["items"]
    assert listed["holders"] == expected
    # Resolution is a read: the event keeps what was written.
    assert created["history"][0]["payload"]["holders"][0] == {
        "name": "Lumentum Holdings",
        "slug": "lumentum",
        "cik": None,
    }


def test_status_set_at_is_the_last_status_event_else_the_creation(board: Board) -> None:
    created = board.create()
    chokepoint = created["id"]
    born = created["created_at"]
    assert created["status_set_at"] == born

    board.clock.advance(hours=1)
    board.ok(chokepoint, "note", {"text": "a note is not a status"})
    board.ok(chokepoint, "field_set", {"crowding": "early"})
    assert board.get(f"/api/v1/chokepoints/{chokepoint}")["status_set_at"] == born

    board.clock.advance(hours=1)
    candidate = board.ok(chokepoint, "status_set", {"status": "candidate"})["history"][-1]["at"]
    board.clock.advance(hours=1)
    board.ok(chokepoint, "step_set", board.step("lead", "a", lead_ids=[board.lead()]))
    read = board.get(f"/api/v1/chokepoints/{chokepoint}")
    assert read["status_set_at"] == candidate
    assert read["last_event_at"] != candidate
    assert board.get("/api/v1/chokepoints")["items"][0]["status_set_at"] == candidate

    board.clock.advance(hours=1)
    board.ok(chokepoint, "status_set", {"status": "killed"}, reason="a second source ships")
    again = board.get(f"/api/v1/chokepoints/{chokepoint}")
    assert again["status_set_at"] == again["last_event_at"] != candidate


def test_the_board_counts_each_status_and_the_two_derived_flags(board: Board) -> None:
    board.create()  # lead
    board.create(constraint="b", layer=LAYER)  # lead
    killed = board.create(constraint="c", layer=LAYER)["id"]
    board.ok(killed, "status_set", {"status": "killed"}, reason="no longer true")
    candidate = board.create(constraint="d", layer=LAYER)["id"]
    board.ok(candidate, "status_set", {"status": "candidate"})
    other = board.create(theme="robotics", constraint="Harmonic reducers", layer="parts")["id"]
    board.ok(other, "status_set", {"status": "candidate"})
    board.clock.advance(days=60)  # what is not killed is now stale
    board.create(constraint="e", layer=LAYER)  # a lead, just made
    ready = board.create(constraint="f", layer=LAYER)["id"]
    fact, issue = board.fact(), board.issue()
    for step in "abd":
        board.ok(ready, "step_set", board.step("primary", step, fact_ids=[fact]))
    board.ok(ready, "field_set", {"kill_criteria": ["a second vendor ships"], "issue_ids": [issue]})
    board.ok(ready, "status_set", {"status": "thesis_ready"})
    assert board.get(f"/api/v1/chokepoints/{ready}")["needs_review"] is False
    assert board.api.post(f"/api/v1/issues/{issue}/abandon").status_code == 200

    everywhere = board.get("/api/v1/chokepoints/counts")
    photonics = board.get("/api/v1/chokepoints/counts", theme=THEME)

    # The same numbers as the list's own filters give, whichever way it is asked.
    for counts, scope in ((everywhere, {}), (photonics, {"theme": THEME})):
        assert set(counts) == {
            "lead",
            "candidate",
            "thesis_ready",
            "killed",
            "stale",
            "needs_review",
        }
        for status, number in counts.items():
            assert board.get("/api/v1/chokepoints", status=status, **scope)["total"] == number
    # Six photonics chokepoints: three leads, a candidate, a killed one and a thesis_ready one
    # whose open Issue was abandoned. The three older ones (not the killed) are stale.
    assert photonics == {
        "lead": 3,
        "candidate": 1,
        "thesis_ready": 1,
        "killed": 1,
        "stale": 3,
        "needs_review": 1,
    }
    assert everywhere["candidate"] == 2 and everywhere["stale"] == 4
    assert board.get("/api/v1/chokepoints/counts", theme="no-such-theme") == dict.fromkeys(
        photonics, 0
    )


def test_a_theme_in_the_list_carries_its_board_counts(board: Board) -> None:
    first = board.create()["id"]
    board.create(constraint="b", layer=LAYER)
    board.ok(first, "status_set", {"status": "candidate"})
    board.create(theme="memory-packaging", constraint="HBM base dies", layer="logic")

    themes = {each["id"]: each for each in board.get("/api/v1/themes")}

    zero = dict.fromkeys(
        ("lead", "candidate", "thesis_ready", "killed", "stale", "needs_review"), 0
    )
    assert themes["photonics"]["board"] == board.get("/api/v1/chokepoints/counts", theme=THEME)
    assert themes["photonics"]["board"] == zero | {"lead": 1, "candidate": 1}
    assert themes["memory-packaging"]["board"] == zero | {"lead": 1}
    mapped = board.get("/api/v1/themes/photonics/map", include="theme")["theme"]
    assert mapped["board"] == themes["photonics"]["board"]
