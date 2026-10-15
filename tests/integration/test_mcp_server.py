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
    "upcoming_reports",
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
        assert recorded["recorded"] is True
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
