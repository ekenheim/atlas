"""The Atlas MCP server (atlas-beliefs ticket 15): `POST /mcp`, streamable HTTP.

Seam: the HTTP endpoint of the API (JSON-RPC over the TestClient) on a fresh database holding
Lumentum's recorded EDGAR filings (the 10-Q of 6 May, the Q4 press release of 11 August, the
10-K of 17 August 2026), the Hindsight fake and the LiteLLM fake scripting the two judges. The
tools call the existing `/api/v1` routes in process; what is tested here is the tool list, one
call per tool, the as-of rule the server takes from the session's row, the refusals and the
calls Atlas counts on the session. Nothing live.
"""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import JsonValue
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from atlas.api.app import create_app
from atlas.audit import Actor
from atlas.cli import run_apply_template
from atlas.jobs import JobQueue, Worker, builtin_registry
from atlas.ledger.ingest import INGEST_KIND, ingest_payload
from tests.fakes.hindsight import RecordedHindsight
from tests.fakes.litellm import API_KEY, ChatReply, FakeLiteLLM
from tests.fakes.serve import Served, serve
from tests.harness import (
    BANK,
    EDGAR_FIXTURES,
    TEMPLATE,
    THEMES,
    make_settings,
)

ACTOR = "mcp-test-owner"
QUESTION = "Is laser capacity the constraint on AI optics?"
# The fixtures' availability: the 10-Q on 6 May, the press release on 11 August, the 10-K on
# 17 August 2026 (103 days after the 10-Q, 6 after the press release).
BEFORE_10K = "2026-08-12T00:00:00Z"
LATER = "2026-09-30T00:00:00Z"
REVENUE_QUOTE = "Net revenue for the fourth quarter of fiscal year 2026 was $1.01 billion"
REVENUE_SPAN = (1604, 1676)
REVENUE_STATEMENT = "Lumentum's fourth-quarter fiscal 2026 net revenue was $1.01 billion."
SHARES_QUOTE = (
    "As of April 30, 2026, the Registrant had 77.8 million shares of common stock outstanding."
)
TENK_SHARES = (
    "As of August 14, 2026, the Registrant had 89.7 million shares of common stock outstanding."
)
PHONE = "Registrant" + chr(0x2019) + "s telephone number, including area code"
URL_EX991 = (
    "https://www.sec.gov/Archives/edgar/data/1633978/000162828026055726/lite_ex991xq4fy26.htm"
)
URL_10Q = "https://www.sec.gov/Archives/edgar/data/1633978/000162828026030777/lite-20260328.htm"
URL_10K = "https://www.sec.gov/Archives/edgar/data/1633978/000162828026057358/lite-20260627.htm"

TOOLS = {
    "open_session",
    "close_session",
    "companies",
    "search",
    "read",
    "locate",
    "record_fact",
    "get_fact",
    "judge_statement",
    "relate_facts",
    "propose_belief",
    "cite_belief",
    "supersede_belief",
    "open_issue",
    "narrow_issue",
    "complete_issue",
    "next_issue",
    "recall",
    "newest_documents",
    "list_beliefs",
    "get_belief",
    "list_issues",
    "draft_hypothesis",
    "get_hypothesis",
    "upcoming_reports",
    "signal_leads",
    "prior_work",
    "examine_belief",
}
NO_SESSION_REQUIRED = {"open_session", "companies", "next_issue"}


@pytest.fixture
def hindsight_fake() -> RecordedHindsight:
    fake = RecordedHindsight()
    fake.derive_memories()
    return fake


@pytest.fixture
def llm() -> FakeLiteLLM:
    return FakeLiteLLM()


@pytest.fixture
def litellm(llm: FakeLiteLLM) -> Iterator[Served]:
    with serve(llm.handle) as served:
        yield served
        served.raise_errors()


class Mcp:
    """The API over a database holding Lumentum's filings, spoken to over `/mcp`."""

    def __init__(self, database_url: str, tmp_path: Path, hindsight_url: str, litellm_url: str):
        archive = tmp_path / "archive"
        archive.mkdir(exist_ok=True)
        self.engine = create_engine(database_url)
        settings = make_settings(
            archive,
            database_url=database_url,
            actor=ACTOR,
            themes_config=THEMES,
            sec_fixtures_dir=EDGAR_FIXTURES,
            hindsight_url=hindsight_url,
            hindsight_bank_id=BANK,
            hindsight_template_path=TEMPLATE,
            litellm_url=litellm_url,
            litellm_api_key=API_KEY,
            llm_role_models={"finding_judge": "luna", "counter_judge": "luna"},
            finding_judge=False,
            finding_judge_votes=1,
            retention_triage="off",
            retain_poll_timeout_seconds=0.3,
            retain_poll_interval_seconds=0.01,
        )
        assert run_apply_template(settings, None) == 0
        queue = JobQueue(self.engine, actor=Actor(ACTOR))
        queue.enqueue(INGEST_KIND, "lumentum", ingest_payload("lumentum", None, None))
        worker = Worker(queue, builtin_registry(settings))
        for _ in range(12):  # the ingest, then the retains it enqueues
            if worker.run_once() == 0:
                break
        self.settings = settings
        self.api = TestClient(create_app(settings))
        self.requests = 0

    # --- the transport ---

    def rpc(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        self.requests += 1
        return self.api.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": self.requests, "method": method, "params": params or {}},
            headers=headers,
        )

    def call(self, tool: str, **arguments: Any) -> tuple[bool, dict[str, Any]]:
        """(`isError`, the tool's JSON answer)."""
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

    # --- the archive and the sessions ---

    def get(self, path: str, **params: Any) -> Any:
        response = self.api.get(path, params=params)
        assert response.status_code == 200, response.text
        return response.json()

    def open(self, as_of: str = LATER, **extra: Any) -> str:
        opened = self.ok(
            "open_session",
            question=QUESTION,
            as_of=as_of,
            seeds=["lumentum"],
            model="claude-fable-5-1",
            actor="claude-session",
            **extra,
        )
        return opened["session_id"]

    def version(self, url: str) -> str:
        lumentum = next(
            c for c in self.get("/api/v1/companies")["items"] if c["slug"] == "lumentum"
        )
        documents = self.get(f"/api/v1/companies/{lumentum['id']}/sources", limit=100)["items"]
        return next(d["latest_version_id"] for d in documents if d["canonical_url"] == url)

    def fact(self, session: str, url: str, quote: str, **extra: Any) -> str:
        recorded = self.ok(
            "record_fact",
            session_id=session,
            version_id=self.version(url),
            quote=quote,
            step="context",
            status="in_effect",
            statement=extra.pop("statement", "Lumentum says so."),
            **extra,
        )
        assert recorded["recorded"] is True or recorded["reused"] is True  # a repeat: reused
        return recorded["fact_id"]

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
def mcp(
    database_url: str, tmp_path: Path, hindsight: tuple[RecordedHindsight, Served], litellm: Served
) -> Iterator[Mcp]:
    harness = Mcp(database_url, tmp_path, hindsight[1].url, litellm.url)
    yield harness
    harness.engine.dispose()


def asked(body: dict[str, Any]) -> dict[str, Any]:
    return json.loads(body["messages"][1]["content"])


def supported(body: dict[str, Any]) -> JsonValue:
    """The finding judge: supported, the statement one clause based on the first quote whole."""
    request = asked(body)
    quote = request["retrieved_data"][0]
    return {
        "clauses": [
            {
                "text": request["request"]["finding"]["statement"],
                "ref": quote["id"],
                "basis": quote["text"],
            }
        ],
        "verdict": "supported",
        "beyond": [],
        "kinds": [],
        "reason": "the quote states it",
    }


def relating(relation: str) -> Any:
    def answer(body: dict[str, Any]) -> JsonValue:
        challenged = asked(body)["request"]["challenged"]
        return {
            "relations": [
                {"ref": each["ref"], "relation": relation, "reason": f"k1 {relation} it"}
                for each in challenged
            ]
        }

    return answer


# --- the transport and the tool list ---


def test_the_server_answers_initialize_and_lists_its_typed_tools(mcp: Mcp) -> None:
    initialized = mcp.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})
    assert initialized.status_code == 200
    result = initialized.json()["result"]
    assert result["protocolVersion"] == "2025-06-18"
    assert result["serverInfo"]["name"] == "atlas-research"
    assert result["capabilities"] == {"tools": {"listChanged": False}}
    older = mcp.rpc("initialize", {"protocolVersion": "2024-11-05"}).json()["result"]
    assert older["protocolVersion"] == "2024-11-05"
    unknown = mcp.rpc("initialize", {"protocolVersion": "1999-01-01"}).json()["result"]
    assert unknown["protocolVersion"] == "2025-06-18"

    notified = mcp.api.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert (notified.status_code, notified.content) == (202, b"")
    assert mcp.rpc("ping").json()["result"] == {}

    listed = mcp.rpc("tools/list").json()["result"]["tools"]
    assert {each["name"] for each in listed} == TOOLS
    for each in listed:
        schema = each["inputSchema"]
        assert schema["type"] == "object" and each["description"]
        assert schema["additionalProperties"] is False
        required = set(schema.get("required", []))
        if each["name"] in NO_SESSION_REQUIRED:
            assert "session_id" not in required
        else:
            assert "session_id" in required
    by_name = {each["name"]: each["inputSchema"] for each in listed}
    assert "session_id" not in by_name["open_session"]["properties"]
    # No tool takes an as-of time: it is the session's.
    assert [
        n for n, s in by_name.items() if "as_of" in s["properties"] and n != "open_session"
    ] == []


def test_the_transport_refuses_what_it_does_not_speak(mcp: Mcp) -> None:
    assert mcp.api.get("/mcp").status_code == 405
    assert mcp.api.delete("/mcp").status_code == 405
    origin = mcp.rpc("ping", headers={"Origin": "https://evil.example"})
    assert origin.status_code == 403
    assert mcp.rpc("resources/list").json()["error"]["code"] == -32601
    nameless = mcp.rpc("tools/call", {"name": "shell", "arguments": {}})
    assert nameless.json()["error"]["code"] == -32602
    garbage = mcp.api.post("/mcp", content=b"{not json")
    assert garbage.status_code == 400 and garbage.json()["error"]["code"] == -32700
    assert "/mcp" not in mcp.get("/openapi.json")["paths"]


def test_the_server_can_be_switched_off(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, mcp_enabled=False)
    assert TestClient(create_app(settings)).post("/mcp", json={}).status_code in (404, 405)


# --- one call per tool ---


def test_a_session_works_the_method_through_the_tools_and_atlas_counts_its_calls(
    mcp: Mcp, llm: FakeLiteLLM
) -> None:
    llm.script_role("finding_judge", ChatReply.answer(supported, tokens=(400, 40)))
    llm.script_role("counter_judge", ChatReply.answer(relating("limits"), tokens=(600, 60)))

    session = mcp.open()
    companies = mcp.ok("companies")["companies"]
    assert [c["slug"] for c in companies if c["slug"] == "lumentum"] == ["lumentum"]
    assert set(companies[0]) == {"slug", "id", "display_name", "layer", "country"}

    found = mcp.ok(
        "search",
        session_id=session,
        company="lumentum",
        q="net revenue fourth quarter fiscal year 2026",
    )
    ex991 = mcp.version(URL_EX991)
    hit = next(h for h in found["hits"] if h["source_version_id"] == ex991)
    assert hit["available_at"] == "2026-08-11T20:24:11Z" and hit["parser_version"]
    assert hit["char_start"] < hit["char_end"] and "revenue" in hit["text"].lower()

    window = mcp.ok(
        "read", session_id=session, version_id=ex991, start=REVENUE_SPAN[0], end=REVENUE_SPAN[1]
    )
    assert window["text"] == REVENUE_QUOTE
    assert (window["start"], window["end"], window["clamped"]) == (*REVENUE_SPAN, False)
    assert window["available_at"] == "2026-08-11T20:24:11Z"

    located = mcp.ok("locate", session_id=session, version_id=ex991, quote=REVENUE_QUOTE)
    assert (located["span_start"], located["span_end"]) == REVENUE_SPAN
    assert located["offset_source"] == "exact"

    revenue = mcp.fact(
        session,
        URL_EX991,
        REVENUE_QUOTE,
        statement=REVENUE_STATEMENT,
        period="Q4 FY2026",
        quantity={"value": 1.01, "unit": "USD billion", "metric": "net revenue"},
    )
    shares = mcp.fact(session, URL_10Q, SHARES_QUOTE, statement="Lumentum had 77.8 million shares.")
    got = mcp.ok("get_fact", session_id=session, fact_id=revenue)
    assert got["session_id"] == session
    assert got["assertion"]["quote"] == REVENUE_QUOTE
    assert (got["assertion"]["span_start"], got["assertion"]["span_end"]) == REVENUE_SPAN

    judged = mcp.ok(
        "judge_statement", session_id=session, statement=REVENUE_STATEMENT, fact_ids=[revenue]
    )
    assert judged["verdict"] == "supported" and judged["refs"] == {"c1": revenue}
    [call] = [b for b in llm.chat_requests() if b["metadata"]["role"] == "finding_judge"]
    assert asked(call)["request"]["research_question"] == QUESTION  # the session's, verbatim
    related = mcp.ok("relate_facts", session_id=session, fact_id=revenue, counter_fact_id=shares)
    assert (related["relation"], related["judge"]) == ("limits", "counter_judge.v1")

    belief = mcp.ok(
        "propose_belief",
        session_id=session,
        statement=REVENUE_STATEMENT,
        step="capture",
        companies=["lumentum"],
        citations=[
            {"fact_id": revenue, "how": 0.9, "weight": "load_bearing"},
            {"fact_id": shares, "how": "limits", "weight": "context"},
        ],
    )
    assert (belief["judgement"], belief["status"], belief["citations"]) == (
        "unproven",
        "active",
        2,
    )
    assert "warnings" not in belief  # the 10-Q's Fact only limits it: no supporting Facts joined
    held = mcp.get(f"/api/v1/beliefs/{belief['id']}")
    assert held["theme"] == "photonics" and held["produced_by"] == session
    assert held["as_of"] == LATER  # the session's, not an argument's
    other = mcp.ok(
        "propose_belief",
        session_id=session,
        statement="Lumentum reported $1.01 billion of net revenue in its fourth quarter of 2026.",
        step="capture",
        citations=[{"fact_id": revenue, "how": "supports", "weight": "load_bearing"}],
    )
    cited = mcp.ok(
        "cite_belief",
        session_id=session,
        belief_id=other["id"],
        citation={"fact_id": shares, "how": -0.25, "weight": "context"},
    )
    assert cited["citations"] == 2
    superseded = mcp.ok(
        "supersede_belief",
        session_id=session,
        belief_id=belief["id"],
        by=[other["id"]],
        reason="a finer proposition",
    )
    assert superseded["status"] == "superseded"

    parent = mcp.ok("open_issue", session_id=session, title="What limits laser output?")
    assert (parent["status"], parent["kind"], parent["theme"]) == ("active", "read", "photonics")
    child = mcp.ok(
        "open_issue", session_id=session, title="Who qualifies InP lasers?", narrows=parent["id"]
    )
    assert child["parent_id"] == parent["id"]
    sibling = mcp.ok("open_issue", session_id=session, title="Which fabs ramp?", kind="step")
    linked = mcp.ok(
        "narrow_issue",
        session_id=session,
        issue_id=sibling["id"],
        parent_id=parent["id"],
        requires=True,
    )
    assert linked["linked"] is True
    done = mcp.ok(
        "complete_issue",
        session_id=session,
        issue_id=child["id"],
        fact_id=revenue,
        belief_id=other["id"],
    )
    assert done["status"] == "complete"
    upcoming = mcp.ok("next_issue", session_id=session)
    assert upcoming["issue"] is not None and upcoming["reason"] in {
        "step_without_belief",
        "flagged_or_disputed",
        "priority",
    }
    assert mcp.ok("next_issue", theme="photonics")["issue"] is not None

    recalled = mcp.ok("recall", session_id=session, query="laser capacity", max_tokens=2048)
    assert recalled["as_of"] == LATER and recalled["bank"] == "research"
    assert recalled["memories"] and "dropped_future" in recalled
    assert "never evidence" in recalled["note"]
    assert all({"provenance_state", "sections"} <= set(m) for m in recalled["memories"])

    closed = mcp.ok(
        "close_session",
        session_id=session,
        usage={"calls": 99},
        card={"steps": [], "open_questions": ["Who else makes InP lasers?"]},
        card_markdown="# Card",
    )
    assert closed == {"closed": True, "session_id": session, "facts": 2}

    # Atlas's count: every call but `companies` and the sessionless `next_issue` (the open is
    # counted on the session it opened), on the session read; the agent's own usage is its own.
    names = [tool for tool, _, _ in mcp.calls(session)]
    assert names == [
        "open_session", "search", "read", "locate", "record_fact", "record_fact", "get_fact",
        "judge_statement", "relate_facts", "propose_belief", "propose_belief", "cite_belief",
        "supersede_belief", "open_issue", "open_issue", "open_issue", "narrow_issue",
        "complete_issue", "next_issue", "recall", "close_session",
    ]  # fmt: skip
    assert {outcome for _, outcome, _ in mcp.calls(session)} == {"ok"}
    read = mcp.get(f"/api/v1/sessions/{session}")
    assert read["tool_calls"] == len(names) == 21
    assert read["usage"] == {"calls": 99}
    assert mcp.get("/api/v1/sessions")["items"][0]["tool_calls"] == 21


# --- the as-of time is the session's ---


def test_a_document_public_after_the_sessions_as_of_cannot_be_searched_read_or_cited(
    mcp: Mcp,
) -> None:
    later = mcp.open(LATER)
    ten_k = mcp.version(URL_10K)
    late_fact = mcp.fact(later, URL_10K, TENK_SHARES, statement="Lumentum had 89.7 million shares.")
    early = mcp.open(BEFORE_10K)

    query = {
        "company": "lumentum",
        "q": "Registrant had million shares of common stock outstanding",
    }
    ids = {h["source_version_id"] for h in mcp.ok("search", session_id=later, **query)["hits"]}
    assert ten_k in ids
    ids = {h["source_version_id"] for h in mcp.ok("search", session_id=early, **query)["hits"]}
    assert ten_k not in ids

    refusal = mcp.refused(
        "read", "available_after_as_of", session_id=early, version_id=ten_k, start=0, end=500
    )
    assert refusal["available_at"] == "2026-08-17T20:03:17Z" and refusal["as_of"].startswith(
        "2026-08-12"
    )
    mcp.refused(
        "locate", "available_after_as_of", session_id=early, version_id=ten_k, quote=TENK_SHARES
    )
    mcp.refused(
        "record_fact", "available_after_as_of", session_id=early, version_id=ten_k,
        quote=TENK_SHARES, step="context", status="in_effect", statement="x",
    )  # fmt: skip
    mcp.refused("get_fact", "fact_available_after_as_of", session_id=early, fact_id=late_fact)
    mcp.refused(
        "judge_statement", "fact_available_after_as_of", session_id=early, statement="x",
        fact_ids=[late_fact],
    )  # fmt: skip
    mcp.refused(
        "propose_belief", "fact_available_after_as_of", session_id=early, statement="Parts.",
        step="control", citations=[{"fact_id": late_fact, "how": 1, "weight": "load_bearing"}],
    )  # fmt: skip
    early_fact = mcp.fact(early, URL_EX991, REVENUE_QUOTE, statement=REVENUE_STATEMENT)
    early_belief = mcp.ok(
        "propose_belief", session_id=early, statement=REVENUE_STATEMENT, step="capture",
        citations=[{"fact_id": early_fact, "how": 1, "weight": "load_bearing"}],
    )  # fmt: skip
    mcp.refused(
        "relate_facts", "fact_available_after_as_of", session_id=early, fact_id=early_fact,
        counter_fact_id=late_fact,
    )  # fmt: skip
    mcp.refused(
        "relate_facts", "fact_available_after_as_of", session_id=early, fact_id=late_fact,
        counter_fact_id=early_fact,
    )  # fmt: skip
    mcp.refused(
        "cite_belief", "fact_available_after_as_of", session_id=early,
        belief_id=early_belief["id"],
        citation={"fact_id": late_fact, "how": 0.5, "weight": "context"},
    )  # fmt: skip
    assert len(mcp.get(f"/api/v1/beliefs/{early_belief['id']}")["citations"]) == 1  # not added
    assert mcp.get(f"/api/v1/facts/{late_fact}")["session_id"] == later  # the Fact stands

    # The press release of 11 August was public by then; and the time is not an argument.
    mcp.ok("read", session_id=early, version_id=mcp.version(URL_EX991), start=0, end=100)
    mcp.refused(
        "read", "invalid_arguments", session_id=early, version_id=ten_k, start=0, end=5,
        as_of=LATER,
    )  # fmt: skip
    assert mcp.ok("recall", session_id=early, query="laser capacity")["as_of"] == BEFORE_10K


# --- quotes, warnings ---


def test_recall_is_asked_and_filtered_as_of_the_sessions_time(
    mcp: Mcp, hindsight_fake: RecordedHindsight
) -> None:
    early, later = mcp.open(BEFORE_10K), mcp.open(LATER)

    def recall_bodies() -> list[dict[str, Any]]:
        return [
            json.loads(request.content)
            for request in hindsight_fake.calls
            if request.method == "POST" and request.url.path.endswith("/memories/recall")
        ]

    kept = mcp.ok("recall", session_id=later, query="laser capacity")
    assert kept["as_of"] == LATER and kept["dropped_future"] == 0
    first = recall_bodies()[-1]
    assert first["query_timestamp"] == "2026-09-30T00:00:00+00:00"

    narrow = mcp.ok("recall", session_id=early, query="laser capacity")
    assert narrow["as_of"] == BEFORE_10K
    assert recall_bodies()[-1]["query_timestamp"] == "2026-08-12T00:00:00+00:00"
    # `available_by` is applied by Atlas on what Hindsight returned: the memories whose sections
    # became public after the session's as-of time are dropped, and counted.
    assert narrow["dropped_future"] > 0
    assert len(narrow["memories"]) + narrow["dropped_future"] == len(kept["memories"])
    for memory in narrow["memories"]:
        for section in memory["sections"]:
            assert section["available_at"] <= "2026-08-12T00:00:00Z"


def test_a_tool_call_whose_arguments_are_not_an_object_is_refused_not_a_server_error(
    mcp: Mcp,
) -> None:
    session = mcp.open()
    for arguments in (["session_id"], "x", 7, True):
        response = mcp.rpc("tools/call", {"name": "search", "arguments": arguments})
        assert response.status_code == 200, response.text
        result = response.json()["result"]
        value = json.loads(result["content"][0]["text"])
        assert result["isError"] is True and value["refused"] == "invalid_arguments", value
    # Missing or null arguments are an empty object: the schema refuses them, and an open
    # session named inside a malformed object is still counted.
    assert mcp.rpc("tools/call", {"name": "search"}).status_code == 200
    mcp.refused("search", "invalid_arguments", session_id=session, company=["x"], q="laser")
    mcp.refused("search", "invalid_arguments", session_id=[session], company="lumentum", q="laser")
    assert mcp.calls(session) == [
        ("open_session", "ok", None),
        ("search", "refused", "invalid_arguments"),
    ]


def test_a_quote_is_located_through_the_typographic_fold_and_only_if_it_occurs_once(
    mcp: Mcp,
) -> None:
    session = mcp.open()
    ten_k = mcp.version(URL_10K)
    plain = PHONE.replace(chr(0x2019), "'")
    assert plain != PHONE

    located = mcp.ok("locate", session_id=session, version_id=ten_k, quote=plain)
    assert located["offset_source"] == "folded"
    assert located["archived_quote"] == PHONE  # the archive's text, not the caller's
    assert located["span_end"] - located["span_start"] == len(PHONE)
    text_ = mcp.api.get(
        f"/api/v1/source-versions/{ten_k}/content", params={"kind": "parsed"}
    ).content.decode()
    assert text_[located["span_start"] : located["span_end"]] == PHONE

    ambiguous = mcp.ok("locate", session_id=session, version_id=ten_k, quote="Lumentum")
    assert ambiguous["reason"] == "quote_ambiguous" and ambiguous["occurrences"] > 1
    missing = mcp.ok("locate", session_id=session, version_id=ten_k, quote="no such sentence")
    assert (missing["located"], missing["reason"]) == (False, "quote_not_found")
    mcp.refused(
        "record_fact", "quote_not_found", session_id=session, version_id=ten_k,
        quote="no such sentence", step="context", status="in_effect", statement="x",
    )  # fmt: skip

    dry = mcp.ok(
        "record_fact", session_id=session, version_id=ten_k, quote=plain, step="control",
        status="in_effect", statement="Lumentum has a registrant.", dry_run=True,
    )  # fmt: skip
    assert dry["recorded"] is False and dry["body"]["quote"] == PHONE
    assert mcp.get("/api/v1/facts", session_id=session)["total"] == 0


def test_propose_belief_warns_never_refuses_when_its_facts_join_dated_documents(
    mcp: Mcp,
) -> None:
    session = mcp.open()
    shares = mcp.fact(session, URL_10Q, SHARES_QUOTE)  # 6 May
    components = mcp.fact(session, URL_10K, TENK_SHARES)  # 17 August: 103 days later
    revenue = mcp.fact(session, URL_EX991, REVENUE_QUOTE)  # 11 August: 6 days before the 10-K

    joined = mcp.ok(
        "propose_belief",
        session_id=session,
        statement="Lumentum had 77.8 million shares in April and 89.7 million in August.",
        step="capture",
        citations=[
            {"fact_id": shares, "how": 1, "weight": "load_bearing"},
            {"fact_id": components, "how": "supports", "weight": "context"},
        ],
    )
    assert joined["status"] == "active"  # a warning, not a refusal
    [warning] = joined["warnings"]
    assert warning["warning"] == "joins_dated_documents"
    assert warning["documents"] == {"2026-05-06": shares, "2026-08-17": components}
    assert warning["days_apart"] == 103

    near = mcp.ok(
        "propose_belief",
        session_id=session,
        statement="Lumentum reported revenue, and had 89.7 million shares in August.",
        step="capture",
        citations=[
            {"fact_id": revenue, "how": 1, "weight": "load_bearing"},
            {"fact_id": components, "how": 1, "weight": "context"},
        ],
    )
    assert "warnings" not in near

    counter = mcp.ok(
        "propose_belief",
        session_id=session,
        statement="Lumentum reported revenue.",
        step="capture",
        citations=[
            {"fact_id": revenue, "how": 1, "weight": "load_bearing"},
            {"fact_id": shares, "how": "contradicts", "weight": "context"},  # counts against
        ],
    )
    assert "warnings" not in counter  # only supporting Facts are joined


# --- refusals and errors ---


def test_refusals_and_errors_are_returned_and_counted_on_the_session(
    mcp: Mcp, llm: FakeLiteLLM
) -> None:
    llm.script_role(
        "finding_judge", ChatReply.error(500, "Unknown items in responses API response")
    )
    nobody = "00000000-0000-0000-0000-000000000000"
    mcp.refused("read", "unknown_session", session_id=nobody, version_id=nobody, start=0, end=1)
    mcp.refused("search", "invalid_arguments", company="lumentum", q="x")  # no session_id given

    session = mcp.open()
    shares = mcp.fact(session, URL_10Q, SHARES_QUOTE)
    mcp.refused("search", "unknown_company", session_id=session, company="nope", q="laser")
    bad = mcp.refused(
        "search", "invalid_arguments", session_id=session, company="lumentum", q="", top=0
    )
    assert "q:" in bad["message"] and "top:" in bad["message"]
    mcp.refused(
        "record_fact", "quantity_not_in_quote", session_id=session,
        version_id=mcp.version(URL_10Q), quote=SHARES_QUOTE, step="context", status="in_effect",
        statement="Lumentum had 99 million shares.",
        quantity={"value": 99, "unit": "shares", "metric": "shares outstanding"},
    )  # fmt: skip
    mcp.refused(
        "propose_belief", "no_load_bearing_citation", session_id=session, statement="x",
        step="control", citations=[{"fact_id": shares, "how": 0.5, "weight": "context"}],
    )  # fmt: skip
    unavailable = mcp.call(
        "judge_statement", session_id=session, statement="Shares.", fact_ids=[shares]
    )
    assert unavailable[0] is True and unavailable[1]["error"] == "role_unavailable"
    mcp.ok("close_session", session_id=session)
    mcp.refused("search", "session_closed", session_id=session, company="lumentum", q="laser")

    assert mcp.calls(session) == [
        ("open_session", "ok", None),
        ("record_fact", "ok", None),
        ("search", "refused", "unknown_company"),
        ("search", "refused", "invalid_arguments"),
        ("record_fact", "refused", "quantity_not_in_quote"),
        ("propose_belief", "refused", "no_load_bearing_citation"),
        ("judge_statement", "error", "role_unavailable"),
        ("close_session", "ok", None),
    ]
    assert mcp.get(f"/api/v1/sessions/{session}")["tool_calls"] == 8


def test_tool_calls_cannot_be_changed_once_recorded(mcp: Mcp) -> None:
    session = mcp.open()
    mcp.ok("companies", session_id=session)
    for statement in (
        "UPDATE session_tool_call SET outcome = 'ok'",
        "DELETE FROM session_tool_call",
    ):
        with pytest.raises(DBAPIError, match="insert-only"), mcp.engine.begin() as connection:
            connection.execute(text(statement))
    assert len(mcp.calls(session)) == 2


def test_a_closed_session_cannot_be_driven_through_the_tools(mcp: Mcp) -> None:
    session = mcp.open()
    with mcp.engine.begin() as connection:
        connection.execute(
            text("UPDATE research_session SET finished_at = now() WHERE id = :id"), {"id": session}
        )
    mcp.refused("companies", "session_closed", session_id=session)
    assert mcp.calls(session) == [("open_session", "ok", None)]


# --- the agents' tools (ticket 16): documents, Beliefs, Issues, Hypotheses ---

NOBODY = "00000000-0000-0000-0000-000000000000"


def judge_proven(mcp: Mcp, belief_id: str) -> None:
    """An author's judgement, as the lead's would be: there is no tool for it."""
    response = mcp.api.post(
        f"/api/v1/beliefs/{belief_id}/judge",
        json={"actor": "lead", "judgement": "proven", "confidence": 0.8, "reason": "tested"},
    )
    assert response.status_code == 200, response.text


def believe(mcp: Mcp, session: str, url: str, quote: str, statement: str) -> tuple[str, str]:
    """(the Fact, the Belief) a session records and proposes."""
    fact = mcp.fact(session, url, quote)
    belief = mcp.ok(
        "propose_belief",
        session_id=session,
        statement=statement,
        step="capture",
        companies=["lumentum"],
        citations=[{"fact_id": fact, "how": 1, "weight": "load_bearing"}],
    )
    return fact, belief["id"]


def test_newest_documents_lists_what_was_public_by_the_sessions_time_newest_first(
    mcp: Mcp,
) -> None:
    early = mcp.open(BEFORE_10K)  # after the 10-Q (6 May) and the press release (11 August)
    listed = mcp.ok("newest_documents", session_id=early, companies=["lumentum"])
    assert listed["as_of"] == BEFORE_10K
    assert [d["source_version_id"] for d in listed["documents"]] == [
        mcp.version(URL_EX991),
        mcp.version(URL_10Q),
    ]
    first = listed["documents"][0]
    assert first["company"] == "lumentum" and first["available_at"] == "2026-08-11T20:24:11Z"
    assert first["title"] and first["parser_version"]
    assert first["source_type"] != "xbrl_companyfacts"
    assert listed["total"] == 2

    # The session's theme is the default; the 10-K is not public yet, a later session sees it.
    assert mcp.ok("newest_documents", session_id=early)["total"] == 2
    late = mcp.open(LATER)
    later = mcp.ok("newest_documents", session_id=late)
    assert later["documents"][0]["source_version_id"] == mcp.version(URL_10K)

    # since, kinds and limit narrow it.
    since = mcp.ok("newest_documents", session_id=late, since="2026-08-12T00:00:00Z")
    assert [d["source_version_id"] for d in since["documents"]] == [mcp.version(URL_10K)]
    quarterly = mcp.ok("newest_documents", session_id=late, kinds=["10-q"], companies=["lumentum"])
    assert [d["source_version_id"] for d in quarterly["documents"]] == [mcp.version(URL_10Q)]
    one = mcp.ok("newest_documents", session_id=late, limit=1)
    assert (one["total"], len(one["documents"])) == (3, 1)

    # Naming both a theme and companies, or an unknown company, is refused.
    mcp.refused(
        "newest_documents", "theme_or_companies", session_id=late,
        theme="photonics", companies=["lumentum"],
    )  # fmt: skip
    mcp.refused("newest_documents", "unknown_company", session_id=late, companies=["nope"])
    assert mcp.calls(late)[-1] == ("newest_documents", "refused", "unknown_company")


def test_beliefs_are_listed_and_read_only_as_of_the_sessions_time(mcp: Mcp) -> None:
    early, late = mcp.open(BEFORE_10K), mcp.open(LATER)
    fact_early, belief_early = believe(
        mcp, early, URL_EX991, REVENUE_QUOTE, "Lumentum reported $1.01 billion in revenue."
    )
    fact_late, belief_late = believe(
        mcp, late, URL_10K, TENK_SHARES, "Lumentum had 89.7 million shares in August 2026."
    )

    seen_early = mcp.ok("list_beliefs", session_id=early)
    assert [b["id"] for b in seen_early["beliefs"]] == [belief_early]
    assert (seen_early["total"], seen_early["hidden_after_as_of"]) == (1, 1)
    seen_late = mcp.ok("list_beliefs", session_id=late)
    assert [b["id"] for b in seen_late["beliefs"]] == [belief_early, belief_late]
    summary = seen_late["beliefs"][0]
    assert summary["judgement"]["judgement"] == "unproven" and summary["companies"] == ["lumentum"]
    assert summary["step"] == "capture" and summary["citation_count"] == 1
    assert summary["as_of"] == BEFORE_10K

    # An author judges; filters by judgement, step and company.
    judge_proven(mcp, belief_early)
    proven = mcp.ok("list_beliefs", session_id=late, judgement="proven", company="lumentum")
    assert [b["id"] for b in proven["beliefs"]] == [belief_early]
    assert proven["beliefs"][0]["judgement"]["actor"] == "lead"
    assert mcp.ok("list_beliefs", session_id=late, step="control")["beliefs"] == []
    limited = mcp.ok("list_beliefs", session_id=late, limit=1)
    assert (limited["total"], len(limited["beliefs"])) == (2, 1)

    # A Belief after the session's time cannot be read; one before it is read with its quotes.
    mcp.refused("get_belief", "belief_after_as_of", session_id=early, belief_id=belief_late)
    read = mcp.ok("get_belief", session_id=early, belief_id=belief_early)
    [citation] = read["citations"]
    assert citation["ref_id"] == fact_early and citation["quote"] == REVENUE_QUOTE
    assert citation["available_at"] == "2026-08-11T20:24:11Z" and read["hidden_citations"] == 0
    assert read["history"][-1]["judgement"] == "proven"

    # A later session cites the 10-K's Fact on the earlier Belief: the early session does not
    # see that citation (its document is not public to it), the late one does.
    mcp.ok(
        "cite_belief", session_id=late, belief_id=belief_early,
        citation={"fact_id": fact_late, "how": "limits", "weight": "context"},
    )  # fmt: skip
    hidden = mcp.ok("get_belief", session_id=early, belief_id=belief_early)
    assert [c["ref_id"] for c in hidden["citations"]] == [fact_early]
    assert (hidden["hidden_citations"], hidden["counterevidence"]) == (1, [])
    full = mcp.ok("get_belief", session_id=late, belief_id=belief_early)
    assert {c["ref_id"] for c in full["citations"]} == {fact_early, fact_late}
    assert [c["ref_id"] for c in full["counterevidence"]] == [fact_late]
    mcp.refused("get_belief", "not_found", session_id=late, belief_id=NOBODY)


def test_a_belief_read_as_of_an_early_session_hides_what_later_work_added_to_it(
    mcp: Mcp,
) -> None:
    early, late = mcp.open(BEFORE_10K), mcp.open(LATER)
    _, belief_early = believe(
        mcp, early, URL_EX991, REVENUE_QUOTE, "Lumentum reported $1.01 billion in revenue."
    )
    fact_late, belief_late = believe(
        mcp, late, URL_10K, TENK_SHARES, "Lumentum had 89.7 million shares in August 2026."
    )
    # Later work: a load-bearing contradiction (Atlas raises the flag) and a supersession.
    mcp.ok(
        "cite_belief", session_id=late, belief_id=belief_early,
        citation={"fact_id": fact_late, "how": "contradicts", "weight": "load_bearing"},
    )  # fmt: skip

    # prior_work counts the flag the 10-K's citation raised for the late asker alone.
    def held_flags(session: str) -> int:
        items = mcp.ok("prior_work", session_id=session)["beliefs"]["items"]
        return next(b["open_flags"] for b in items if b["id"] == belief_early)

    assert (held_flags(early), held_flags(late)) == (0, 1)
    mcp.ok(
        "supersede_belief", session_id=late, belief_id=belief_early,
        by=[belief_late], reason="narrowed by the 10-K",
    )  # fmt: skip

    seen = mcp.ok("get_belief", session_id=late, belief_id=belief_early)
    assert [link["id"] for link in seen["superseded_by"]] == [belief_late]
    assert (seen["open_flags"], [f["kind"] for f in seen["flags"]]) == (
        1,
        ["counterevidence_stands"],
    )
    assert (seen["hidden_links"], seen["hidden_flags"], seen["hidden_citations"]) == (0, 0, 0)

    blind = mcp.ok("get_belief", session_id=early, belief_id=belief_early)
    assert blind["superseded_by"] == [] and blind["supersedes"] == []
    assert blind["flags"] == [] and blind["open_flags"] == 0
    assert (blind["hidden_links"], blind["hidden_flags"], blind["hidden_citations"]) == (1, 1, 1)
    assert "10-K" not in json.dumps(blind) and "89.7 million" not in json.dumps(blind)

    # The later Belief links back to the early one, which the late session may read.
    back = mcp.ok("get_belief", session_id=late, belief_id=belief_late)
    assert [link["id"] for link in back["supersedes"]] == [belief_early]
    assert back["hidden_links"] == 0


def test_issues_and_beliefs_are_paged_through_and_too_many_is_a_refusal(
    mcp: Mcp, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = mcp.open()
    for number in range(3):
        mcp.ok(
            "open_issue", session_id=session, kind="read" if number else "question",
            title=f"Issue {number}",
        )  # fmt: skip
    monkeypatch.setattr("atlas.mcp.agents.SCAN_PAGE", 2)
    listed = mcp.ok("list_issues", session_id=session, kind="read")
    assert sorted(each["title"] for each in listed["issues"]) == ["Issue 1", "Issue 2"]
    assert listed["of_theme"] == 3
    monkeypatch.setattr("atlas.mcp.agents.SCAN_LIMIT", 2)
    mcp.refused("list_issues", "too_many_issues", session_id=session)
    for number in range(3):
        believe(
            mcp, session, URL_EX991, REVENUE_QUOTE, f"Lumentum reported $1.01 billion {number}."
        )
    mcp.refused("list_beliefs", "too_many_beliefs", session_id=session)


def test_issues_are_listed_so_a_question_is_not_opened_twice(mcp: Mcp) -> None:
    session = mcp.open()
    asked = mcp.ok(
        "open_issue", session_id=session, kind="question", companies=["lumentum"],
        title="Is Lumentum's laser capacity sold out?", body="Fact f1: 'sold out'",
    )  # fmt: skip
    mcp.ok("open_issue", session_id=session, kind="read", title="Read the 10-K's risk factors")
    listed = mcp.ok("list_issues", session_id=session)
    assert listed["of_theme"] == 2
    titles = {each["title"] for each in listed["issues"]}
    assert titles == {"Is Lumentum's laser capacity sold out?", "Read the 10-K's risk factors"}
    question = next(each for each in listed["issues"] if each["id"] == asked["id"])
    assert question["companies"] == ["lumentum"] and question["body"] == "Fact f1: 'sold out'"
    assert question["kind"] == "question" and question["status"] == "active"
    only = mcp.ok("list_issues", session_id=session, kind="question")
    assert [each["id"] for each in only["issues"]] == [asked["id"]]

    mcp.ok("complete_issue", session_id=session, issue_id=asked["id"])
    assert [each["title"] for each in mcp.ok("list_issues", session_id=session)["issues"]] == [
        "Read the 10-K's risk factors"
    ]
    done = mcp.ok("list_issues", session_id=session, status="complete")
    assert [each["id"] for each in done["issues"]] == [asked["id"]]
    assert mcp.ok("list_issues", session_id=session, theme="other")["issues"] == []


def test_a_hypothesis_is_drafted_from_the_proven_beliefs_the_sessions_time_allows(
    mcp: Mcp,
) -> None:
    early, late = mcp.open(BEFORE_10K), mcp.open(LATER)
    _, belief_early = believe(
        mcp, early, URL_EX991, REVENUE_QUOTE, "Lumentum reported $1.01 billion in revenue."
    )
    _, belief_late = believe(
        mcp, late, URL_10K, TENK_SHARES, "Lumentum had 89.7 million shares in August 2026."
    )

    # Nothing is proven: nothing to draft.
    mcp.refused("draft_hypothesis", "conflict", session_id=late, question="Is it a bottleneck?")

    # Only the Belief at or before the session's time is drafted from: the early session's.
    judge_proven(mcp, belief_early)
    judge_proven(mcp, belief_late)
    drafted = mcp.ok(
        "draft_hypothesis", session_id=early, question="Does Lumentum capture the value?"
    )
    assert drafted["draft_status"] == "queued" and drafted["status"] == "draft"
    assert drafted["theme"] == "photonics" and drafted["as_of"] == BEFORE_10K
    assert drafted["question"] == "Does Lumentum capture the value?"
    hypothesis = mcp.get(f"/api/v1/hypotheses/{drafted['hypothesis_id']}")
    assert hypothesis["as_of"] == BEFORE_10K

    # Before the Editor has drafted a version there is no version, and the gate says so.
    read = mcp.ok("get_hypothesis", session_id=early, hypothesis_id=drafted["hypothesis_id"])
    assert (read["draft_status"], read["latest_version"], read["version"]) == ("queued", None, None)
    assert read["publish_gate"]["publishable"] is False
    assert read["publish_gate"]["blocked"] == "no_version"

    # A session of an earlier time than the cutoff cannot read it; a later one can.
    before_cutoff = mcp.open("2026-08-01T00:00:00Z")
    mcp.refused(
        "get_hypothesis", "hypothesis_after_as_of",
        session_id=before_cutoff, hypothesis_id=drafted["hypothesis_id"],
    )  # fmt: skip
    mcp.refused("draft_hypothesis", "conflict", session_id=before_cutoff)  # no Belief that early
    assert mcp.ok("get_hypothesis", session_id=late, hypothesis_id=drafted["hypothesis_id"])
    mcp.refused("get_hypothesis", "not_found", session_id=late, hypothesis_id=NOBODY)

    # There is no tool that publishes or judges.
    names = {each["name"] for each in mcp.rpc("tools/list").json()["result"]["tools"]}
    assert not {"publish_hypothesis", "publish_version", "judge_belief"} & names


# --- research that compounds (ticket 26) -----------------------------------------------------

LONG_REVENUE_QUOTE = (
    "Net revenue for the fourth quarter of fiscal year 2026 was $1.01 billion, with GAAP net loss"
    " of $7.2 billion, or $84.65 per diluted share."
)
LOSS_STATEMENT = "Lumentum recorded a GAAP net loss of $7.2 billion in its fourth quarter."
SECOND_STATEMENT = "Lumentum's Q4 FY2026 net revenue was $1.01 billion."
TENK_STATEMENT = "Lumentum had 89.7 million shares outstanding on 14 August 2026."
MIDDLE = "2026-08-20T00:00:00Z"  # after the press release (11 August), before the 1 September
SEPTEMBER = "2026-09-01T00:00:00Z"


def record(
    mcp: Mcp,
    session: str,
    url: str,
    quote: str,
    statement: str,
    step: str = "context",
    status: str = "in_effect",
) -> dict[str, Any]:
    """`record_fact` with its answer, whether the Fact was recorded or reused."""
    return mcp.ok(
        "record_fact",
        session_id=session,
        version_id=mcp.version(url),
        quote=quote,
        step=step,
        status=status,
        statement=statement,
    )


def test_prior_work_lists_what_earlier_sessions_left_within_the_sessions_as_of(mcp: Mcp) -> None:
    early, middle, early_again = mcp.open(BEFORE_10K), mcp.open(LATER), mcp.open(BEFORE_10K)
    revenue = record(mcp, early, URL_EX991, REVENUE_QUOTE, REVENUE_STATEMENT, step="capture")
    shares = record(mcp, early, URL_10Q, SHARES_QUOTE, "Lumentum had 77.8 million shares.")
    mcp.ok("read", session_id=early, version_id=mcp.version(URL_EX991), start=1604, end=1676)
    belief = mcp.ok(
        "propose_belief",
        session_id=early,
        statement="Lumentum reported $1.01 billion in revenue.",
        step="capture",
        companies=["lumentum"],
        citations=[{"fact_id": revenue["fact_id"], "how": 1, "weight": "load_bearing"}],
    )["id"]
    judge_proven(mcp, belief)
    tenk = record(mcp, middle, URL_10K, TENK_SHARES, TENK_STATEMENT)
    mcp.ok("open_issue", session_id=early, title="Read Lumentum's 10-K", companies=["lumentum"])
    mcp.ok("open_issue", session_id=middle, title="Is the count diluted?", companies=["lumentum"])
    mcp.ok(
        "close_session",
        session_id=early,
        card={"steps": [], "open_questions": ["Who else makes InP lasers?"]},
    )
    asker = mcp.open(LATER)

    work = mcp.ok("prior_work", session_id=asker)  # the session's seeds: Lumentum

    assert work["as_of"] == LATER and work["theme"] == "photonics"
    assert work["companies"] == ["lumentum"]
    # Facts: newest document first (the 10-K, the press release, the 10-Q).
    assert work["facts"]["total"] == 3 and work["facts"]["beyond"] == 0
    assert [(f["id"], f["step"]) for f in work["facts"]["items"]] == [
        (tenk["fact_id"], "context"),
        (revenue["fact_id"], "capture"),
        (shares["fact_id"], "context"),
    ]
    assert [f["document_available_at"][:10] for f in work["facts"]["items"]] == [
        "2026-08-17",
        "2026-08-11",
        "2026-05-06",
    ]
    assert work["facts"]["items"][0]["document_available_at"] == "2026-08-17T20:03:17Z"
    assert work["facts"]["items"][1]["statement"] == REVENUE_STATEMENT
    assert work["facts"]["items"][1]["company"] == "lumentum"
    # Beliefs of any judgement, with who judged them and when they were last examined.
    [held] = work["beliefs"]["items"]
    assert (held["id"], held["judgement"], held["judged_by"], held["step"]) == (
        belief,
        "proven",
        "lead",
        "capture",
    )
    assert (held["last_examined_as_of"], held["examined_through"]) == (None, BEFORE_10K)
    # Documents read, each with the as-of time of the sessions that read it.
    assert [(d["source_version_id"], d["facts"]) for d in work["documents_read"]["items"]] == [
        (mcp.version(URL_10K), 1),
        (mcp.version(URL_EX991), 1),
        (mcp.version(URL_10Q), 1),
    ]
    read_by = {
        d["source_version_id"]: sorted((r["session_id"], r["session_as_of"]) for r in d["read_by"])
        for d in work["documents_read"]["items"]
    }
    assert read_by[mcp.version(URL_10K)] == [(middle, LATER)]
    assert read_by[mcp.version(URL_EX991)] == [(early, BEFORE_10K)]
    assert work["latest_session_as_of"] == LATER
    # Sessions with the open questions a card named; the Issues that touch the company.
    assert {s["id"] for s in work["sessions"]["items"]} == {early, middle, early_again}
    assert next(s for s in work["sessions"]["items"] if s["id"] == early)["open_questions"] == [
        "Who else makes InP lasers?"
    ]
    assert all(s["same_question"] for s in work["sessions"]["items"])
    titles = {i["title"] for i in work["issues"]["items"]}
    assert {"Read Lumentum's 10-K", "Is the count diluted?", "Who else makes InP lasers?"} <= titles
    # A step filter narrows the Facts; a cap says what it left out.
    only = mcp.ok("prior_work", session_id=asker, steps=["capture"])
    assert [f["id"] for f in only["facts"]["items"]] == [revenue["fact_id"]]
    capped = mcp.ok("prior_work", session_id=asker, limit=2)
    assert (capped["facts"]["total"], capped["facts"]["shown"], capped["facts"]["beyond"]) == (
        3,
        2,
        1,
    )

    # The same question as of before the 10-K sees nothing that came after it.
    view = mcp.ok("prior_work", session_id=early_again)
    assert view["facts"]["total"] == 2
    assert tenk["fact_id"] not in {f["id"] for f in view["facts"]["items"]}
    assert [d["source_version_id"] for d in view["documents_read"]["items"]] == [
        mcp.version(URL_EX991),
        mcp.version(URL_10Q),
    ]
    assert view["latest_session_as_of"] == BEFORE_10K
    assert [s["id"] for s in view["sessions"]["items"]] == [early]
    assert view["hidden_sessions"] == 2  # the middle and the asker, both as of LATER
    view_titles = {i["title"] for i in view["issues"]["items"]}
    assert "Read Lumentum's 10-K" in view_titles and "Is the count diluted?" not in view_titles
    assert "89.7" not in json.dumps(view) and "Is the count diluted?" not in json.dumps(view)


def test_a_span_an_earlier_fact_covers_is_reused_not_recorded_again(mcp: Mcp) -> None:
    first, second = mcp.open(BEFORE_10K), mcp.open(LATER)
    recorded = record(mcp, first, URL_EX991, REVENUE_QUOTE, REVENUE_STATEMENT)
    assert recorded["recorded"] is True and "same_span_as" not in recorded
    original = recorded["fact_id"]

    # The same span, the same step and status, the same statement (case and punctuation aside,
    # ticket 28): the existing Fact comes back.
    again = record(
        mcp, second, URL_EX991, REVENUE_QUOTE, REVENUE_STATEMENT.upper().removesuffix(".")
    )
    assert (again["recorded"], again["reused"], again["fact_id"]) == (False, True, original)
    assert "nothing was recorded" in again["note"]
    assert mcp.get("/api/v1/facts")["total"] == 1
    assert mcp.get(f"/api/v1/sessions/{second}")["facts_reused"] == 1
    assert mcp.get(f"/api/v1/sessions/{second}")["facts"] == 0
    assert mcp.get(f"/api/v1/sessions/{first}")["facts_reused"] == 0

    # A span that only overlaps (the longer sentence) with another statement is a
    # new Fact, flagged as covering the same span.
    longer = record(mcp, second, URL_EX991, LONG_REVENUE_QUOTE, LOSS_STATEMENT)
    assert longer["recorded"] is True and longer["same_span_as"] == original
    assert longer["fact_id"] != original
    assert mcp.get("/api/v1/facts")["total"] == 2
    assert mcp.get(f"/api/v1/facts/{longer['fact_id']}")["same_span_as"] == original
    # Another status is a different statement too.
    hedged = record(mcp, second, URL_EX991, REVENUE_QUOTE, REVENUE_STATEMENT, status="hedged")
    assert hedged["recorded"] is True and hedged["same_span_as"] == original
    # Another step is its own Fact: nothing overlaps it.
    other = record(mcp, second, URL_EX991, REVENUE_QUOTE, REVENUE_STATEMENT, step="capture")
    assert other["recorded"] is True and "same_span_as" not in other
    assert mcp.get("/api/v1/facts")["total"] == 4
    # A longer quote of the same sentence, the same statement, same step: reused too.
    longer_again = record(mcp, second, URL_EX991, LONG_REVENUE_QUOTE, LOSS_STATEMENT)
    assert longer_again["reused"] is True and longer_again["fact_id"] == longer["fact_id"]
    assert mcp.get(f"/api/v1/sessions/{second}")["facts_reused"] == 2

    # The call is on the session, and the audit trail says the Fact was reused, not created.
    calls = [(tool, outcome) for tool, outcome, _ in mcp.calls(second)]
    assert calls.count(("record_fact", "ok")) == 5
    with mcp.engine.connect() as connection:
        actions = list(
            connection.execute(
                text("SELECT action FROM audit_event WHERE entity_id = :id ORDER BY id"),
                {"id": original},
            ).scalars()
        )
    assert (actions.count("fact.created"), actions.count("fact.reused")) == (1, 1)

    # Over HTTP: a session's repeat is 200 with `reused`; a Fact with no session is recorded as
    # before (201); a unknown session is refused before anything is reused.
    body = {
        "subject_company_id": mcp.get("/api/v1/facts/" + original)["assertion"][
            "subject_company_id"
        ],
        "source_version_id": mcp.version(URL_EX991),
        "quote": REVENUE_QUOTE,
        "span_start": REVENUE_SPAN[0],
        "span_end": REVENUE_SPAN[1],
        "epistemic_type": "direct_source_statement",
        "step": "context",
        "statement": REVENUE_STATEMENT,
        "status": "in_effect",
    }
    reused = mcp.api.post("/api/v1/facts", json=body | {"session_id": second})
    assert reused.status_code == 200 and reused.json()["reused"] is True
    assert reused.json()["fact"]["id"] == original
    sessionless = mcp.api.post("/api/v1/facts", json=body)
    assert sessionless.status_code == 201 and sessionless.json()["reused"] is False
    assert sessionless.json()["fact"]["id"] != original
    unknown = mcp.api.post("/api/v1/facts", json=body | {"session_id": NOBODY})
    assert unknown.status_code == 422 and unknown.json()["error"]["code"] == "unknown_session"


def test_examine_belief_sets_the_staleness_fields_and_list_beliefs_orders_by_them(
    mcp: Mcp,
) -> None:
    older, newer = mcp.open(BEFORE_10K), mcp.open(MIDDLE)
    _, first = believe(
        mcp, older, URL_EX991, REVENUE_QUOTE, "Lumentum reported $1.01 billion in revenue."
    )
    _, second = believe(
        mcp, newer, URL_EX991, LONG_REVENUE_QUOTE, "Lumentum reported a $7.2 billion GAAP loss."
    )
    judge_proven(mcp, first)
    judge_proven(mcp, second)
    asker = mcp.open(SEPTEMBER)

    def order(session: str, **extra: Any) -> list[str]:
        return [b["id"] for b in mcp.ok("list_beliefs", session_id=session, **extra)["beliefs"]]

    # Never examined: stalest is the one whose own as-of time is older.
    assert order(asker) == [first, second]
    assert order(asker, sort="created") == [first, second]
    assert mcp.ok("list_beliefs", session_id=asker)["beliefs"][0]["examined_through"] == BEFORE_10K

    examined = mcp.ok(
        "examine_belief", session_id=asker, belief_id=first, outcome="nothing_new", note="read 10-K"
    )
    assert examined["examined"] is True and examined["outcome"] == "nothing_new"
    assert examined["last_examined_as_of"] == SEPTEMBER
    assert (examined["judgement"], examined["open_flags"]) == ("proven", 0)
    assert "open_notices" not in examined
    # The examined Belief is now the fresher one: never-examined first, then oldest examined.
    assert order(asker) == [second, first]
    listed = {b["id"]: b for b in mcp.ok("list_beliefs", session_id=asker)["beliefs"]}
    assert listed[first]["last_examined_outcome"] == "nothing_new"
    assert listed[first]["last_examined_as_of"] == SEPTEMBER
    assert listed[first]["examined_through"] == SEPTEMBER
    assert listed[first]["last_examined_at"] is not None
    assert (
        listed[second]["last_examined_as_of"] is None
        and listed[second]["examined_through"] == MIDDLE
    )
    over_http = mcp.get("/api/v1/beliefs", theme="photonics", sort="stalest")["items"]
    assert [b["id"] for b in over_http] == [second, first]
    assert over_http[1]["last_examined_as_of"] == SEPTEMBER

    # The later examination, by a session as of LATER, moves it past the other.
    mcp.ok("examine_belief", session_id=asker, belief_id=second, outcome="confirmed")
    assert order(asker) == [first, second]  # both examined through SEPTEMBER: the older first
    later = mcp.open(LATER)
    mcp.ok("examine_belief", session_id=later, belief_id=first, outcome="qualified")
    assert order(later) == [second, first]
    again = mcp.get(f"/api/v1/beliefs/{first}")
    assert (again["last_examined_as_of"], again["last_examined_outcome"]) == (LATER, "qualified")
    assert [e["outcome"] for e in again["examinations"]] == ["nothing_new", "qualified"]
    assert [e["as_of"] for e in again["examinations"]] == [SEPTEMBER, LATER]
    assert again["judgement"]["judgement"] == "proven"  # an examination judges nothing
    # An earlier session does not see an examination by a later one.
    seen = mcp.ok("get_belief", session_id=newer, belief_id=first)
    assert (seen["last_examined_as_of"], seen["hidden_examinations"], seen["examinations"]) == (
        None,
        2,
        [],
    )
    blind = {b["id"]: b for b in mcp.ok("list_beliefs", session_id=newer)["beliefs"]}
    assert blind[first]["last_examined_as_of"] is None

    # Refusals: a session older than the Belief, an unknown session, a Belief that is not active.
    mcp.refused(
        "examine_belief",
        "belief_after_as_of",
        session_id=older,
        belief_id=second,
        outcome="confirmed",
    )
    refused = mcp.api.post(
        f"/api/v1/beliefs/{first}/examine", json={"session_id": NOBODY, "outcome": "confirmed"}
    )
    assert refused.status_code == 422 and refused.json()["error"]["code"] == "unknown_session"
    mcp.ok("supersede_belief", session_id=later, belief_id=first, by=[second], reason="narrowed")
    gone = mcp.api.post(
        f"/api/v1/beliefs/{first}/examine", json={"session_id": later, "outcome": "confirmed"}
    )
    assert gone.status_code == 409 and gone.json()["error"]["code"] == "belief_not_active"
    with mcp.engine.connect() as connection:
        actions = list(
            connection.execute(
                text("SELECT action FROM audit_event WHERE entity_id = :id ORDER BY id"),
                {"id": first},
            ).scalars()
        )
    assert actions.count("belief.examined") == 2


def test_stalest_orders_by_examined_through_and_an_earlier_replay_leaves_the_summary(
    mcp: Mcp,
) -> None:
    may, august, middle = mcp.open("2026-05-10T00:00:00Z"), mcp.open(BEFORE_10K), mcp.open(MIDDLE)
    _, first = believe(
        mcp, august, URL_EX991, REVENUE_QUOTE, "Lumentum reported $1.01 billion in revenue."
    )
    _, second = believe(
        mcp, middle, URL_EX991, LONG_REVENUE_QUOTE, "Lumentum reported a $7.2 billion GAAP loss."
    )
    # Created last, but with the oldest own as-of time: the stalest, as the MCP orders them.
    _, third = believe(mcp, may, URL_10Q, SHARES_QUOTE, "Lumentum had 77.8 million shares.")

    def over_http(sort: str) -> list[str]:
        return [b["id"] for b in mcp.get("/api/v1/beliefs", theme="photonics", sort=sort)["items"]]

    assert over_http("stalest") == [third, first, second]
    assert over_http("created") == [first, second, third]

    # Examined, it follows the never-tested ones; the order is by what it was tested against.
    september, replay = mcp.open(SEPTEMBER), mcp.open(MIDDLE)
    mcp.ok("examine_belief", session_id=september, belief_id=first, outcome="confirmed")
    assert over_http("stalest") == [third, second, first]
    # A replay as of an earlier time is recorded, but the summary stays the furthest one's.
    mcp.ok("examine_belief", session_id=replay, belief_id=first, outcome="contradicted")
    kept = mcp.get(f"/api/v1/beliefs/{first}")
    assert (kept["last_examined_as_of"], kept["last_examined_outcome"]) == (SEPTEMBER, "confirmed")
    assert [e["outcome"] for e in kept["examinations"]] == ["confirmed", "contradicted"]
    # prior_work reads the examination with the furthest as-of time it may see.
    asker = mcp.open(LATER)
    [held] = [
        b
        for b in mcp.ok("prior_work", session_id=asker, steps=["capture"])["beliefs"]["items"]
        if b["id"] == first
    ]
    assert (held["last_examined_as_of"], held["last_examined_outcome"]) == (SEPTEMBER, "confirmed")
    as_of_middle = mcp.ok("prior_work", session_id=mcp.open(MIDDLE), steps=["capture"])
    [early_view] = [b for b in as_of_middle["beliefs"]["items"] if b["id"] == first]
    assert (early_view["last_examined_as_of"], early_view["last_examined_outcome"]) == (
        MIDDLE,
        "contradicted",
    )


def test_an_alike_but_other_statement_is_recorded_naming_the_fact_on_its_span(mcp: Mcp) -> None:
    # Ticket 28: reuse is for the same statement. A reworded one (most of its words shared, as
    # word-set Jaccard >= 0.5 would call alike) is a new Fact naming the first.
    first, second = mcp.open(BEFORE_10K), mcp.open(LATER)
    original = record(mcp, first, URL_EX991, REVENUE_QUOTE, REVENUE_STATEMENT)["fact_id"]
    reworded = record(mcp, second, URL_EX991, REVENUE_QUOTE, SECOND_STATEMENT)
    assert reworded["recorded"] is True and not reworded.get("reused")
    assert reworded["same_span_as"] == original and reworded["fact_id"] != original
    # One word fewer is another statement too, and the same one again is then reused.
    shorter = record(mcp, second, URL_EX991, REVENUE_QUOTE, SECOND_STATEMENT.replace("net ", ""))
    assert shorter["recorded"] is True and shorter["same_span_as"] == original
    again = record(mcp, second, URL_EX991, REVENUE_QUOTE, SECOND_STATEMENT.lower())
    assert again["reused"] is True and again["fact_id"] == reworded["fact_id"]
    assert mcp.get("/api/v1/facts")["total"] == 3


def test_a_quote_of_more_words_than_the_existing_fact_is_not_reused(mcp: Mcp) -> None:
    first, second = mcp.open(BEFORE_10K), mcp.open(LATER)
    original = record(mcp, first, URL_EX991, REVENUE_QUOTE, REVENUE_STATEMENT)["fact_id"]
    # The longer quote contains the earlier span but says more: its own Fact, naming the first.
    longer = record(mcp, second, URL_EX991, LONG_REVENUE_QUOTE, SECOND_STATEMENT)
    assert longer["recorded"] is True and not longer.get("reused")
    assert longer["same_span_as"] == original and longer["fact_id"] != original
    # The shorter quote of the same statement is covered by the first, shorter Fact: reused.
    shorter = record(mcp, second, URL_EX991, REVENUE_QUOTE, REVENUE_STATEMENT)
    assert shorter["reused"] is True and shorter["fact_id"] == original
    assert mcp.get("/api/v1/facts")["total"] == 2


def test_a_supporting_fact_from_a_newer_document_notices_a_proven_belief(
    mcp: Mcp, llm: FakeLiteLLM
) -> None:
    early, late = mcp.open(BEFORE_10K), mcp.open(LATER)
    revenue, belief = believe(
        mcp, early, URL_EX991, REVENUE_QUOTE, "Lumentum reported $1.01 billion in revenue."
    )
    _, other_belief = believe(
        mcp, early, URL_10Q, SHARES_QUOTE, "Lumentum had 77.8 million shares in April."
    )
    tenk = record(mcp, late, URL_10K, TENK_SHARES, TENK_STATEMENT)["fact_id"]
    tenq = record(mcp, late, URL_10Q, SHARES_QUOTE, "Lumentum had 77.8 million shares.")["fact_id"]

    def relate(fact: str, counter: str, relation: str) -> dict[str, Any]:
        llm.script_role("counter_judge", ChatReply.answer(relating(relation)))
        return mcp.ok("relate_facts", session_id=late, fact_id=fact, counter_fact_id=counter)

    # An unproven Belief is not noticed: nothing is confirmed yet.
    assert relate(revenue, tenk, "supports")["confirmed_beliefs"] == []
    judge_proven(mcp, belief)
    judge_proven(mcp, other_belief)
    # Only `supports` confirms; a document older than the Belief's as-of time does not.
    assert relate(revenue, tenk, "limits")["confirmed_beliefs"] == []
    assert relate(revenue, tenq, "supports")["confirmed_beliefs"] == []
    quiet = mcp.get(f"/api/v1/beliefs/{belief}")
    assert (quiet["open_notices"], quiet["notices"]) == (0, [])

    confirmed = relate(revenue, tenk, "supports")
    assert (confirmed["relation"], confirmed["confirmed_beliefs"]) == ("supports", [belief])
    noticed = mcp.get(f"/api/v1/beliefs/{belief}")
    assert noticed["open_notices"] == 1 and noticed["open_flags"] == 0
    assert noticed["judgement"]["judgement"] == "proven"  # a notice never changes the judgement
    [notice] = noticed["notices"]
    assert (notice["kind"], notice["ref_id"], notice["cleared_by"]) == (
        "belief_confirmed",
        tenk,
        None,
    )
    assert "2026-08-17" in notice["detail"] and TENK_STATEMENT in notice["detail"]
    # The same Fact does not notice it twice; the other Belief rests on another Fact.
    assert relate(revenue, tenk, "supports")["confirmed_beliefs"] == []
    assert mcp.get(f"/api/v1/beliefs/{belief}")["open_notices"] == 1
    assert mcp.get(f"/api/v1/beliefs/{other_belief}")["open_notices"] == 0
    # Notices are no flags: the flagged filter, the theme and the Belief list see no doubt.
    assert mcp.get("/api/v1/beliefs", flagged="true")["total"] == 0
    shown = {b["id"]: b for b in mcp.get("/api/v1/beliefs", theme="photonics")["items"]}
    assert (shown[belief]["open_notices"], shown[belief]["open_flags"]) == (1, 0)
    assert mcp.ok("get_belief", session_id=late, belief_id=belief)["open_notices"] == 1
    on_map = mcp.get("/api/v1/themes/photonics/map")["beliefs"]
    assert {b["id"]: b["open_notices"] for b in on_map}[belief] == 1

    # Citing a Fact with the relation `supports` notices a proven Belief the same way.
    cited = mcp.ok(
        "cite_belief",
        session_id=late,
        belief_id=other_belief,
        citation={"fact_id": tenk, "how": "supports", "weight": "context"},
    )
    assert cited["open_flags"] == 0 and "open_notices" not in cited
    noticed_other = mcp.ok("get_belief", session_id=late, belief_id=other_belief)
    assert (noticed_other["open_notices"], noticed_other["open_flags"]) == (1, 0)
    # A plain positive valence is the author's own weighing: no notice.
    third = mcp.ok(
        "propose_belief",
        session_id=early,
        statement="Lumentum had 77.8 million shares in April.",
        step="capture",
        citations=[{"fact_id": tenq, "how": 1, "weight": "load_bearing"}],
    )["id"]
    judge_proven(mcp, third)
    mcp.ok(
        "cite_belief",
        session_id=late,
        belief_id=third,
        citation={"fact_id": tenk, "how": 0.7, "weight": "context"},
    )
    assert mcp.get(f"/api/v1/beliefs/{third}")["open_notices"] == 0

    # prior_work bounds the count the same way: the early asker counts no notice, the late one does.
    def held_notices(session: str) -> int:
        items = mcp.ok("prior_work", session_id=session)["beliefs"]["items"]
        return next(b["open_notices"] for b in items if b["id"] == belief)

    assert (held_notices(early), held_notices(late)) == (0, 1)
    assert "open_notices" not in mcp.ok("list_beliefs", session_id=early)["beliefs"][0]
    assert (
        mcp.ok("list_beliefs", session_id=early)["beliefs"][0]["judgement"]["judgement"] == "proven"
    )

    # An earlier session cannot see a notice its document is after.
    blind = mcp.ok("get_belief", session_id=early, belief_id=belief)
    assert (blind["notices"], blind["hidden_notices"], blind["open_notices"]) == ([], 1, 0)
    assert TENK_STATEMENT not in json.dumps(blind)

    # Only a judgement clears it.
    judge_proven(mcp, belief)
    cleared = mcp.get(f"/api/v1/beliefs/{belief}")
    assert cleared["open_notices"] == 0
    assert cleared["notices"][0]["cleared_by"] == cleared["history"][-1]["id"]
    assert mcp.get(f"/api/v1/beliefs/{other_belief}")["open_notices"] == 1
