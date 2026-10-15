"""A Fact's statement, a session's thesis and a Belief judged where they are written down
(atlas-beliefs ticket 23): `POST /api/v1/facts`, `POST /api/v1/sessions/{id}/close`,
`POST /api/v1/beliefs` and the MCP tools over them.

Seam: the `/api/v1` API (and `/mcp`) on a fresh database holding Lumentum's recorded Q4 FY26
press release, the Hindsight fake (a judge's run records the bank template and Hindsight's
version) and the LiteLLM fake scripting the `finding_judge`'s answers. A call the fake was not
scripted for fails the test, so "no judge call" is asserted by scripting none. Nothing live.
"""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import JsonValue
from sqlalchemy import create_engine, text

from atlas.api.app import create_app
from atlas.audit import Actor, verify_chain
from atlas.cli import run_apply_template
from atlas.jobs import JobQueue, Worker, builtin_registry
from atlas.ledger.ingest import INGEST_KIND, ingest_payload
from tests.fakes.hindsight import RecordedHindsight
from tests.fakes.litellm import API_KEY, ChatReply, FakeLiteLLM
from tests.fakes.serve import Served, serve
from tests.harness import BANK, EDGAR_FIXTURES, TEMPLATE, THEMES, make_settings

ACTOR = "judged-at-record-owner"
QUESTION = "Is laser capacity the constraint on AI optics?"
URL_EX991 = (
    "https://www.sec.gov/Archives/edgar/data/1633978/000162828026055726/lite_ex991xq4fy26.htm"
)
REVENUE_QUOTE = "Net revenue for the fourth quarter of fiscal year 2026 was $1.01 billion"
REVENUE_SPAN = (1604, 1676)
STATEMENT = "Lumentum's fourth-quarter fiscal 2026 net revenue was $1.01 billion."
OVERSTATED = STATEMENT.removesuffix(".") + ", driven by data-center laser demand."
THESIS = "Lumentum's revenue was $1.01 billion in its fourth quarter of fiscal 2026."
COMPOUND = "Lumentum's net revenue was $1.01 billion; its laser capacity is sold out."
AS_OF = "2026-09-30T00:00:00Z"


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


class Judged:
    """The API over a database holding Lumentum's Q4 press release, the judge on."""

    def __init__(
        self,
        database_url: str,
        tmp_path: Path,
        hindsight_url: str,
        litellm_url: str,
        **overrides: Any,
    ) -> None:
        archive = tmp_path / "archive"
        archive.mkdir(exist_ok=True)
        self.engine = create_engine(database_url)
        values: dict[str, Any] = {
            "database_url": database_url,
            "actor": ACTOR,
            "themes_config": THEMES,
            "sec_fixtures_dir": EDGAR_FIXTURES,
            "hindsight_url": hindsight_url,
            "hindsight_bank_id": BANK,
            "hindsight_template_path": TEMPLATE,
            "litellm_url": litellm_url,
            "litellm_api_key": API_KEY,
            "llm_role_models": {"finding_judge": "luna", "counter_judge": "luna"},
            "finding_judge": False,
            "finding_judge_votes": 1,
            "fact_statement_judge": "sessions",
            "retention_triage": "off",
            "retain_poll_timeout_seconds": 0.3,
            "retain_poll_interval_seconds": 0.01,
        }
        self.settings = make_settings(archive, **(values | overrides))
        assert run_apply_template(self.settings, None) == 0
        queue = JobQueue(self.engine, actor=Actor(ACTOR))
        queue.enqueue(INGEST_KIND, "lumentum", ingest_payload("lumentum", ["8-K"], None))
        worker = Worker(queue, builtin_registry(self.settings))
        for _ in range(12):  # the ingest, then the retains it enqueues
            if worker.run_once() == 0:
                break
        self.api = TestClient(create_app(self.settings))
        self.requests = 0

    def get(self, path: str, **params: Any) -> Any:
        response = self.api.get(path, params=params)
        assert response.status_code == 200, response.text
        return response.json()

    def company_id(self) -> str:
        return next(
            c["id"] for c in self.get("/api/v1/companies")["items"] if c["slug"] == "lumentum"
        )

    def version_id(self) -> str:
        documents = self.get(f"/api/v1/companies/{self.company_id()}/sources", limit=100)["items"]
        return next(d["latest_version_id"] for d in documents if d["canonical_url"] == URL_EX991)

    def open(self) -> str:
        response = self.api.post(
            "/api/v1/sessions",
            json={
                "question": QUESTION,
                "theme": "photonics",
                "seed_company_ids": [self.company_id()],
                "as_of": AS_OF,
                "model": "claude-fable-5-1",
                "actor": "claude-session",
            },
        )
        assert response.status_code == 201, response.text
        return response.json()["id"]

    def fact_body(self, session_id: str | None, statement: str = STATEMENT) -> dict[str, Any]:
        start, end = REVENUE_SPAN
        return {
            "subject_company_id": self.company_id(),
            "source_version_id": self.version_id(),
            "quote": REVENUE_QUOTE,
            "span_start": start,
            "span_end": end,
            "epistemic_type": "company_claim",
            "step": "context",
            "statement": statement,
            "quantity": {"value": 1.01, "unit": "USD billion", "metric": "net revenue"},
            "period": "Q4 FY2026",
            "status": "in_effect",
            "session_id": session_id,
        }

    def record(self, session_id: str | None, llm: FakeLiteLLM, statement: str = STATEMENT) -> str:
        """A Fact recorded in the session, the judge scripted to support its statement."""
        if session_id is not None:
            llm.script_role("finding_judge", ChatReply.answer(supported, tokens=(400, 40)))
        response = self.api.post("/api/v1/facts", json=self.fact_body(session_id, statement))
        assert response.status_code == 201, response.text
        return response.json()["fact"]["id"]

    # --- the MCP transport ---

    def call(self, tool: str, **arguments: Any) -> tuple[bool, dict[str, Any]]:
        self.requests += 1
        response = self.api.post(
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


@pytest.fixture
def atlas(
    database_url: str, tmp_path: Path, hindsight: tuple[RecordedHindsight, Served], litellm: Served
) -> Iterator[Judged]:
    harness = Judged(database_url, tmp_path, hindsight[1].url, litellm.url)
    yield harness
    harness.engine.dispose()


@pytest.fixture
def always(
    database_url: str, tmp_path: Path, hindsight: tuple[RecordedHindsight, Served], litellm: Served
) -> Iterator[Judged]:
    harness = Judged(
        database_url, tmp_path, hindsight[1].url, litellm.url, fact_statement_judge="always"
    )
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


def misstated(body: dict[str, Any]) -> JsonValue:
    quote = asked(body)["retrieved_data"][0]
    return {
        "clauses": [
            {"text": STATEMENT.removesuffix("."), "ref": quote["id"], "basis": quote["text"]},
            {"text": "driven by data-center laser demand", "ref": None, "basis": None},
        ],
        "verdict": "misstated",
        "beyond": ["driven by data-center laser demand"],
        "kinds": ["unstated"],
        "reason": "the quote gives the revenue and no cause for it",
    }


def judge_calls(llm: FakeLiteLLM) -> list[dict[str, Any]]:
    return [b for b in llm.chat_requests() if b["metadata"]["role"] == "finding_judge"]


# --- a Fact's statement, judged against its own quote ---------------------------------------------


def test_a_session_fact_whose_statement_says_more_than_its_quote_is_refused_with_the_judges_words(
    atlas: Judged, llm: FakeLiteLLM
) -> None:
    session = atlas.open()
    llm.script_role("finding_judge", ChatReply.answer(misstated, tokens=(400, 40)))

    response = atlas.api.post("/api/v1/facts", json=atlas.fact_body(session, OVERSTATED))

    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "statement_beyond_quote"
    assert "driven by data-center laser demand" in error["message"]
    assert "longer quote" in error["message"]
    assert error["detail"]["beyond"] == ["driven by data-center laser demand"]
    assert error["detail"]["kinds"] == ["unstated"]
    assert error["detail"]["judge"] == "finding_judge.v4"
    # Nothing was recorded: the Fact is the agent's to rewrite.
    assert atlas.get("/api/v1/facts", session_id=session)["total"] == 0
    [call] = judge_calls(llm)
    assert asked(call)["request"]["finding"]["statement"] == OVERSTATED


def test_a_supported_session_fact_is_recorded_with_the_verdict_the_judge_gave(
    atlas: Judged, llm: FakeLiteLLM
) -> None:
    session = atlas.open()
    llm.script_role("finding_judge", ChatReply.answer(supported, tokens=(400, 40)))

    response = atlas.api.post("/api/v1/facts", json=atlas.fact_body(session))

    assert response.status_code == 201, response.text
    fact = response.json()["fact"]
    judgement = fact["statement_judgement"]
    assert (judgement["verdict"], judgement["judge"]) == ("supported", "finding_judge.v4")
    assert judgement["reason"] == "the quote states it"
    # The verdict is on the Fact as read again, and its role call is in the judge's run.
    again = atlas.get(f"/api/v1/facts/{fact['id']}")
    assert again["statement_judgement"] == judgement
    calls = atlas.get(f"/api/v1/runs/{judgement['run_id']}/role-calls")["role_calls"]
    assert [c["role"] for c in calls] == ["finding_judge"]
    # The judge was sent the Fact's own quote, the source title and the document's date, on the
    # role's model, with the Fact's status and period beside the statement.
    [call] = judge_calls(llm)
    assert call["model"] == "luna"
    request = asked(call)
    [claim] = request["request"]["claims"]
    assert claim["status"] == "in_effect"
    assert claim["period"] == "Q4 FY2026"
    assert claim["source_date"] == "2026-08-11"
    assert claim["source_title"]
    [quote] = request["retrieved_data"]
    assert (quote["id"], quote["text"], quote["trust"]) == ("c1", REVENUE_QUOTE, "low")
    assert request["request"]["research_question"] == QUESTION


@pytest.mark.parametrize(
    "outage",
    [ChatReply.error(503, "upstream overloaded"), ChatReply.error(429, "rate limit exceeded")],
    ids=["a 5xx", "a quota"],
)
def test_a_judge_that_cannot_be_reached_records_the_fact_unjudged(
    atlas: Judged, llm: FakeLiteLLM, outage: ChatReply
) -> None:
    session = atlas.open()
    llm.script_role("finding_judge", outage)

    response = atlas.api.post("/api/v1/facts", json=atlas.fact_body(session, OVERSTATED))

    assert response.status_code == 201, response.text
    judgement = response.json()["fact"]["statement_judgement"]
    assert judgement["verdict"] == "unjudged"
    assert (
        judgement["reason"].startswith("role_unavailable") or "judge_failed" in judgement["reason"]
    )
    assert judgement.get("judge") is None
    assert atlas.get("/api/v1/facts", session_id=session)["total"] == 1


def test_a_fact_the_other_checks_refuse_costs_no_judge_call(
    atlas: Judged, llm: FakeLiteLLM
) -> None:
    session = atlas.open()
    body = atlas.fact_body(session) | {"span_start": 1, "span_end": 73}

    response = atlas.api.post("/api/v1/facts", json=body)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "quote_mismatch"
    assert judge_calls(llm) == []  # nothing was scripted: an unplanned call would fail the test


def test_a_fact_without_a_session_is_not_judged_by_default(atlas: Judged, llm: FakeLiteLLM) -> None:
    response = atlas.api.post("/api/v1/facts", json=atlas.fact_body(None, OVERSTATED))

    assert response.status_code == 201, response.text
    assert response.json()["fact"]["statement_judgement"] is None
    assert judge_calls(llm) == []


def test_a_fact_without_a_session_is_judged_when_the_setting_says_always(
    always: Judged, llm: FakeLiteLLM
) -> None:
    llm.script_role("finding_judge", ChatReply.answer(misstated, tokens=(400, 40)))

    response = always.api.post("/api/v1/facts", json=always.fact_body(None, OVERSTATED))

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "statement_beyond_quote"
    [call] = judge_calls(llm)
    assert asked(call)["request"]["research_question"] == ""  # no session, no question


def test_the_setting_off_judges_nothing(
    database_url: str,
    tmp_path: Path,
    hindsight: tuple[RecordedHindsight, Served],
    litellm: Served,
    llm: FakeLiteLLM,
) -> None:
    off = Judged(database_url, tmp_path, hindsight[1].url, litellm.url, fact_statement_judge="off")
    try:
        session = off.open()
        response = off.api.post("/api/v1/facts", json=off.fact_body(session, OVERSTATED))
        assert response.status_code == 201, response.text
        assert response.json()["fact"]["statement_judgement"] is None
        assert judge_calls(llm) == []
    finally:
        off.engine.dispose()


# --- the thesis, judged when the session closes ----


def card(fact_id: str, **extra: Any) -> dict[str, Any]:
    return {
        "steps": [
            {
                "step": "constraint",
                "status": "supported",
                "statements": [
                    {"statement": STATEMENT, "facts": [{"fact_id": fact_id, "company_name": "L"}]}
                ],
            }
        ],
        "open_questions": [],
        **extra,
    }


def close(atlas: Judged, session: str, body: dict[str, Any]) -> Any:
    return atlas.api.post(
        f"/api/v1/sessions/{session}/close", json={"usage": {}, "card": body, "card_markdown": "#"}
    )


def test_the_thesis_is_judged_against_the_facts_its_statements_cite_and_the_verdict_is_on_the_card(
    atlas: Judged, llm: FakeLiteLLM
) -> None:
    session = atlas.open()
    fact_id = atlas.record(session, llm)
    llm.script_role("finding_judge", ChatReply.answer(supported, tokens=(400, 40)))

    response = close(atlas, session, card(fact_id, thesis=THESIS))

    assert response.status_code == 200, response.text
    judged = atlas.get(f"/api/v1/sessions/{session}")["card"]["thesis_judged"]
    assert judged["verdict"] == "supported"
    assert judged["fact_ids"] == [fact_id]
    assert judged["judge"] == "finding_judge.v4"
    thesis_call = judge_calls(llm)[-1]
    assert asked(thesis_call)["request"]["finding"]["statement"] == THESIS
    assert asked(thesis_call)["request"]["research_question"] == QUESTION
    # The card is the agent's, with the verdict beside it.
    assert response.json()["card"]["thesis"] == THESIS


def test_a_misstated_thesis_is_flagged_on_the_card_and_the_session_still_closes(
    atlas: Judged, llm: FakeLiteLLM
) -> None:
    session = atlas.open()
    fact_id = atlas.record(session, llm)
    llm.script_role("finding_judge", ChatReply.answer(misstated, tokens=(400, 40)))

    response = close(atlas, session, card(fact_id, thesis=OVERSTATED))

    assert response.status_code == 200, response.text
    judged = response.json()["card"]["thesis_judged"]
    assert judged["verdict"] == "misstated"
    assert judged["beyond"] == ["driven by data-center laser demand"]
    assert judged["kinds"] == ["unstated"]
    assert response.json()["finished_at"] is not None


def test_a_thesis_the_judge_cannot_reach_is_marked_unjudged(
    atlas: Judged, llm: FakeLiteLLM
) -> None:
    session = atlas.open()
    fact_id = atlas.record(session, llm)
    llm.script_role("finding_judge", ChatReply.error(503, "upstream overloaded"))

    response = close(atlas, session, card(fact_id, thesis=THESIS))

    assert response.status_code == 200, response.text
    judged = response.json()["card"]["thesis_judged"]
    assert judged["verdict"] == "unjudged"
    assert judged["fact_ids"] == [fact_id]


def test_a_thesis_over_a_card_that_cites_no_fact_is_unjudged_and_says_why(
    atlas: Judged, llm: FakeLiteLLM
) -> None:
    session = atlas.open()

    response = close(atlas, session, {"steps": [], "thesis": THESIS})

    assert response.status_code == 200, response.text
    judged = response.json()["card"]["thesis_judged"]
    assert judged["verdict"] == "unjudged"
    assert "cite no recorded Fact" in judged["reason"]
    assert judge_calls(llm) == []


def test_a_card_without_a_thesis_is_stored_as_it_came(atlas: Judged, llm: FakeLiteLLM) -> None:
    session = atlas.open()
    fact_id = atlas.record(session, llm)
    body = card(fact_id)

    response = close(atlas, session, body)

    assert response.status_code == 200, response.text
    assert response.json()["card"] == body
    assert len(judge_calls(llm)) == 1  # the Fact's, none for the card


# --- a Belief, judged when it is proposed ----


def belief(atlas: Judged, session: str | None, fact_id: str, statement: str) -> Any:
    return atlas.api.post(
        "/api/v1/beliefs",
        json={
            "statement": statement,
            "theme": "photonics",
            "step": "constraint",
            "company_ids": [atlas.company_id()],
            "as_of": AS_OF,
            "session_id": session,
            "citations": [
                {"kind": "fact", "ref_id": fact_id, "valence": 1.0, "weight": "load_bearing"}
            ],
        },
    )


def test_an_atomic_belief_judged_supported_is_proposed(atlas: Judged, llm: FakeLiteLLM) -> None:
    session = atlas.open()
    fact_id = atlas.record(session, llm)
    llm.script_role("finding_judge", ChatReply.answer(supported, tokens=(400, 40)))

    response = belief(atlas, session, fact_id, STATEMENT)

    assert response.status_code == 201, response.text
    assert response.json()["judgement"]["judgement"] == "unproven"
    belief_call = judge_calls(llm)[-1]
    request = asked(belief_call)
    assert request["request"]["finding"]["statement"] == STATEMENT
    assert [q["text"] for q in request["retrieved_data"]] == [REVENUE_QUOTE]


def test_a_compound_belief_is_refused_with_the_reasons_before_any_judge_call(
    atlas: Judged, llm: FakeLiteLLM
) -> None:
    session = atlas.open()
    fact_id = atlas.record(session, llm)
    calls = len(judge_calls(llm))

    response = belief(atlas, session, fact_id, COMPOUND)

    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "belief_compound"
    assert error["detail"]["reasons"] == ["a semicolon joins its clauses"]
    assert "Split it" in error["message"]
    assert len(judge_calls(llm)) == calls
    assert atlas.get("/api/v1/beliefs")["total"] == 0


def test_a_belief_that_says_more_than_its_load_bearing_quotes_is_refused(
    atlas: Judged, llm: FakeLiteLLM
) -> None:
    session = atlas.open()
    fact_id = atlas.record(session, llm)
    llm.script_role("finding_judge", ChatReply.answer(misstated, tokens=(400, 40)))

    response = belief(atlas, session, fact_id, OVERSTATED)

    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "belief_beyond_quotes"
    assert error["detail"]["beyond"] == ["driven by data-center laser demand"]
    assert atlas.get("/api/v1/beliefs")["total"] == 0


def test_a_belief_waits_when_the_judge_cannot_be_reached(atlas: Judged, llm: FakeLiteLLM) -> None:
    session = atlas.open()
    fact_id = atlas.record(session, llm)
    llm.script_role("finding_judge", ChatReply.error(503, "upstream overloaded"))

    response = belief(atlas, session, fact_id, STATEMENT)

    assert response.status_code == 503, response.text
    assert response.json()["error"]["code"] == "judge_unavailable"
    assert atlas.get("/api/v1/beliefs")["total"] == 0


def test_a_belief_with_no_session_is_not_judged_by_default(atlas: Judged, llm: FakeLiteLLM) -> None:
    fact_id = atlas.record(None, llm)

    response = belief(atlas, None, fact_id, COMPOUND)

    assert response.status_code == 201, response.text
    assert judge_calls(llm) == []


# --- through the MCP tools ----


def test_the_tools_carry_the_refusals_and_the_verdicts_to_the_agent(
    atlas: Judged, llm: FakeLiteLLM
) -> None:
    opened, value = atlas.call(
        "open_session", question=QUESTION, as_of=AS_OF, seeds=["lumentum"], actor="claude-session"
    )
    assert not opened, value
    session = value["session_id"]
    arguments = {
        "session_id": session,
        "version_id": atlas.version_id(),
        "quote": REVENUE_QUOTE,
        "step": "context",
        "status": "in_effect",
        "period": "Q4 FY2026",
        "quantity": {"value": 1.01, "unit": "USD billion", "metric": "net revenue"},
    }

    # A statement beyond its quote comes back as a refusal with the judge's words.
    llm.script_role("finding_judge", ChatReply.answer(misstated, tokens=(400, 40)))
    is_error, refused = atlas.call("record_fact", statement=OVERSTATED, **arguments)
    assert is_error
    assert refused["refused"] == "statement_beyond_quote"
    assert refused["beyond"] == ["driven by data-center laser demand"]
    assert refused["kinds"] == ["unstated"]
    assert "reason" in refused and "longer quote" in refused["message"]

    # Rewritten to what the quote says, it is recorded and says how it was judged.
    llm.script_role("finding_judge", ChatReply.answer(supported, tokens=(400, 40)))
    is_error, recorded = atlas.call("record_fact", statement=STATEMENT, **arguments)
    assert not is_error, recorded
    assert recorded["judged"] == "supported"
    fact_id = recorded["fact_id"]

    # An outage records it unjudged, and the answer says so.
    llm.script_role("finding_judge", ChatReply.error(503, "upstream overloaded"))
    other = arguments | {"quote": REVENUE_QUOTE.removeprefix("Net revenue for the ")}
    is_error, unjudged = atlas.call("record_fact", statement="Revenue was $1.01 billion.", **other)
    assert not is_error, unjudged
    assert unjudged["judged"] == "unjudged"
    assert unjudged["judge_note"]

    # A compound Belief is refused with its reasons; an atomic one goes through.
    citation = [{"fact_id": fact_id, "how": 1.0, "weight": "load_bearing"}]
    is_error, compound = atlas.call(
        "propose_belief",
        session_id=session,
        statement=COMPOUND,
        step="constraint",
        citations=citation,
        companies=["lumentum"],
    )
    assert is_error and compound["refused"] == "belief_compound"
    assert compound["reasons"] == ["a semicolon joins its clauses"]
    llm.script_role("finding_judge", ChatReply.answer(supported, tokens=(400, 40)))
    is_error, proposed = atlas.call(
        "propose_belief",
        session_id=session,
        statement=STATEMENT,
        step="constraint",
        citations=citation,
        companies=["lumentum"],
    )
    assert not is_error, proposed

    # The thesis verdict comes back with the close.
    llm.script_role("finding_judge", ChatReply.answer(supported, tokens=(400, 40)))
    is_error, closed = atlas.call(
        "close_session", session_id=session, card=card(fact_id, thesis=THESIS)
    )
    assert not is_error, closed
    assert closed["thesis_judged"]["verdict"] == "supported"


def test_nothing_in_the_database_changes_for_a_session_fact_refused_by_the_judge(
    atlas: Judged, llm: FakeLiteLLM
) -> None:
    session = atlas.open()
    llm.script_role("finding_judge", ChatReply.answer(misstated, tokens=(400, 40)))
    with atlas.engine.connect() as connection:
        before = connection.execute(text("SELECT count(*) FROM assertion")).scalar_one()

    response = atlas.api.post("/api/v1/facts", json=atlas.fact_body(session, OVERSTATED))

    assert response.status_code == 422
    with atlas.engine.connect() as connection:
        after = connection.execute(text("SELECT count(*) FROM assertion")).scalar_one()
        events = connection.execute(
            text("SELECT count(*) FROM audit_event WHERE action IN ('fact.created')")
        ).scalar_one()
        assert verify_chain(connection).breaks == []  # the dry run left no gap in the trail
    assert (before, after, events) == (0, 0, 0)
