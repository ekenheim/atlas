"""An investigation's one bounded follow-up round on an open question, and what the research
workbench reads: the list of investigations, the Evidence tray and the saved Hypothesis
(Phase 3-6a ticket 17; spec "Research workflow", user stories 33 and 34).

Seams: `POST /api/v1/investigations` and `.../follow-up`, single worker passes, and
everything observed through `/api/v1` and the requests the fakes received. The first round
reads the recorded Coherent EDGAR filings; the follow-up round reads a hand-written note
(`tests/fixtures/investigations/lumentum-follow-up.txt`, imported for Lumentum between the
rounds), so it has new independent Evidence to find. LiteLLM is the scripted chat fake
(**every role's answer is written here**), SearXNG the scripted fake, Hindsight the recorded
fake. Nothing live is called.
"""

import json
import os
import subprocess
import sys
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import JsonValue
from sqlalchemy import text

from tests.fakes.hindsight import RecordedHindsight
from tests.fakes.litellm import ChatReply, FakeLiteLLM
from tests.fakes.searxng import FakeSearXNG, SearchReply
from tests.fakes.serve import Served, serve
from tests.harness import REPO, THEMES, Atlas

QUESTION = "Who supplies the lasers in AI data-center optics, and to whom?"
OPEN_QUESTION = "Does NVIDIA qualify a second laser source?"
CARD_QUESTION = "Is InP substrate capacity a constraint for 2027?"
SUBSTRATE = "indium phosphide substrate capacity expansion 2026"
SECOND_SOURCE = "InP laser second source qualification hyperscaler"
FOLLOW_UP_QUERY = "NVIDIA second laser source qualification 2026"
PLAN = [
    "scout",
    "investigator:coherent",
    "investigator:lumentum",
    "skeptic",
    "financial_analyst",
    "editor",
]
# From the Coherent FY2026 10-K (the recorded fixture's parsed text).
COHERENT_QUOTE = (
    "we announced the expansion of our Sherman, Texas, manufacturing facility, entered into a"
    " strategic multi-year supply agreement with NVIDIA for advanced lasers and optical"
    " networking products"
)
# From the hand-written note the follow-up round reads.
NOTE = REPO / "tests" / "fixtures" / "investigations" / "lumentum-follow-up.txt"
NOTE_URL = "https://notes.example.test/lumentum-nvidia-eml"
LUMENTUM_QUOTE = "Lumentum supplies NVIDIA with EML lasers for 1.6T transceivers"


# --- fixtures -------------------------------------------------------------------------------------


@pytest.fixture
def hindsight_fake() -> RecordedHindsight:
    fake = RecordedHindsight()
    fake.derive_memories()
    return fake


@pytest.fixture
def llm() -> FakeLiteLLM:
    return FakeLiteLLM()


@pytest.fixture
def searxng() -> FakeSearXNG:
    return FakeSearXNG()


@pytest.fixture
def litellm(llm: FakeLiteLLM) -> Iterator[Served]:
    with serve(llm.handle) as served:
        yield served
        served.raise_errors()


@pytest.fixture
def searxng_served(searxng: FakeSearXNG) -> Iterator[Served]:
    with serve(searxng.handle) as served:
        yield served
        served.raise_errors()


@pytest.fixture
def themes(tmp_path: Path) -> Path:
    """The repo's universe plus NVIDIA, which the 10-K and the note name."""
    universe = yaml.safe_load(THEMES.read_text(encoding="utf-8"))
    universe["companies"]["nvidia"] = {
        "legal_name": "NVIDIA Corporation",
        "display_name": "NVIDIA",
        "cik": "0001045810",
        "country": "US",
        "source_path": "sec",
    }
    path = tmp_path / "themes.yaml"
    path.write_text(yaml.safe_dump(universe), encoding="utf-8")
    return path


@pytest.fixture
def atlas(
    database_url: str,
    tmp_path: Path,
    hindsight: tuple[RecordedHindsight, Served],
    litellm: Served,
    searxng_served: Served,
    themes: Path,
) -> Iterator[Atlas]:
    """Atlas with the template applied, the universe seeded and Coherent ingested."""
    started = Atlas(
        database_url,
        tmp_path,
        hindsight[1].url,
        litellm.url,
        themes_config=themes,
        searxng_url=searxng_served.url,
        investigator_passages_per_call=50,
    )
    started.apply_template()
    seeded = subprocess.run(
        [sys.executable, "-m", "atlas", "companies", "seed"],
        cwd=tmp_path,
        env={
            "PATH": os.environ["PATH"],
            "HOME": str(tmp_path),
            "ATLAS_DATABASE_URL": database_url,
            "ATLAS_ACTOR": "local-researcher",
            "ATLAS_ARCHIVE_ROOT": str(started.archive),
            "ATLAS_THEMES_CONFIG": str(themes),
        },
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert seeded.returncode == 0, seeded.stderr
    started.ingest_company("coherent")
    yield started
    started.engine.dispose()


# --- helpers --------------------------------------------------------------------------------------


def company_id(atlas: Atlas, slug: str) -> str:
    return atlas.company(slug)["id"]


def start(atlas: Atlas, *slugs: str, **body: Any) -> dict[str, Any]:
    body = {
        "theme": "photonics",
        "question": QUESTION,
        "seed_company_ids": [company_id(atlas, slug) for slug in slugs],
    } | body
    response = atlas.api.post("/api/v1/investigations", json=body)
    assert response.status_code == 202, response.text
    return response.json()


def investigation(atlas: Atlas, investigation_id: str) -> dict[str, Any]:
    return atlas.get(f"/api/v1/investigations/{investigation_id}")


def events(atlas: Atlas, investigation_id: str) -> list[dict[str, Any]]:
    return atlas.get(f"/api/v1/investigations/{investigation_id}/events", limit=500)["items"]


def follow_up(atlas: Atlas, investigation_id: str, question: str = OPEN_QUESTION) -> Any:
    return atlas.api.post(
        f"/api/v1/investigations/{investigation_id}/follow-up", json={"question": question}
    )


def statuses(found: dict[str, Any], round_: int) -> dict[str, str]:
    return {t["key"]: t["status"] for t in found["tasks"] if t["round"] == round_}


def asked(body: dict[str, Any]) -> dict[str, Any]:
    return json.loads(body["messages"][1]["content"])


# The Skeptic and the Financial Analyst run in parallel, in either order: compared in plan order.
PARALLEL_ORDER = {"skeptic": 0, "financial_analyst": 1}


def requests(llm: FakeLiteLLM) -> list[dict[str, Any]]:
    """The chat requests, oldest first, with each run of consecutive Skeptic and Analyst
    requests put in plan order (the Skeptic's first)."""
    ordered: list[dict[str, Any]] = []
    run: list[dict[str, Any]] = []
    for body in [*llm.chat_requests(), None]:
        if body is not None and body["metadata"]["role"] in PARALLEL_ORDER:
            run.append(body)
            continue
        ordered.extend(sorted(run, key=lambda each: PARALLEL_ORDER[each["metadata"]["role"]]))
        run = []
        if body is not None:
            ordered.append(body)
    return ordered


def roles(llm: FakeLiteLLM) -> list[str]:
    return [body["metadata"]["role"] for body in requests(llm)]


def error_code(response: Any) -> str:
    return response.json()["error"]["code"]


def claim(atlas: Atlas, subject: str, quote: str, product: str) -> dict[str, JsonValue]:
    return {
        "subject_company_id": company_id(atlas, subject),
        "predicate": "supplies",
        "object_company_id": company_id(atlas, "nvidia"),
        "object_name": None,
        "object_text": None,
        "product": product,
        "layer": "chip-laser",
        "quote": quote,
        "epistemic_type": "company_claim",
    }


def quoting(*claims: dict[str, JsonValue]) -> Callable[[dict[str, Any]], JsonValue]:
    """An Investigator answer proposing each claim whose quote a passage it was sent holds."""

    def respond(body: dict[str, Any]) -> JsonValue:
        passages = asked(body)["retrieved_data"]
        answered: list[JsonValue] = []
        for each in claims:
            quote = str(each["quote"])
            holding = [p for p in passages if quote in p["text"]]
            if holding:
                at = holding[0]["text"].index(quote)
                answered.append(
                    each
                    | {
                        "passage_id": holding[0]["id"],
                        "quote_start": at,
                        "quote_end": at + len(quote),
                    }
                )
        return {"claims": answered}

    return respond


def editing(statement: str) -> Callable[[dict[str, Any]], JsonValue]:
    """An Editor answer: one finding citing every Claim it was sent, and two open questions."""

    def respond(body: dict[str, Any]) -> JsonValue:
        request = asked(body)["request"]
        return {
            "findings": [
                {
                    "statement": statement,
                    "claim_ids": [c["claim_id"] for c in request["claims"]],
                    "limitations": ["A company's own statement; no volumes or prices."],
                    "open_questions": [OPEN_QUESTION],
                }
            ],
            "open_questions": [CARD_QUESTION],
            "verdict": "answered",
        }

    return respond


def reviewing(body: dict[str, Any]) -> JsonValue:
    return {
        "reviews": [
            {
                "item_id": item["item_id"],
                "hedge": "none",
                "direction": "as_proposed",
                "layer": "correct",
                "suggested_layer": None,
                "reasoning": "the quote states it",
            }
            for item in asked(body)["request"]["items"]
        ]
    }


def finding_nothing(body: dict[str, Any]) -> JsonValue:
    """The Skeptic finding nothing: its plan writes no query, and its reading of what Memory
    pointed to (or code's fallback chose) proposes nothing."""
    if "passages" in asked(body)["request"]:
        return {"counterevidence": []}
    return {"queries": []}


# Enough answers for the plan and every reading call (the unused ones are never asked for).
NOTHING_TO_READ = (ChatReply.answer(finding_nothing, tokens=(500, 50)),) * 8
# The Financial Analyst (run each round while an accepted Claim names a seed company)
# proposes no scenario here; its proposals are ticket 19's tests (test_scenarios.py).
ANALYSED = ChatReply.json({"scenarios": []}, tokens=(1500, 200))


def script_parallel(llm: FakeLiteLLM) -> None:
    """Script the Skeptic's and the Financial Analyst's answers by role: their jobs are queued
    together and run in either order."""
    llm.script_role("skeptic", *NOTHING_TO_READ).script_role("financial_analyst", ANALYSED)


def first_round(atlas: Atlas, llm: FakeLiteLLM, searxng: FakeSearXNG, **body: Any) -> str:
    """Run round 1 (Coherent's 10-K supplies the one Claim) to an answered research card."""
    started = start(atlas, "coherent", "lumentum", **body)
    script_parallel(llm)
    llm.script_chat(
        ChatReply.json(
            {
                "queries": [
                    {"query": SUBSTRATE, "purpose": "InP substrate capacity"},
                    {"query": SECOND_SOURCE, "purpose": "second sources"},
                ]
            },
            tokens=(900, 120),
        ),
        ChatReply.answer(
            quoting(claim(atlas, "coherent", COHERENT_QUOTE, "advanced lasers")),
            tokens=(9000, 700),
        ),
        ChatReply.answer(
            editing("Coherent supplies NVIDIA with advanced lasers."), tokens=(3000, 400)
        ),
        ChatReply.answer(reviewing, tokens=(700, 90)),
    )
    searxng.script(SUBSTRATE, SearchReply.of("inp-substrate-capacity"))
    searxng.script(SECOND_SOURCE, SearchReply.of("inp-laser-second-source"))
    atlas.worker_pass()
    found = investigation(atlas, started["id"])
    assert (found["status"], found["stop_reason"]) == ("stopped", "answered"), found
    return started["id"]


def import_note(atlas: Atlas) -> None:
    """Record the hand-written note for Lumentum (published before the investigation's as-of
    time), then run its retention."""
    imported = atlas.cli(
        "sources",
        "import",
        "--company",
        "lumentum",
        "--file",
        str(NOTE),
        "--origin-url",
        NOTE_URL,
        "--published-at",
        "2026-08-20T12:00:00+00:00",
    )
    assert imported.returncode == 0, imported.stderr
    atlas.worker_pass()


# --- the follow-up round --------------------------------------------------------------------------


def test_a_follow_up_round_pursues_an_open_question_within_the_run_s_budgets(
    atlas: Atlas, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    investigation_id = first_round(atlas, llm, searxng)
    before = investigation(atlas, investigation_id)
    card_before = before["research_card"]
    assert before["usage"]["rounds"] == 1
    assert before["follow_ups"] == []
    import_note(atlas)

    response = follow_up(atlas, investigation_id)

    assert response.status_code == 200, response.text
    launched = response.json()
    assert (launched["status"], launched["stop_reason"], launched["stopped_at"]) == (
        "running",
        None,
        None,
    )
    assert launched["usage"]["rounds"] == 2
    [recorded] = launched["follow_ups"]
    assert (recorded["round"], recorded["question"], recorded["requested_by"]) == (
        2,
        OPEN_QUESTION,
        "local-researcher",
    )
    assert recorded["card_before"] == card_before
    # Round 2 is the same fixed plan, beside round 1's, which is kept as it ended.
    assert [t["key"] for t in launched["tasks"] if t["round"] == 2] == PLAN
    assert statuses(launched, 1) == statuses(before, 1)
    round_2 = statuses(launched, 2)
    assert round_2["scout"] == "queued"
    assert {round_2[key] for key in PLAN if key != "scout"} == {"pending"}
    [started_event] = [e for e in events(atlas, investigation_id) if e["round"] == 2][:1]
    assert (started_event["type"], started_event["round"]) == ("follow_up_started", 2)
    assert started_event["detail"]["question"] == OPEN_QUESTION
    assert started_event["detail"]["by"] == "local-researcher"
    with atlas.engine.connect() as connection:
        audited = connection.execute(
            text("SELECT actor FROM audit_event WHERE action = 'investigation.follow_up_started'")
        ).scalars()
        assert list(audited) == ["local-researcher"]

    # The round runs in the same run: the Scout searches for the open question, the
    # Investigators read only what the investigation hasn't (Coherent has nothing new; the
    # note is Lumentum's) with the open question for recall, then the Skeptic and the Financial
    # Analyst (over the investigation's accepted Claims), and the Editor.
    script_parallel(llm)
    llm.script_chat(
        ChatReply.json(
            {"queries": [{"query": FOLLOW_UP_QUERY, "purpose": "second source"}]},
            tokens=(400, 60),
        ),
        ChatReply.answer(
            quoting(claim(atlas, "lumentum", LUMENTUM_QUOTE, "EML lasers")), tokens=(2000, 300)
        ),
        ChatReply.answer(
            editing("Coherent and Lumentum both supply NVIDIA with lasers."), tokens=(3000, 400)
        ),
        ChatReply.answer(reviewing, tokens=(700, 90)),
    )
    searxng.script(FOLLOW_UP_QUERY, SearchReply.of("no-results"))
    atlas.worker_pass()

    found = investigation(atlas, investigation_id)
    assert (found["status"], found["stop_reason"]) == ("stopped", "answered")
    assert statuses(found, 2) == {
        "scout": "succeeded",
        "investigator:coherent": "succeeded",
        "investigator:lumentum": "succeeded",
        "skeptic": "succeeded",
        "financial_analyst": "succeeded",
        "editor": "succeeded",
    }
    # Each round's Skeptic asks Memory and plans, then reads where Memory points (a second
    # call): round 1 Coherent's filings, round 2 Lumentum's note (Coherent's were read by
    # round 1's Skeptic, so round 2's leaves them out).
    assert roles(llm)[7:] == [
        "scout",
        "investigator",
        "skeptic",
        "skeptic",
        "financial_analyst",
        "editor",
        "reviewer",
    ]
    sent = requests(llm)
    assert {body["metadata"]["run_id"] for body in sent[7:13]} == {found["run_id"]}
    assert asked(sent[7])["request"]["research_question"] == OPEN_QUESTION
    round_2 = {t["key"]: t for t in found["tasks"] if t["round"] == 2}
    assert round_2["investigator:coherent"]["artifacts"]["documents"] == 0
    discovery = atlas.get(f"/api/v1/discoveries/{round_2['scout']['artifacts']['discovery_id']}")
    assert discovery["question"] == OPEN_QUESTION
    extraction = atlas.get(
        f"/api/v1/claim-extractions/{round_2['investigator:lumentum']['artifacts']['extraction_id']}"
    )
    assert extraction["question"] == OPEN_QUESTION
    # Each round asks Memory its own question (query 0) and keeps its own reading pointers.
    assert {(p["round"], p["query"]) for p in found["pointers"] if p["query_index"] == 0} == {
        (1, QUESTION),
        (2, OPEN_QUESTION),
    }
    assert round_2["scout"]["artifacts"]["pointers"] == sum(
        1 for p in found["pointers"] if p["round"] == 2 and p["task_key"] == "scout"
    )
    assert [d["title"] for d in found["documents"] if d["task_key"] == "investigator:lumentum"] == [
        "lumentum-follow-up.txt"
    ]
    # The new card cites both rounds' Claims; the one before the round is kept with it.
    [finding] = found["research_card"]["findings"]
    assert [span["quote"] for span in finding["source_spans"]] == [COHERENT_QUOTE, LUMENTUM_QUOTE]
    assert found["follow_ups"][0]["card_before"] == card_before
    assert found["usage"]["rounds"] == 2
    assert found["usage"]["tokens_in"] == (
        900 + 9000 + 500 + 500 + 1500 + 3000 + 400 + 2000 + 500 + 500 + 1500 + 3000
    )
    # Round 1's Skeptic read where Memory pointed (Coherent's filings): no fallback. Round
    # 2's asked about Lumentum too (its Claim is the round's); Memory holds nothing of
    # Lumentum's and Coherent's filings were read by round 1's Skeptic, so code's fallback
    # chose the one document left, Lumentum's note.
    skeptics = [r for r in found["research_card"]["read"] if r["role"] == "skeptic"]
    assert [(r["round"], r["documents_fallback"]) for r in skeptics] == [(1, False), (2, True)]
    assert {d["selected_by"] for d in skeptics[0]["documents"]} == {"pointer"}
    assert [(d["title"], d["selected_by"]) for d in skeptics[1]["documents"]] == [
        ("lumentum-follow-up.txt", "fallback")
    ]
    assert (skeptics[1]["passages"], skeptics[1]["detail"]) == (1, None)
    asked_about = {
        (p["round"], p["query_company_name"])
        for p in found["pointers"]
        if p["task_key"] == "skeptic"
    }
    assert asked_about == {
        (1, "Coherent"),
        (1, "NVIDIA"),
        (2, "Coherent"),
        (2, "Lumentum"),
        (2, "NVIDIA"),
    }
    # The Evidence tray: each accepted Claim with its source span, by round.
    tray = [
        (e["round"], e["subject_name"], e["object_name"], e["quote"]) for e in found["evidence"]
    ]
    assert tray == [
        (1, "Coherent", "NVIDIA", COHERENT_QUOTE),
        (2, "Lumentum", "NVIDIA", LUMENTUM_QUOTE),
    ]
    assert found["evidence"][1]["source_title"] == "lumentum-follow-up.txt"
    assert found["evidence"][1]["excluded"] is False
    # Round 2's stop queues the review of round 2's Assertions only.
    reviews = [
        e for e in events(atlas, investigation_id) if e["type"] == "relationship_review_queued"
    ]
    assert [e["detail"]["assertions"] for e in reviews] == [1, 1]
    job = atlas.get(f"/api/v1/jobs/{reviews[1]['detail']['job_ids'][0]}")
    assert job["payload"] == {"assertion_ids": [found["evidence"][1]["assertion_id"]]}

    # One follow-up round: the round budget (≤ 2 rounds) is spent.
    again = follow_up(atlas, investigation_id, CARD_QUESTION)
    assert again.status_code == 409
    assert error_code(again) == "round_budget_spent"


def test_a_follow_up_with_nothing_new_to_read_stops_without_new_independent_evidence(
    atlas: Atlas, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    investigation_id = first_round(atlas, llm, searxng)
    card_before = investigation(atlas, investigation_id)["research_card"]

    response = follow_up(atlas, investigation_id, CARD_QUESTION)

    assert response.status_code == 200, response.text
    script_parallel(llm)
    llm.script_chat(ChatReply.json({"queries": [{"query": FOLLOW_UP_QUERY, "purpose": None}]}))
    searxng.script(FOLLOW_UP_QUERY, SearchReply.of("no-results"))
    atlas.worker_pass()
    found = investigation(atlas, investigation_id)
    assert (found["status"], found["stop_reason"]) == ("stopped", "no_new_independent_evidence")
    # No Investigator read anything new, so the Editor made no call; the card is round 1's.
    # (The Skeptic and the Analyst still see round 1's accepted Claim.)
    # (Round 2's Skeptic plans only: nothing is archived that round 1's Skeptic didn't read.)
    assert roles(llm)[7:] == ["scout", "skeptic", "financial_analyst"]
    assert found["research_card"] == card_before


def test_a_follow_up_round_reads_the_companies_its_own_question_s_pointers_name(
    atlas: Atlas, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    # Round 1: Memory holds only the seed Coherent's filings, so its plan is the seeds'.
    investigation_id = first_round(atlas, llm, searxng)
    before = investigation(atlas, investigation_id)
    assert [t["key"] for t in before["tasks"]] == PLAN
    assert [(c["slug"], c["outcome"]) for c in before["pointed_companies"]] == [
        ("coherent", "seed")
    ]
    # Between the rounds a document of AXT, a theme company that is no seed, is archived and
    # retained (a hand-written note, not an AXT document; plain English, so it is retained).
    note = atlas.tmp_path / "axt-note.txt"
    note.write_text(
        "Synthetic test note: this is a hand-written note for a test, and it is not a"
        " document of AXT.\n\n"
        "The note says that AXT is one of the companies in the supply chain of the lasers that"
        " are used in data centers, and that it has not named any of its customers here.\n",
        encoding="utf-8",
    )
    imported = atlas.cli(
        "sources",
        "import",
        "--company",
        "axt",
        "--file",
        str(note),
        "--origin-url",
        "https://notes.example.test/axt-note",
        "--published-at",
        "2026-08-21T12:00:00+00:00",
        "--title",
        "axt-note",
    )
    assert imported.returncode == 0, imported.stderr
    atlas.worker_pass()
    axt = atlas.company("axt")

    assert follow_up(atlas, investigation_id).status_code == 200
    script_parallel(llm)
    llm.script_chat(
        ChatReply.json({"queries": [{"query": FOLLOW_UP_QUERY, "purpose": "second source"}]}),
        ChatReply.json({"claims": []}),  # AXT's Investigator: the note states no relation
    )
    searxng.script(FOLLOW_UP_QUERY, SearchReply.of("no-results"))
    atlas.worker_pass()

    found = investigation(atlas, investigation_id)
    assert (found["status"], found["stop_reason"]) == ("stopped", "no_new_independent_evidence")
    # Round 2 asked Memory the open question and its query; the answers point to AXT's note
    # too, so round 2's plan gains AXT's Investigator. Round 1's plan is as it ended.
    assert [t["key"] for t in found["tasks"] if t["round"] == 1] == PLAN
    assert [t["key"] for t in found["tasks"] if t["round"] == 2] == [
        *PLAN[:3],
        "investigator:axt",
        *PLAN[3:],
    ]
    round_2 = {t["key"]: t for t in found["tasks"] if t["round"] == 2}
    investigators = [*PLAN[1:3], "investigator:axt"]
    assert round_2["skeptic"]["depends_on"] == investigators
    assert round_2["editor"]["depends_on"] == [*investigators, "skeptic", "financial_analyst"]
    pointers = [
        p for p in found["pointers"] if p["company_id"] == axt["id"] and p["task_key"] == "scout"
    ]
    assert {(p["round"], p["query"]) for p in pointers} == {
        (2, OPEN_QUESTION),
        (2, FOLLOW_UP_QUERY),
    }
    assert [
        (c["round"], c["slug"], c["outcome"], c["task_key"]) for c in found["pointed_companies"]
    ] == [
        (1, "coherent", "seed", "investigator:coherent"),
        (2, "coherent", "seed", "investigator:coherent"),
        (2, "axt", "added", "investigator:axt"),
    ]
    assert round_2["investigator:axt"]["artifacts"]["added_for_pointers"]["pointers"] == 2
    rankings = [e for e in events(atlas, investigation_id) if e["type"] == "companies_ranked"]
    assert [(e["round"], e["detail"]["added"]) for e in rankings] == [
        (1, []),
        (2, ["investigator:axt"]),
    ]
    # It read the note, with the open question; the seeds had nothing new to read.
    assert [d["title"] for d in found["documents"] if d["task_key"] == "investigator:axt"] == [
        "axt-note"
    ]
    extraction = atlas.get(
        f"/api/v1/claim-extractions/{round_2['investigator:axt']['artifacts']['extraction_id']}"
    )
    assert extraction["question"] == OPEN_QUESTION
    assert round_2["investigator:coherent"]["artifacts"]["documents"] == 0
    assert roles(llm)[7:9] == ["scout", "investigator"]
    assert roles(llm).count("investigator") == 2  # round 1's Coherent, round 2's AXT
    assert [p["key"] for p in found["premises"]][-1] == "company:axt"


def test_a_disproven_company_premise_cancels_only_its_follow_up_investigator(
    atlas: Atlas, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    investigation_id = first_round(atlas, llm, searxng)
    # The premise is disproven while round 2 runs: its Investigator is cancelled.
    assert follow_up(atlas, investigation_id).status_code == 200
    disproved = atlas.api.post(
        f"/api/v1/investigations/{investigation_id}/premises/company:lumentum/disprove",
        json={"reason": "Lumentum makes no lasers for NVIDIA"},
    )
    assert disproved.status_code == 200, disproved.text
    round_2 = statuses(disproved.json(), 2)
    assert round_2["investigator:lumentum"] == "cancelled"
    assert round_2["investigator:coherent"] == "pending"
    assert round_2["scout"] == "queued"


def test_a_follow_up_is_refused_unless_it_is_allowed(
    atlas: Atlas, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    missing = follow_up(atlas, str(uuid.uuid4()))
    assert (missing.status_code, error_code(missing)) == (404, "not_found")

    # One round allowed: no follow-up.
    one_round = first_round(atlas, llm, searxng, budgets={"max_rounds": 1})
    refused = follow_up(atlas, one_round)
    assert (refused.status_code, error_code(refused)) == (409, "round_budget_spent")

    investigation_id = first_round(atlas, llm, searxng)
    # Only an open question of the research card.
    unknown = follow_up(atlas, investigation_id, "Who makes the DSPs?")
    assert (unknown.status_code, error_code(unknown)) == (422, "unknown_open_question")
    blank = follow_up(atlas, investigation_id, "  ")
    assert (blank.status_code, error_code(blank)) == (422, "invalid_request")

    # A running investigation (round 2 under way) has no follow-up of its own yet.
    running = start(atlas, "coherent")
    busy = follow_up(atlas, running["id"])
    assert (busy.status_code, error_code(busy)) == (409, "follow_up_not_allowed")

    # A saved Hypothesis is drawn from the card: no follow-up changes it afterwards.
    saved = atlas.api.post("/api/v1/hypotheses", json={"investigation_id": investigation_id})
    assert saved.status_code == 202, saved.text
    assert (
        investigation(atlas, investigation_id)["request"]["hypothesis_id"] == (saved.json()["id"])
    )
    after = follow_up(atlas, investigation_id)
    assert (after.status_code, error_code(after)) == (409, "hypothesis_saved")


def test_a_budget_exhausted_investigation_is_resumed_not_followed_up(
    atlas: Atlas, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    started = start(atlas, "coherent", budgets={"token_budget": 1000})
    llm.script_chat(
        ChatReply.json({"queries": [{"query": SUBSTRATE, "purpose": None}]}, tokens=(900, 150))
    )
    searxng.script(SUBSTRATE, SearchReply.of("inp-substrate-capacity"))
    atlas.worker_pass()
    assert investigation(atlas, started["id"])["stop_reason"] == "budget_exhausted"

    refused = follow_up(atlas, started["id"])

    assert (refused.status_code, error_code(refused)) == (409, "follow_up_not_allowed")
    assert "resume" in refused.json()["error"]["message"]


def test_the_workbench_lists_investigations_newest_first(atlas: Atlas) -> None:
    first = start(atlas, "coherent")
    second = start(atlas, "coherent", "lumentum", question="Who makes 1.6T DSPs?")

    listed = atlas.get("/api/v1/investigations")

    assert listed["total"] == 2
    assert [(i["id"], i["question"], i["status"]) for i in listed["items"]] == [
        (second["id"], "Who makes 1.6T DSPs?", "running"),
        (first["id"], QUESTION, "running"),
    ]
    summary = listed["items"][0]
    assert (summary["theme"], summary["round"], summary["stop_reason"]) == ("photonics", 1, None)
    assert summary["seed_company_ids"] == [
        company_id(atlas, "coherent"),
        company_id(atlas, "lumentum"),
    ]
    assert atlas.get("/api/v1/investigations", limit=1, offset=1)["items"][0]["id"] == first["id"]
