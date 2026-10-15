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
from typing import Any, cast

import pytest
from pydantic import JsonValue

from atlas.tradingview import TokenSet
from tests.fakes.hindsight import RecordedHindsight
from tests.fakes.litellm import ChatReply, FakeLiteLLM
from tests.fakes.searxng import FakeSearXNG, SearchReply
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


@pytest.fixture
def searxng() -> FakeSearXNG:
    return FakeSearXNG()


@pytest.fixture
def searxng_served(searxng: FakeSearXNG) -> Iterator[Served]:
    with serve(searxng.handle) as served:
        yield served
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
def researching(
    database_url: str,
    tmp_path: Path,
    hindsight: tuple[RecordedHindsight, Served],
    litellm: Served,
    tradingview: tuple[FakeTradingView, Served],
    searxng_served: Served,
) -> Iterator[Atlas]:
    """An Atlas that can run an investigation: SearXNG for the Scout, one Investigator call."""
    harness = build(
        database_url,
        tmp_path,
        hindsight,
        litellm,
        tradingview,
        finding_judge=True,
        searxng_url=searxng_served.url,
        investigator_passages_per_call=50,
    )
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


# --- the investigations' Editors judge with the speaker too -------------------------------------

AS_OF = "2026-09-30T00:00:00Z"
SUBSTRATE = "indium phosphide substrate capacity expansion 2026"
SECOND_SOURCE = "InP laser second source qualification hyperscaler"
SEARCH = "indium phosphide laser capacity constraint 1.6T transceiver shipments"
QUERIES: list[JsonValue] = [
    {"query": SUBSTRATE, "purpose": "capacity"},
    {"query": SECOND_SOURCE, "purpose": "second sources"},
]
ACTIONS = ("search_archive", "recall", "read", "record_fact", "done")


def script_searches(searxng: FakeSearXNG) -> None:
    searxng.script(SUBSTRATE, SearchReply.of("inp-substrate-capacity"))
    searxng.script(SECOND_SOURCE, SearchReply.of("inp-laser-second-source"))


def act(name: str, **args: JsonValue) -> dict[str, JsonValue]:
    answer: dict[str, JsonValue] = {"action": name}
    answer.update({each: None for each in ACTIONS})
    answer[name] = args
    return answer


def reading_the_ceo(body: dict[str, Any]) -> JsonValue:
    """The six Readers: Constraint searches the archive and records the CEO's sentence as a
    Fact; the others search once and stop."""
    request = asked(body)["request"]
    if not request["searched"]:
        return act("search_archive", query=SEARCH, company_slugs=["lumentum"])
    if request["step"]["key"] == "constraint" and not request["recorded"]:
        [passage] = [each for each in asked(body)["retrieved_data"] if CEO_QUOTE in each["text"]]
        return act(
            "record_fact",
            passage_id=passage["id"],
            quote=CEO_QUOTE,
            company_slug="lumentum",
            step="constraint",
            statement="Lumentum's CEO says laser capacity constrained 1.6T shipments.",
            quantity=None,
            period=None,
            status="in_effect",
            challenges=[],
        )
    return act("done", summary="nothing more found")


def searching_once(body: dict[str, Any]) -> JsonValue:
    request = asked(body)["request"]
    if not request["searched"]:
        return act("search_archive", query=SEARCH, company_slugs=["lumentum"])
    return act("done", summary="nothing to challenge")


def editing_the_argument(body: dict[str, Any]) -> JsonValue:
    """The argument Editor: the CEO's statement for Constraint, citing its Fact; the other
    steps unknown."""
    steps: list[JsonValue] = []
    for step in asked(body)["request"]["steps"]:
        constraint = step["step"] == "constraint"
        statement = CEO_STATEMENT if constraint else "The Facts do not establish this step."
        steps.append(
            {
                "step": step["step"],
                "status": "supported" if constraint else "unknown",
                "statements": [
                    {
                        "statement": statement,
                        "fact_refs": step["fact_refs"] if constraint else [],
                        "counter_refs": [],
                    }
                ],
                "unchecked": [],
            }
        )
    return {"steps": steps, "open_questions": [], "verdict": "needs_review"}


def judging_the_ceo(body: dict[str, Any]) -> JsonValue:
    """The finding judge on `CEO_STATEMENT`: the words naming the speaker rest on the label (no
    basis), the rest on the quote."""
    [quote] = asked(body)["retrieved_data"]
    return {
        "clauses": [
            {"text": "Alex Example, Lumentum's President and CEO", "ref": "c1", "basis": None},
            {
                "text": "indium phosphide laser capacity was the constraint on 1.6T transceiver"
                " shipments",
                "ref": "c1",
                "basis": quote["text"].removeprefix("our "),
            },
        ],
        "verdict": "supported",
        "beyond": [],
        "kinds": [],
        "reason": "the quote states it and its label names the speaker",
    }


def test_the_argument_editor_s_statements_are_judged_with_the_speaker_of_a_transcript_fact(
    researching: Atlas, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    transcript(researching)
    llm.script_role("reader", *(ChatReply.answer(reading_the_ceo, tokens=(1000, 50)),) * 14)
    llm.script_role("skeptic", *(ChatReply.answer(searching_once, tokens=(1200, 60)),) * 3)
    llm.script_role("financial_analyst", ChatReply.json({"scenarios": []}, tokens=(1500, 200)))
    llm.script_role("finding_judge", *(ChatReply.answer(judging_the_ceo, tokens=(400, 40)),) * 2)
    llm.script_role(
        "question_planner",
        ChatReply.json(
            {
                "parts": [
                    {
                        "key": "inp_capacity",
                        "text": "indium phosphide laser capacity the constraint",
                        "terms": ["indium phosphide", "1.6T", "shipments"],
                        "layer": "laser",
                    },
                    {
                        "key": "second_source",
                        "text": "second sources",
                        "terms": ["second source", "hyperscaler"],
                        "layer": None,
                    },
                ],
                "step_focus": [],
            },
            tokens=(700, 150),
        ),
    )
    llm.script_chat(
        ChatReply.json({"queries": QUERIES}, tokens=(900, 120)),  # the Scout
        ChatReply.answer(editing_the_argument, tokens=(3000, 400)),  # the Editor
    )
    script_searches(searxng)
    response = researching.api.post(
        "/api/v1/investigations",
        json={
            "theme": "photonics",
            "question": QUESTION,
            "seed_company_ids": [researching.company("lumentum")["id"]],
            "as_of": AS_OF,
            "plan": "argument",
        },
    )
    assert response.status_code == 202, response.text

    researching.worker_pass()

    found = researching.get(f"/api/v1/investigations/{response.json()['id']}")
    steps = {each["step"]: each for each in found["research_card"]["steps"]}
    # The statement naming the speaker was grounded, judged and kept.
    assert steps["constraint"]["statement"] == CEO_STATEMENT
    assert found["research_card"]["unsupported_findings"] == []
    [sent] = judge_requests(llm)
    assert [each["speaker"] for each in sent["request"]["claims"]] == [CEO]
    assert [each["text"] for each in sent["retrieved_data"]] == [CEO_QUOTE]


def test_the_default_card_s_findings_are_judged_with_the_speaker_of_a_transcript_claim(
    researching: Atlas, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    transcript(researching)
    lumentum = researching.company("lumentum")["id"]

    def investigating(body: dict[str, Any]) -> JsonValue:
        [passage] = [each for each in asked(body)["retrieved_data"] if CEO_QUOTE in each["text"]]
        start = passage["text"].index(CEO_QUOTE)
        return {
            "claims": [
                {
                    "subject_company_id": lumentum,
                    "predicate": "capacity_constrained",
                    "object_company_id": None,
                    "object_name": None,
                    "object_text": None,
                    "product": None,
                    "layer": None,
                    "epistemic_type": "company_claim",
                    "quote": CEO_QUOTE,
                    "passage_id": passage["id"],
                    "quote_start": start,
                    "quote_end": start + len(CEO_QUOTE),
                }
            ]
        }

    def skeptic(body: dict[str, Any]) -> JsonValue:
        return {"counterevidence": []} if "passages" in asked(body)["request"] else {"queries": []}

    def editing(body: dict[str, Any]) -> JsonValue:
        request = cast(dict[str, Any], asked(body)["request"])
        return {
            "findings": [
                {
                    "statement": CEO_STATEMENT,
                    "claim_refs": [each["ref"] for each in request["claims"]],
                    "limitations": [],
                    "open_questions": [],
                }
            ],
            "open_questions": [],
            "verdict": "answered",
        }

    llm.script_role("skeptic", *(ChatReply.answer(skeptic, tokens=(500, 50)),) * 8)
    llm.script_role("financial_analyst", ChatReply.json({"scenarios": []}, tokens=(1500, 200)))
    llm.script_role("finding_judge", ChatReply.answer(judging_the_ceo, tokens=(400, 40)))
    llm.script_chat(
        ChatReply.json({"queries": QUERIES}, tokens=(900, 120)),  # the Scout
        ChatReply.answer(investigating, tokens=(9000, 700)),
        ChatReply.answer(editing, tokens=(3000, 400)),
    )
    script_searches(searxng)
    response = researching.api.post(
        "/api/v1/investigations",
        json={
            "theme": "photonics",
            "question": QUESTION,
            "seed_company_ids": [lumentum],
            "as_of": AS_OF,
        },
    )
    assert response.status_code == 202, response.text

    researching.worker_pass()

    found = researching.get(f"/api/v1/investigations/{response.json()['id']}")
    [accepted] = researching.get("/api/v1/claims", outcome="accepted")["items"]
    assert accepted["speaker"].startswith("Alex Example (")
    card = found["research_card"]
    [finding] = card["findings"]
    assert finding["claim_text"] == CEO_STATEMENT and card["unsupported_findings"] == []
    [sent] = judge_requests(llm)
    assert [each["speaker"] for each in sent["request"]["claims"]] == [CEO]
