"""The argument plan (bottleneck-argument ticket 05): `{"plan": "argument"}` runs Scout -> one
Reader per argument step, in parallel -> Skeptic (a Reader challenging their Facts) ||
Financial Analyst -> the Editor writing the argument, each of a step's statements held to its
Facts' quotes by the grounding check and the finding judge on its own (`editor-argument.v2`;
the v1 answer, one statement per step, is still read), each step's status decided by code.

Seam: `POST /api/v1/investigations`, single worker passes, and `/api/v1` (the investigation,
its events, the Facts, the run's role calls) with the requests the fakes received. The Source
Versions are the recorded Coherent EDGAR filings, ingested and retained through the fixture
path with the recorded Hindsight fake; SearXNG is the scripted fake over
`tests/fixtures/searxng/`. **Every role's answers are scripted here** (the Scout, the six
Readers, the Skeptic, the Financial Analyst, the Editor and the finding judge), each Reader's
computed from the request it answers (its step, the hits it was sent). The Readers' jobs run
in either order, so their answers are scripted by role and dispatched on the step. Nothing
live is called.
"""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from pydantic import JsonValue

from tests.fakes.hindsight import RecordedHindsight
from tests.fakes.litellm import ChatReply, FakeLiteLLM
from tests.fakes.searxng import FakeSearXNG, SearchReply
from tests.fakes.serve import Served, serve
from tests.harness import Atlas

QUESTION = (
    "Is Coherent's InP laser capacity the constraint on AI data-center optics, and who gains?"
)
AS_OF = "2026-09-30T00:00:00Z"
STEPS = ["constraint", "demand_vs_supply", "relief", "control", "capture", "invalidation"]
PLAN = [
    "scout",
    *(f"reader:{step}" for step in STEPS),
    "skeptic",
    "financial_analyst",
    "editor",
]
SUBSTRATE = "indium phosphide substrate capacity expansion 2026"
SECOND_SOURCE = "InP laser second source qualification hyperscaler"
QUERIES: list[JsonValue] = [
    {"query": SUBSTRATE, "purpose": "capacity"},
    {"query": SECOND_SOURCE, "purpose": "second sources"},
]
# From the Coherent FY2026 10-K (the recorded fixture's parsed text).
SHERMAN = "we announced the expansion of our Sherman, Texas, manufacturing facility"
SHERMAN_QUERY = "Sherman Texas manufacturing facility expansion"
AGREEMENT = (
    "On March 2, 2026, the Company entered into a multi-year strategic agreement with NVIDIA to"
    " advance the development of advanced optics technologies"
)
AGREEMENT_QUERY = "Agreements with NVIDIA strategic agreement development advanced optics"
COMPETITION = "We may encounter increased competition"
COMPETITION_QUERY = "increased competition backward integrate competencies"
ACTIONS = ("search_archive", "recall", "read", "record_fact", "done")
RELIEF_STATEMENT = "Coherent announced the expansion of its Sherman, Texas, manufacturing facility."
CONTROL_STATEMENT = (
    "Coherent entered into a multi-year strategic agreement with NVIDIA to advance the"
    " development of advanced optics technologies, and says it may encounter increased"
    " competition."
)
UNKNOWN_STATEMENT = "The Facts do not establish this step."


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
def searxng() -> FakeSearXNG:
    return FakeSearXNG()


@pytest.fixture
def searxng_served(searxng: FakeSearXNG) -> Iterator[Served]:
    with serve(searxng.handle) as served:
        yield served
        served.raise_errors()


@pytest.fixture
def atlas(
    database_url: str,
    tmp_path: Path,
    hindsight: tuple[RecordedHindsight, Served],
    litellm: Served,
    searxng_served: Served,
) -> Iterator[Atlas]:
    harness = Atlas(
        database_url,
        tmp_path,
        hindsight[1].url,
        litellm.url,
        searxng_url=searxng_served.url,
        finding_judge=True,
    )
    harness.apply_template()
    seeded = harness.cli("companies", "seed")
    assert seeded.returncode == 0, seeded.stderr
    harness.ingest_company("coherent")
    yield harness
    harness.engine.dispose()


# --- helpers --------------------------------------------------------------------------------------


def asked(body: dict[str, Any]) -> dict[str, Any]:
    return json.loads(body["messages"][1]["content"])


def act(name: str, **args: JsonValue) -> dict[str, JsonValue]:
    answer: dict[str, JsonValue] = {"action": name}
    answer.update({each: None for each in ACTIONS})
    answer[name] = args
    return answer


def holding(body: dict[str, Any], words: str) -> str:
    sent = [each for each in asked(body)["retrieved_data"] if words in each["text"]]
    assert sent, f"no passage sent holds {words!r}"
    return sent[0]["id"]


def record(
    body: dict[str, Any],
    quote: str,
    *,
    step: str,
    statement: str,
    status: str,
    period: str | None = None,
    challenges: list[str] | None = None,
) -> dict[str, JsonValue]:
    return act(
        "record_fact",
        passage_id=holding(body, quote),
        quote=quote,
        company_slug="coherent",
        step=step,
        statement=statement,
        quantity=None,
        period=period,
        status=status,
        challenges=list[JsonValue](challenges or []),
    )


def reading(body: dict[str, Any]) -> JsonValue:
    """The six Readers: Relief and Control each search, record one Fact and stop; the other
    steps search once, record nothing and stop (a done before any search is refused)."""
    request = asked(body)["request"]
    step = request["step"]["key"]
    searched, recorded = request["searched"], request["recorded"]
    if step == "relief":
        if not searched:
            return act("search_archive", query=SHERMAN_QUERY, company_slugs=["coherent"])
        if not recorded:
            return record(
                body,
                SHERMAN,
                step="relief",
                statement="Coherent announced the expansion of its Sherman, Texas,"
                " manufacturing facility during fiscal 2026.",
                status="planned",
                period="fiscal 2026",
            )
    if step == "control":
        if not searched:
            return act("search_archive", query=AGREEMENT_QUERY, company_slugs=["coherent"])
        if not recorded:
            return record(
                body,
                AGREEMENT,
                step="control",
                statement="Coherent entered into a multi-year strategic agreement with NVIDIA to"
                " advance the development of advanced optics technologies.",
                status="in_development",
                period="March 2, 2026",
            )
    if not searched:
        return act("search_archive", query=f"{step} wafers per month", company_slugs=["coherent"])
    return act("done", summary=f"{step}: nothing more found in Coherent's filings")


def challenging(body: dict[str, Any]) -> JsonValue:
    """The Skeptic: searches, records one counterevidence Fact against the Control Fact, stops."""
    request = asked(body)["request"]
    if not request["searched"]:
        return act("search_archive", query=COMPETITION_QUERY, company_slugs=["coherent"])
    if not request["recorded"]:
        [control] = [f["ref"] for f in request["challenge"] if f["step"] == "control"]
        return record(
            body,
            COMPETITION,
            step="control",
            statement="Coherent says it may encounter increased competition.",
            status="hedged",
            challenges=[control],
        )
    return act("done", summary="one risk against the NVIDIA agreement's control")


def editing(body: dict[str, Any]) -> JsonValue:
    """The argument's Editor in the v1 shape (one statement per step, still read): a statement
    for Relief and Control citing their Facts (Control with the counterevidence), the other
    steps unknown."""
    request = asked(body)["request"]
    steps: list[JsonValue] = []
    for step in request["steps"]:
        if step["step"] == "relief":
            statement, status = RELIEF_STATEMENT, "supported"
        elif step["step"] == "control":
            statement, status = CONTROL_STATEMENT, "disputed"
        else:
            statement, status = UNKNOWN_STATEMENT, "unknown"
        steps.append(
            {
                "step": step["step"],
                "status": status,
                "statement": statement,
                "fact_refs": step["fact_refs"],
                "counter_refs": step["counter_refs"],
                "unchecked": [f"whether {step['title'].lower()} holds beyond Coherent"],
            }
        )
    return {
        "steps": steps,
        "open_questions": ["What is Coherent's InP capacity in wafers per month?"],
        "verdict": "needs_review",
    }


SUPPORTED: JsonValue = {
    "verdict": "supported",
    "beyond": [],
    "kinds": [],
    "reason": "the quotes state it",
}

# editor-argument.v2: several statements per step, each checked on its own.
RELIEF_SECOND = "The expansion of the Sherman, Texas, manufacturing facility was announced."
RELIEF_UNGROUNDED = (
    "Coherent's Sherman, Texas, facility will add 6,000 wafer starts per month by 2027."
)
CONTROL_UNGROUNDED = "Coherent entered into a strategic agreement with Broadcom in 2025."


def editing_by_point(body: dict[str, Any]) -> JsonValue:
    """The argument's Editor in the v2 shape: three statements on Relief, one of them with a
    figure and a year its quote doesn't hold; one statement on Control naming a company and a
    year its quotes don't hold; the other steps unknown."""
    request = asked(body)["request"]
    steps: list[JsonValue] = []
    for step in request["steps"]:
        facts = step["fact_refs"]
        if step["step"] == "relief":
            statements: list[JsonValue] = [
                {"statement": RELIEF_STATEMENT, "fact_refs": facts, "counter_refs": []},
                {"statement": RELIEF_UNGROUNDED, "fact_refs": facts, "counter_refs": []},
                {"statement": RELIEF_SECOND, "fact_refs": facts, "counter_refs": []},
            ]
            status = "supported"
        elif step["step"] == "control":
            statements = [
                {
                    "statement": CONTROL_UNGROUNDED,
                    "fact_refs": facts,
                    "counter_refs": step["counter_refs"],
                }
            ]
            status = "disputed"
        else:
            statements = [{"statement": UNKNOWN_STATEMENT, "fact_refs": [], "counter_refs": []}]
            status = "unknown"
        steps.append(
            {"step": step["step"], "status": status, "statements": statements, "unchecked": []}
        )
    return {"steps": steps, "open_questions": [], "verdict": "needs_review"}


def regrounding_unchanged(body: dict[str, Any]) -> JsonValue:
    """The Editor asked again for its ungrounded statements writes them as they were."""
    findings = asked(body)["request"]["findings"]
    return {"findings": [{"finding": f["finding"], "statement": f["statement"]} for f in findings]}


# --- the test -------------------------------------------------------------------------------------


def test_an_argument_investigation_reads_each_step_challenges_it_and_writes_the_argument(
    atlas: Atlas, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    llm.script_role("reader", *(ChatReply.answer(reading, tokens=(1000, 50)),) * 14)
    llm.script_role("skeptic", *(ChatReply.answer(challenging, tokens=(1200, 60)),) * 3)
    llm.script_role("financial_analyst", ChatReply.json({"scenarios": []}, tokens=(1500, 200)))
    llm.script_role("finding_judge", *(ChatReply.json(SUPPORTED, tokens=(400, 40)),) * 2)
    llm.script_chat(
        ChatReply.json({"queries": QUERIES}, tokens=(900, 120)),  # the Scout
        ChatReply.answer(editing, tokens=(3000, 400)),  # the Editor
    )
    searxng.script(SUBSTRATE, SearchReply.of("inp-substrate-capacity"))
    searxng.script(SECOND_SOURCE, SearchReply.of("inp-laser-second-source"))
    coherent = atlas.company("coherent")["id"]

    response = atlas.api.post(
        "/api/v1/investigations",
        json={
            "theme": "photonics",
            "question": QUESTION,
            "seed_company_ids": [coherent],
            "as_of": AS_OF,
            "plan": "argument",
        },
    )
    assert response.status_code == 202, response.text
    started = response.json()
    # The plan is chosen by the request, recorded and visible from the start.
    assert started["plan"] == "argument"
    assert [task["key"] for task in started["tasks"]] == PLAN
    by_key = {task["key"]: task for task in started["tasks"]}
    assert all(by_key[f"reader:{step}"]["depends_on"] == ["scout"] for step in STEPS)
    assert all(by_key[f"reader:{step}"]["role"] == "reader" for step in STEPS)
    assert by_key["skeptic"]["depends_on"] == [f"reader:{step}" for step in STEPS]
    assert by_key["editor"]["depends_on"] == [
        *(f"reader:{step}" for step in STEPS),
        "skeptic",
        "financial_analyst",
    ]

    atlas.worker_pass()

    found = atlas.get(f"/api/v1/investigations/{started['id']}")
    assert {task["key"]: task["status"] for task in found["tasks"]} == {
        key: "succeeded" for key in PLAN
    }
    assert found["usage"]["companies"] == 0  # no Investigator: the Readers choose companies
    created = atlas.get(f"/api/v1/investigations/{started['id']}/events", limit=500)["items"][0]
    assert (created["type"], created["detail"]["plan_name"]) == ("created", "argument")
    roles = [body["metadata"]["role"] for body in llm.chat_requests()]
    assert roles.count("reader") == 14
    assert roles.count("skeptic") == 3
    assert (roles[0], roles[-3:]) == ("scout", ["editor", "finding_judge", "finding_judge"])
    assert {body["metadata"]["run_id"] for body in llm.chat_requests()} == {found["run_id"]}

    # Each Reader's task says what it searched, read and recorded.
    tasks = {task["key"]: task for task in found["tasks"]}
    relief = tasks["reader:relief"]["artifacts"]
    assert (relief["step"], relief["reader_status"], relief["facts_recorded"]) == (
        "relief",
        "done",
        1,
    )
    assert [s["query"] for s in relief["searches"]] == [SHERMAN_QUERY]
    assert tasks["reader:capture"]["artifacts"]["calls"] == 2
    # The Facts were recorded for the investigation: two by the Readers, one by the Skeptic.
    facts = atlas.get("/api/v1/facts", investigation_id=started["id"])["items"]
    assert sorted((f["step"], f["status"], f["assertion"]["quote"]) for f in facts) == sorted(
        [
            ("relief", "planned", SHERMAN),
            ("control", "in_development", AGREEMENT),
            ("control", "hedged", COMPETITION),
        ]
    )
    by_quote = {f["assertion"]["quote"]: f for f in facts}
    assert by_quote[COMPETITION]["assertion"]["extractor_version"] == "skeptic-argument.v2"
    assert by_quote[SHERMAN]["assertion"]["extractor_version"] == "reader.v2"
    # The Skeptic was sent the Readers' Facts to challenge, their quotes as low-trust data.
    skeptic_call = next(b for b in llm.chat_requests() if b["metadata"]["role"] == "skeptic")
    challenge = asked(skeptic_call)["request"]["challenge"]
    assert sorted(f["step"] for f in challenge) == ["control", "relief"]
    quoted = {each["id"]: each for each in asked(skeptic_call)["retrieved_data"]}
    assert {quoted[f["ref"]]["text"] for f in challenge} == {SHERMAN, AGREEMENT}
    assert tasks["skeptic"]["artifacts"]["facts_to_challenge"] == 2
    # The Financial Analyst was sent the Readers' Facts in place of Claims.
    analyst = next(b for b in llm.chat_requests() if b["metadata"]["role"] == "financial_analyst")
    assert sorted(c["predicate"] for c in asked(analyst)["request"]["claims"]) == ["fact", "fact"]

    # The Editor was sent each step with its Facts and counterevidence by short reference.
    editor_call = next(b for b in llm.chat_requests() if b["metadata"]["role"] == "editor")
    editor = asked(editor_call)["request"]
    assert [s["step"] for s in editor["steps"]] == STEPS
    sent_steps = {s["step"]: s for s in editor["steps"]}
    assert len(sent_steps["relief"]["fact_refs"]) == 1
    assert len(sent_steps["control"]["counter_refs"]) == 1
    [counter] = editor["counterevidence"]
    assert counter["against"] == sent_steps["control"]["fact_refs"]
    assert {e["text"] for e in asked(editor_call)["retrieved_data"]} >= {
        SHERMAN,
        AGREEMENT,
        COMPETITION,
    }

    # The card is the argument: each step with its status, statement, Facts, counterevidence
    # and what remains unchecked.
    card = found["research_card"]
    assert (card["plan"], card["findings"], card["editor_verdict"]) == (
        "argument",
        [],
        "needs_review",
    )
    steps = {step["step"]: step for step in card["steps"]}
    assert [step["step"] for step in card["steps"]] == STEPS
    assert {key: step["status"] for key, step in steps.items()} == {
        "constraint": "unknown",
        "demand_vs_supply": "unknown",
        "relief": "supported",
        "control": "disputed",
        "capture": "unknown",
        "invalidation": "unknown",
    }
    assert steps["relief"]["statement"] == RELIEF_STATEMENT
    assert (steps["relief"]["grounded"], steps["relief"]["judged"]) == (True, True)
    # The v1 answer's one statement is the step's one statement, with its cited Fact.
    [relief_said] = steps["relief"]["statements"]
    assert (relief_said["statement"], relief_said["judged"]) == (RELIEF_STATEMENT, True)
    assert [f["source_span"]["quote"] for f in relief_said["facts"]] == [SHERMAN]
    assert relief_said["counterevidence"] == []
    [control_said] = steps["control"]["statements"]
    assert [f["source_span"]["quote"] for f in control_said["facts"]] == [AGREEMENT]
    assert [f["source_span"]["quote"] for f in control_said["counterevidence"]] == [COMPETITION]
    assert steps["capture"]["statements"] == []
    [sherman] = steps["relief"]["facts"]
    assert (sherman["status"], sherman["period"], sherman["quantity"]) == (
        "planned",
        "fiscal 2026",
        None,
    )
    assert sherman["source_span"]["quote"] == SHERMAN
    ten_k = sherman["source_span"]["source_version_id"]
    span = sherman["source_span"]
    assert atlas.parsed(ten_k)[span["span_start"] : span["span_end"]] == SHERMAN
    assert steps["relief"]["counterevidence"] == []
    assert steps["relief"]["skeptic_checked"] is True
    assert steps["relief"]["searched"] == [SHERMAN_QUERY]
    [agreement] = steps["control"]["facts"]
    [competition] = steps["control"]["counterevidence"]
    assert competition["source_span"]["quote"] == COMPETITION
    assert competition["against"] == [agreement["fact_id"]]
    assert steps["control"]["statement"] == CONTROL_STATEMENT
    assert steps["control"]["editor_status"] == "disputed"
    # A step with no Fact has no statement, whatever the Editor wrote: it is unknown.
    assert steps["capture"]["statement"] is None
    assert "no Fact was recorded for this step" in steps["capture"]["unchecked"]
    assert steps["capture"]["reader_summary"] == "capture: nothing more found in Coherent's filings"
    # Both statements were judged against their quotes and kept.
    assert [(j["finding"], j["verdict"], j["outcome"]) for j in card["judged"]] == [
        ("f1", "supported", "kept"),
        ("f2", "supported", "kept"),
    ]
    assert card["open_questions"] == ["What is Coherent's InP capacity in wafers per month?"]
    assert card["unsupported_findings"] == []
    assert (found["status"], found["stop_reason"]) == ("stopped", "needs_review")
    assert found["stop_detail"] == (
        "steps unknown: constraint, demand_vs_supply, capture, invalidation;"
        " steps disputed: control; the Editor asks for review"
    )
    # The workbench list shows the plan too.
    listed = atlas.get("/api/v1/investigations")["items"]
    assert [(i["id"], i["plan"]) for i in listed] == [(started["id"], "argument")]


def test_each_statement_of_a_step_is_checked_on_its_own(
    atlas: Atlas, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    llm.script_role("reader", *(ChatReply.answer(reading, tokens=(1000, 50)),) * 14)
    llm.script_role("skeptic", *(ChatReply.answer(challenging, tokens=(1200, 60)),) * 3)
    llm.script_role("financial_analyst", ChatReply.json({"scenarios": []}, tokens=(1500, 200)))
    llm.script_role("finding_judge", *(ChatReply.json(SUPPORTED, tokens=(400, 40)),) * 2)
    llm.script_chat(
        ChatReply.json({"queries": QUERIES}, tokens=(900, 120)),  # the Scout
        ChatReply.answer(editing_by_point, tokens=(3000, 400)),  # the Editor
        ChatReply.answer(regrounding_unchanged, tokens=(800, 100)),  # asked again, once
    )
    searxng.script(SUBSTRATE, SearchReply.of("inp-substrate-capacity"))
    searxng.script(SECOND_SOURCE, SearchReply.of("inp-laser-second-source"))
    coherent = atlas.company("coherent")["id"]

    response = atlas.api.post(
        "/api/v1/investigations",
        json={
            "theme": "photonics",
            "question": QUESTION,
            "seed_company_ids": [coherent],
            "as_of": AS_OF,
            "plan": "argument",
        },
    )
    assert response.status_code == 202, response.text
    started = response.json()
    atlas.worker_pass()

    found = atlas.get(f"/api/v1/investigations/{started['id']}")
    roles = [body["metadata"]["role"] for body in llm.chat_requests()]
    assert roles[-4:] == ["editor", "editor", "finding_judge", "finding_judge"]
    # The two ungrounded statements were sent back together, once, and came back unchanged.
    reground = [b for b in llm.chat_requests() if b["metadata"]["role"] == "editor"][1]
    assert sorted(f["statement"] for f in asked(reground)["request"]["findings"]) == sorted(
        [RELIEF_UNGROUNDED, CONTROL_UNGROUNDED]
    )

    card = found["research_card"]
    steps = {step["step"]: step for step in card["steps"]}
    # Relief: one of its three statements is dropped; the other two stand, so it is supported.
    relief = steps["relief"]
    assert relief["status"] == "supported"
    assert [s["statement"] for s in relief["statements"]] == [RELIEF_STATEMENT, RELIEF_SECOND]
    assert all(s["judged"] is True for s in relief["statements"])
    assert all(
        [f["source_span"]["quote"] for f in s["facts"]] == [SHERMAN] for s in relief["statements"]
    )
    assert (relief["statement"], relief["grounded"], relief["judged"]) == (
        RELIEF_STATEMENT,
        True,
        True,
    )
    # Control: its only statement is dropped, so it is unknown, whatever stands against it.
    control = steps["control"]
    assert (control["status"], control["statement"], control["statements"]) == (
        "unknown",
        None,
        [],
    )
    assert control["editor_status"] == "disputed"
    assert [f["source_span"]["quote"] for f in control["facts"]] == [AGREEMENT]
    # Each dropped statement is in unsupported_findings with its reason.
    dropped = {each["statement"]: each for each in card["unsupported_findings"]}
    assert set(dropped) == {RELIEF_UNGROUNDED, CONTROL_UNGROUNDED}
    assert dropped[RELIEF_UNGROUNDED]["reason"].startswith("ungrounded: ")
    assert "6,000" in dropped[RELIEF_UNGROUNDED]["reason"]
    assert "Broadcom" in dropped[CONTROL_UNGROUNDED]["reason"]
    assert dropped[RELIEF_UNGROUNDED]["claim_ids"] == [relief["facts"][0]["fact_id"]]
    assert [(j["statement"], j["outcome"]) for j in card["judged"]] == [
        (RELIEF_STATEMENT, "kept"),
        (RELIEF_SECOND, "kept"),
    ]
    editor = next(t for t in found["tasks"] if t["key"] == "editor")["artifacts"]
    assert (editor["statements_kept"], editor["unsupported_findings"]) == (2, 2)
    assert editor["grounding"]["asked_again"] == 2
    assert found["stop_detail"] == (
        "steps unknown: constraint, demand_vs_supply, control, capture, invalidation;"
        " 2 statements were dropped; the Editor asks for review"
    )


def test_an_unusable_analyst_answer_leaves_the_card_to_the_editor(
    atlas: Atlas, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    # Ticket 07: on pilot question 2 the Analyst's answers were quarantined on every attempt,
    # the investigation stopped and the Editor was cancelled, so 188 Facts reached no card.
    unusable = ChatReply.json({"scenarios": [{"company_id": "x"}]}, tokens=(1500, 200))
    llm.script_role("reader", *(ChatReply.answer(reading, tokens=(1000, 50)),) * 14)
    llm.script_role("skeptic", *(ChatReply.answer(challenging, tokens=(1200, 60)),) * 3)
    llm.script_role("financial_analyst", unusable, unusable)  # the answer and its repair
    llm.script_role("finding_judge", *(ChatReply.json(SUPPORTED, tokens=(400, 40)),) * 2)
    llm.script_chat(
        ChatReply.json({"queries": QUERIES}, tokens=(900, 120)),  # the Scout
        ChatReply.answer(editing, tokens=(3000, 400)),  # the Editor
    )
    searxng.script(SUBSTRATE, SearchReply.of("inp-substrate-capacity"))
    searxng.script(SECOND_SOURCE, SearchReply.of("inp-laser-second-source"))
    coherent = atlas.company("coherent")["id"]

    response = atlas.api.post(
        "/api/v1/investigations",
        json={
            "theme": "photonics",
            "question": QUESTION,
            "seed_company_ids": [coherent],
            "as_of": AS_OF,
            "plan": "argument",
        },
    )
    assert response.status_code == 202, response.text
    started = response.json()
    atlas.worker_pass()

    found = atlas.get(f"/api/v1/investigations/{started['id']}")
    tasks = {task["key"]: task for task in found["tasks"]}
    analyst = tasks["financial_analyst"]
    assert analyst["status"] == "skipped"
    assert analyst["detail"].startswith("the Financial Analyst's answer was unusable")
    assert analyst["artifacts"]["analyst_failed"] is True
    # One job attempt: the quarantine is the task's outcome, not a failure to retry.
    roles = [body["metadata"]["role"] for body in llm.chat_requests()]
    assert roles.count("financial_analyst") == 2
    assert tasks["editor"]["status"] == "succeeded"
    card = found["research_card"]
    steps = {step["step"]: step for step in card["steps"]}
    assert steps["relief"]["statement"] == RELIEF_STATEMENT
    assert (found["status"], found["stop_reason"]) == ("stopped", "needs_review")


def test_the_default_plan_stays_the_default(atlas: Atlas) -> None:
    coherent = atlas.company("coherent")["id"]
    response = atlas.api.post(
        "/api/v1/investigations",
        json={"theme": "photonics", "question": QUESTION, "seed_company_ids": [coherent]},
    )
    assert response.status_code == 202, response.text
    started = response.json()
    assert started["plan"] == "default"
    assert [task["key"] for task in started["tasks"]] == [
        "scout",
        "investigator:coherent",
        "skeptic",
        "financial_analyst",
        "editor",
    ]
    refused = atlas.api.post(
        "/api/v1/investigations",
        json={"theme": "photonics", "question": QUESTION, "plan": "freeform"},
    )
    assert refused.status_code == 422


RELIEF_DOMAIN = (
    "Coherent announced only the expansion of its Sherman, Texas, manufacturing facility"
    " for gallium arsenide."
)


def editing_with_domain_term(body: dict[str, Any]) -> JsonValue:
    """The v2 Editor: on Relief one statement that adds a domain term and a scope word its quote
    lacks, and one that stands; the other steps unknown."""
    request = asked(body)["request"]
    steps: list[JsonValue] = []
    for step in request["steps"]:
        if step["step"] == "relief":
            facts = step["fact_refs"]
            statements: list[JsonValue] = [
                {"statement": RELIEF_DOMAIN, "fact_refs": facts, "counter_refs": []},
                {"statement": RELIEF_STATEMENT, "fact_refs": facts, "counter_refs": []},
            ]
            status = "supported"
        else:
            statements = [{"statement": UNKNOWN_STATEMENT, "fact_refs": [], "counter_refs": []}]
            status = "unknown"
        steps.append(
            {"step": step["step"], "status": status, "statements": statements, "unchecked": []}
        )
    return {"steps": steps, "open_questions": [], "verdict": "needs_review"}


def test_a_statement_adding_a_domain_term_or_qualifier_its_quotes_lack_is_sent_back_then_dropped(
    atlas: Atlas, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    llm.script_role("reader", *(ChatReply.answer(reading, tokens=(1000, 50)),) * 14)
    llm.script_role("skeptic", *(ChatReply.answer(challenging, tokens=(1200, 60)),) * 3)
    llm.script_role("financial_analyst", ChatReply.json({"scenarios": []}, tokens=(1500, 200)))
    llm.script_role("finding_judge", *(ChatReply.json(SUPPORTED, tokens=(400, 40)),) * 2)
    llm.script_chat(
        ChatReply.json({"queries": QUERIES}, tokens=(900, 120)),  # the Scout
        ChatReply.answer(editing_with_domain_term, tokens=(3000, 400)),  # the Editor
        ChatReply.answer(regrounding_unchanged, tokens=(800, 100)),  # asked again, once
    )
    searxng.script(SUBSTRATE, SearchReply.of("inp-substrate-capacity"))
    searxng.script(SECOND_SOURCE, SearchReply.of("inp-laser-second-source"))
    coherent = atlas.company("coherent")["id"]

    response = atlas.api.post(
        "/api/v1/investigations",
        json={
            "theme": "photonics",
            "question": QUESTION,
            "seed_company_ids": [coherent],
            "as_of": AS_OF,
            "plan": "argument",
        },
    )
    assert response.status_code == 202, response.text
    atlas.worker_pass()

    found = atlas.get(f"/api/v1/investigations/{response.json()['id']}")
    card = found["research_card"]
    [dropped] = card["unsupported_findings"]
    assert dropped["statement"] == RELIEF_DOMAIN
    assert dropped["reason"] == "ungrounded: gallium arsenide, only"
    relief = next(step for step in card["steps"] if step["step"] == "relief")
    assert [s["statement"] for s in relief["statements"]] == [RELIEF_STATEMENT]
