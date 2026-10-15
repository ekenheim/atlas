"""The judge knows whose words a transcript quote is (atlas-beliefs ticket 25).

Seam: the `/api/v1` API over Lumentum's recorded Q4 FY26 press release (a filing) and the
synthetic call transcript the TradingView fake serves (`tests/fixtures/tradingview/
view-syn-view-1001-t.json`, paragraphs labelled "Alex Example (President and CEO, Lumentum
Holdings Inc)", "Sam Sample (Managing Director and Equity Research Analyst, Example
Securities)", ...), the Hindsight fake, and the LiteLLM fake scripting the finding judge and the
Belief draft's Editor. Facts are recorded through `POST /api/v1/facts` at their real offsets.
The assertions read the requests the fake LiteLLM received: the judge is sent a transcript
quote's speaker as metadata of the claim (name, title, firm), never inside the quote's text; a
filing's claim has no `speaker` key; a statement naming the speaker passes the grounding check
and the judge's basis check. Nothing live.
"""

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import JsonValue

from atlas.tradingview import TokenSet
from tests.fakes.hindsight import RecordedHindsight
from tests.fakes.litellm import ChatReply, FakeLiteLLM
from tests.fakes.serve import Served, serve
from tests.fakes.tradingview import ACCESS_TOKEN, REFRESH_TOKEN, FakeTradingView
from tests.harness import Atlas

QUESTION = "Is indium phosphide laser capacity the constraint on 1.6T transceiver shipments?"
URL_EX991 = (
    "https://www.sec.gov/Archives/edgar/data/1633978/000162828026055726/lite_ex991xq4fy26.htm"
)
CEO_QUOTE = (
    "our indium phosphide laser capacity was the constraint on shipments of 1.6T transceivers"
)
ANALYST_QUOTE = "You said that we are expanding our indium phosphide wafer fab capacity"
FILING_QUOTE = "Net revenue for the fourth quarter of fiscal year 2026 was $1.01 billion"
CEO = {"name": "Alex Example", "title": "President and CEO", "firm": "Lumentum Holdings Inc"}
ANALYST = {
    "name": "Sam Sample",
    "title": "Managing Director and Equity Research Analyst",
    "firm": "Example Securities",
}
# Names the speaker as the label does: "Alex Example", "President" and "CEO" occur in no quote.
CEO_STATEMENT = (
    "Alex Example, Lumentum's President and CEO, said indium phosphide laser capacity was the"
    " constraint on 1.6T transceiver shipments."
)
FILING_STATEMENT = "Lumentum reported net revenue of $1.01 billion for its fourth fiscal quarter."


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


@pytest.fixture
def tradingview() -> Iterator[tuple[FakeTradingView, Served]]:
    fake = FakeTradingView()
    with serve(fake.handle) as served:
        yield fake, served
        served.raise_errors()


def build(
    database_url: str,
    tmp_path: Path,
    hindsight: tuple[RecordedHindsight, Served],
    litellm: Served,
    tradingview: tuple[FakeTradingView, Served],
    **overrides: Any,
) -> Atlas:
    served = tradingview[1]
    token_file = tmp_path / "tradingview-token.json"
    # Written plainly: `write_token_file` sets the mode with `os.fchmod`, which Windows lacks.
    token_file.write_text(
        json.dumps(
            TokenSet(
                access_token=ACCESS_TOKEN,
                refresh_token=REFRESH_TOKEN,
                expires_at=datetime.now(UTC) + timedelta(hours=1),
                token_endpoint=f"{served.url}/auth/token",
                client_id="fake-registered-client",
                resource=f"{served.url}/mcp",
            ).to_json()
        ),
        encoding="utf-8",
    )
    harness = Atlas(
        database_url,
        tmp_path,
        hindsight[1].url,
        litellm.url,
        tradingview_enabled=True,
        tradingview_mcp_url=f"{served.url}/mcp",
        tradingview_token_file=token_file,
        tradingview_rate_per_s=1.0,
        llm_role_models={"finding_judge": "luna", "counter_judge": "luna"},
        **overrides,
    )
    harness.apply_template()
    seeded = harness.cli("companies", "seed")
    assert seeded.returncode == 0, seeded.stderr
    harness.ingest_company("lumentum")
    return harness


@pytest.fixture
def atlas(
    database_url: str,
    tmp_path: Path,
    hindsight: tuple[RecordedHindsight, Served],
    litellm: Served,
    tradingview: tuple[FakeTradingView, Served],
) -> Iterator[Atlas]:
    harness = build(database_url, tmp_path, hindsight, litellm, tradingview, finding_judge=True)
    yield harness
    harness.engine.dispose()


@pytest.fixture
def always(
    database_url: str,
    tmp_path: Path,
    hindsight: tuple[RecordedHindsight, Served],
    litellm: Served,
    tradingview: tuple[FakeTradingView, Served],
) -> Iterator[Atlas]:
    harness = build(
        database_url,
        tmp_path,
        hindsight,
        litellm,
        tradingview,
        finding_judge=True,
        fact_statement_judge="always",
    )
    yield harness
    harness.engine.dispose()


def transcript(atlas: Atlas) -> str:
    """Record the synthetic call transcript through the TradingView catalog; its version ID."""
    payload = json.dumps({"company": "lumentum"})
    catalog_id = atlas.enqueue(
        "jobs", "enqueue", "tradingview_catalog", "--key", "lite", "--payload", payload
    )
    atlas.worker_pass()
    catalog = atlas.get(f"/api/v1/jobs/{catalog_id}")
    assert catalog["status"] == "succeeded", catalog["failures"]
    transcripts = atlas.get(f"/api/v1/jobs/{catalog['artifacts']['transcripts_job_id']}")
    assert transcripts["status"] == "succeeded", transcripts["failures"]
    [version_id] = transcripts["artifacts"]["source_versions"]
    return version_id


def asked(body: dict[str, Any]) -> dict[str, Any]:
    return json.loads(body["messages"][1]["content"])


def fact_body(atlas: Atlas, version_id: str, quote: str, statement: str) -> dict[str, Any]:
    parsed = atlas.parsed(version_id)
    assert parsed.count(quote) == 1
    start = parsed.index(quote)
    return {
        "subject_company_id": atlas.company("lumentum")["id"],
        "source_version_id": version_id,
        "quote": quote,
        "span_start": start,
        "span_end": start + len(quote),
        "epistemic_type": "company_claim",
        "step": "constraint",
        "statement": statement,
        "period": None,
        "status": "in_effect",
    }


def record(atlas: Atlas, version_id: str, quote: str, statement: str) -> str:
    response = atlas.api.post("/api/v1/facts", json=fact_body(atlas, version_id, quote, statement))
    assert response.status_code == 201, response.text
    return response.json()["fact"]["id"]


def filing(atlas: Atlas) -> str:
    return atlas.version(URL_EX991)["id"]


def supporting(body: dict[str, Any]) -> JsonValue:
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
        "reason": "the quotes state it",
    }


def naming_the_speaker(body: dict[str, Any]) -> JsonValue:
    """The finding judge on `CEO_STATEMENT` and `FILING_STATEMENT` as it should answer: the
    words naming the speaker rest on no quote's words (no basis), the rest on the quotes."""
    quotes = {each["id"]: each["text"] for each in asked(body)["retrieved_data"]}
    return {
        "clauses": [
            {"text": "Alex Example, Lumentum's President and CEO", "ref": "c1", "basis": None},
            {
                "text": "indium phosphide laser capacity was the constraint on 1.6T"
                " transceiver shipments",
                "ref": "c1",
                "basis": quotes["c1"].removeprefix("our "),
            },
            {
                "text": "Lumentum reported net revenue of $1.01 billion for its fourth fiscal"
                " quarter",
                "ref": "c2",
                "basis": quotes["c2"],
            },
        ],
        "verdict": "supported",
        "beyond": [],
        "kinds": [],
        "reason": "c1 states the constraint and its label names the speaker; c2 the revenue",
    }


def judge_requests(llm: FakeLiteLLM) -> list[dict[str, Any]]:
    """The user message (`request` and `retrieved_data`) of each finding judge call."""
    return [
        asked(body) for body in llm.chat_requests() if body["metadata"]["role"] == "finding_judge"
    ]


def test_a_transcript_quote_is_judged_with_its_speaker_and_a_filing_quote_with_none(
    atlas: Atlas, llm: FakeLiteLLM
) -> None:
    ceo = record(atlas, transcript(atlas), CEO_QUOTE, "Lumentum's CEO says capacity constrains.")
    revenue = record(atlas, filing(atlas), FILING_QUOTE, "Lumentum's Q4 net revenue was $1.01B.")
    llm.script_role("finding_judge", ChatReply.answer(naming_the_speaker, tokens=(600, 120)))

    response = atlas.api.post(
        "/api/v1/statements/judge",
        json={
            "question": QUESTION,
            "statement": f"{CEO_STATEMENT.removesuffix('.')}, and {FILING_STATEMENT}",
            "fact_ids": [ceo, revenue],
        },
    )

    assert response.status_code == 200, response.text
    judged = response.json()
    # The clause naming the speaker has no quote words to rest on: the label is its basis, so
    # the basis check does not turn the verdict.
    assert (judged["verdict"], judged["unverified"]) == ("supported", [])
    [sent] = judge_requests(llm)
    first, second = sent["request"]["claims"]
    assert first["ref"] == "c1" and first["speaker"] == CEO
    assert second["ref"] == "c2" and "speaker" not in second
    # Metadata beside the quote, never in its text: the quotes are the archived words alone.
    assert [each["text"] for each in sent["retrieved_data"]] == [CEO_QUOTE, FILING_QUOTE]
    assert "Alex Example" not in json.dumps(sent["retrieved_data"])


def test_an_analysts_quote_is_sent_with_the_analysts_label(atlas: Atlas, llm: FakeLiteLLM) -> None:
    analyst = record(
        atlas,
        transcript(atlas),
        ANALYST_QUOTE,
        "Lumentum is expanding its indium phosphide wafer fab capacity.",
    )
    llm.script_role("finding_judge", ChatReply.answer(supporting, tokens=(400, 40)))

    response = atlas.api.post(
        "/api/v1/statements/judge",
        json={
            "question": QUESTION,
            "statement": "Lumentum is expanding its indium phosphide wafer fab capacity.",
            "fact_ids": [analyst],
        },
    )

    assert response.status_code == 200, response.text
    [sent] = judge_requests(llm)
    [claim] = sent["request"]["claims"]
    # Not the company's words, and the label shows it: nothing hides who spoke.
    assert claim["speaker"] == ANALYST


def test_a_fact_judged_at_record_is_sent_its_speaker(always: Atlas, llm: FakeLiteLLM) -> None:
    llm.script_role(
        "finding_judge",
        ChatReply.answer(supporting, tokens=(400, 40)),
        ChatReply.answer(supporting, tokens=(400, 40)),
    )

    record(always, transcript(always), CEO_QUOTE, "Alex Example says capacity is the constraint.")
    record(always, filing(always), FILING_QUOTE, FILING_STATEMENT)

    transcript_call, filing_call = (sent["request"]["claims"] for sent in judge_requests(llm))
    assert transcript_call[0]["speaker"] == CEO
    assert "speaker" not in filing_call[0]


def draft(body: dict[str, Any]) -> JsonValue:
    """The Belief draft's Editor: one step statement that names the speaker the way the label
    does, a hedged thesis."""
    [belief] = asked(body)["request"]["beliefs"]
    return {
        "thesis_statement": "Lumentum may be straining its indium phosphide laser capacity.",
        "thesis_belief_refs": [belief["ref"]],
        "mechanism": {
            "demand_driver": "1.6T transceivers",
            "possible_constraint": "indium phosphide laser capacity",
            "economic_capture_question": None,
        },
        "measurable_predictions": ["Shipments stay constrained"],
        "catalysts": ["Capacity additions"],
        "falsifiers": ["A qualified second source comes online"],
        "required_evidence": ["Capacity figures"],
        "alternative_explanations": ["Inventory build"],
        "unresolved_questions": ["Is the constraint lasting?"],
        "steps": [
            {"step": "constraint", "statement": CEO_STATEMENT, "belief_refs": [belief["ref"]]}
        ],
    }


def test_a_statement_naming_the_speaker_is_grounded_and_judged_with_the_label(
    atlas: Atlas, llm: FakeLiteLLM
) -> None:
    fact = record(atlas, transcript(atlas), CEO_QUOTE, "Lumentum's CEO says capacity constrains.")
    lumentum = atlas.company("lumentum")["id"]
    belief = atlas.api.post(
        "/api/v1/beliefs",
        json={
            "statement": "Lumentum's indium phosphide laser capacity constrains 1.6T shipments.",
            "theme": "photonics",
            "step": "constraint",
            "company_ids": [lumentum],
            "as_of": "2026-09-30T00:00:00Z",
            "actor": "claude-session",
            "citations": [
                {"ref_id": fact, "valence": 0.9, "weight": "load_bearing", "note": "the CEO"}
            ],
        },
    )
    assert belief.status_code == 201, belief.text
    judged = atlas.api.post(
        f"/api/v1/beliefs/{belief.json()['id']}/judge",
        json={"actor": "owner", "judgement": "proven", "confidence": 0.8, "reason": "stated"},
    )
    assert judged.status_code == 200, judged.text
    llm.script_role("hypothesis_editor", ChatReply.answer(draft, tokens=(3000, 700)))
    llm.script_role("finding_judge", *(ChatReply.answer(supporting, tokens=(400, 40)),) * 2)
    created = atlas.api.post("/api/v1/hypotheses", json={"theme": "photonics"})
    assert created.status_code == 202, created.text

    atlas.worker_pass()

    hypothesis = atlas.get(f"/api/v1/hypotheses/{created.json()['id']}")
    assert hypothesis["draft_status"] == "drafted", hypothesis["draft_error"]
    content = hypothesis["versions"][0]["content"]
    # "Alex", "Example", "President" and "CEO" are in no quote: the label grounds them.
    assert [each["statement"] for each in content["steps"]] == [CEO_STATEMENT]
    assert content["unsupported_findings"] == []
    assert (content["steps"][0]["judged"], content["thesis_judged"]) == (True, "supported")
    # The thesis and the step were both judged with the speaker beside the quote.
    sent = judge_requests(llm)
    assert [each["request"]["claims"][0]["speaker"] for each in sent] == [CEO, CEO]
    assert [each["retrieved_data"][0]["text"] for each in sent] == [CEO_QUOTE, CEO_QUOTE]
