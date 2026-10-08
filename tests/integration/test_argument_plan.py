"""The argument plan (bottleneck-argument ticket 05): `{"plan": "argument"}` runs Scout -> one
Reader per argument step, in parallel -> Skeptic (a Reader challenging their Facts) ||
Financial Analyst -> the Editor writing the argument, each of a step's statements held to its
Facts' quotes by the grounding check and the finding judge on its own (`editor-argument.v2`;
the v1 answer, one statement per step, is still read), each step's status decided by code: a
step is disputed only by a Skeptic Fact the counter-judge finds contradicting one of its Facts
(pilot-review T3).

Seam: `POST /api/v1/investigations`, single worker passes, and `/api/v1` (the investigation,
its events, the Facts, the run's role calls) with the requests the fakes received. The Source
Versions are the recorded Coherent EDGAR filings, ingested and retained through the fixture
path with the recorded Hindsight fake; SearXNG is the scripted fake over
`tests/fixtures/searxng/`. **Every role's answers are scripted here** (the Scout, the six
Readers, the Skeptic, the counter-judge, the Financial Analyst, the Editor and the finding
judge), each Reader's
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
def judge_settings() -> dict[str, Any]:
    """The finding judge's settings beyond the harness's (one vote): a test parametrizes it."""
    return {}


@pytest.fixture
def atlas(
    database_url: str,
    tmp_path: Path,
    hindsight: tuple[RecordedHindsight, Served],
    litellm: Served,
    searxng_served: Served,
    judge_settings: dict[str, Any],
) -> Iterator[Atlas]:
    harness = Atlas(
        database_url,
        tmp_path,
        hindsight[1].url,
        litellm.url,
        searxng_url=searxng_served.url,
        finding_judge=True,
        **judge_settings,
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


def supporting(body: dict[str, Any]) -> JsonValue:
    """The finding judge (`finding_judge.v3`): supported, the statement one clause whose basis
    is the first cited quote, whole (code checks it occurs there)."""
    request = asked(body)
    statement = request["request"]["finding"]["statement"]
    quote = request["retrieved_data"][0]
    return {
        "clauses": [{"text": statement, "ref": quote["id"], "basis": quote["text"]}],
        "verdict": "supported",
        "beyond": [],
        "kinds": [],
        "reason": "the quotes state it",
    }


SUPPORTED = ChatReply.answer(supporting, tokens=(400, 40))


def relating(relation: str) -> Any:
    """The counter-judge answering `relation` for every Fact the counter-Fact challenges."""

    def answer(body: dict[str, Any]) -> JsonValue:
        challenged = asked(body)["request"]["challenged"]
        return {
            "relations": [
                {"ref": each["ref"], "relation": relation, "reason": f"k1 {relation} it"}
                for each in challenged
            ]
        }

    return answer


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
    llm.script_role("counter_judge", ChatReply.answer(relating("contradicts"), tokens=(600, 60)))
    llm.script_role("financial_analyst", ChatReply.json({"scenarios": []}, tokens=(1500, 200)))
    llm.script_role("finding_judge", *(SUPPORTED,) * 2)
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
    assert roles.count("counter_judge") == 1
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
    assert by_quote[COMPETITION]["assertion"]["extractor_version"] == "skeptic-argument.v3"
    assert by_quote[SHERMAN]["assertion"]["extractor_version"] == "reader.v3"
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
    assert sent_steps["invalidation"]["note"] == (
        "cite only the Facts listed for this step; the others were judged to support the"
        " argument or to be unrelated"
    )
    assert {s["note"] for k, s in sent_steps.items() if k != "invalidation"} == {None}
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
        # The Skeptic's Fact contradicts a thesis Fact (Control's): an observation against the
        # argument was found (R2-03).
        "invalidation": "found",
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
    assert [(r["fact_id"], r["relation"]) for r in competition["relations"]] == [
        (agreement["fact_id"], "contradicts")
    ]
    assert steps["control"]["contested"] is True
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
    assert [c["source_span"]["quote"] for c in steps["invalidation"]["counterevidence"]] == [
        COMPETITION
    ]
    assert found["stop_detail"] == (
        "steps unknown: constraint, demand_vs_supply, capture;"
        " steps disputed: control; invalidation: an observation against the argument was found;"
        " the Editor asks for review"
    )
    # No invalidation Fact was recorded, so none was judged.
    skeptic = tasks["skeptic"]["artifacts"]
    assert (skeptic["invalidation_relations"], skeptic["invalidation_judge_calls"]) == ({}, 0)
    # The workbench list shows the plan too.
    listed = atlas.get("/api/v1/investigations")["items"]
    assert [(i["id"], i["plan"]) for i in listed] == [(started["id"], "argument")]


def test_each_statement_of_a_step_is_checked_on_its_own(
    atlas: Atlas, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    llm.script_role("reader", *(ChatReply.answer(reading, tokens=(1000, 50)),) * 14)
    llm.script_role("skeptic", *(ChatReply.answer(challenging, tokens=(1200, 60)),) * 3)
    llm.script_role("counter_judge", ChatReply.answer(relating("contradicts"), tokens=(600, 60)))
    llm.script_role("financial_analyst", ChatReply.json({"scenarios": []}, tokens=(1500, 200)))
    llm.script_role("finding_judge", *(SUPPORTED,) * 2)
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
        "steps unknown: constraint, demand_vs_supply, control, capture;"
        " invalidation: an observation against the argument was found;"
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
    llm.script_role("counter_judge", ChatReply.answer(relating("contradicts"), tokens=(600, 60)))
    llm.script_role("financial_analyst", unusable, unusable)  # the answer and its repair
    llm.script_role("finding_judge", *(SUPPORTED,) * 2)
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


RELIEF_REWRITTEN = (
    "Coherent says it announced the expansion of its Sherman, Texas, manufacturing facility."
)
RELIEF_READING = (
    "Coherent announced the expansion of its Sherman, Texas, manufacturing facility during"
    " fiscal 2026."
)
# The votes the judge has been asked, by statement (the judge is asked one call at a time).
VOTES: dict[str, int] = {}


def judging_relief_misstated_once(body: dict[str, Any]) -> JsonValue:
    """The finding judge: the second vote on the Relief statement says misstated (its Fact is
    `planned`); every other vote is supported, with a verifiable basis."""
    statement = asked(body)["request"]["finding"]["statement"]
    VOTES[statement] = VOTES.get(statement, 0) + 1
    if statement == RELIEF_STATEMENT and VOTES[statement] == 2:
        return {
            "clauses": [{"text": "announced the expansion", "ref": None, "basis": None}],
            "verdict": "misstated",
            "beyond": ["announced the expansion"],
            "kinds": ["tense_or_status"],
            "reason": "vote 2: the cited Fact is planned",
        }
    return supporting(body)


def revising(body: dict[str, Any]) -> JsonValue:
    """The Editor's rewrite of a misstated statement."""
    findings = asked(body)["request"]["findings"]
    return {
        "findings": [
            {"finding": f["finding"], "statement": RELIEF_REWRITTEN, "limitations": []}
            for f in findings
        ]
    }


@pytest.mark.parametrize(
    "judge_settings", [{"finding_judge_votes": 2, "finding_judge_vote_rule": "any"}]
)
def test_the_argument_plan_asks_the_judge_as_many_votes_as_configured(
    atlas: Atlas, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    # Pilot 0.5.3: the argument plan asked one vote per statement whatever the setting.
    VOTES.clear()
    llm.script_role("reader", *(ChatReply.answer(reading, tokens=(1000, 50)),) * 14)
    llm.script_role("skeptic", *(ChatReply.answer(challenging, tokens=(1200, 60)),) * 3)
    llm.script_role("counter_judge", ChatReply.answer(relating("contradicts"), tokens=(600, 60)))
    llm.script_role("financial_analyst", ChatReply.json({"scenarios": []}, tokens=(1500, 200)))
    llm.script_role(
        "finding_judge",
        *(ChatReply.answer(judging_relief_misstated_once, tokens=(400, 40)),) * 6,
    )
    llm.script_chat(
        ChatReply.json({"queries": QUERIES}, tokens=(900, 120)),  # the Scout
        ChatReply.answer(editing, tokens=(3000, 400)),  # the Editor
        ChatReply.answer(revising, tokens=(800, 100)),  # its rewrite of the misstated one
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
    judge_calls = [b for b in llm.chat_requests() if b["metadata"]["role"] == "finding_judge"]
    # Two votes on each of the two statements, then two on the rewrite.
    assert len(judge_calls) == 6
    card = found["research_card"]
    relief = [
        (j["attempt"], j["vote"], j["verdict"], j["decided"], j["outcome"])
        for j in card["judged"]
        if j["finding"] == "f1"
    ]
    # Rule any: both votes asked; the misstated second vote decides and the statement goes to
    # the rewrite, which is judged by two votes again.
    assert relief == [
        (1, 1, "supported", False, "sent_back"),
        (1, 2, "misstated", True, "sent_back"),
        (2, 1, "supported", True, "kept"),
        (2, 2, "supported", False, "kept"),
    ]
    sent_back = next(j for j in card["judged"] if j["finding"] == "f1" and j["decided"])
    assert sent_back["reason"] == "vote 2: the cited Fact is planned"
    assert [j["verdict"] for j in card["judged"] if j["finding"] == "f2"] == [
        "supported",
        "supported",
    ]
    # Each vote's clauses and bases are on the card, verified.
    first = card["judged"][0]
    assert first["clauses"][0]["basis"] == SHERMAN
    assert first["unverified"] == []
    assert first["judge"] == "finding_judge.v3"
    steps = {step["step"]: step for step in card["steps"]}
    assert [s["statement"] for s in steps["relief"]["statements"]] == [RELIEF_REWRITTEN]
    # Every judge call was sent the cited Fact's reading: its status, period and statement.
    for body in judge_calls:
        claims = {c["ref"]: c for c in asked(body)["request"]["claims"]}
        assert all(c["predicate"] == "fact" for c in claims.values())
        assert all(c["status"] and c["reading"] for c in claims.values())
    relief_calls = [
        asked(b)["request"]["claims"]
        for b in judge_calls
        if asked(b)["request"]["finding"]["statement"] in {RELIEF_STATEMENT, RELIEF_REWRITTEN}
    ]
    assert len(relief_calls) == 4
    assert all(
        [(c["status"], c["period"], c["reading"]) for c in claims]
        == [("planned", "fiscal 2026", RELIEF_READING)]
        for claims in relief_calls
    )


def start_argument(atlas: Atlas, llm: FakeLiteLLM, searxng: FakeSearXNG) -> str:
    """An argument investigation of Coherent with the Readers, the Skeptic, the Analyst, the
    Scout and the Editor (v1 shape) scripted, run to its end; its ID."""
    llm.script_role("reader", *(ChatReply.answer(reading, tokens=(1000, 50)),) * 14)
    llm.script_role("skeptic", *(ChatReply.answer(challenging, tokens=(1200, 60)),) * 3)
    llm.script_role("financial_analyst", ChatReply.json({"scenarios": []}, tokens=(1500, 200)))
    llm.script_role("finding_judge", *(SUPPORTED,) * 2)
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
    atlas.worker_pass()
    return response.json()["id"]


@pytest.mark.parametrize("relation", ["qualifies", "contradicts"])
def test_the_skeptic_s_counter_fact_is_judged_and_disputes_only_when_it_contradicts(
    atlas: Atlas, llm: FakeLiteLLM, searxng: FakeSearXNG, relation: str
) -> None:
    # Pilot-review T3: on the four 0.5.3 cards none of the Skeptic's 50 Facts denied, limited
    # or dated what it was filed against, yet 14 of 24 steps were disputed.
    llm.script_role("counter_judge", ChatReply.answer(relating(relation), tokens=(600, 60)))
    investigation = start_argument(atlas, llm, searxng)

    found = atlas.get(f"/api/v1/investigations/{investigation}")
    assert {task["key"]: task["status"] for task in found["tasks"]} == {
        key: "succeeded" for key in PLAN
    }
    # One counter-judge call, in the run, for the Skeptic's one Fact, sent both quotes as
    # low-trust retrieved data: the counter-Fact's as k1, the Control Fact's by its reference.
    judged = [b for b in llm.chat_requests() if b["metadata"]["role"] == "counter_judge"]
    assert len(judged) == 1
    assert judged[0]["metadata"]["run_id"] == found["run_id"]
    request = asked(judged[0])["request"]
    assert request["research_question"] == QUESTION
    assert (request["counter"]["ref"], request["counter"]["step"]) == ("k1", "control")
    [challenged] = request["challenged"]
    assert challenged["step"] == "control"
    assert challenged["ref"].startswith("f")
    quoted = {each["id"]: each for each in asked(judged[0])["retrieved_data"]}
    assert set(quoted) == {"k1", challenged["ref"]}
    assert quoted["k1"]["text"] == COMPETITION
    assert quoted[challenged["ref"]]["text"] == AGREEMENT
    assert {each["trust"] for each in quoted.values()} == {"low"}

    facts = atlas.get("/api/v1/facts", investigation_id=investigation)["items"]
    by_quote = {f["assertion"]["quote"]: f["id"] for f in facts}
    competition, agreement = by_quote[COMPETITION], by_quote[AGREEMENT]
    skeptic = next(t for t in found["tasks"] if t["key"] == "skeptic")["artifacts"]
    assert skeptic["counter_relations"] == {competition: {agreement: relation}}
    assert skeptic["counter_relations_unjudged"] == []
    assert skeptic["counter_judge_calls"] == 1

    steps = {step["step"]: step for step in found["research_card"]["steps"]}
    control = steps["control"]
    # Either way the Skeptic's Fact is shown with Control's counterevidence, with its relation.
    [shown] = control["counterevidence"]
    assert shown["fact_id"] == competition
    assert [(r["fact_id"], r["relation"]) for r in shown["relations"]] == [(agreement, relation)]
    assert control["editor_status"] == "disputed"
    if relation == "qualifies":
        assert (control["status"], control["contested"], shown["against"]) == (
            "supported",
            False,
            [],
        )
        assert "steps disputed" not in found["stop_detail"]
    else:
        assert (control["status"], control["contested"], shown["against"]) == (
            "disputed",
            True,
            [agreement],
        )
        assert "steps disputed: control" in found["stop_detail"]
    assert not any("could not be judged" in note for note in control["unchecked"])


def test_a_failed_counter_judge_call_leaves_the_relation_unjudged_and_the_step_disputed(
    atlas: Atlas, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    unusable = ChatReply.json(
        {"relations": [{"ref": "f1", "relation": "denies", "reason": "?"}]}, tokens=(600, 60)
    )
    llm.script_role("counter_judge", unusable, unusable)  # the answer and its repair
    investigation = start_argument(atlas, llm, searxng)

    found = atlas.get(f"/api/v1/investigations/{investigation}")
    tasks = {task["key"]: task for task in found["tasks"]}
    # The quarantine is the pair's label, not the task's failure.
    assert tasks["skeptic"]["status"] == "succeeded"
    facts = atlas.get("/api/v1/facts", investigation_id=investigation)["items"]
    by_quote = {f["assertion"]["quote"]: f["id"] for f in facts}
    competition, agreement = by_quote[COMPETITION], by_quote[AGREEMENT]
    skeptic = tasks["skeptic"]["artifacts"]
    assert skeptic["counter_relations_unjudged"] == [competition]
    assert skeptic["counter_relations"] == {competition: {agreement: "unjudged"}}
    assert skeptic["counter_judge_calls"] == 1
    calls = atlas.get(f"/api/v1/runs/{found['run_id']}/role-calls")["role_calls"]
    assert [c["status"] for c in calls if c["role"] == "counter_judge"] == ["quarantined"]

    control = {step["step"]: step for step in found["research_card"]["steps"]}["control"]
    assert (control["status"], control["contested"]) == ("disputed", False)
    [shown] = control["counterevidence"]
    assert shown["against"] == [agreement]
    assert [r["relation"] for r in shown["relations"]] == ["unjudged"]
    assert "1 counter-Fact could not be judged" in control["unchecked"]


# --- the invalidation step (pilot-review R2-03) -----------------------------------------------
#
# On every reviewed card the invalidation step was `supported`, its statements arguing for the
# thesis. Each invalidation Fact is now judged against the thesis Facts it would break, and the
# step is `found` or `nothing_found`.

AGREEMENT_STATEMENT = (
    "Coherent entered into a multi-year strategic agreement with NVIDIA to advance the"
    " development of advanced optics technologies."
)
INVALIDATION_STATEMENT = "Coherent is expanding its Sherman, Texas, manufacturing facility."
COMPETITION_STATEMENT = "Coherent says it may encounter increased competition."


def reading_every_step(body: dict[str, Any]) -> JsonValue:
    """Six Readers each recording one Fact: the NVIDIA agreement under constraint, demand,
    control and capture, the Sherman expansion under relief, and under invalidation the
    seed's own capacity plan (the Sherman expansion again)."""
    request = asked(body)["request"]
    step = request["step"]["key"]
    searched, recorded = request["searched"], request["recorded"]
    sherman = step in ("relief", "invalidation")
    if not searched:
        query = SHERMAN_QUERY if sherman else AGREEMENT_QUERY
        return act("search_archive", query=query, company_slugs=["coherent"])
    if not recorded:
        if sherman:
            return record(
                body,
                SHERMAN,
                step=step,
                statement="Coherent announced the expansion of its Sherman, Texas,"
                " manufacturing facility during fiscal 2026.",
                status="planned",
                period="fiscal 2026",
            )
        return record(
            body,
            AGREEMENT,
            step=step,
            statement=AGREEMENT_STATEMENT,
            status="in_development",
            period="March 2, 2026",
        )
    return act("done", summary=f"{step}: one Fact recorded")


def reading_with_competition(body: dict[str, Any]) -> JsonValue:
    """The Readers of `reading`, but the invalidation Reader records the risk of competition
    (a competitor's qualification would read like it) under invalidation."""
    request = asked(body)["request"]
    if request["step"]["key"] != "invalidation":
        return reading(body)
    if not request["searched"]:
        return act("search_archive", query=COMPETITION_QUERY, company_slugs=["coherent"])
    if not request["recorded"]:
        return record(
            body,
            COMPETITION,
            step="invalidation",
            statement="Coherent says it may encounter increased competition.",
            status="hedged",
        )
    return act("done", summary="increased competition; no customer cancellation found")


def challenging_nothing(body: dict[str, Any]) -> JsonValue:
    """The Skeptic: searches once and finds nothing to record."""
    if not asked(body)["request"]["searched"]:
        return act("search_archive", query=COMPETITION_QUERY, company_slugs=["coherent"])
    return act("done", summary="nothing denies, limits or dates the Readers' Facts")


def editing_every_step(statements: dict[str, str], verdict: str) -> Any:
    """The v2 Editor writing one statement per step of `statements`, each citing the step's
    Facts; the invalidation statement cites every invalidation Fact it was sent, listed for the
    step or not."""

    def answer(body: dict[str, Any]) -> JsonValue:
        request = asked(body)["request"]
        invalidation = [f["ref"] for f in request["facts"] if f["step"] == "invalidation"]
        steps: list[JsonValue] = []
        for step in request["steps"]:
            refs = invalidation if step["step"] == "invalidation" else step["fact_refs"]
            said = statements.get(step["step"])
            entry: list[JsonValue] = (
                [{"statement": said, "fact_refs": refs, "counter_refs": []}]
                if said and refs
                else [{"statement": UNKNOWN_STATEMENT, "fact_refs": [], "counter_refs": []}]
            )
            steps.append(
                {
                    "step": step["step"],
                    "status": "supported" if said and refs else "unknown",
                    "statements": entry,
                    "unchecked": [],
                }
            )
        return {"steps": steps, "open_questions": [], "verdict": verdict}

    return answer


def run_argument(atlas: Atlas, llm: FakeLiteLLM, searxng: FakeSearXNG, editor: Any) -> str:
    """An argument investigation of Coherent, the Scout and the Editor scripted (the Readers,
    the Skeptic, the judges and the Analyst by the test), run to its end; its ID."""
    llm.script_role("financial_analyst", ChatReply.json({"scenarios": []}, tokens=(1500, 200)))
    llm.script_chat(
        ChatReply.json({"queries": QUERIES}, tokens=(900, 120)),  # the Scout
        ChatReply.answer(editor, tokens=(3000, 400)),  # the Editor
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
    return response.json()["id"]


def test_invalidation_facts_are_judged_against_the_thesis_and_a_supporting_one_is_not_a_finding(
    atlas: Atlas, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    llm.script_role("reader", *(ChatReply.answer(reading_every_step, tokens=(1000, 50)),) * 18)
    llm.script_role("skeptic", *(ChatReply.answer(challenging_nothing, tokens=(1200, 60)),) * 2)
    llm.script_role("counter_judge", ChatReply.answer(relating("supports"), tokens=(600, 60)))
    llm.script_role("finding_judge", *(SUPPORTED,) * 5)
    thesis = {
        step: AGREEMENT_STATEMENT
        for step in ("constraint", "demand_vs_supply", "control", "capture")
    }
    investigation = run_argument(
        atlas,
        llm,
        searxng,
        editing_every_step(
            {**thesis, "relief": RELIEF_STATEMENT, "invalidation": INVALIDATION_STATEMENT},
            "answered",
        ),
    )

    found = atlas.get(f"/api/v1/investigations/{investigation}")
    tasks = {task["key"]: task for task in found["tasks"]}
    assert {key: task["status"] for key, task in tasks.items()} == {
        key: "succeeded" for key in PLAN
    }
    facts = atlas.get("/api/v1/facts", investigation_id=investigation)["items"]
    by_step = {f["step"]: f["id"] for f in facts}
    invalidation_fact = by_step["invalidation"]
    # One judge call: the seed's capacity plan (k1) against the thesis, the seed's constraint,
    # demand and control Facts (f1...), every quote as low-trust retrieved data.
    [judged] = [b for b in llm.chat_requests() if b["metadata"]["role"] == "counter_judge"]
    request = asked(judged)["request"]
    assert (request["counter"]["ref"], request["counter"]["step"]) == ("k1", "invalidation")
    assert sorted(each["step"] for each in request["challenged"]) == [
        "constraint",
        "control",
        "demand_vs_supply",
    ]
    quoted = {each["id"]: each for each in asked(judged)["retrieved_data"]}
    assert quoted["k1"]["text"] == SHERMAN
    assert {quoted[each["ref"]]["text"] for each in request["challenged"]} == {AGREEMENT}
    assert {each["trust"] for each in quoted.values()} == {"low"}
    skeptic = tasks["skeptic"]["artifacts"]
    thesis_ids = {by_step[step] for step in ("constraint", "demand_vs_supply", "control")}
    assert skeptic["invalidation_relations"] == {
        invalidation_fact: dict.fromkeys(thesis_ids, "supports")
    }
    assert skeptic["invalidation_unjudged"] == []
    assert skeptic["invalidation_judge_calls"] == 1
    assert skeptic["counter_judge_calls"] == 0

    # The Editor was sent no invalidation Fact for the step, and told why.
    editor_call = next(b for b in llm.chat_requests() if b["metadata"]["role"] == "editor")
    sent = {s["step"]: s for s in asked(editor_call)["request"]["steps"]}
    assert sent["invalidation"]["fact_refs"] == []
    assert sent["invalidation"]["note"].startswith("cite only the Facts listed for this step")

    card = found["research_card"]
    steps = {step["step"]: step for step in card["steps"]}
    invalidation = steps["invalidation"]
    assert (invalidation["status"], invalidation["statement"], invalidation["statements"]) == (
        "nothing_found",
        None,
        [],
    )
    assert "nothing found against the argument after 1 search" in invalidation["unchecked"]
    assert invalidation["searched"] == [SHERMAN_QUERY]
    [shown] = invalidation["facts"]
    assert (shown["fact_id"], shown["against"]) == (invalidation_fact, [])
    assert {(r["fact_id"], r["relation"]) for r in shown["relations"]} == {
        (each, "supports") for each in thesis_ids
    }
    [dropped] = card["unsupported_findings"]
    assert dropped["statement"] == INVALIDATION_STATEMENT
    assert dropped["reason"].startswith("not_invalidating")
    assert dropped["claim_ids"] == [invalidation_fact]
    assert {key: step["status"] for key, step in steps.items() if key != "invalidation"} == {
        key: "supported" for key in STEPS if key != "invalidation"
    }
    # Found or nothing found, the invalidation step is settled: every other step is supported.
    assert (found["status"], found["stop_reason"]) == ("stopped", "answered")
    assert found["stop_detail"] == (
        "every step of the argument is supported by its Facts;"
        " invalidation: nothing found against the argument"
    )
    editor = tasks["editor"]["artifacts"]
    assert (editor["steps"]["invalidation"], editor["not_invalidating"]) == ("nothing_found", 1)


def test_a_competitor_s_qualification_recorded_under_invalidation_makes_the_step_found(
    atlas: Atlas, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    llm.script_role(
        "reader", *(ChatReply.answer(reading_with_competition, tokens=(1000, 50)),) * 15
    )
    llm.script_role("skeptic", *(ChatReply.answer(challenging_nothing, tokens=(1200, 60)),) * 2)
    llm.script_role("counter_judge", ChatReply.answer(relating("qualifies"), tokens=(600, 60)))
    llm.script_role("finding_judge", *(SUPPORTED,) * 3)
    investigation = run_argument(
        atlas,
        llm,
        searxng,
        editing_every_step(
            {
                "relief": RELIEF_STATEMENT,
                "control": AGREEMENT_STATEMENT,
                "invalidation": COMPETITION_STATEMENT,
            },
            "needs_review",
        ),
    )

    found = atlas.get(f"/api/v1/investigations/{investigation}")
    facts = atlas.get("/api/v1/facts", investigation_id=investigation)["items"]
    by_step = {f["step"]: f["id"] for f in facts}
    competition, agreement = by_step["invalidation"], by_step["control"]
    skeptic = next(t for t in found["tasks"] if t["key"] == "skeptic")["artifacts"]
    assert skeptic["invalidation_relations"] == {competition: {agreement: "qualifies"}}
    assert skeptic["invalidation_reasons"] == {competition: {agreement: "k1 qualifies it"}}
    # The Editor was sent the Fact for the step: it bears against the argument.
    editor_call = next(b for b in llm.chat_requests() if b["metadata"]["role"] == "editor")
    sent = {s["step"]: s for s in asked(editor_call)["request"]["steps"]}
    assert len(sent["invalidation"]["fact_refs"]) == 1

    invalidation = {s["step"]: s for s in found["research_card"]["steps"]}["invalidation"]
    assert invalidation["status"] == "found"
    assert invalidation["statement"] == COMPETITION_STATEMENT
    [said] = invalidation["statements"]
    assert said["judged"] is True
    [cited] = said["facts"]
    assert (cited["fact_id"], cited["against"]) == (competition, [agreement])
    assert [(r["fact_id"], r["relation"], r["reason"]) for r in cited["relations"]] == [
        (agreement, "qualifies", "k1 qualifies it")
    ]
    [shown] = invalidation["facts"]
    assert shown["against"] == [agreement]
    assert found["research_card"]["unsupported_findings"] == []
    assert "invalidation: an observation against the argument was found" in found["stop_detail"]


def test_a_failed_invalidation_judge_call_leaves_the_fact_unjudged_and_the_step_found_with_the_note(
    atlas: Atlas, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    unusable = ChatReply.json(
        {"relations": [{"ref": "f1", "relation": "denies", "reason": "?"}]}, tokens=(600, 60)
    )
    llm.script_role(
        "reader", *(ChatReply.answer(reading_with_competition, tokens=(1000, 50)),) * 15
    )
    llm.script_role("skeptic", *(ChatReply.answer(challenging_nothing, tokens=(1200, 60)),) * 2)
    llm.script_role("counter_judge", unusable, unusable)  # the answer and its repair
    llm.script_role("finding_judge", *(SUPPORTED,) * 3)
    investigation = run_argument(
        atlas,
        llm,
        searxng,
        editing_every_step(
            {
                "relief": RELIEF_STATEMENT,
                "control": AGREEMENT_STATEMENT,
                "invalidation": COMPETITION_STATEMENT,
            },
            "needs_review",
        ),
    )

    found = atlas.get(f"/api/v1/investigations/{investigation}")
    tasks = {task["key"]: task for task in found["tasks"]}
    # The quarantine is the Fact's label, not the task's failure.
    assert tasks["skeptic"]["status"] == "succeeded"
    facts = atlas.get("/api/v1/facts", investigation_id=investigation)["items"]
    by_step = {f["step"]: f["id"] for f in facts}
    competition, agreement = by_step["invalidation"], by_step["control"]
    skeptic = tasks["skeptic"]["artifacts"]
    assert skeptic["invalidation_unjudged"] == [competition]
    assert skeptic["invalidation_relations"] == {competition: {agreement: "unjudged"}}
    assert skeptic["invalidation_reasons"][competition][agreement].startswith(
        "the judge's answer was unusable"
    )
    assert skeptic["invalidation_judge_calls"] == 1
    calls = atlas.get(f"/api/v1/runs/{found['run_id']}/role-calls")["role_calls"]
    assert [c["status"] for c in calls if c["role"] == "counter_judge"] == ["quarantined"]

    invalidation = {s["step"]: s for s in found["research_card"]["steps"]}["invalidation"]
    assert invalidation["status"] == "found"
    assert invalidation["statement"] == COMPETITION_STATEMENT
    assert "1 invalidation Fact could not be judged" in invalidation["unchecked"]
    [shown] = invalidation["facts"]
    assert shown["against"] == [agreement]
    assert [r["relation"] for r in shown["relations"]] == ["unjudged"]


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
    llm.script_role("counter_judge", ChatReply.answer(relating("contradicts"), tokens=(600, 60)))
    llm.script_role("financial_analyst", ChatReply.json({"scenarios": []}, tokens=(1500, 200)))
    llm.script_role("finding_judge", *(SUPPORTED,) * 2)
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
