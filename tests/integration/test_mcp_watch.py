"""The Chokepoint Watch's MCP tools (Chokepoint Watch ticket W1): `board`, `get_chokepoint`,
`add_chokepoint`, `update_chokepoint` and `write_memo`.

Seam: `POST /mcp` (JSON-RPC over the TestClient) on a fresh database holding Lumentum's recorded
Q4 FY26 press release (public on 11 August 2026). The tools call the `/api/v1` routes in process,
so what is tested is the tools' shape, that the routes' rules come back as refusals, and the
frozen surface (ticket 29): every tool refuses an isolated session before doing anything.
"""

import json
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from atlas.api.app import create_app
from atlas.audit import Actor
from atlas.jobs import JobQueue, Worker, builtin_registry
from atlas.ledger.ingest import INGEST_KIND, ingest_payload
from tests.harness import EDGAR_FIXTURES, THEMES, Clock, at, make_settings

URL_EX991 = (
    "https://www.sec.gov/Archives/edgar/data/1633978/000162828026055726/lite_ex991xq4fy26.htm"
)
ACTOR = "mcp-watch-test-owner"
REVENUE_QUOTE = "Net revenue for the fourth quarter of fiscal year 2026 was $1.01 billion"
REVENUE_SPAN = (1604, 1676)
QUESTION = "Where will demand outrun qualified supply next?"
START = "2026-10-18T09:00:00+00:00"
BEFORE_RELEASE = "2026-08-01T12:00:00+00:00"  # the press release became public on 11 August
WATCH_TOOLS = ("board", "get_chokepoint", "add_chokepoint", "update_chokepoint", "write_memo")
NO_SUCH_ID = "00000000-0000-0000-0000-000000000000"


class Mcp:
    def __init__(self, database_url: str, tmp_path: Path) -> None:
        archive = tmp_path / "archive"
        archive.mkdir(exist_ok=True)
        self.engine = create_engine(database_url)
        settings = make_settings(
            archive,
            database_url=database_url,
            actor=ACTOR,
            themes_config=THEMES,
            sec_fixtures_dir=EDGAR_FIXTURES,
        )
        queue = JobQueue(self.engine, actor=Actor(ACTOR))
        queue.enqueue(INGEST_KIND, "lumentum", ingest_payload("lumentum", ["8-K"], None))
        assert Worker(queue, builtin_registry(settings)).run_once() == 1
        self.clock = Clock(at(START))  # the board is prospective: sessions are of this clock
        self.api = TestClient(create_app(settings, clock=self.clock))
        self.requests = 0

    def rpc(self, method: str, params: dict[str, Any] | None = None) -> Any:
        self.requests += 1
        return self.api.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": self.requests, "method": method, "params": params or {}},
        )

    def call(self, tool: str, **arguments: Any) -> tuple[bool, dict[str, Any]]:
        response = self.rpc("tools/call", {"name": tool, "arguments": arguments})
        assert response.status_code == 200, response.text
        result = response.json()["result"]
        value = json.loads(result["content"][0]["text"])
        assert result["structuredContent"] == value
        return result["isError"], value

    def ok(self, tool: str, **arguments: Any) -> dict[str, Any]:
        is_error, value = self.call(tool, **arguments)
        assert not is_error, value
        return value

    def refused(self, tool: str, code: str, **arguments: Any) -> dict[str, Any]:
        is_error, value = self.call(tool, **arguments)
        assert is_error, value
        assert value.get("refused") == code, value
        return value

    def open(self, as_of: str | None = None, **extra: Any) -> str:
        return self.ok(
            "open_session",
            question=QUESTION,
            as_of=as_of or self.clock.now.isoformat(),
            theme="photonics",
            model="claude-fable-5-1",
            actor="watch-agent",
            **extra,
        )["session_id"]

    def get(self, path: str, **params: Any) -> Any:
        response = self.api.get(path, params=params)
        assert response.status_code == 200, response.text
        return response.json()

    def fact(self) -> str:
        company = next(
            c["id"] for c in self.get("/api/v1/companies")["items"] if c["slug"] == "lumentum"
        )
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
            },
        )
        assert response.status_code == 201, response.text
        return response.json()["fact"]["id"]

    def calls(self, session: str) -> list[tuple[str, str, str | None]]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT tool, outcome, reason FROM session_tool_call"
                    " WHERE session_id = :id ORDER BY created_at, id"
                ),
                {"id": session},
            ).all()
        return [(row.tool, row.outcome, row.reason) for row in rows]


@pytest.fixture
def mcp(database_url: str, tmp_path: Path) -> Iterator[Mcp]:
    harness = Mcp(database_url, tmp_path)
    yield harness
    harness.engine.dispose()


def test_the_watch_tools_are_listed_with_a_required_session(mcp: Mcp) -> None:
    listed = {each["name"]: each for each in mcp.rpc("tools/list").json()["result"]["tools"]}

    for name in WATCH_TOOLS:
        schema = listed[name]["inputSchema"]
        assert listed[name]["description"]
        assert "session_id" in schema["required"], name
        assert schema["additionalProperties"] is False
        assert "as_of" not in schema["properties"]  # the session's, never an argument
    assert set(listed["update_chokepoint"]["inputSchema"]["required"]) == {
        "session_id",
        "id",
        "kind",
        "payload",
    }


def test_a_session_adds_a_chokepoint_updates_it_and_reads_the_board(mcp: Mcp) -> None:
    session = mcp.open()
    fact = mcp.fact()

    empty = mcp.ok("board", session_id=session)
    assert (empty["theme"], empty["total"], empty["chokepoints"], empty["last_memo"]) == (
        "photonics",
        0,
        [],
        None,
    )

    added = mcp.ok(
        "add_chokepoint",
        session_id=session,
        constraint="Indium phosphide substrates",
        layer="materials",
        holders=[{"name": "AXT Inc", "slug": "axt"}, {"name": "Sumitomo Electric"}],
    )
    chokepoint = added["id"]
    assert (added["created"], added["status"], added["stale"]) == (True, "lead", False)
    assert added["steps"] == dict.fromkeys("abcdef", "unexamined")

    mcp.ok(
        "update_chokepoint",
        session_id=session,
        id=chokepoint,
        kind="field_set",
        payload={"crowding": "early", "kill_criteria": ["a second vendor ships"]},
        reason="first look",
    )
    updated = mcp.ok(
        "update_chokepoint",
        session_id=session,
        id=chokepoint,
        kind="step_set",
        payload={"step": "a", "status": "primary", "evidence": {"fact_ids": [fact]}},
    )
    assert (updated["updated"], updated["events"], updated["steps"]["a"]) == (True, 3, "primary")

    on_board = mcp.ok("board", session_id=session)
    assert on_board["total"] == 1
    line = on_board["chokepoints"][0]
    assert (line["id"], line["crowding"], line["steps"]["a"]) == (chokepoint, "early", "primary")
    assert line["kill_criteria"] == ["a second vendor ships"]
    assert "never evidence" in on_board["note"]

    full = mcp.ok("get_chokepoint", session_id=session, id=chokepoint)
    assert [event["kind"] for event in full["history"]] == ["created", "field_set", "step_set"]
    assert {event["session_id"] for event in full["history"]} == {session}
    assert full["history"][1]["reason"] == "first look"
    assert full["created_by_session"] == session
    assert mcp.ok("board", session_id=session, status="killed")["total"] == 0
    assert mcp.ok("board", session_id=session, theme="robotics")["total"] == 0


def test_a_route_rule_comes_back_as_a_refusal_with_its_code_and_detail(mcp: Mcp) -> None:
    mcp.clock.now = at(BEFORE_RELEASE)
    early = mcp.open()
    chokepoint = mcp.ok("add_chokepoint", session_id=early, constraint="c", layer="l")["id"]
    fact = mcp.fact()

    mcp.refused(
        "update_chokepoint",
        "step_needs_fact",
        session_id=early,
        id=chokepoint,
        kind="step_set",
        payload={"step": "a", "status": "primary"},
    )
    later = mcp.refused(
        "update_chokepoint",
        "fact_available_after_as_of",
        session_id=early,
        id=chokepoint,
        kind="step_set",
        payload={"step": "a", "status": "primary", "evidence": {"fact_ids": [fact]}},
    )
    assert later["fact"] == fact
    mcp.refused(
        "update_chokepoint",
        "reason_required",
        session_id=early,
        id=chokepoint,
        kind="status_set",
        payload={"status": "killed"},
    )
    gate = mcp.refused(
        "update_chokepoint",
        "thesis_not_ready",
        session_id=early,
        id=chokepoint,
        kind="status_set",
        payload={"status": "thesis_ready"},
    )
    assert gate["missing"] == [
        "step_a_primary",
        "step_b_primary",
        "step_d_primary",
        "kill_criteria",
        "open_issue",
    ]
    mcp.refused(
        "update_chokepoint",
        "invalid_payload",
        session_id=early,
        id=chokepoint,
        kind="field_set",
        payload={"crowding": "hot"},
    )
    mcp.refused("get_chokepoint", "not_found", session_id=early, id=NO_SUCH_ID)
    mcp.refused(
        "update_chokepoint",
        "invalid_arguments",
        session_id=early,
        id=chokepoint,
        kind="created",
        payload={},
    )
    assert mcp.ok("get_chokepoint", session_id=early, id=chokepoint)["event_count"] == 1
    assert [outcome for _, outcome, _ in mcp.calls(early)[-4:]] == ["refused"] * 3 + ["ok"]


def test_a_memo_is_recorded_for_the_sessions_theme_on_its_as_of_day_and_board_returns_it(
    mcp: Mcp,
) -> None:
    session = mcp.open("2026-10-17T22:30:00-04:00")  # 2026-10-18 02:30 UTC
    mcp.ok("board", session_id=session)
    mcp.ok("add_chokepoint", session_id=session, constraint="c", layer="l")

    written = mcp.ok(
        "write_memo",
        session_id=session,
        mode="architect",
        memo="# Week 1\n\nDecomposed the industry.",
        counts={"discovered": 2},
    )

    assert written["recorded"] is True and written["run_date"] == "2026-10-18"
    assert written["tool_calls"] == 3  # open_session, board and add_chokepoint, counted by then
    run = mcp.get(f"/api/v1/watch-runs/{written['watch_run_id']}")
    assert (run["theme"], run["mode"], run["session_id"]) == ("photonics", "architect", session)
    assert run["memo"].startswith("# Week 1") and run["counts"] == {"discovered": 2}

    next_week = mcp.open()
    last = mcp.ok("board", session_id=next_week)["last_memo"]
    assert (last["run_date"], last["mode"], last["counts"]) == (
        "2026-10-18",
        "architect",
        {"discovered": 2},
    )
    assert last["memo"].startswith("# Week 1")
    mcp.refused("write_memo", "invalid_arguments", session_id=session, mode="weekly", memo="m")
    mcp.refused("write_memo", "invalid_arguments", session_id=session, mode="delta")


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("board", {}),
        ("get_chokepoint", {"id": NO_SUCH_ID}),
        ("add_chokepoint", {"constraint": "c", "layer": "l"}),
        (
            "update_chokepoint",
            {"id": NO_SUCH_ID, "kind": "note", "payload": {"text": "x"}},
        ),
        ("write_memo", {"mode": "delta", "memo": "m"}),
    ],
)
def test_an_isolated_session_is_refused_every_watch_tool_before_anything_is_called(
    mcp: Mcp, tool: str, arguments: dict[str, Any]
) -> None:
    isolated = mcp.open(isolated=True)

    refusal = mcp.refused(tool, "isolated_session", session_id=isolated, **arguments)

    assert tool in refusal["message"]
    assert mcp.calls(isolated)[1:] == [(tool, "refused", "isolated_session")]  # after open_session
    assert mcp.get("/api/v1/chokepoints")["total"] == 0
    assert mcp.get("/api/v1/watch-runs")["total"] == 0


def test_a_closed_or_unknown_session_is_refused_the_watch_tools(mcp: Mcp) -> None:
    session = mcp.open()
    mcp.ok("close_session", session_id=session)

    mcp.refused("board", "session_closed", session_id=session)
    mcp.refused("board", "unknown_session", session_id=NO_SUCH_ID)


# --- review round ---


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("board", {}),
        ("get_chokepoint", {"id": NO_SUCH_ID}),
        ("add_chokepoint", {"constraint": "c", "layer": "l"}),
        ("update_chokepoint", {"id": NO_SUCH_ID, "kind": "note", "payload": {"text": "x"}}),
        ("write_memo", {"mode": "delta", "memo": "m"}),
    ],
)
def test_a_replay_session_is_refused_every_watch_tool_the_board_is_prospective(
    mcp: Mcp, tool: str, arguments: dict[str, Any]
) -> None:
    replay = mcp.open((mcp.clock.now - timedelta(hours=37)).isoformat())
    fresh = mcp.open((mcp.clock.now - timedelta(hours=35)).isoformat())

    refusal = mcp.refused(tool, "not_prospective", session_id=replay, **arguments)

    assert refusal["as_of"]
    assert mcp.get("/api/v1/chokepoints")["total"] == 0
    assert mcp.get("/api/v1/watch-runs")["total"] == 0
    if tool == "board":
        assert mcp.ok(tool, session_id=fresh, **arguments)["total"] == 0


def test_the_memo_keeps_the_runs_cost_and_tokens(mcp: Mcp) -> None:
    session = mcp.open()

    written = mcp.ok(
        "write_memo", session_id=session, mode="delta", memo="m", cost_usd=2.5, tokens=900_000
    )

    run = mcp.get(f"/api/v1/watch-runs/{written['watch_run_id']}")
    assert (run["cost_usd"], run["tokens"]) == (2.5, 900_000)
    mcp.refused(
        "write_memo", "invalid_arguments", session_id=session, mode="delta", memo="m", tokens=-1
    )


def test_the_tools_name_the_steps_and_say_a_list_replaces_the_whole_list(mcp: Mcp) -> None:
    listed = {each["name"]: each for each in mcp.rpc("tools/list").json()["result"]["tools"]}
    update = listed["update_chokepoint"]["description"]

    for name in ("constraint", "demand_vs_supply", "relief", "control", "capture", "invalidation"):
        assert name in update and name in listed["board"]["description"]
    assert "replaces the whole list" in update
    assert "replaces the step's whole evidence" in update
    assert "add_issue_ids" in update and "add_evidence" in update


def test_a_session_moves_a_chokepoint_to_thesis_ready_through_the_tools(mcp: Mcp) -> None:
    session = mcp.open()
    fact = mcp.fact()
    chokepoint = mcp.ok("add_chokepoint", session_id=session, constraint="c", layer="l")["id"]
    issue = mcp.ok("open_issue", session_id=session, title="Is c the constraint?")["id"]

    def update(kind: str, payload: dict[str, Any], **extra: Any) -> dict[str, Any]:
        return mcp.ok(
            "update_chokepoint",
            session_id=session,
            id=chokepoint,
            kind=kind,
            payload=payload,
            **extra,
        )

    for step in ("constraint", "demand_vs_supply", "control"):
        update(
            "step_set", {"step": step, "status": "primary", "add_evidence": {"fact_ids": [fact]}}
        )
    update("field_set", {"kill_criteria": ["a second vendor ships"], "add_issue_ids": [issue]})
    ready = update("status_set", {"status": "thesis_ready"}, reason="a, b and d are primary")

    assert ready["status"] == "thesis_ready" and ready["status_reason"] == "a, b and d are primary"
    assert ready["needs_review"] is False and ready["thesis_gate"] == {"holds": True, "missing": []}
    full = mcp.ok("get_chokepoint", session_id=session, id=chokepoint)
    assert {event["actor"] for event in full["history"]} == {"watch-agent"}  # the session's actor
    mcp.refused(
        "update_chokepoint",
        "thesis_ready_step_locked",
        session_id=session,
        id=chokepoint,
        kind="step_set",
        payload={"step": "a", "status": "contradicted", "evidence": {"fact_ids": [fact]}},
    )
    line = mcp.ok("board", session_id=session)["chokepoints"][0]
    assert (line["status"], line["status_reason"]) == ("thesis_ready", "a, b and d are primary")
    assert line["needs_review"] is False and line["steps"]["a"] == "primary"
    assert mcp.ok("board", session_id=session, status="needs_review")["total"] == 0


def test_the_tools_answers_keep_their_shapes_after_the_pages_reads_grew(mcp: Mcp) -> None:
    """W8 added `facts`, `leads`, `issues`, `status_set_at` and a holder's `company_id` to the
    routes' answers, for the owner's pages. The agents' tools answer as they always did."""
    session = mcp.open()
    fact = mcp.fact()
    added = mcp.ok(
        "add_chokepoint",
        session_id=session,
        constraint="Indium phosphide substrates",
        layer="materials",
        holders=[{"name": "Lumentum", "slug": "lumentum"}],
    )
    updated = mcp.ok(
        "update_chokepoint",
        session_id=session,
        id=added["id"],
        kind="step_set",
        payload={"step": "a", "status": "primary", "evidence": {"fact_ids": [fact]}},
    )
    line_keys = {
        "id",
        "constraint",
        "layer",
        "holders",
        "status",
        "status_reason",
        "stale",
        "needs_review",
        "thesis_gate",
        "steps",
        "kill_criteria",
        "relief_horizon",
        "crowding",
        "issue_ids",
        "last_event_at",
    }

    on_board = mcp.ok("board", session_id=session)["chokepoints"][0]
    full = mcp.ok("get_chokepoint", session_id=session, id=added["id"])

    assert set(on_board) == line_keys
    assert set(added) == line_keys | {"created", "note"}
    assert set(updated) == line_keys | {"updated", "events"}
    for holders in (on_board["holders"], added["holders"], updated["holders"], full["holders"]):
        assert holders == [{"name": "Lumentum", "slug": "lumentum", "cik": None}]
    assert set(full) == {
        "id",
        "theme",
        "created_at",
        "created_by_session",
        "created_by_run",
        "constraint",
        "layer",
        "holders",
        "status",
        "status_reason",
        "thesis_gate",
        "needs_review",
        "stale",
        "steps",
        "kill_criteria",
        "relief_horizon",
        "crowding",
        "issue_ids",
        "last_event_at",
        "last_evidence_at",
        "event_count",
        "history",
        "note",
    }
