"""Investigations: a theme question run as a fixed, visible plan on the job queue, within
per-run budgets, every stop's reason recorded (Phase 3-6a ticket 14; spec "Research
workflow", §7.2-§7.4).

Seams: `POST /api/v1/investigations` starts one, single worker passes run its tasks, and
everything is observed through `/api/v1` (the investigation, its events, runs' role calls,
discoveries, claim extractions, `/metrics`) and the requests the fakes received. The
Source Versions are the recorded Coherent EDGAR filings (a 10-K and a 10-Q), ingested and
retained through the fixture path, Hindsight the recorded fake with `derive_memories`.
LiteLLM is the scripted chat fake: **the Scout's, Investigator's, Skeptic's, Financial
Analyst's and Editor's answers are written here** (the Investigator's quote the recorded
Coherent 10-K; the Skeptic's quote the passages it is sent, of the recorded filings and of
one hand-shaped later statement (`SUPPLY_UPDATE`, imported by hand); the Analyst proposes no
scenario; the Editor's cite the short references (`c1`, ...) of the Claims it is sent; the
Reviewer, chained after a final stop, confirms what it is sent). The Skeptic's and the
Analyst's jobs run in parallel, in either order, so their answers are scripted by role
(`script_role`) and their calls compared in plan order.
SearXNG is the scripted fake over `tests/fixtures/searxng/`. The
test universe is the repo's plus NVIDIA, which the 10-K names. Nothing live is called.
"""

import json
import os
import subprocess
import sys
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import JsonValue
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from atlas.investigations.pointers import round_reading
from atlas.jobs import JobQueue, Pacing, Worker, builtin_registry
from tests.fakes.hindsight import RecordedHindsight
from tests.fakes.litellm import ChatReply, FakeLiteLLM
from tests.fakes.searxng import FakeSearXNG, SearchReply, fixture
from tests.fakes.serve import Served, serve
from tests.harness import BANK, ITEM_1, REPO, THEMES, Atlas, Clock, at

QUESTION = "Who supplies the lasers in AI data-center optics, and to whom?"
SUBSTRATE = "indium phosphide substrate capacity expansion 2026"
SECOND_SOURCE = "InP laser second source qualification hyperscaler"
NOTHING = "electro-absorption modulated laser shortage 800G transceivers"
QUERIES: list[JsonValue] = [
    {"query": SUBSTRATE, "purpose": "InP substrate capacity"},
    {"query": SECOND_SOURCE, "purpose": "second sources"},
    {"query": NOTHING, "purpose": None},
]
# The leads the fixtures give, in the order the queries found them.
AXT = "https://photonics-news.test/2026/08/axt-expands-inp-substrate-capacity"
SUMITOMO = "https://optics-trade.test/articles/sumitomo-electric-inp-wafers"
BLOG = "https://blog.photonics.test/second-sources-for-inp-lasers?a=1&b=2"
COHR_10K = "https://www.sec.gov/Archives/edgar/data/820318/000082031826000020/iivi-20260630.htm"
COHR_10Q = "https://www.sec.gov/Archives/edgar/data/820318/000082031826000013/iivi-20260331.htm"
# From the Coherent FY2026 10-K (the recorded fixture's parsed text).
SUPPLY_QUOTE = (
    "we announced the expansion of our Sherman, Texas, manufacturing facility, entered into a"
    " strategic multi-year supply agreement with NVIDIA for advanced lasers and optical"
    " networking products"
)
PLAN = [
    "scout",
    "investigator:coherent",
    "investigator:lumentum",
    "skeptic",
    "financial_analyst",
    "editor",
]
STOP_REASONS = [
    "answered",
    "no_new_independent_evidence",
    "budget_exhausted",
    "needs_review",
    "premise_disproven",
]


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


class Services:
    """What a test's Atlas is started with."""

    def __init__(
        self,
        database_url: str,
        tmp_path: Path,
        hindsight: tuple[RecordedHindsight, Served],
        litellm: Served,
        searxng_served: Served,
        themes: Path,
    ) -> None:
        self.database_url = database_url
        self.tmp_path = tmp_path
        self.hindsight = hindsight
        self.litellm = litellm
        self.searxng = searxng_served
        self.themes = themes
        self.started: list[Atlas] = []

    def start(self, *, ingest: bool = True, **overrides: Any) -> Atlas:
        """Atlas with the template applied, the universe seeded and (optionally) Coherent's
        filings ingested and retained."""
        settings: dict[str, Any] = {
            "themes_config": self.themes,
            "searxng_url": self.searxng.url,
            "investigator_passages_per_call": 50,  # one Investigator call unless a test says
        }
        atlas = Atlas(
            self.database_url,
            self.tmp_path,
            self.hindsight[1].url,
            self.litellm.url,
            **(settings | overrides),
        )
        self.started.append(atlas)
        atlas.apply_template()
        seeded = subprocess.run(
            [sys.executable, "-m", "atlas", "companies", "seed"],
            cwd=self.tmp_path,
            env={
                "PATH": os.environ["PATH"],
                "HOME": str(self.tmp_path),
                "ATLAS_DATABASE_URL": self.database_url,
                "ATLAS_ACTOR": "local-researcher",
                "ATLAS_ARCHIVE_ROOT": str(atlas.archive),
                "ATLAS_THEMES_CONFIG": str(self.themes),
            },
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert seeded.returncode == 0, seeded.stderr
        if ingest:
            atlas.ingest_company("coherent")
        return atlas


@pytest.fixture
def services(
    database_url: str,
    tmp_path: Path,
    hindsight: tuple[RecordedHindsight, Served],
    litellm: Served,
    searxng_served: Served,
    themes: Path,
) -> Iterator[Services]:
    started = Services(database_url, tmp_path, hindsight, litellm, searxng_served, themes)
    yield started
    for atlas in started.started:
        atlas.engine.dispose()


# --- helpers --------------------------------------------------------------------------------------


def company_id(atlas: Atlas, slug: str) -> str:
    return atlas.company(slug)["id"]


def start(atlas: Atlas, **body: Any) -> dict[str, Any]:
    """POST an investigation; returns the accepted response."""
    body = {"theme": "photonics", "question": QUESTION} | body
    response = atlas.api.post("/api/v1/investigations", json=body)
    assert response.status_code == 202, response.text
    return response.json()


def seeded(atlas: Atlas, *slugs: str, **body: Any) -> dict[str, Any]:
    return start(atlas, seed_company_ids=[company_id(atlas, slug) for slug in slugs], **body)


def investigation(atlas: Atlas, investigation_id: str) -> dict[str, Any]:
    return atlas.get(f"/api/v1/investigations/{investigation_id}")


def events(atlas: Atlas, investigation_id: str) -> list[dict[str, Any]]:
    return atlas.get(f"/api/v1/investigations/{investigation_id}/events", limit=500)["items"]


def tasks(found: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {task["key"]: task for task in found["tasks"]}


def statuses(found: dict[str, Any]) -> dict[str, str]:
    return {task["key"]: task["status"] for task in found["tasks"]}


def asked(body: dict[str, Any]) -> dict[str, Any]:
    """The user message of a chat request: `{"request": ..., "retrieved_data": [...]}`."""
    return json.loads(body["messages"][1]["content"])


# The Skeptic and the Financial Analyst run in parallel, in either order: compared in plan order.
PARALLEL_ORDER = {"skeptic": 0, "financial_analyst": 1}


def in_plan_order[T](items: list[T], role: Callable[[T], str]) -> list[T]:
    """`items` with each run of consecutive Skeptic and Analyst items put in plan order (the
    Skeptic's first; each role's own items keep their order)."""
    ordered: list[T] = []
    run: list[T] = []
    for item in [*items, None]:
        if item is not None and role(item) in PARALLEL_ORDER:
            run.append(item)
            continue
        ordered.extend(sorted(run, key=lambda each: PARALLEL_ORDER[role(each)]))
        run = []
        if item is not None:
            ordered.append(item)
    return ordered


def requests(llm: FakeLiteLLM) -> list[dict[str, Any]]:
    """The chat requests, oldest first, with the parallel roles' in plan order."""
    return in_plan_order(llm.chat_requests(), lambda body: body["metadata"]["role"])


def roles(llm: FakeLiteLLM) -> list[str]:
    return [body["metadata"]["role"] for body in requests(llm)]


def call_roles(calls: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """A run's role calls as (role, status), with the parallel roles' in plan order."""
    return [(c["role"], c["status"]) for c in in_plan_order(calls, lambda c: c["role"])]


def scout_reply(tokens: tuple[int, int] = (900, 120)) -> ChatReply:
    return ChatReply.json({"queries": QUERIES}, tokens=tokens)


def finding_nothing(body: dict[str, Any]) -> JsonValue:
    """The Skeptic finding nothing: its plan writes no query (as pilot investigation 1's
    did), and its reading of what Memory pointed to (or code's fallback chose) proposes
    nothing."""
    if "passages" in asked(body)["request"]:
        return {"counterevidence": []}
    return {"queries": []}


# Enough answers for the plan and every reading call (the unused ones are never asked for).
NOTHING_TO_READ = (ChatReply.answer(finding_nothing, tokens=(500, 50)),) * 8


def script_searches(searxng: FakeSearXNG) -> None:
    searxng.script(SUBSTRATE, SearchReply.of("inp-substrate-capacity"))
    searxng.script(SECOND_SOURCE, SearchReply.of("inp-laser-second-source"))
    searxng.script(NOTHING, SearchReply.of("no-results"))


def supply_claim(atlas: Atlas) -> dict[str, JsonValue]:
    return {
        "subject_company_id": company_id(atlas, "coherent"),
        "predicate": "supplies",
        "object_company_id": company_id(atlas, "nvidia"),
        "object_name": None,
        "object_text": None,
        "product": "advanced lasers",
        "layer": "chip-laser",
        "quote": SUPPLY_QUOTE,
        "epistemic_type": "company_claim",
    }


def quoting(
    *claims: dict[str, JsonValue], version: str | None = None
) -> Callable[[dict[str, Any]], JsonValue]:
    """An Investigator answer proposing each claim whose quote a passage it was sent holds
    (with that passage's ID and the quote's offsets there), and nothing else. With `version`,
    only that Source Version's passages are quoted."""

    def respond(body: dict[str, Any]) -> JsonValue:
        passages = [
            p
            for p in asked(body)["retrieved_data"]
            if version is None or p["source"].startswith(f"{version}#")
        ]
        answered: list[JsonValue] = []
        for each in claims:
            quote = str(each["quote"])
            holding = [p for p in passages if quote in p["text"]]
            if holding:
                start_at = holding[0]["text"].index(quote)
                answered.append(
                    each
                    | {
                        "passage_id": holding[0]["id"],
                        "quote_start": start_at,
                        "quote_end": start_at + len(quote),
                    }
                )
        return {"claims": answered}

    return respond


def editing(
    *,
    verdict: str = "answered",
    extra: list[dict[str, JsonValue]] | None = None,
    statement: str = (
        "Coherent supplies NVIDIA with advanced lasers under a multi-year supply agreement."
    ),
) -> Callable[[dict[str, Any]], JsonValue]:
    """An Editor answer with one finding citing every Claim it was sent, plus `extra`. The
    finding's `statement` must say only what those Claims say (pilot-fixes ticket 21): the
    default is the supply Claim's."""

    def respond(body: dict[str, Any]) -> JsonValue:
        request = asked(body)["request"]
        finding: dict[str, JsonValue] = {
            "statement": statement,
            "claim_refs": [claim["ref"] for claim in request["claims"]],
            "limitations": ["A company's own statement; no volumes or prices."],
            "open_questions": ["Does NVIDIA qualify a second laser source?"],
        }
        return {
            "findings": [finding, *(extra or [])],
            "open_questions": ["Is InP substrate capacity a constraint for 2027?"],
            "verdict": verdict,
        }

    return respond


# The Editor's card when no Claim was accepted: no finding, the next round's questions.
NEXT_ROUND: list[JsonValue] = [
    "Does Coherent's 10-K state its InP laser capacity or who qualifies its EML lasers?",
    "Which of Lumentum's filings describe its laser sourcing?",
]
NOTHING_ACCEPTED = ChatReply.json(
    {"findings": [], "open_questions": NEXT_ROUND, "verdict": "needs_review"}, tokens=(2000, 150)
)


def reviewing(body: dict[str, Any]) -> JsonValue:
    """The Reviewer (chained after a final stop) confirms every edge it is sent."""
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


REVIEWED = ChatReply.answer(reviewing, tokens=(700, 90))
# The Financial Analyst (between the Investigators and the Editor when a Claim is accepted)
# proposes no scenario here; its proposals are ticket 19's tests (test_scenarios.py).
ANALYSED = ChatReply.json({"scenarios": []}, tokens=(1500, 200))
# The stop detail's clause when the Claims name NVIDIA, which has no archived document, so the
# Skeptic cannot check it (pilot-fixes ticket 25).
NVIDIA_UNCHECKED = (
    "; the Skeptic did not check NVIDIA, so nothing said of it was challenged"
    " (see the card's skeptic_coverage)"
)


def script_parallel(
    llm: FakeLiteLLM,
    skeptic: tuple[ChatReply, ...] = NOTHING_TO_READ,
    analyst: ChatReply = ANALYSED,
) -> None:
    """Script the Skeptic's and the Financial Analyst's answers by role: their jobs are queued
    together and run in either order."""
    llm.script_role("skeptic", *skeptic).script_role("financial_analyst", analyst)


def metric(atlas: Atlas, name: str, **labels: str) -> float:
    return atlas.metrics().get((name, frozenset(labels.items())), 0.0)


def paced(atlas: Atlas, clock: Clock) -> Worker:
    """A worker on `clock` whose pause lasts 30 minutes (so the API still sees it)."""
    pacing = Pacing(pause_base=timedelta(minutes=30))
    return Worker(
        JobQueue(atlas.engine, pacing=pacing, clock=clock), builtin_registry(atlas.settings())
    )


# --- the plan and a full run ----------------------------------------------------------------------


def test_an_investigation_starts_with_a_fixed_visible_plan_and_its_7_2_request(
    services: Services,
) -> None:
    atlas = services.start(ingest=False)
    coherent, lumentum = company_id(atlas, "coherent"), company_id(atlas, "lumentum")

    started = seeded(atlas, "coherent", "lumentum", as_of="2026-09-01T00:00:00Z")

    assert (started["status"], started["stop_reason"], started["paused"]) == (
        "running",
        None,
        False,
    )
    assert [task["key"] for task in started["tasks"]] == PLAN
    plan = tasks(started)
    assert plan["scout"]["status"] == "queued"
    assert plan["scout"]["job_id"] is not None
    for key in ("investigator:coherent", "investigator:lumentum", "editor"):
        assert plan[key]["status"] == "pending"
    assert plan["skeptic"]["status"] == "pending"
    assert plan["financial_analyst"]["status"] == "pending"
    assert plan["investigator:coherent"]["depends_on"] == ["scout"]
    assert plan["investigator:coherent"]["company_id"] == coherent
    assert (
        plan["skeptic"]["depends_on"]
        == plan["financial_analyst"]["depends_on"]
        == [
            "investigator:coherent",
            "investigator:lumentum",
        ]
    )
    assert plan["editor"]["depends_on"] == [
        "investigator:coherent",
        "investigator:lumentum",
        "skeptic",
        "financial_analyst",
    ]
    assert plan["investigator:lumentum"]["premise_keys"] == ["question", "company:lumentum"]
    assert [(p["key"], p["status"]) for p in started["premises"]] == [
        ("question", "open"),
        ("company:coherent", "open"),
        ("company:lumentum", "open"),
    ]
    request = started["request"]
    assert request["research_question"] == QUESTION
    assert request["theme_id"] == "photonics"
    assert request["seed_entity_ids"] == [coherent, lumentum]
    assert at(request["as_of_utc"]) == at("2026-09-01T00:00:00+00:00")
    assert request["run_id"] is None  # the first task starts the run
    assert request["hypothesis_id"] is None
    assert request["max_depth"] == 2
    assert request["max_new_leads"] == 10
    assert request["allowed_source_tiers"] == ["A", "C"]
    assert started["budgets"] == {
        "max_rounds": 2,
        "max_leads": 10,
        "max_documents": 25,
        "max_companies": 6,  # Investigators a round, the seeds among them
        "token_budget": 200_000,
    }
    assert request["available_budget"] == started["budgets"]
    # Memory has pointed nowhere yet: the plan holds the seeds' Investigators only.
    assert started["pointed_companies"] == []
    assert started["usage"]["companies"] == 2
    assert [(e["type"], e["task_key"]) for e in events(atlas, started["id"])] == [
        ("created", None),
        ("task_queued", "scout"),
    ]


def test_the_default_seeds_are_the_theme_s_companies(services: Services) -> None:
    atlas = services.start(ingest=False)

    started = start(atlas)

    investigators = [t["key"] for t in started["tasks"] if t["role"] == "investigator"]
    assert investigators == [
        f"investigator:{slug}"
        for slug in [
            "axt",
            "soitec",
            "iqe",
            "coherent",
            "lumentum",
            "macom",
            "stmicroelectronics",
            "marvell",
            "innolight",
            "applied-optoelectronics",
            "fabrinet",
            "ciena",
        ]
    ]


def test_scout_investigator_and_editor_run_in_one_run_to_an_answered_research_card(
    services: Services, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    atlas = services.start()
    started = seeded(atlas, "coherent", "lumentum")
    script_parallel(llm)
    llm.script_chat(
        scout_reply(),
        ChatReply.answer(quoting(supply_claim(atlas)), tokens=(9000, 700)),
        ChatReply.answer(editing(), tokens=(3000, 400)),
        REVIEWED,
    )
    script_searches(searxng)

    atlas.worker_pass()

    found = investigation(atlas, started["id"])
    assert (found["status"], found["stop_reason"]) == ("stopped", "answered")
    # NVIDIA, which the Claim names, has no archived document: the Skeptic did not check it,
    # and the detail says so (pilot-fixes ticket 25).
    assert found["stop_detail"] == (
        "the Editor judged the question answered by 1 findings;"
        " the Skeptic did not check NVIDIA, so nothing said of it was challenged"
        " (see the card's skeptic_coverage)"
    )
    unchecked = [c for c in found["research_card"]["skeptic_coverage"] if c["outcome"] != "checked"]
    assert [(c["company_name"], c["reason_code"]) for c in unchecked] == [("NVIDIA", "no_document")]
    assert found["resumable"] is False
    assert statuses(found) == {
        "scout": "succeeded",
        "investigator:coherent": "succeeded",
        "investigator:lumentum": "succeeded",
        "skeptic": "succeeded",
        "financial_analyst": "succeeded",
        "editor": "succeeded",
    }
    # Lumentum has nothing archived: its Investigator task makes no LLM call.
    assert "no parsed Source Version" in tasks(found)["investigator:lumentum"]["detail"]
    assert roles(llm) == [
        "scout",
        "investigator",
        "skeptic",
        "skeptic",
        "financial_analyst",
        "editor",
        "reviewer",
    ]
    # The Skeptic's plan wrote no query; Memory pointed it to Coherent's filings (ticket 07),
    # so no fallback was needed; it read them and found no counterevidence.
    skeptic = tasks(found)["skeptic"]["artifacts"]
    assert skeptic["supporting_claims"] == 1
    assert (skeptic["documents_fallback"], skeptic["documents"]) == (False, 2)
    assert skeptic["documents_from_pointers"] == 2
    assert skeptic["passages"] > 0
    assert skeptic["counterevidence_accepted"] == 0
    assert found["counterevidence"] == []
    # Every role call is in the investigation's run, which the stop finished (the chained
    # relationship review has its own).
    run_id = found["run_id"]
    assert run_id is not None and found["request"]["run_id"] == run_id
    assert {body["metadata"]["run_id"] for body in llm.chat_requests()[:6]} == {run_id}
    calls = atlas.get(f"/api/v1/runs/{run_id}/role-calls")
    assert call_roles(calls["role_calls"]) == [
        ("scout", "accepted"),
        ("investigator", "accepted"),
        ("skeptic", "accepted"),
        ("skeptic", "accepted"),
        ("financial_analyst", "accepted"),
        ("editor", "accepted"),
    ]
    assert (calls["tokens_in"], calls["tokens_out"]) == (15_400, 1_520)
    assert found["usage"] == {
        "rounds": 1,
        "leads": 3,
        "documents": 2,
        "companies": 2,
        "tokens_in": 15_400,
        "tokens_out": 1_520,
        "repairs": {},
    }
    tokens = "atlas_llm_tokens_total"
    assert metric(atlas, tokens, kind="investigation", direction="input") == 15_400
    assert metric(atlas, tokens, kind="investigation", direction="output") == 1_520
    discovery = atlas.get(
        f"/api/v1/discoveries/{tasks(found)['scout']['artifacts']['discovery_id']}"
    )
    assert (discovery["run_id"], discovery["status"]) == (run_id, "completed")
    extraction = atlas.get(
        "/api/v1/claim-extractions/"
        f"{tasks(found)['investigator:coherent']['artifacts']['extraction_id']}"
    )
    assert (extraction["run_id"], extraction["question"]) == (run_id, QUESTION)
    # The leads, best-ranked first (never Evidence), and the documents. The Sumitomo article
    # names its query's terms only in its snippet, so the blog, found later, ranks above it.
    assert [(lead["rank"], lead["canonical_url"], lead["tier"]) for lead in found["leads"]] == [
        (1, AXT, "C"),
        (2, BLOG, "C"),
        (3, SUMITOMO, "C"),
    ]
    ten_k = atlas.version(COHR_10K, "coherent")["id"]
    ten_q = atlas.version(COHR_10Q, "coherent")["id"]
    assert [d["source_version_id"] for d in found["documents"]] == [ten_k, ten_q]
    assert extraction["source_version_ids"] == [ten_k, ten_q]
    # The Editor was sent the accepted Claim (its quote as low-trust data) and the leads.
    editor = asked(requests(llm)[5])
    assert (editor["request"]["contradictions"], editor["request"]["bear_context"]) == ([], [])
    [sent] = editor["request"]["claims"]
    [accepted] = atlas.get("/api/v1/claims", outcome="accepted")["items"]
    # By its short reference, not its ID: code maps the Editor's citations back.
    assert sent["ref"] == "c1"
    assert accepted["id"] not in json.dumps(editor)
    assert (sent["subject"], sent["predicate"], sent["object"]) == (
        "Coherent",
        "supplies",
        "NVIDIA",
    )
    assert [lead["title"] for lead in editor["request"]["leads"]] == [
        lead["title"] for lead in found["leads"]
    ]
    quoted = {each["id"]: each for each in editor["retrieved_data"]}
    assert quoted["c1"]["text"] == SUPPLY_QUOTE
    assert all(each["trust"] == "low" for each in editor["retrieved_data"])
    # The Claim and the Evidence tray say which selections chose its passage: the window
    # matches the question's terms and names NVIDIA.
    [evidence] = found["evidence"]
    assert evidence["passage_selected_by"] == accepted["passage_selected_by"]
    assert "search" in accepted["passage_selected_by"]
    assert f"entity:{company_id(atlas, 'nvidia')}" in accepted["passage_selected_by"]
    # The draft research card: the finding's spans are the accepted Claim's, filled by code.
    card = found["research_card"]
    assert (card["status"], card["editor_verdict"], card["question"]) == (
        "draft",
        "answered",
        QUESTION,
    )
    assert card["open_questions"] == ["Is InP substrate capacity a constraint for 2027?"]
    assert card["unsupported_findings"] == []
    [finding] = card["findings"]
    assert finding["claim_text"].startswith("Coherent supplies NVIDIA")
    assert finding["epistemic_type"] == "agent_inference"
    assert finding["cited_epistemic_types"] == ["company_claim"]
    assert finding["claim_ids"] == [accepted["id"]]
    assert finding["original_source_version_ids"] == [ten_k]
    [span] = finding["source_spans"]
    assert (span["assertion_id"], span["quote"]) == (accepted["assertion_id"], SUPPLY_QUOTE)
    assert atlas.parsed(ten_k)[span["span_start"] : span["span_end"]] == SUPPLY_QUOTE
    assert span["verification_status"] == "unreviewed"
    assert finding["needs_review"] is True  # its Assertion isn't corroborated yet
    assert finding["entity_ids"] == [company_id(atlas, "coherent"), company_id(atlas, "nvidia")]
    family = atlas.get(f"/api/v1/source-versions/{ten_k}")["evidence_family"]
    assert finding["independent_evidence_families"] == [f"family:{family['evidence_family_id']}"]
    assert at(finding["validity_dates"]["evidence_available_at"]) == at(
        atlas.version(COHR_10K, "coherent")["available_at"]
    )
    assert finding["counterevidence_ids"] == []
    assert (card["contradictions"], card["bear_context"]) == ([], [])
    assert finding["limitations"] == ["A company's own statement; no volumes or prices."]
    # Every name in its statement is in its Claim: grounded, with no second Editor call.
    assert finding["grounded"] is True
    assert tasks(found)["editor"]["artifacts"]["grounding"] == {
        "asked_again": 0,
        "repaired": 0,
        "role_call_id": None,
        "failure": None,
    }
    assert card["editor_role_call_id"] == calls["role_calls"][-1]["id"]
    # The event log tells the story in order, ending with the stop and its reason.
    log = events(atlas, started["id"])
    assert [(e["type"], e["task_key"]) for e in log if e["task_key"] == "scout"] == [
        ("task_queued", "scout"),
        ("task_started", "scout"),
        ("pointers_recorded", "scout"),  # what Memory was asked, and what it pointed at
        ("entity_pointers_recorded", "scout"),  # the entity hop (memory-quality ticket 09)
        ("task_succeeded", "scout"),
    ]
    assert log[-1]["type"] == "stopped"
    assert log[-1]["detail"] == {
        "reason": "answered",
        "detail": found["stop_detail"],
        "tokens_in": 15_400,
        "tokens_out": 1_520,
    }
    assert metric(atlas, "atlas_investigation_stops_total", reason="answered") == 1


def test_an_editor_finding_that_cites_no_accepted_claim_is_dropped_and_needs_review(
    services: Services, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    atlas = services.start()
    started = seeded(atlas, "coherent")
    lead_citing: dict[str, JsonValue] = {
        "statement": "AXT is expanding InP substrate capacity.",
        "claim_refs": ["LEAD"],
        "limitations": [],
        "open_questions": [],
    }
    invented: dict[str, JsonValue] = {
        "statement": "Coherent is the only qualified laser supplier.",
        "claim_refs": [],
        "limitations": [],
        "open_questions": [],
    }
    # A reference it wasn't sent (one Claim is: `c1`), beside one it was.
    unknown_ref: dict[str, JsonValue] = {
        "statement": "Coherent supplies NVIDIA and Lumentum supplies NVIDIA.",
        "claim_refs": ["c1", "c2"],
        "limitations": [],
        "open_questions": [],
    }

    def cite_a_lead(body: dict[str, Any]) -> JsonValue:
        lead_id = asked(body)["request"]["leads"][0]["lead_id"]
        citing: dict[str, JsonValue] = {**lead_citing, "claim_refs": [lead_id]}
        return editing(extra=[citing, invented, unknown_ref])(body)

    script_parallel(llm)
    llm.script_chat(
        scout_reply(),
        ChatReply.answer(quoting(supply_claim(atlas))),
        ChatReply.answer(cite_a_lead),
        REVIEWED,
    )
    script_searches(searxng)

    atlas.worker_pass()

    found = investigation(atlas, started["id"])
    assert (found["status"], found["stop_reason"]) == ("stopped", "needs_review")
    assert found["stop_detail"] == "3 unsupported findings were dropped" + NVIDIA_UNCHECKED
    card = found["research_card"]
    assert [f["claim_text"][:25] for f in card["findings"]] == ["Coherent supplies NVIDIA "]
    lead_id = found["leads"][0]["lead_id"]
    [accepted] = atlas.get("/api/v1/claims", outcome="accepted")["items"]
    assert card["unsupported_findings"] == [
        {
            "statement": "AXT is expanding InP substrate capacity.",
            "claim_ids": [lead_id],
            "reason": f"cites what isn't an accepted Claim of this investigation: {lead_id}",
        },
        {
            "statement": "Coherent is the only qualified laser supplier.",
            "claim_ids": [],
            "reason": "cites no Claim",
        },
        {
            # The reference it was sent is recorded as its Claim's ID, the other as written.
            "statement": "Coherent supplies NVIDIA and Lumentum supplies NVIDIA.",
            "claim_ids": [accepted["id"], "c2"],
            "reason": "cites what isn't an accepted Claim of this investigation: c2",
        },
    ]


def test_a_final_stop_queues_the_relationship_review_of_the_investigation_s_assertions(
    services: Services, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    atlas = services.start()
    started = seeded(atlas, "coherent")
    script_parallel(llm)
    llm.script_chat(
        scout_reply(),
        ChatReply.answer(quoting(supply_claim(atlas))),
        ChatReply.answer(editing()),
        REVIEWED,
    )
    script_searches(searxng)

    atlas.worker_pass()

    found = investigation(atlas, started["id"])
    assert found["stop_reason"] == "answered"
    [accepted] = atlas.get("/api/v1/claims", outcome="accepted")["items"]
    log = events(atlas, started["id"])
    assert [e["type"] for e in log[-2:]] == ["relationship_review_queued", "stopped"]
    queued = log[-2]["detail"]
    assert queued["assertions"] == 1
    [job_id] = queued["job_ids"]
    job = atlas.get(f"/api/v1/jobs/{job_id}")
    assert (job["kind"], job["status"]) == ("review_relationships", "succeeded")
    assert job["payload"] == {"assertion_ids": [accepted["assertion_id"]]}
    # The Reviewer ran in its own run (the investigation's was finished by the stop).
    reviewer = llm.chat_requests()[-1]
    assert reviewer["metadata"]["role"] == "reviewer"
    assert reviewer["metadata"]["run_id"] != found["run_id"]
    [edge] = atlas.get("/api/v1/relationships")["items"]
    assert (edge["subject_name"], edge["predicate"], edge["object_name"]) == (
        "Coherent",
        "supplies",
        "NVIDIA",
    )
    assert (edge["review_state"], edge["evidence_count"]) == ("machine_reviewed", 1)


# --- lead ranking ---------------------------------------------------------------------------------

# Pilot investigation 1's query (`.scratch/pilot/results.md`) and the kinds of results it kept:
# dictionary, encyclopedia, Swedish broker and translation pages ahead of on-topic articles.
EML = "Coherent EML laser chip capacity 200G per lane 800G transceiver"
EML_ARTICLE = "https://photonics-news.test/2026/09/coherent-200g-eml-capacity"
EML_RACE = "https://optics-trade.test/articles/eml-capacity-race"
# The re-run's first query and its real results (`rerun-lumentum-eml-allocation.json`): the
# companies' own pages, LinkedIn and quote pages, all kept by ranking version 1.
ALLOCATION = "Lumentum 200G EML chip allocation qualified second source 2026"
LUMENTUM_IR = "https://investor.lumentum.com/overview/default.aspx"


def test_the_scout_keeps_the_top_ranked_leads_with_their_scores_and_reasons(
    services: Services, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    atlas = services.start()
    started = seeded(atlas, "coherent")
    llm.script_chat(
        ChatReply.json(
            {
                "queries": [
                    {"query": ALLOCATION, "purpose": "components: 200G EML chip allocation"},
                    {"query": EML, "purpose": "chip-laser: EML capacity"},
                ]
            }
        ),
        ChatReply.json({"claims": []}),
        NOTHING_ACCEPTED,
    )
    searxng.script(ALLOCATION, SearchReply.of("rerun-lumentum-eml-allocation"))
    searxng.script(EML, SearchReply.of("coherent-eml-capacity"))

    atlas.worker_pass()

    # English was asked for, whatever the instance's locale.
    assert searxng.searches()[0]["language"] == "en"
    found = investigation(atlas, started["id"])
    # The on-topic articles, found last, are kept, best first; the companies' own pages and
    # the dictionary, encyclopedia, broker and translation pages found first are not.
    assert [(lead["rank"], lead["canonical_url"]) for lead in found["leads"]] == [
        (1, EML_ARTICLE),
        (2, EML_RACE),
    ]
    article, race = found["leads"]
    assert article["score"] > race["score"] >= 15
    assert (article["query"], article["ranking_version"]) == (EML, 3)
    assert article["reasons"] == [
        "query terms in the title: eml, laser, capacity, 200g, lane, 800g, transceiver",
        "query terms in the snippet: chip",
        "names Coherent",
        "product and layer terms: laser, chip, transceiver, eml, indium phosphide, indium, 800g,"
        " 1.6t, 200g, capacity, supply",
    ]
    scout = tasks(found)["scout"]["artifacts"]
    assert (
        scout["leads_found"],
        scout["leads_taken"],
        scout["leads_dropped"],
        scout["leads_rejected"],
        scout["ranking_version"],
    ) == (17, 2, 0, 15, 3)
    # Rejected leads are still leads (Tier C metadata), just not the investigation's.
    leads = atlas.get("/api/v1/leads", theme="photonics", limit=50)
    assert leads["total"] == 17
    assert LUMENTUM_IR in {lead["canonical_url"] for lead in leads["items"]}


# --- reading pointers -----------------------------------------------------------------------------

# Lumentum's recorded filings (`LITE_8K`, `LITE_EX991`, `LITE_10K`, `LITE_10Q`, below): the
# fourth-quarter results 8-K and its press release (accepted 11 August 2026), the 10-K
# (17 August 2026) and the third-quarter 10-Q (May 2026).
TWO_QUERIES: list[JsonValue] = [
    {"query": SUBSTRATE, "purpose": "InP substrate capacity"},
    {"query": SECOND_SOURCE, "purpose": "second sources"},
]
THEME_SCOPE = (["theme:photonics"], "any_strict")


def script_two_queries(llm: FakeLiteLLM, searxng: FakeSearXNG, *, investigators: int = 1) -> None:
    """The Scout writes two queries; each of the `investigators` that reads proposes nothing;
    the Editor's card has no finding."""
    llm.script_chat(
        ChatReply.json({"queries": TWO_QUERIES}),
        *[ChatReply.json({"claims": []})] * investigators,
        NOTHING_ACCEPTED,
    )
    searxng.script(SUBSTRATE, SearchReply.of("inp-substrate-capacity"))
    searxng.script(SECOND_SOURCE, SearchReply.of("inp-laser-second-source"))


def retained_sections(atlas: Atlas, url: str, company: str) -> list[dict[str, Any]]:
    """The Source Version's sections as retained (its memory documents), with the version."""
    version = atlas.version(url, company)
    return [d | {"version": version} for d in atlas.memory(version["id"])["documents"]]


def asked_of_memory(found: dict[str, Any], query_index: int) -> list[dict[str, Any]]:
    return [p for p in found["pointers"] if p["query_index"] == query_index]


def test_the_question_and_each_scout_query_are_asked_of_memory_and_stored_as_reading_pointers(
    services: Services, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    atlas = services.start()  # Coherent, the seed
    atlas.ingest_company("lumentum")  # in the theme, not a seed
    fake = services.hindsight[0]
    coherent, lumentum = atlas.company("coherent"), atlas.company("lumentum")
    as_of = "2026-08-15T12:00:00+00:00"
    available = [
        *retained_sections(atlas, COHR_10K, "coherent"),
        *retained_sections(atlas, COHR_10Q, "coherent"),
        *retained_sections(atlas, LITE_8K, "lumentum"),
        *retained_sections(atlas, LITE_EX991, "lumentum"),
        *retained_sections(atlas, LITE_10Q, "lumentum"),
    ]
    later = retained_sections(atlas, LITE_10K, "lumentum")
    assert all(at(s["version"]["available_at"]) <= at(as_of) for s in available)
    assert later and all(at(s["version"]["available_at"]) > at(as_of) for s in later)
    cohr_item_1 = atlas.section(COHR_10K, "coherent")
    cohr_versions = {atlas.version(url, "coherent")["id"] for url in (COHR_10K, COHR_10Q)}
    release = retained_sections(atlas, LITE_EX991, "lumentum")[0]
    # What Hindsight holds: a fact per retained section (the fake's derivation) and one
    # observation consolidated from a fact of each company's filing.
    observation = fake.derive_observation([cohr_item_1["document_id"], release["document_id"]])
    facts = fake.bank_facts(BANK)
    assert len(facts) == len(available) + len(later)
    started = seeded(atlas, "coherent", as_of=as_of)
    script_two_queries(llm, searxng, investigators=2)  # the seed's, and Lumentum's (below)

    atlas.worker_pass()

    found = investigation(atlas, started["id"])
    assert statuses(found)["scout"] == "succeeded"
    # One recall for the question and one per Scout query, each across the theme, and no
    # other: the Investigators read by these pointers and ask Memory nothing themselves
    # (memory-directed reading ticket 05).
    recalls = fake.requests("POST", "memories/recall")
    assert [(r["query"], (r["tags"], r["tags_match"])) for r in recalls] == [
        (QUESTION, THEME_SCOPE),
        (SUBSTRATE, THEME_SCOPE),
        (SECOND_SOURCE, THEME_SCOPE),
    ]
    pointers = found["pointers"]
    assert {(p["query_index"], p["query"]) for p in pointers} == {
        (0, QUESTION),
        (1, SUBSTRATE),
        (2, SECOND_SOURCE),
    }
    assert {(p["round"], p["task_key"], p["citation_state"]) for p in pointers} == {
        (1, "scout", "resolved")
    }
    # Both companies' documents are pointed at, the seed's and the other's; every section
    # retained from a version available by the as-of time, for every query (the fake recalls
    # everything in scope), and none of the 10-K that became available after it.
    assert {p["company_id"] for p in pointers} == {coherent["id"], lumentum["id"]}
    expected = {(s["version"]["id"], s["section_anchor"]) for s in available}
    for index in (0, 1, 2):
        asked_for = asked_of_memory(found, index)
        assert {(p["source_version_id"], p["section_anchor"]) for p in asked_for} == expected
        assert len(asked_for) == len(available) + 2  # and the observation's two sections
    assert later[0]["version"]["id"] not in {p["source_version_id"] for p in pointers}
    second = asked_of_memory(found, 2)
    # The observation, recalled first, resolves through its two source facts: one pointer per
    # section, with the observation's text as Memory.
    first = [p for p in second if p["rank"] == 1]
    assert [(p["memory_id"], p["memory_type"]) for p in first] == [(observation, "observation")] * 2
    assert {(p["company_id"], p["source_version_id"], p["section_anchor"]) for p in first} == {
        (coherent["id"], cohr_item_1["version"]["id"], ITEM_1),
        (lumentum["id"], release["version"]["id"], release["section_anchor"]),
    }
    # A fact points at the section it was extracted from, at its rank in the recall's results.
    fact = fake.derived_fact(release["document_id"])
    [pointer] = [p for p in second if p["memory_id"] == fact]
    section_text = atlas.parsed(release["version"]["id"])[
        release["char_start"] : release["char_end"]
    ]
    assert pointer["rank"] == facts.index(fact) + 2  # after the observation
    assert (pointer["memory_type"], pointer["memory_text"]) == (
        "world",
        " ".join(section_text.split())[:200],
    )
    assert (pointer["source_version_id"], pointer["section_anchor"]) == (
        release["version"]["id"],
        release["section_anchor"],
    )
    assert (pointer["section_char_start"], pointer["section_char_end"]) == (
        release["char_start"],
        release["char_end"],
    )
    assert (pointer["company_id"], pointer["company_name"]) == (
        lumentum["id"],
        lumentum["display_name"],
    )
    assert pointer["source_title"] == release["version"]["source_document"]["title"]
    assert at(pointer["available_at"]) == at(release["version"]["available_at"])
    # The Scout task counts what it asked and what came back.
    scout = tasks(found)["scout"]["artifacts"]
    assert (scout["pointer_recalls"], scout["pointer_recalls_failed"]) == (3, 0)
    assert scout["memories_recalled"] == 3 * (len(facts) + 1)
    assert scout["sections_after_as_of"] == 3 * len(later)
    assert scout["pointers"] == len(pointers) == 3 * (len(available) + 2)
    by_slug = {coherent["id"]: "coherent", lumentum["id"]: "lumentum"}
    assert scout["pointers_by_company"] == {
        slug: sum(1 for p in pointers if p["company_id"] == each) for each, slug in by_slug.items()
    }
    [recorded] = [e for e in events(atlas, started["id"]) if e["type"] == "pointers_recorded"]
    assert (recorded["task_key"], recorded["detail"]["pointers"]) == ("scout", len(pointers))
    assert recorded["detail"]["queries_without_pointers"] == []
    # The pointers choose companies too (ticket 06): Lumentum, a theme company Memory points
    # to, gains an Investigator beside the seed's, and it reads the recorded filings the
    # pointers name: the three available by the as-of time, never the later 10-K.
    assert [t["key"] for t in found["tasks"] if t["role"] == "investigator"] == [
        "investigator:coherent",
        "investigator:lumentum",
    ]
    lumentum_read = [d for d in found["documents"] if d["task_key"] == "investigator:lumentum"]
    assert {d["source_version_id"] for d in lumentum_read} == {
        s["version"]["id"] for s in available if s["version"]["id"] not in cohr_versions
    }
    assert [(c["slug"], c["outcome"]) for c in found["pointed_companies"]] == [
        ("coherent", "seed"),
        ("lumentum", "added"),
    ]


def test_reading_pointers_are_insert_only_and_audited(
    services: Services, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    atlas = services.start()
    started = seeded(atlas, "coherent")
    script_two_queries(llm, searxng)

    atlas.worker_pass()

    found = investigation(atlas, started["id"])
    assert found["pointers"]
    refused = [
        "UPDATE reading_pointer SET rank = rank + 1",
        "DELETE FROM reading_pointer",
        "TRUNCATE reading_pointer",
    ]
    for sql in refused:
        with pytest.raises(DBAPIError), atlas.engine.begin() as connection:
            connection.execute(text(sql))
    assert investigation(atlas, started["id"])["pointers"] == found["pointers"]
    # One audit event for the task's pointers, by the Scout; the chain still verifies.
    with atlas.engine.connect() as connection:
        audited = connection.execute(
            text(
                "SELECT actor, entity_type, entity_id FROM audit_event"
                " WHERE action = 'investigation.pointers_recorded'"
            )
        ).all()
    assert [tuple(row) for row in audited] == [
        ("atlas-scout", "investigation_task", tasks(found)["scout"]["id"])
    ]
    verified = atlas.cli("audit", "verify")
    assert verified.returncode == 0, verified.stdout + verified.stderr


def test_the_scout_asks_memory_like_a_reading_index_and_each_pointer_keeps_score_and_entities(
    services: Services, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    # Memory-quality ticket 07: more results (the setting's max_tokens, 8,192 by default),
    # budget high, an observation instead of the facts it was built from, recency judged from
    # the as-of time, and an observation's sources in the same answer.
    atlas = services.start()
    fake = services.hindsight[0]
    item_1 = atlas.section(COHR_10K, "coherent")
    observation = fake.derive_observation([item_1["document_id"]])
    as_of = "2026-08-15T12:00:00+00:00"
    started = seeded(atlas, "coherent", as_of=as_of)
    script_two_queries(llm, searxng)
    lookups_before = len([r for r in fake.calls if r.method == "GET"])

    atlas.worker_pass()

    recalls = fake.requests("POST", "memories/recall")
    assert [r["query"] for r in recalls] == [QUESTION, SUBSTRATE, SECOND_SOURCE]
    for sent in recalls:
        assert sent == {
            "query": sent["query"],
            "budget": "high",
            "tags": ["theme:photonics"],
            "tags_match": "any_strict",
            "max_tokens": 8192,
            "prefer_observations": True,
            "query_timestamp": as_of,
            "include": {"source_facts": {"max_tokens": -1}, "chunks": {}},  # chunks: ticket 08
        }
    # The observation resolved from the source facts its answer carried: no memory was asked
    # for one by one.
    asked_one_by_one = [
        r
        for r in fake.calls[lookups_before:]
        if r.method == "GET" and "/memories/" in r.url.path and not r.url.path.endswith("/list")
    ]
    assert asked_one_by_one == []
    # Each pointer keeps the recall's final score and its memory's entity names (as the
    # derived recall serves them: the recorded result of the memory's type).
    recorded: dict[str, Any] = dict(fake.recording("tags/02-tags-any_strict").response_object())
    by_type = {r["type"]: r for r in reversed(recorded["results"])}
    found = investigation(atlas, started["id"])
    pointers = found["pointers"]
    assert pointers
    for pointer in pointers:
        expected = by_type[pointer["memory_type"]]
        assert pointer["score"] == expected["scores"]["final"]
        assert pointer["entity_names"] == expected["entities"]
    from_observation = [p for p in pointers if p["memory_id"] == observation]
    assert {(p["source_version_id"], p["section_anchor"]) for p in from_observation} == {
        (item_1["version"]["id"], ITEM_1)
    }
    # Pointed companies are still ranked by reciprocal rank: the score weights nothing yet.
    assert [(c["slug"], c["outcome"]) for c in found["pointed_companies"]] == [("coherent", "seed")]


def test_a_failed_recall_leaves_the_scout_succeeded_with_the_other_queries_pointers(
    services: Services, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    atlas = services.start()
    services.hindsight[0].fail_recalls(lambda query: query == SUBSTRATE, status=500)
    started = seeded(atlas, "coherent")
    script_two_queries(llm, searxng)

    atlas.worker_pass()

    found = investigation(atlas, started["id"])
    assert statuses(found)["scout"] == "succeeded"
    assert {p["query_index"] for p in found["pointers"]} == {0, 2}
    assert len(asked_of_memory(found, 0)) == len(asked_of_memory(found, 2)) > 0
    [failed] = [e for e in events(atlas, started["id"]) if e["type"] == "pointer_recall_failed"]
    assert (failed["round"], failed["task_key"]) == (1, "scout")
    assert (failed["detail"]["query_index"], failed["detail"]["query"]) == (1, SUBSTRATE)
    assert "HTTP 500" in failed["detail"]["error"]
    scout = tasks(found)["scout"]["artifacts"]
    assert (scout["pointer_recalls"], scout["pointer_recalls_failed"]) == (3, 1)
    assert scout["pointers"] == len(found["pointers"])
    # The investigation went on to its stop: the Scout's leads, the Investigator, the Editor.
    assert scout["leads_taken"] == len(found["leads"]) == 3
    assert (found["status"], found["stop_reason"]) == ("stopped", "no_new_independent_evidence")


def test_recalls_that_return_nothing_leave_no_pointer_and_the_event_log_says_so(
    services: Services, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    atlas = services.start(ingest=False)  # nothing retained: Memory holds nothing
    started = seeded(atlas, "coherent")
    llm.script_chat(ChatReply.json({"queries": TWO_QUERIES}), NOTHING_ACCEPTED)
    searxng.script(SUBSTRATE, SearchReply.of("inp-substrate-capacity"))
    searxng.script(SECOND_SOURCE, SearchReply.of("inp-laser-second-source"))

    atlas.worker_pass()

    found = investigation(atlas, started["id"])
    assert (statuses(found)["scout"], found["pointers"]) == ("succeeded", [])
    scout = tasks(found)["scout"]["artifacts"]
    assert (scout["pointer_recalls"], scout["memories_recalled"], scout["pointers"]) == (3, 0, 0)
    assert scout["pointers_by_company"] == {}
    [recorded] = [e for e in events(atlas, started["id"]) if e["type"] == "pointers_recorded"]
    assert recorded["detail"]["queries_without_pointers"] == [QUESTION, SUBSTRATE, SECOND_SOURCE]


def script_layered_queries(
    llm: FakeLiteLLM, searxng: FakeSearXNG, layer: str | None = "substrate"
) -> None:
    """The Scout writes the two queries, the first one concerning `layer`; the Investigator
    proposes nothing and the Editor's card has no finding."""
    first, second = TWO_QUERIES
    assert isinstance(first, dict) and isinstance(second, dict)
    llm.script_chat(
        ChatReply.json({"queries": [first | {"layer": layer}, second | {"layer": None}]}),
        ChatReply.json({"claims": []}),
        NOTHING_ACCEPTED,
    )
    searxng.script(SUBSTRATE, SearchReply.of("inp-substrate-capacity"))
    searxng.script(SECOND_SOURCE, SearchReply.of("inp-laser-second-source"))


def layer_pointers(found: dict[str, Any]) -> list[dict[str, Any]]:
    return [p for p in found["pointers"] if p["scope"] == "theme_layer"]


def test_a_query_with_a_layer_is_also_asked_among_the_facts_labelled_with_it(
    services: Services, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    # Memory-quality ticket 13: the theme AND the layer's label tag, a compound tag filter.
    atlas = services.start()
    fake = services.hindsight[0]
    item_1 = atlas.section(COHR_10K, "coherent")
    # A fact worded unlike the query ("wafers cut from crystal boules" for "substrate capacity")
    # that the extractor labelled with the layer; another fact is not labelled.
    fake.script_fact_text(item_1["document_id"], "Wafers are cut from crystal boules we grow.")
    fake.script_fact_labels(item_1["document_id"], ["layer:substrate"])
    started = seeded(atlas, "coherent")
    script_layered_queries(llm, searxng)

    atlas.worker_pass()

    found = investigation(atlas, started["id"])
    assert statuses(found)["scout"] == "succeeded"
    recalls = fake.requests("POST", "memories/recall")
    theme = {"tag_groups": None, "tags": ["theme:photonics"], "tags_match": "any_strict"}
    in_layer = {
        "tag_groups": [
            {"tags": ["theme:photonics"], "match": "any_strict"},
            {"tags": ["layer:substrate"], "match": "any_strict"},
        ],
        "tags": None,
        "tags_match": None,
    }
    assert [
        (r["query"], {k: r.get(k) for k in ("tag_groups", "tags", "tags_match")}) for r in recalls
    ] == [
        (QUESTION, theme),
        (SUBSTRATE, theme),
        (SUBSTRATE, in_layer),
        (SECOND_SOURCE, theme),
    ]
    # The labelled fact is pointed at through the second recall: its section, once, naming the
    # scope; every other pointer is the theme's.
    [pointer] = layer_pointers(found)
    assert (pointer["query_index"], pointer["query"], pointer["layer"]) == (
        1,
        SUBSTRATE,
        "substrate",
    )
    assert (pointer["source_version_id"], pointer["section_anchor"]) == (
        item_1["version"]["id"],
        ITEM_1,
    )
    assert pointer["memory_text"] == "Wafers are cut from crystal boules we grow."
    assert pointer["memory_id"] == fake.derived_fact(item_1["document_id"])
    themed = [p for p in found["pointers"] if p["scope"] == "theme"]
    assert {p["layer"] for p in themed} == {None}
    # The same memory is also a theme pointer of the query: one pointer per recall.
    assert pointer["memory_id"] in {p["memory_id"] for p in themed if p["query_index"] == 1}
    scout = tasks(found)["scout"]["artifacts"]
    assert (scout["pointer_recalls"], scout["pointer_recalls_failed"]) == (3, 0)
    assert (
        scout["layer_recalls"],
        scout["layer_recalls_failed"],
        scout["layer_recalls_empty"],
    ) == (
        1,
        0,
        0,
    )
    assert (scout["layer_pointers"], scout["layer_memories_recalled"]) == (1, 1)
    assert scout["pointers"] == len(found["pointers"])
    discovery = atlas.get(f"/api/v1/discoveries/{scout['discovery_id']}")
    assert [(q["position"], q["layer"]) for q in discovery["queries"]] == [
        (1, "substrate"),
        (2, None),
    ]


def test_a_layer_no_fact_carries_yet_gives_an_empty_second_recall_and_no_failure(
    services: Services, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    atlas = services.start()  # facts exist, none labelled (the backfill is ticket 12)
    fake = services.hindsight[0]
    started = seeded(atlas, "coherent")
    script_layered_queries(llm, searxng)

    atlas.worker_pass()

    found = investigation(atlas, started["id"])
    assert statuses(found)["scout"] == "succeeded"
    layered = [r for r in fake.requests("POST", "memories/recall") if r.get("tag_groups")]
    assert [r["query"] for r in layered] == [SUBSTRATE]
    assert layer_pointers(found) == []
    assert {p["query_index"] for p in found["pointers"]} == {0, 1, 2}  # the theme's, as before
    scout = tasks(found)["scout"]["artifacts"]
    assert (
        scout["layer_recalls"],
        scout["layer_recalls_failed"],
        scout["layer_recalls_empty"],
    ) == (
        1,
        0,
        1,
    )
    assert (scout["layer_memories_recalled"], scout["layer_pointers"]) == (0, 0)
    assert [e for e in events(atlas, started["id"]) if e["type"] == "pointer_recall_failed"] == []
    [recorded] = [e for e in events(atlas, started["id"]) if e["type"] == "pointers_recorded"]
    assert recorded["detail"]["layer_recalls_empty_for"] == [
        {"query_index": 1, "layer": "substrate"}
    ]
    assert (found["status"], found["stop_reason"]) == ("stopped", "no_new_independent_evidence")


def test_a_layer_the_taxonomy_does_not_name_is_not_asked(
    services: Services, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    atlas = services.start()
    fake = services.hindsight[0]
    started = seeded(atlas, "coherent")
    script_layered_queries(llm, searxng, layer="feedstock")  # a raw material: no layer

    atlas.worker_pass()

    found = investigation(atlas, started["id"])
    assert [r for r in fake.requests("POST", "memories/recall") if r.get("tag_groups")] == []
    assert layer_pointers(found) == []
    scout = tasks(found)["scout"]["artifacts"]
    assert (scout["layer_recalls"], scout["layer_pointers"]) == (0, 0)


def test_a_hindsight_outage_during_the_recalls_pauses_the_scout_and_it_resumes(
    services: Services, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    atlas = services.start()
    clock = Clock(datetime.now(UTC))
    worker = paced(atlas, clock)
    services.hindsight[0].fail_recalls(lambda query: query == SECOND_SOURCE, status=503, times=1)
    started = seeded(atlas, "coherent")
    script_two_queries(llm, searxng)

    worker.run_once()

    paused = investigation(atlas, started["id"])
    assert (paused["status"], paused["paused"]) == ("running", True)
    assert (statuses(paused)["scout"], paused["pointers"]) == ("queued", [])
    [paused_event] = [e for e in events(atlas, started["id"]) if e["type"] == "task_paused"]
    assert (paused_event["task_key"], paused_event["detail"]["error_class"]) == (
        "scout",
        "unavailable",
    )

    clock.advance(hours=2)
    worker.run_once()

    found = investigation(atlas, started["id"])
    assert (found["status"], found["stop_reason"]) == ("stopped", "no_new_independent_evidence")
    # The resumed Scout asked Memory again and stored every query's pointers once; its
    # queries were not written or searched again, and its leads are as without a pause.
    assert {p["query_index"] for p in found["pointers"]} == {0, 1, 2}
    log = events(atlas, started["id"])
    assert [e["type"] for e in log if e["type"].startswith("pointer")] == ["pointers_recorded"]
    assert roles(llm).count("scout") == 1
    assert len(searxng.searches()) == 2
    scout = tasks(found)["scout"]["artifacts"]
    assert (scout["pointer_recalls"], scout["pointer_recalls_failed"]) == (3, 0)
    assert scout["leads_taken"] == len(found["leads"]) == 3


# --- budgets and no new evidence ------------------------------------------------------------------


def test_the_lead_and_document_budgets_and_the_as_of_time_bound_what_is_read(
    services: Services, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    atlas = services.start()
    # The 10-Q was available in May 2026 and the 10-K only in August: as of July, the
    # Investigator may read the 10-Q only, and one document at most.
    started = seeded(
        atlas,
        "coherent",
        as_of="2026-07-01T00:00:00Z",
        budgets={"max_leads": 2, "max_documents": 1},
    )
    llm.script_chat(scout_reply(), ChatReply.json({"claims": []}), NOTHING_ACCEPTED)
    script_searches(searxng)

    atlas.worker_pass()

    found = investigation(atlas, started["id"])
    assert [lead["canonical_url"] for lead in found["leads"]] == [AXT, BLOG]  # the top two
    scout = tasks(found)["scout"]["artifacts"]
    assert (scout["leads_found"], scout["leads_taken"], scout["leads_dropped"]) == (3, 2, 1)
    ten_q = atlas.version(COHR_10Q, "coherent")["id"]
    assert [d["source_version_id"] for d in found["documents"]] == [ten_q]
    budget_events = [
        (e["type"], e["detail"])
        for e in events(atlas, started["id"])
        if e["type"].endswith("budget_reached")
    ]
    assert budget_events == [("lead_budget_reached", {"max_leads": 2, "dropped": 1})]
    # No accepted Claim: no new independent Evidence; the Editor's card has no finding.
    assert roles(llm) == ["scout", "investigator", "editor"]
    assert (found["status"], found["stop_reason"]) == ("stopped", "no_new_independent_evidence")
    assert tasks(found)["editor"]["status"] == "succeeded"
    assert found["research_card"]["findings"] == []
    read, skeptic_read = found["research_card"]["read"]
    assert [d["source_version_id"] for d in read["documents"]] == [ten_q]
    assert (skeptic_read["role"], skeptic_read["status"]) == ("skeptic", "skipped")
    assert (
        metric(atlas, "atlas_investigation_stops_total", reason="no_new_independent_evidence") == 1
    )


def test_the_document_budget_is_shared_by_the_investigator_tasks(
    services: Services, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    atlas = services.start()
    started = seeded(atlas, "coherent", budgets={"max_documents": 1})
    llm.script_chat(scout_reply(), ChatReply.json({"claims": []}), NOTHING_ACCEPTED)
    script_searches(searxng)

    atlas.worker_pass()

    found = investigation(atlas, started["id"])
    ten_k = atlas.version(COHR_10K, "coherent")["id"]
    assert [d["source_version_id"] for d in found["documents"]] == [ten_k]  # the newest
    artifacts = tasks(found)["investigator:coherent"]["artifacts"]
    assert (artifacts["documents"], artifacts["documents_dropped"]) == (1, 1)
    assert [
        e["detail"] for e in events(atlas, started["id"]) if e["type"] == "document_budget_reached"
    ] == [{"max_documents": 1, "dropped": 1}]


def import_notes(atlas: Atlas, slug: str, name: str, count: int) -> None:
    """Record `count` short hand-written notes for the company (`atlas sources import`), each
    published in September 2026 and naming NVIDIA (so the Investigator is sent a passage of
    each), then run their retention."""
    for number in range(1, count + 1):
        note = atlas.tmp_path / f"{slug}-note-{number}.txt"
        note.write_text(
            f"Synthetic test note {number}: a hand-written note, not a {name} document.\n\n"
            f"Note {number} mentions NVIDIA, with no volume, price or direction of supply.\n",
            encoding="utf-8",
        )
        imported = atlas.cli(
            "sources",
            "import",
            "--company",
            slug,
            "--file",
            str(note),
            "--origin-url",
            f"https://notes.example.test/{slug}-{number}",
            "--published-at",
            f"2026-09-{number:02d}T12:00:00+00:00",
            "--title",
            f"{slug}-note-{number}",
        )
        assert imported.returncode == 0, imported.stderr
    atlas.worker_pass()


def test_the_document_budget_is_split_fairly_across_the_seed_companies(
    services: Services, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    # Pilot investigation 1: the first Investigator took all 25 documents, the second none.
    # Here each company has 14 parsed Source Versions, more than half the budget: Coherent its
    # recorded 10-K and 10-Q and 12 notes, Lumentum 14 notes.
    atlas = services.start()
    import_notes(atlas, "coherent", "Coherent", 12)
    import_notes(atlas, "lumentum", "Lumentum", 14)
    started = seeded(atlas, "coherent", "lumentum")  # the default budget: 25 documents
    llm.script_chat(
        scout_reply(),
        ChatReply.json({"claims": []}),
        ChatReply.json({"claims": []}),
        NOTHING_ACCEPTED,
    )
    script_searches(searxng)

    atlas.worker_pass()

    found = investigation(atlas, started["id"])
    assert found["budgets"]["max_documents"] == 25
    # The Investigators run in either order: the first to choose gets half the budget,
    # rounded up (12 are held back for the other), the second the 12 left.
    read = {
        key: (task["artifacts"]["documents"], task["artifacts"]["documents_dropped"])
        for key, task in tasks(found).items()
        if key.startswith("investigator:")
    }
    assert sorted(read.values()) == [(12, 2), (13, 1)]
    assert found["usage"]["documents"] == 25
    for key, (documents, _) in read.items():
        assert len([d for d in found["documents"] if d["task_key"] == key]) == documents
    reached = [
        (e["task_key"], e["detail"])
        for e in events(atlas, started["id"])
        if e["type"] == "document_budget_reached"
    ]
    assert sorted(reached) == [
        (key, {"max_documents": 25, "dropped": dropped})
        for key, (_, dropped) in sorted(read.items())
    ]
    # Both extractions ran, and the card reports what each read.
    assert roles(llm) == ["scout", "investigator", "investigator", "editor"]
    card = {each["task_key"]: each for each in found["research_card"]["read"]}
    for key, (documents, dropped) in read.items():
        assert (len(card[key]["documents"]), card[key]["documents_dropped"]) == (documents, dropped)


LITE = "https://www.sec.gov/Archives/edgar/data/1633978"
LITE_10K = f"{LITE}/000162828026057358/lite-20260627.htm"
LITE_8K = f"{LITE}/000162828026055726/lite-20260811.htm"
LITE_EX991 = f"{LITE}/000162828026055726/lite_ex991xq4fy26.htm"
LITE_10Q = f"{LITE}/000162828026030777/lite-20260328.htm"


# Lumentum's allocation statement, from the recorded FY2026 10-K's Item 1: pilot investigation
# 1's best finding, which the equal passage share stopped 2,000 characters short of on 0.2.5.
ALLOCATION_STATEMENT = "This demand is outpacing our current supply"
LITE_ALLOCATION = (
    "we have seen increasing demand from AI and cloud customers as they continue to expand"
    " their data centers, driven in part by the continued advances in cloud and AI"
    " infrastructure. This demand is outpacing our current supply which has required us to"
    " make decisions on supply allocation."
)
# What Memory holds of it: the fact in Hindsight's own words (written here, the fake's
# `script_fact_text`), a paraphrase that quotes nothing.
ALLOCATION_MEMORY = (
    "Lumentum said demand from AI and cloud customers is outpacing its current supply, which"
    " forced it to make supply allocation decisions."
)
# A hand-shaped stand-in for an administrative 8-K (Items 5.02 and 9.01 only), not a Lumentum
# filing: it names none of the question's or the queries' terms and no other company.
ADMINISTRATIVE_8K = (
    "Synthetic test document: a hand-shaped current report, not a Lumentum filing.\n\n"
    "Item 5.02 Departure of Directors or Certain Officers; Election of Directors;"
    " Appointment of Certain Officers.\n\n"
    "The board appointed a new chief accounting officer, who succeeds the retiring"
    " controller.\n\n"
    "Item 9.01 Financial Statements and Exhibits.\n\n"
    "Exhibit 104: the cover page as an interactive file.\n"
)


def import_administrative_8k(atlas: Atlas) -> str:
    """Record `ADMINISTRATIVE_8K` as a Lumentum document published after its 10-K (`atlas
    sources import`) and run its retention; its Source Version's ID."""
    path = atlas.tmp_path / "lumentum-administrative-8k.txt"
    path.write_text(ADMINISTRATIVE_8K, encoding="utf-8")
    imported = atlas.cli(
        "sources",
        "import",
        "--company",
        "lumentum",
        "--file",
        str(path),
        "--origin-url",
        "https://filings.example.test/lumentum-8k-items-5-02-and-9-01",
        "--published-at",
        "2026-08-20T20:05:00+00:00",
        "--title",
        "Lumentum 8-K (Items 5.02 and 9.01), hand-shaped",
    )
    assert imported.returncode == 0, imported.stderr
    atlas.worker_pass()
    return json.loads(imported.stdout)["source_version_id"]


def test_the_investigator_reads_the_window_memory_points_to_and_the_best_search_windows(
    services: Services, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    # The recorded Lumentum filings: the FY2026 10-K (August 17), the Q4 results 8-K with its
    # press release, EX-99.1 (August 11), and the Q3 10-Q (May); and an administrative 8-K.
    atlas = services.start(ingest=False, investigation_max_passages=30)
    fake = services.hindsight[0]
    atlas.ingest_company("lumentum")
    administrative = import_administrative_8k(atlas)
    ids = {
        name: atlas.version(url, "lumentum")["id"]
        for name, url in [
            ("10-K", LITE_10K),
            ("8-K", LITE_8K),
            ("EX-99.1", LITE_EX991),
            ("10-Q", LITE_10Q),
        ]
    }
    # Memory holds one fact of these filings: the allocation statement in its own words,
    # extracted from the 10-K's Item 1. (The fake recalls every fact in scope whatever the
    # query, so one fact keeps this test about where a pointer leads.)
    item_1 = atlas.section(LITE_10K, "lumentum")
    fake.script_fact_text(item_1["document_id"], ALLOCATION_MEMORY)
    fake.report_zero_facts(lambda document_id: document_id != item_1["document_id"])
    lumentum = company_id(atlas, "lumentum")
    allocation: dict[str, JsonValue] = {
        "subject_company_id": lumentum,
        "predicate": "capacity_constrained",
        "object_company_id": None,
        "object_name": None,
        "object_text": "optical components for AI and cloud data centers",
        "product": "optical components",
        "layer": "module",
        "quote": LITE_ALLOCATION,
        "epistemic_type": "company_claim",
    }
    started = seeded(atlas, "lumentum")
    script_parallel(llm)
    llm.script_chat(
        scout_reply(),
        ChatReply.answer(quoting(allocation)),
        ChatReply.answer(editing(statement="Lumentum's demand is outpacing its supply.")),
        REVIEWED,
    )
    script_searches(searxng)

    atlas.worker_pass()

    found = investigation(atlas, started["id"])
    assert statuses(found)["investigator:lumentum"] == "succeeded"
    assert len(found["documents"]) == 5
    # The question and the Scout's three queries each recalled the one fact: four pointers
    # into the 10-K's Item 1, all at rank 1. (The Skeptic's own recalls, later, find the same
    # fact: its pointers are recorded apart and the Investigator never reads by them.)
    assert {
        (p["source_version_id"], p["section_anchor"], p["rank"], p["memory_text"])
        for p in found["pointers"]
    } == {(ids["10-K"], ITEM_1, 1, ALLOCATION_MEMORY)}
    scouted = [p for p in found["pointers"] if p["task_key"] == "scout"]
    assert sorted(p["query_index"] for p in scouted) == [0, 1, 2, 3]
    assert {p["query_kind"] for p in found["pointers"] if p not in scouted} == {"bear_checklist"}
    task = tasks(found)["investigator:lumentum"]["artifacts"]
    extraction = atlas.get(f"/api/v1/claim-extractions/{task['extraction_id']}")
    passages = extraction["passages"]
    parsed = atlas.parsed(ids["10-K"])
    at_ = parsed.index(ALLOCATION_STATEMENT)

    # The pointer's window is read first: the window of Item 1 that holds the statement the
    # Memory paraphrases, not the Item's opening one.
    first = passages[0]
    assert (first["source_version_id"], first["section_anchor"]) == (ids["10-K"], ITEM_1)
    assert first["char_start"] <= at_ < first["char_end"]
    assert first["char_start"] > item_1["char_start"]
    assert first["selected_by"][:4] == ["pointer:0", "pointer:1", "pointer:2", "pointer:3"]
    pointed = [p for p in passages if any(tag.startswith("pointer:") for tag in p["selected_by"])]
    assert pointed == [first]
    # The Memory text chose the window and went nowhere else: no role was sent it.
    assert ALLOCATION_MEMORY not in json.dumps(llm.chat_requests())

    per_document: dict[str, int] = {}
    for passage in passages:
        per_document[passage["source_version_id"]] = (
            per_document.get(passage["source_version_id"], 0) + 1
        )
    # The budget, 30 passages, is spent on the search's best windows: every other passage is
    # a search window (the question's and the queries' terms).
    assert len(passages) == 30
    assert all("search" in p["selected_by"] for p in passages[1:])
    # The results release (the 8-K with Item 2.02 and its EX-99.1) and the 10-Q each keep at
    # least one passage.
    assert all(per_document.get(ids[name], 0) >= 1 for name in ("8-K", "EX-99.1", "10-Q"))
    # One document may take a third of the budget (10) while others have candidates; the
    # share the short filings can't use passes on to the 10-K's next-best windows.
    assert per_document[ids["10-K"]] > 10
    assert per_document[ids["EX-99.1"]] <= 10
    # The administrative 8-K has no pointer, no search and no entity window, only lead
    # windows, and gets no passage while other documents have unread candidates.
    assert administrative not in per_document
    assert extraction["passages_dropped"] > 0
    # The task's and the extraction's artifacts count the passages per document and selection.
    assert task["passages_by_document"] == per_document
    assert task["passages_by_selection"]["pointer"] == 1
    assert task["passages_by_selection"]["search"] >= 29
    assert "lead" not in task["passages_by_selection"]

    # The accepted Claim says which selections found its passage: on the Claim read and in the
    # investigation's Evidence tray.
    [claim] = atlas.get("/api/v1/claims", outcome="accepted")["items"]
    assert claim["passage_id"] == first["id"]
    assert claim["passage_selected_by"] == first["selected_by"]
    [evidence] = found["evidence"]
    assert (evidence["claim_id"], evidence["passage_selected_by"]) == (
        claim["id"],
        first["selected_by"],
    )
    # The card's `read` shows each document's passages and how they were selected.
    [read] = [r for r in found["research_card"]["read"] if r["role"] == "investigator"]
    shown = {d["source_version_id"]: d for d in read["documents"]}
    assert {key: d["passages"] for key, d in shown.items() if d["passages"]} == per_document
    assert read["passages"] == 30
    assert shown[ids["10-K"]]["selections"]["pointer"] == 1
    assert shown[ids["10-K"]]["selections"]["search"] >= per_document[ids["10-K"]] - 1
    assert shown[ids["EX-99.1"]]["selections"] == {"search": per_document[ids["EX-99.1"]]}
    assert (shown[administrative]["passages"], shown[administrative]["selections"]) == (0, {})


# --- multi-hop Investigators (memory-directed reading ticket 06) ----------------------------------

# A hand-shaped stand-in for an AXT document (no AXT filing is recorded in the fixtures): a
# note of some 3,700 characters whose last paragraph states a supply agreement with Coherent,
# the spec's recall-probe evidence in a test's words.
AXT_NOTE = REPO / "tests" / "fixtures" / "investigations" / "axt-supply-agreement.txt"
AXT_NOTE_URL = "https://notes.example.test/axt-coherent-supply-agreement"
AXT_QUOTE = "AXT supplies Coherent with 6-inch indium phosphide substrates"
# What Memory holds of it: the fact in Hindsight's own words (`script_fact_text`), quoting
# nothing.
AXT_MEMORY = "AXT signed a three-year agreement to supply Coherent with 6-inch InP substrates."
GROWN_PLAN = [
    "scout",
    "investigator:coherent",
    "investigator:lumentum",
    "investigator:axt",
    "skeptic",
    "financial_analyst",
    "editor",
]


def import_axt_note(atlas: Atlas) -> str:
    """Record `AXT_NOTE` as an AXT document (`atlas sources import`) and run its retention;
    its Source Version's ID."""
    imported = atlas.cli(
        "sources",
        "import",
        "--company",
        "axt",
        "--file",
        str(AXT_NOTE),
        "--origin-url",
        AXT_NOTE_URL,
        "--published-at",
        "2026-08-05T12:00:00+00:00",
        "--title",
        "AXT supply agreement note, hand-shaped",
    )
    assert imported.returncode == 0, imported.stderr
    atlas.worker_pass()
    return json.loads(imported.stdout)["source_version_id"]


def import_memo(atlas: Atlas, slug: str, name: str) -> str:
    """Record a short hand-written memo for the company (`atlas sources import`), in plain
    English so that it is retained (one section, so one fact in Memory by the fake's
    derivation), and run its retention; its Source Version's ID."""
    memo = atlas.tmp_path / f"{slug}-memo.txt"
    memo.write_text(
        "Synthetic test memo: this is a hand-written memo for a test, and it is not a"
        f" document of {name}.\n\n"
        f"The memo says that {name} is one of the companies in the supply chain of the lasers"
        " that are used in data centers, and that it has not named any of its customers"
        " here.\n",
        encoding="utf-8",
    )
    imported = atlas.cli(
        "sources",
        "import",
        "--company",
        slug,
        "--file",
        str(memo),
        "--origin-url",
        f"https://notes.example.test/{slug}-memo",
        "--published-at",
        "2026-09-02T12:00:00+00:00",
        "--title",
        f"{slug}-memo",
    )
    assert imported.returncode == 0, imported.stderr
    atlas.worker_pass()
    version_id = json.loads(imported.stdout)["source_version_id"]
    assert atlas.memory(version_id)["retained"] is True
    return version_id


def pointed(found: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The companies Memory pointed to in round 1, by slug."""
    return {c["slug"]: c for c in found["pointed_companies"] if c["round"] == 1}


def test_a_company_memory_points_to_gains_an_investigator_that_reads_where_memory_points(
    services: Services, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    # The seeds are Coherent (its recorded filings) and Lumentum (nothing archived). AXT is a
    # theme company, not a seed, with one archived document.
    atlas = services.start()
    fake = services.hindsight[0]
    note = import_axt_note(atlas)
    coherent, lumentum, axt = (atlas.company(slug) for slug in ("coherent", "lumentum", "axt"))
    # Memory holds one fact: the supply agreement in its own words, extracted from AXT's
    # document. (The fake recalls every fact in scope whatever the query, so one fact keeps
    # this test about where a pointer leads.)
    [section] = retained_sections(atlas, AXT_NOTE_URL, "axt")
    fake.script_fact_text(section["document_id"], AXT_MEMORY)
    fake.report_zero_facts(lambda document_id: document_id != section["document_id"])
    agreement: dict[str, JsonValue] = {
        "subject_company_id": axt["id"],
        "predicate": "supplies",
        "object_company_id": coherent["id"],
        "object_name": None,
        "object_text": None,
        "product": "6-inch indium phosphide substrates",
        "layer": "substrate",
        "quote": AXT_QUOTE,
        "epistemic_type": "company_claim",
    }
    started = seeded(atlas, "coherent", "lumentum")
    assert [task["key"] for task in started["tasks"]] == PLAN  # as created: the seeds only
    script_parallel(llm)
    llm.script_chat(
        scout_reply(),
        # Coherent's Investigator and AXT's, in either order: each quotes what it was sent.
        ChatReply.answer(quoting(agreement)),
        ChatReply.answer(quoting(agreement)),
        ChatReply.answer(editing(statement="AXT supplies Coherent with 6-inch InP substrates.")),
        REVIEWED,
    )
    script_searches(searxng)

    atlas.worker_pass()

    found = investigation(atlas, started["id"])
    assert (found["status"], found["stop_reason"]) == ("stopped", "answered")
    # The question and the Scout's three queries each recalled the one fact: four pointers,
    # all at rank 1, all into AXT's document. (The Skeptic's pointers are its own.)
    scouted = [p for p in found["pointers"] if p["task_key"] == "scout"]
    assert {(p["company_id"], p["source_version_id"], p["rank"]) for p in scouted} == {
        (axt["id"], note, 1)
    }
    assert len(scouted) == 4

    # The plan grew after the Scout: AXT's Investigator, after the seeds' and before the
    # Skeptic, with its own company premise; the Skeptic, the Analyst and the Editor wait
    # for all three.
    assert [task["key"] for task in found["tasks"]] == GROWN_PLAN
    assert [task["position"] for task in found["tasks"]] == [1, 2, 3, 4, 5, 6, 7]
    plan = tasks(found)
    added = plan["investigator:axt"]
    assert (added["role"], added["company_id"], added["status"]) == (
        "investigator",
        axt["id"],
        "succeeded",
    )
    assert (added["depends_on"], added["premise_keys"]) == (["scout"], ["question", "company:axt"])
    # Why it was added: four pointers at rank 1, each weighing 1/rank.
    assert added["artifacts"]["added_for_pointers"] == {
        "pointers": 4,
        "entity_pointers": 0,  # the note's section is pointed at by recall already
        "score": 4.0,
        "best_rank": 1,
    }
    investigators = GROWN_PLAN[1:4]
    assert plan["skeptic"]["depends_on"] == plan["financial_analyst"]["depends_on"] == investigators
    assert plan["editor"]["depends_on"] == [*investigators, "skeptic", "financial_analyst"]
    assert [(p["key"], p["status"]) for p in found["premises"]] == [
        ("question", "open"),
        ("company:coherent", "open"),
        ("company:lumentum", "open"),
        ("company:axt", "open"),
    ]
    assert found["premises"][-1]["company_id"] == axt["id"]
    assert (found["budgets"]["max_companies"], found["usage"]["companies"]) == (6, 3)
    # The investigation read says which companies Memory pointed to and what became of each.
    ranked = {
        "company_id": axt["id"],
        "company_name": "AXT",
        "slug": "axt",
        "pointers": 4,
        "entity_pointers": 0,
        "score": 4.0,
        "best_rank": 1,
        "outcome": "added",
        "task_key": "investigator:axt",
    }
    assert found["pointed_companies"] == [{"round": 1} | ranked]
    scout = plan["scout"]["artifacts"]
    assert (scout["investigators_added"], scout["companies_not_read"]) == (1, 0)
    # The events tell it in order: the Scout succeeds, the companies are ranked and AXT's
    # Investigator added, then every Investigator is queued; the Skeptic and the Analyst are
    # queued only after the three have finished.
    log = events(atlas, started["id"])
    kinds = [(e["type"], e["task_key"]) for e in log]
    [ranking] = [e for e in log if e["type"] == "companies_ranked"]
    assert (ranking["round"], ranking["task_key"]) == (1, None)
    assert ranking["detail"] == {
        "max_companies": 6,
        "investigators": 3,
        "added": ["investigator:axt"],
        "not_read": [],
        "companies": [ranked],
    }
    at_ranking = kinds.index(("companies_ranked", None))
    assert kinds.index(("task_succeeded", "scout")) < at_ranking
    assert all(at_ranking < kinds.index(("task_queued", key)) for key in investigators)
    for waiting in ("skeptic", "financial_analyst"):
        queued = kinds.index(("task_queued", waiting))
        assert all(kinds.index(("task_succeeded", key)) < queued for key in investigators)

    # AXT's Investigator read the document the pointers name, and first the window Memory
    # pointed to: the one holding the agreement, beyond the note's first 3,000 characters.
    assert [d["source_version_id"] for d in found["documents"] if d["company_id"] == axt["id"]] == [
        note
    ]
    assert (added["artifacts"]["documents"], added["artifacts"]["documents_pointed"]) == (1, 1)
    extraction = atlas.get(f"/api/v1/claim-extractions/{added['artifacts']['extraction_id']}")
    assert extraction["source_version_ids"] == [note]
    first = extraction["passages"][0]
    at_quote = atlas.parsed(note).index(AXT_QUOTE)
    assert first["char_start"] <= at_quote < first["char_end"]
    assert first["char_start"] > 0
    assert first["selected_by"][:4] == ["pointer:0", "pointer:1", "pointer:2", "pointer:3"]
    assert AXT_MEMORY not in json.dumps(llm.chat_requests())  # Memory reached no role
    assert roles(llm)[:3] == ["scout", "investigator", "investigator"]
    assert roles(llm).count("investigator") == 2  # Lumentum has nothing archived

    # Its accepted Claim is in the Evidence tray and on the card.
    [evidence] = found["evidence"]
    assert (evidence["task_key"], evidence["quote"]) == ("investigator:axt", AXT_QUOTE)
    assert (evidence["subject_company_id"], evidence["object_company_id"]) == (
        axt["id"],
        coherent["id"],
    )
    assert evidence["predicate"] == "supplies"
    assert "pointer:0" in evidence["passage_selected_by"]
    card = found["research_card"]
    [finding] = card["findings"]
    assert finding["claim_ids"] == [evidence["claim_id"]]
    assert finding["entity_ids"] == [axt["id"], coherent["id"]]
    [span] = finding["source_spans"]
    assert (span["source_version_id"], span["quote"]) == (note, AXT_QUOTE)
    # The card's `read` has a row per Investigator, the added one included; nobody was left out.
    assert [r["task_key"] for r in card["read"]] == [*investigators, "skeptic"]
    axt_read = card["read"][2]
    assert (axt_read["company_id"], axt_read["company_name"]) == (axt["id"], "AXT")
    assert (axt_read["claims_proposed"], axt_read["claims_accepted"]) == (1, 1)
    [document] = axt_read["documents"]
    assert (document["source_version_id"], document["selections"]["pointer"]) == (note, 1)
    assert card["not_read"] == []
    # The Financial Analyst still works for the seed companies only: Coherent, which the
    # Claim names; never AXT.
    analyst = next(b for b in requests(llm) if b["metadata"]["role"] == "financial_analyst")
    assert [c["company_id"] for c in asked(analyst)["request"]["companies"]] == [coherent["id"]]
    assert lumentum["id"] in found["request"]["seed_entity_ids"]
    assert axt["id"] not in found["request"]["seed_entity_ids"]
    # The chained relationship review forms the edge between the third company and a seed.
    [edge] = atlas.get("/api/v1/relationships")["items"]
    assert (edge["subject_name"], edge["predicate"], edge["object_name"]) == (
        "AXT",
        "supplies",
        "Coherent",
    )
    assert (edge["subject_company_id"], edge["object_company_id"]) == (axt["id"], coherent["id"])
    assert edge["evidence_count"] == 1


def test_a_pointed_company_the_company_budget_has_no_room_for_is_listed_as_not_read(
    services: Services, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    # Three companies Memory points to (a fact per retained section, recalled by every
    # query): the seeds Coherent and Lumentum, and AXT. The company budget is two.
    atlas = services.start()
    import_memo(atlas, "lumentum", "Lumentum")
    import_memo(atlas, "axt", "AXT")
    axt = atlas.company("axt")
    started = seeded(atlas, "coherent", "lumentum", budgets={"max_companies": 2})
    assert started["budgets"]["max_companies"] == 2
    llm.script_chat(
        scout_reply(),
        ChatReply.json({"claims": []}),
        ChatReply.json({"claims": []}),
        NOTHING_ACCEPTED,
    )
    script_searches(searxng)

    atlas.worker_pass()

    found = investigation(atlas, started["id"])
    assert (found["status"], found["stop_reason"]) == ("stopped", "no_new_independent_evidence")
    # The two seeds are read; the plan did not grow.
    assert [task["key"] for task in found["tasks"]] == PLAN
    assert roles(llm) == ["scout", "investigator", "investigator", "editor"]
    assert (found["budgets"]["max_companies"], found["usage"]["companies"]) == (2, 2)
    # AXT's memo is one retained section: the question and the three queries point to it.
    pointers = [p for p in found["pointers"] if p["company_id"] == axt["id"]]
    assert len(pointers) == 4
    ranked = pointed(found)
    assert {slug: (c["outcome"], c["task_key"]) for slug, c in ranked.items()} == {
        "coherent": ("seed", "investigator:coherent"),
        "lumentum": ("seed", "investigator:lumentum"),
        "axt": ("no_room", None),
    }
    left_out = ranked["axt"]
    assert (left_out["pointers"], left_out["best_rank"]) == (4, min(p["rank"] for p in pointers))
    assert left_out["score"] == pytest.approx(sum(1 / p["rank"] for p in pointers), abs=1e-4)
    scout = tasks(found)["scout"]["artifacts"]
    assert (scout["investigators_added"], scout["companies_not_read"]) == (0, 1)
    [ranking] = [e for e in events(atlas, started["id"]) if e["type"] == "companies_ranked"]
    assert (ranking["detail"]["max_companies"], ranking["detail"]["investigators"]) == (2, 2)
    assert (ranking["detail"]["added"], ranking["detail"]["not_read"]) == ([], ["axt"])
    # The card lists it as not read, with its pointers, so the next investigation can seed it.
    card = found["research_card"]
    assert [r["task_key"] for r in card["read"]] == [
        "investigator:coherent",
        "investigator:lumentum",
        "skeptic",
    ]
    assert card["not_read"] == [
        {
            "round": 1,
            "company_id": axt["id"],
            "company_name": "AXT",
            "pointers": 4,
            "score": left_out["score"],
            "best_rank": left_out["best_rank"],
            "reason": "the company budget (2 Investigators a round) had no room",
            "entity_pointers": 0,
            "channels": ["recall"],
        }
    ]
    assert not [d for d in found["documents"] if d["company_id"] == axt["id"]]


def test_with_room_for_one_more_company_the_better_pointed_one_is_read(
    services: Services, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    # Lumentum's memo is retained before AXT's, so its fact ranks above AXT's in every
    # recall (the fake recalls in retain order) and its pointers weigh more.
    atlas = services.start()
    import_memo(atlas, "lumentum", "Lumentum")
    import_memo(atlas, "axt", "AXT")
    started = seeded(atlas, "coherent", budgets={"max_companies": 2})
    llm.script_chat(
        scout_reply(),
        ChatReply.json({"claims": []}),
        ChatReply.json({"claims": []}),
        NOTHING_ACCEPTED,
    )
    script_searches(searxng)

    atlas.worker_pass()

    found = investigation(atlas, started["id"])
    assert [t["key"] for t in found["tasks"] if t["role"] == "investigator"] == [
        "investigator:coherent",
        "investigator:lumentum",
    ]
    ranked = pointed(found)
    assert list(ranked) == ["coherent", "lumentum", "axt"]  # best first
    assert ranked["lumentum"]["score"] > ranked["axt"]["score"]
    assert [c["outcome"] for c in ranked.values()] == ["seed", "added", "no_room"]
    assert [each["company_name"] for each in found["research_card"]["not_read"]] == ["AXT"]


def test_an_investigator_takes_the_documents_its_pointers_name_before_its_latest_ones(
    services: Services, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    atlas = services.start()
    fake = services.hindsight[0]
    ten_k = atlas.version(COHR_10K, "coherent")
    ten_q = atlas.version(COHR_10Q, "coherent")
    assert at(ten_q["available_at"]) < at(ten_k["available_at"])
    # A document of Coherent's newer than both filings, which Memory holds nothing of.
    [note] = import_transcripts(atlas, "coherent", "Coherent", 1)
    # Memory holds one fact, from the older filing: the 10-Q is pointed at, the newer 10-K
    # and the newest note are not, and the document budget has room for two.
    section = retained_sections(atlas, COHR_10Q, "coherent")[0]
    fake.report_zero_facts(lambda document_id: document_id != section["document_id"])
    started = seeded(atlas, "coherent", budgets={"max_documents": 2})
    llm.script_chat(scout_reply(), ChatReply.json({"claims": []}), NOTHING_ACCEPTED)
    script_searches(searxng)

    atlas.worker_pass()

    found = investigation(atlas, started["id"])
    assert {p["source_version_id"] for p in found["pointers"]} == {ten_q["id"]}
    # The 10-K is the floor (the latest periodic report, pilot fix 24), the 10-Q the pointed
    # document; the newest note, neither, is left out.
    read = {d["source_version_id"] for d in found["documents"]}
    assert read == {ten_k["id"], ten_q["id"]}
    assert note not in read
    artifacts = tasks(found)["investigator:coherent"]["artifacts"]
    assert (artifacts["documents"], artifacts["documents_pointed"]) == (2, 1)
    assert artifacts["documents_floor"] == [ten_k["id"]]
    assert artifacts["documents_dropped"] == 1  # the newest note


def import_transcripts(atlas: Atlas, slug: str, name: str, count: int) -> list[str]:
    """Record `count` short hand-written stand-ins for results-call transcripts of the company
    (`atlas sources import`), published in September 2026 (newer than any recorded filing, the
    first oldest), in plain English so each is retained (one section, so one fact in Memory
    by the fake's derivation), and run their retention; their Source Versions' IDs, in import
    order."""
    ids: list[str] = []
    for number in range(1, count + 1):
        path = atlas.tmp_path / f"{slug}-transcript-{number}.txt"
        path.write_text(
            f"Synthetic test transcript {number}: a hand-written stand-in for a results call,"
            f" and it is not a transcript of {name}.\n\n"
            f"In call {number} the speaker says that demand for the lasers used in data"
            " centers stayed strong in the quarter, and names no customer.\n",
            encoding="utf-8",
        )
        imported = atlas.cli(
            "sources",
            "import",
            "--company",
            slug,
            "--file",
            str(path),
            "--origin-url",
            f"https://transcripts.example.test/{slug}-call-{number}",
            "--published-at",
            f"2026-09-{number + 10:02d}T12:00:00+00:00",
            "--title",
            f"{name} call transcript {number}, hand-shaped",
        )
        assert imported.returncode == 0, imported.stderr
        atlas.worker_pass()
        version_id = json.loads(imported.stdout)["source_version_id"]
        assert atlas.memory(version_id)["retained"] is True
        ids.append(version_id)
    return ids


def lumentum_with_pointed_transcripts(
    services: Services, transcripts: int
) -> tuple[Atlas, dict[str, str], list[str]]:
    """Lumentum's recorded filings (the FY2026 10-K, the Q4 results 8-K with its EX-99.1 and
    the Q3 10-Q) and `transcripts` hand-written transcripts, every one of Memory's facts from
    a transcript: the round's pointers name only transcripts, the first imported best (the
    fake recalls in retain order)."""
    atlas = services.start(ingest=False)
    fake = services.hindsight[0]
    atlas.ingest_company("lumentum")
    filings = {
        name: atlas.version(url, "lumentum")["id"]
        for name, url in [
            ("10-K", LITE_10K),
            ("8-K", LITE_8K),
            ("EX-99.1", LITE_EX991),
            ("10-Q", LITE_10Q),
        ]
    }
    calls = import_transcripts(atlas, "lumentum", "Lumentum", transcripts)
    held = {d["document_id"] for version in calls for d in atlas.memory(version)["documents"]}
    fake.report_zero_facts(lambda document_id: document_id not in held)
    return atlas, filings, calls


def test_a_filing_the_corrected_availability_puts_after_as_of_is_not_read(
    services: Services, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    # Pilot-fix 29: the 10-Q recorded itself available in May 2026, before the as-of time, but
    # a recorded correction (EDGAR held it back) makes it public after it: it is not read, by
    # the pointed documents, the latest documents or the document floor alike.
    atlas = services.start()
    ten_q = atlas.version(COHR_10Q, "coherent")["id"]
    with atlas.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO source_version_availability_correction (id, source_version_id,"
                " available_at, available_at_basis, reason)"
                " VALUES (gen_random_uuid(), :id, '2026-07-02T00:00:00Z', 'sec_dissemination',"
                " 'test')"
            ),
            {"id": ten_q},
        )
    started = seeded(atlas, "coherent", as_of="2026-07-01T00:00:00Z")
    llm.script_chat(scout_reply(), ChatReply.json({"claims": []}), NOTHING_ACCEPTED)
    script_searches(searxng)

    atlas.worker_pass()

    found = investigation(atlas, started["id"])
    assert found["documents"] == []


def test_an_investigator_reads_its_company_s_latest_periodic_report_and_results_release(
    services: Services, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    # Pilot investigation 1 on 0.3.1: the pointers named transcripts only, and no 10-K, 10-Q
    # or 8-K was read. The floor: the latest periodic report and the latest results release.
    atlas, filings, calls = lumentum_with_pointed_transcripts(services, 3)
    started = seeded(atlas, "lumentum", budgets={"max_documents": 4})
    llm.script_chat(scout_reply(), ChatReply.json({"claims": []}), NOTHING_ACCEPTED)
    script_searches(searxng)

    atlas.worker_pass()

    found = investigation(atlas, started["id"])
    scouted = {p["source_version_id"] for p in found["pointers"] if p["task_key"] == "scout"}
    assert scouted == set(calls)
    # The 10-K (the latest periodic report, not the older 10-Q), the press release (EX-99.1,
    # the latest results release) and the best-pointed transcripts, within the share.
    read = {d["source_version_id"] for d in found["documents"]}
    assert read == {filings["10-K"], filings["EX-99.1"], calls[0], calls[1]}
    artifacts = tasks(found)["investigator:lumentum"]["artifacts"]
    assert artifacts["documents_floor"] == [filings["10-K"], filings["EX-99.1"]]
    assert (artifacts["documents"], artifacts["documents_pointed"]) == (4, 2)
    # Left out: the third transcript, the 10-Q and the 8-K's own document.
    assert artifacts["documents_dropped"] == 3
    # The card's `read` says which documents came from the floor.
    [row] = [r for r in found["research_card"]["read"] if r["task_key"] == "investigator:lumentum"]
    assert {d["source_version_id"]: d["floor"] for d in row["documents"]} == {
        filings["10-K"]: True,
        filings["EX-99.1"]: True,
        calls[0]: False,
        calls[1]: False,
    }


def test_a_share_of_two_takes_the_periodic_report_and_the_best_pointed_document(
    services: Services, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    atlas, filings, calls = lumentum_with_pointed_transcripts(services, 2)
    started = seeded(atlas, "lumentum", budgets={"max_documents": 2})
    llm.script_chat(scout_reply(), ChatReply.json({"claims": []}), NOTHING_ACCEPTED)
    script_searches(searxng)

    atlas.worker_pass()

    found = investigation(atlas, started["id"])
    assert {d["source_version_id"] for d in found["documents"]} == {filings["10-K"], calls[0]}
    artifacts = tasks(found)["investigator:lumentum"]["artifacts"]
    assert artifacts["documents_floor"] == [filings["10-K"]]
    assert (artifacts["documents"], artifacts["documents_pointed"]) == (2, 1)
    # The results release, the 10-Q, the 8-K and the second transcript are left out.
    assert artifacts["documents_dropped"] == 4


def test_a_company_with_no_periodic_report_takes_its_pointed_documents(
    services: Services, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    atlas = services.start(ingest=False)
    fake = services.hindsight[0]
    calls = import_transcripts(atlas, "lumentum", "Lumentum", 3)
    # Memory holds the first two transcripts' facts; the third, the newest, is not pointed at.
    held = {d["document_id"] for version in calls[:2] for d in atlas.memory(version)["documents"]}
    fake.report_zero_facts(lambda document_id: document_id not in held)
    started = seeded(atlas, "lumentum", budgets={"max_documents": 2})
    llm.script_chat(scout_reply(), ChatReply.json({"claims": []}), NOTHING_ACCEPTED)
    script_searches(searxng)

    atlas.worker_pass()

    found = investigation(atlas, started["id"])
    assert {d["source_version_id"] for d in found["documents"]} == {calls[0], calls[1]}
    artifacts = tasks(found)["investigator:lumentum"]["artifacts"]
    assert artifacts["documents_floor"] == []
    assert (artifacts["documents"], artifacts["documents_pointed"]) == (2, 2)
    assert artifacts["documents_dropped"] == 1  # the newest transcript


# --- the entity hop (memory-quality ticket 09) -------------------------------------------------


def import_text(atlas: Atlas, slug: str, title: str, body: str, published_at: str) -> str:
    """Record a short hand-written document of the company (`atlas sources import`), published
    at `published_at`, and run its retention; its Source Version's ID."""
    path = atlas.tmp_path / f"{title}.txt"
    path.write_text(body, encoding="utf-8")
    imported = atlas.cli(
        "sources",
        "import",
        "--company",
        slug,
        "--file",
        str(path),
        "--origin-url",
        f"https://notes.example.test/{title}",
        "--published-at",
        published_at,
        "--title",
        title,
    )
    assert imported.returncode == 0, imported.stderr
    atlas.worker_pass()
    version_id = json.loads(imported.stdout)["source_version_id"]
    assert atlas.memory(version_id)["retained"] is True
    return version_id


def company_memo(atlas: Atlas, title: str, published_at: str) -> str:
    """A Coherent memo that names no other company (its title makes its bytes its own)."""
    return import_text(
        atlas,
        "coherent",
        title,
        f"Synthetic test memo {title}, hand-written for a test. The memo says that Coherent"
        " makes lasers for data centers in its own plants and names none of its customers.\n",
        published_at,
    )


LUMENTUM_ON_COHERENT = (
    "Synthetic test memo, hand-written for a test. The memo says that Lumentum competes with"
    " Coherent in datacom lasers and that the two companies sell to the same customers.\n"
)


def entity_hops(found: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Round 1's entity hops, by the slug of the company each was made for."""
    return {hop["slug"]: hop for hop in found["entity_hops"] if hop["round"] == 1}


def test_a_document_of_another_company_naming_a_seed_is_read_through_the_entity_hop(
    services: Services, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    # Memory answers each recall with its one best fact only (a text budget of one token):
    # Coherent's memo, the nearest to the as-of time. AXT's note names Coherent in its last
    # section, which no recall returns.
    atlas = services.start(ingest=False, pointer_recall_max_tokens=1)
    fake = services.hindsight[0]
    fake.derive_recall_options()
    memo = company_memo(atlas, "coherent-memo", "2026-09-02T12:00:00+00:00")
    note = import_axt_note(atlas)  # published 2026-08-05
    coherent, axt = atlas.company("coherent"), atlas.company("axt")
    [section] = retained_sections(atlas, AXT_NOTE_URL, "axt")
    fake.script_fact_text(section["document_id"], AXT_MEMORY)
    started = seeded(atlas, "coherent", as_of="2026-09-10T00:00:00Z")
    llm.script_chat(
        scout_reply(),
        ChatReply.json({"claims": []}),
        ChatReply.json({"claims": []}),
        NOTHING_ACCEPTED,
    )
    script_searches(searxng)

    atlas.worker_pass()

    found = investigation(atlas, started["id"])
    assert (found["status"], found["stop_reason"]) == ("stopped", "no_new_independent_evidence")
    # Every recall pointed at Coherent's memo only; none at AXT's note.
    assert {p["source_version_id"] for p in found["pointers"]} == {memo}
    assert {p["query_kind"] for p in found["pointers"]} == {"scout"}
    # The hop for Coherent listed the theme's facts carrying its entity: its own memo's (no
    # pointer) and the note's, which became one entity pointer, apart from the recall pointers.
    [hopped] = found["entity_pointers"]
    assert (hopped["round"], hopped["task_key"], hopped["query_kind"]) == (1, "scout", "entity")
    assert (hopped["source_version_id"], hopped["section_anchor"]) == (
        note,
        section["section_anchor"],
    )
    assert (hopped["company_id"], hopped["company_name"]) == (axt["id"], "AXT")
    assert (hopped["query_company_id"], hopped["query_company_name"]) == (
        coherent["id"],
        "Coherent",
    )
    assert (hopped["query"], hopped["query_index"], hopped["rank"]) == ("Coherent Corp.", 1, 1)
    assert (hopped["memory_type"], hopped["memory_text"]) == ("world", AXT_MEMORY)
    assert hopped["entity_id"]
    hop = entity_hops(found)["coherent"]
    assert (hop["company_id"], hop["entity_name"], hop["entity_id"]) == (
        coherent["id"],
        "Coherent Corp.",
        hopped["entity_id"],
    )
    assert (hop["outcome"], hop["facts_listed"], hop["pointers"]) == ("listed", 2, 1)
    assert (hop["own_documents"], hop["after_as_of"], hop["already_pointed"]) == (1, 0, 0)
    scout = tasks(found)["scout"]["artifacts"]
    assert (scout["entity_pointers"], scout["entity_listings_failed"]) == (1, 0)

    # AXT joined the ranking by its entity pointer, at half a recall pointer's best weight,
    # and the plan gained its Investigator.
    ranked = pointed(found)
    assert ranked["axt"] == {
        "round": 1,
        "company_id": axt["id"],
        "company_name": "AXT",
        "slug": "axt",
        "pointers": 0,
        "entity_pointers": 1,
        "score": 0.5,
        "best_rank": None,
        "outcome": "added",
        "task_key": "investigator:axt",
    }
    plan = tasks(found)
    added = plan["investigator:axt"]
    assert added["artifacts"]["added_for_pointers"] == {
        "pointers": 0,
        "entity_pointers": 1,
        "score": 0.5,
        "best_rank": None,
    }
    # AXT's Investigator read the note, and its passages include the section that names
    # Coherent, selected by the entity pointer.
    assert [d["source_version_id"] for d in found["documents"] if d["company_id"] == axt["id"]] == [
        note
    ]
    assert added["artifacts"]["documents_pointed"] == 1
    extraction = atlas.get(f"/api/v1/claim-extractions/{added['artifacts']['extraction_id']}")
    tag = f"entity_pointer:{coherent['id']}"
    at_quote = atlas.parsed(note).index(AXT_QUOTE)
    [chosen] = [p for p in extraction["passages"] if tag in p["selected_by"]]
    assert chosen["char_start"] <= at_quote < chosen["char_end"]
    assert chosen["section_anchor"] == section["section_anchor"]
    # The card's `read` names the channel; the memory's text reached no role.
    axt_read = next(
        r for r in found["research_card"]["read"] if r["task_key"] == "investigator:axt"
    )
    [document] = axt_read["documents"]
    assert document["selections"]["entity_pointer"] == 1
    assert AXT_MEMORY not in json.dumps(llm.chat_requests())
    # Co-mention is a reason to read: no Claim was accepted, so no edge and no Evidence.
    assert found["evidence"] == []
    assert atlas.get("/api/v1/relationships")["items"] == []


def test_the_entity_hop_keeps_to_the_as_of_time_its_own_documents_and_its_bounds(
    services: Services, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    # One company hopped, one pointer each; each recall gives its one best fact (a Coherent
    # memo, the nearest to the as-of time).
    atlas = services.start(
        ingest=False,
        pointer_recall_max_tokens=1,
        entity_hop_max_companies=1,
        entity_hop_max_facts=1,
    )
    services.hindsight[0].derive_recall_options()
    company_memo(atlas, "coherent-september", "2026-09-09T12:00:00+00:00")
    company_memo(atlas, "coherent-august", "2026-08-14T12:00:00+00:00")
    note = import_axt_note(atlas)  # 2026-08-05
    lumentum_memo = import_text(
        atlas, "lumentum", "lumentum-on-coherent", LUMENTUM_ON_COHERENT, "2026-09-05T12:00:00+00:00"
    )
    script_searches(searxng)

    # As of September 10, two documents of other companies name Coherent; one fact is taken,
    # the newest: Lumentum's memo.
    llm.script_chat(
        scout_reply(),
        ChatReply.json({"claims": []}),
        ChatReply.json({"claims": []}),
        NOTHING_ACCEPTED,
    )
    september = seeded(atlas, "coherent", as_of="2026-09-10T00:00:00Z")
    atlas.worker_pass()
    found = investigation(atlas, september["id"])
    assert [(p["source_version_id"], p["query_kind"]) for p in found["entity_pointers"]] == [
        (lumentum_memo, "entity")
    ]
    hop = entity_hops(found)["coherent"]
    assert (hop["facts_listed"], hop["own_documents"], hop["after_as_of"]) == (4, 2, 0)
    assert (hop["pointers"], hop["beyond_limit"]) == (1, 1)
    assert [c["slug"] for c in found["pointed_companies"] if c["outcome"] == "added"] == [
        "lumentum"
    ]

    # As of August 15 Lumentum's memo is not public yet: only AXT's note is pointed at. The
    # seeds are Coherent and Lumentum, and the hop is bounded to one company: Coherent. The
    # company budget is the two seeds, so AXT is not read.
    llm.script_chat(scout_reply(), ChatReply.json({"claims": []}), NOTHING_ACCEPTED)
    script_searches(searxng)
    august = seeded(
        atlas,
        "coherent",
        "lumentum",
        as_of="2026-08-15T00:00:00Z",
        budgets={"max_companies": 2},
    )
    atlas.worker_pass()
    found = investigation(atlas, august["id"])
    assert [p["source_version_id"] for p in found["entity_pointers"]] == [note]
    assert list(entity_hops(found)) == ["coherent"]
    hop = entity_hops(found)["coherent"]
    # Its September memo is its own; Lumentum's memo is after the as-of time.
    assert (hop["facts_listed"], hop["own_documents"], hop["after_as_of"]) == (4, 2, 1)
    assert (hop["pointers"], hop["beyond_limit"]) == (1, 0)
    assert all(p["available_at"] <= "2026-08-15" for p in found["entity_pointers"])
    # The card's `not_read` names the channel that reached AXT: the entity hop alone.
    [unread] = found["research_card"]["not_read"]
    assert (unread["company_name"], unread["channels"]) == ("AXT", ["entity"])
    assert (unread["pointers"], unread["entity_pointers"], unread["best_rank"]) == (0, 1, None)
    assert unread["score"] == 0.5


def test_a_failed_listing_leaves_the_scout_succeeded_and_a_company_without_an_entity_is_recorded(
    services: Services, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    atlas = services.start(ingest=False)
    fake = services.hindsight[0]
    company_memo(atlas, "coherent-memo", "2026-09-02T12:00:00+00:00")
    fake.fail_entity_memories(500)
    # Lumentum has no document: no retain item ever named it, so Memory has no entity for it.
    started = seeded(atlas, "coherent", "lumentum", as_of="2026-09-10T00:00:00Z")
    llm.script_chat(scout_reply(), ChatReply.json({"claims": []}), NOTHING_ACCEPTED)
    script_searches(searxng)

    atlas.worker_pass()

    found = investigation(atlas, started["id"])
    assert statuses(found)["scout"] == "succeeded"
    assert (found["status"], found["stop_reason"]) == ("stopped", "no_new_independent_evidence")
    assert found["entity_pointers"] == []
    hops = entity_hops(found)
    assert (hops["coherent"]["outcome"], hops["coherent"]["pointers"]) == ("listing_failed", 0)
    assert (hops["lumentum"]["outcome"], hops["lumentum"]["entity_id"]) == ("no_entity", None)
    assert hops["lumentum"]["entity_name"] == "Lumentum Holdings Inc."
    [failed] = [e for e in events(atlas, started["id"]) if e["type"] == "entity_listing_failed"]
    assert (failed["round"], failed["task_key"]) == (1, "scout")
    assert failed["detail"]["company_id"] == atlas.company("coherent")["id"]
    assert "HTTP 500" in failed["detail"]["error"]
    scout = tasks(found)["scout"]["artifacts"]
    assert (scout["entity_pointers"], scout["entity_listings_failed"]) == (0, 1)


def test_with_no_accepted_claim_the_editor_writes_a_card_of_what_was_searched_and_read(
    services: Services, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    atlas = services.start()
    started = seeded(atlas, "coherent", "lumentum")
    misquote = "Coherent is the sole qualified supplier of EML lasers to NVIDIA"

    def misquoting(body: dict[str, Any]) -> JsonValue:
        first = asked(body)["retrieved_data"][0]
        claim = supply_claim(atlas) | {
            "quote": misquote,
            "passage_id": first["id"],
            "quote_start": 0,
            "quote_end": len(misquote),
        }
        return {"claims": [claim]}

    llm.script_chat(scout_reply(), ChatReply.answer(misquoting), NOTHING_ACCEPTED)
    script_searches(searxng)

    atlas.worker_pass()

    found = investigation(atlas, started["id"])
    # The stop reason is as before; the Skeptic and the Analyst have nothing to work on.
    assert (found["status"], found["stop_reason"]) == ("stopped", "no_new_independent_evidence")
    assert (
        found["stop_detail"] == "no new independent Evidence: the Investigator accepted no Claims"
    )
    assert statuses(found) == {
        "scout": "succeeded",
        "investigator:coherent": "succeeded",
        "investigator:lumentum": "succeeded",
        "skeptic": "skipped",
        "financial_analyst": "skipped",
        "editor": "succeeded",
    }
    assert roles(llm) == ["scout", "investigator", "editor"]
    [rejected] = atlas.get("/api/v1/claims")["items"]
    assert rejected["outcome"] == "rejected"
    reason = rejected["reason_code"]
    extraction = atlas.get(
        "/api/v1/claim-extractions/"
        f"{tasks(found)['investigator:coherent']['artifacts']['extraction_id']}"
    )
    ten_k = atlas.version(COHR_10K, "coherent")["id"]
    ten_q = atlas.version(COHR_10Q, "coherent")["id"]
    titles = {d["source_version_id"]: d["title"] for d in found["documents"]}
    sections: dict[str, list[str]] = {}
    for passage in extraction["passages"]:
        anchors = sections.setdefault(passage["source_version_id"], [])
        if passage["section_anchor"] not in anchors:
            anchors.append(passage["section_anchor"])
    assert sections[ten_k]  # the Investigator was sent passages of the 10-K

    # The Editor was sent no Claim, and what was searched and read.
    editor = asked(requests(llm)[-1])["request"]
    assert editor["claims"] == []
    assert editor["queries"] == QUERIES
    coherent_read, lumentum_read = editor["read"]
    assert coherent_read == {
        "company": "Coherent",
        "documents": [
            {"title": titles[ten_k], "sections": sections[ten_k]},
            {"title": titles[ten_q], "sections": sections.get(ten_q, [])},
        ],
        "documents_dropped": 0,
        "passages": len(extraction["passages"]),
        "claims_proposed": 1,
        "claims_accepted": 0,
        "rejected": {reason: 1},
        "detail": None,
    }
    assert (lumentum_read["company"], lumentum_read["documents"]) == ("Lumentum", [])
    assert "no parsed Source Version" in lumentum_read["detail"]

    # The card: no finding; what was searched and read; the next round's questions.
    card = found["research_card"]
    assert (card["findings"], card["unsupported_findings"]) == ([], [])
    assert (card["editor_verdict"], card["claims_considered"]) == ("needs_review", 0)
    assert card["open_questions"] == NEXT_ROUND
    [searched] = card["searched"]
    assert searched["discovery_id"] == tasks(found)["scout"]["artifacts"]["discovery_id"]
    assert (searched["round"], searched["queries"], searched["leads_found"]) == (1, QUERIES, 3)
    assert searched["lead_ids"] == [lead["lead_id"] for lead in found["leads"]]
    coherent_card, lumentum_card, skeptic_card = card["read"]
    # The Skeptic's row says it read nothing, and why (pilot fix 06).
    assert (skeptic_card["role"], skeptic_card["task_key"], skeptic_card["status"]) == (
        "skeptic",
        "skeptic",
        "skipped",
    )
    assert (skeptic_card["documents"], skeptic_card["passages"]) == ([], 0)
    assert skeptic_card["detail"] == "nothing to challenge: the Investigators accepted no Claim"
    assert (coherent_card["role"], lumentum_card["role"]) == ("investigator", "investigator")
    assert (coherent_card["task_key"], coherent_card["company_id"]) == (
        "investigator:coherent",
        company_id(atlas, "coherent"),
    )
    assert [d["source_version_id"] for d in coherent_card["documents"]] == [ten_k, ten_q]
    assert [d["sections"] for d in coherent_card["documents"]] == [
        sections[ten_k],
        sections.get(ten_q, []),
    ]
    assert (
        coherent_card["passages"],
        coherent_card["claims_proposed"],
        coherent_card["claims_accepted"],
        coherent_card["rejected"],
    ) == (len(extraction["passages"]), 1, 0, {reason: 1})
    assert (lumentum_card["task_key"], lumentum_card["documents"]) == ("investigator:lumentum", [])
    assert "no parsed Source Version" in lumentum_card["detail"]
    # Nothing was accepted, so nothing is queued for relationship review.
    assert "relationship_review_queued" not in [e["type"] for e in events(atlas, started["id"])]
    # The card's open questions can start the follow-up round; it has no finding to save.
    refused = atlas.api.post("/api/v1/hypotheses", json={"investigation_id": started["id"]})
    assert refused.status_code == 409
    assert "without a research card finding" in refused.json()["error"]["message"]
    followed = atlas.api.post(
        f"/api/v1/investigations/{started['id']}/follow-up", json={"question": NEXT_ROUND[1]}
    )
    assert followed.status_code == 200, followed.text


def test_budget_exhaustion_stops_resumably_and_resuming_continues_in_the_same_run(
    services: Services, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    atlas = services.start(investigator_passages_per_call=1, investigation_max_passages=3)
    started = seeded(atlas, "coherent", budgets={"token_budget": 1000, "max_documents": 1})
    llm.script_chat(
        scout_reply(tokens=(100, 20)), ChatReply.json({"claims": []}, tokens=(900, 150))
    )
    script_searches(searxng)

    atlas.worker_pass()

    stopped = investigation(atlas, started["id"])
    assert (stopped["status"], stopped["stop_reason"]) == ("stopped", "budget_exhausted")
    assert stopped["resumable"] is True
    assert stopped["stop_detail"] == (
        "the run's token budget ran out during the Investigator's extraction"
    )
    assert statuses(stopped) == {
        "scout": "succeeded",
        "investigator:coherent": "budget_exhausted",
        "skeptic": "pending",
        "financial_analyst": "pending",
        "editor": "pending",
    }
    # A partial investigation: what was found is kept, nothing was invented.
    assert len(stopped["leads"]) == 3
    assert stopped["research_card"] is None
    assert roles(llm) == ["scout", "investigator"]
    first = tasks(stopped)["investigator:coherent"]["artifacts"]["extraction_id"]
    extraction = atlas.get(f"/api/v1/claim-extractions/{first}")
    assert (extraction["status"], extraction["batches_done"], extraction["batches_total"]) == (
        "budget_exhausted",
        1,
        3,
    )
    # The run stays open for the resume: no investigation tokens are counted as finished.
    run_id = stopped["run_id"]
    tokens = "atlas_llm_tokens_total"
    assert metric(atlas, tokens, kind="investigation", direction="input") == 0
    assert metric(atlas, "atlas_investigation_stops_total", reason="budget_exhausted") == 1

    # A resume needs a larger budget.
    refused = atlas.api.post(
        f"/api/v1/investigations/{started['id']}/resume", json={"token_budget": 1000}
    )
    assert refused.status_code == 422
    llm.script_chat(
        ChatReply.json({"claims": []}), ChatReply.json({"claims": []}), NOTHING_ACCEPTED
    )
    resumed = atlas.api.post(
        f"/api/v1/investigations/{started['id']}/resume", json={"token_budget": 50_000}
    )
    assert resumed.status_code == 200, resumed.text
    assert (resumed.json()["status"], resumed.json()["budgets"]["token_budget"]) == (
        "running",
        50_000,
    )
    assert tasks(resumed.json())["investigator:coherent"]["generation"] == 1

    atlas.worker_pass()

    found = investigation(atlas, started["id"])
    assert (found["status"], found["stop_reason"]) == ("stopped", "no_new_independent_evidence")
    assert found["run_id"] == run_id
    # The continuation sent the remaining passages only, in the same run.
    sent = [asked(body)["retrieved_data"][0]["id"] for body in llm.chat_requests()[1:4]]
    assert sent == ["p1", "p2", "p3"]
    second = tasks(found)["investigator:coherent"]["artifacts"]["extraction_id"]
    continuation = atlas.get(f"/api/v1/claim-extractions/{second}")
    assert (continuation["continues_id"], continuation["run_id"]) == (first, run_id)
    assert (continuation["status"], continuation["batches_total"]) == ("completed", 2)
    calls = atlas.get(f"/api/v1/runs/{run_id}/role-calls")
    assert call_roles(calls["role_calls"]) == [
        ("scout", "accepted"),
        ("investigator", "accepted"),
        ("investigator", "budget_exhausted"),
        ("investigator", "accepted"),
        ("investigator", "accepted"),
        ("editor", "accepted"),
    ]
    # The card counts the passages sent across the extraction and its continuation.
    read, _skeptic = found["research_card"]["read"]
    assert (read["passages"], read["claims_proposed"]) == (3, 0)
    assert [d["passages"] for d in read["documents"]] == [3]
    assert metric(atlas, tokens, kind="investigation", direction="input") == calls["tokens_in"]
    assert [
        e["type"] for e in events(atlas, started["id"]) if e["type"] in ("stopped", "resumed")
    ] == [
        "stopped",
        "resumed",
        "stopped",
    ]
    for reason, count in [("budget_exhausted", 1), ("no_new_independent_evidence", 1)]:
        assert metric(atlas, "atlas_investigation_stops_total", reason=reason) == count


def test_a_budget_spent_before_the_skeptic_and_the_analyst_resumes_into_them_and_the_editor(
    services: Services, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    atlas = services.start()
    started = seeded(atlas, "coherent", budgets={"token_budget": 5000})
    llm.script_chat(
        scout_reply(tokens=(100, 20)),
        ChatReply.answer(quoting(supply_claim(atlas)), tokens=(4500, 500)),
    )
    script_searches(searxng)

    atlas.worker_pass()

    stopped = investigation(atlas, started["id"])
    # The Skeptic's and the Analyst's jobs are queued together; whichever runs first finds
    # the budget spent and stops the investigation, and the other's job then doesn't run.
    parallel = {key: tasks(stopped)[key]["status"] for key in ("skeptic", "financial_analyst")}
    assert sorted(parallel.values()) == ["budget_exhausted", "queued"]
    [spent] = [key for key, status in parallel.items() if status == "budget_exhausted"]
    assert (stopped["stop_reason"], tasks(stopped)["editor"]["status"]) == (
        "budget_exhausted",
        "pending",
    )
    assert f"before the {spent}'s call" in stopped["stop_detail"]
    assert stopped["research_card"] is None
    assert roles(llm) == ["scout", "investigator"]

    # A resumable stop doesn't chain the relationship review: the run isn't over.
    assert "relationship_review_queued" not in [e["type"] for e in events(atlas, started["id"])]

    script_parallel(llm)
    llm.script_chat(ChatReply.answer(editing()), REVIEWED)
    resumed = atlas.api.post(
        f"/api/v1/investigations/{started['id']}/resume", json={"token_budget": 20_000}
    )
    assert resumed.status_code == 200, resumed.text
    atlas.worker_pass()

    found = investigation(atlas, started["id"])
    assert found["stop_reason"] == "answered"
    assert tasks(found)["skeptic"]["status"] == "succeeded"
    assert len(found["research_card"]["findings"]) == 1
    assert tasks(found)["financial_analyst"]["status"] == "succeeded"
    assert roles(llm) == [
        "scout",
        "investigator",
        "skeptic",  # its plan
        "skeptic",  # its reading of the fallback's documents
        "financial_analyst",
        "editor",
        "reviewer",
    ]


# --- an LLM outage --------------------------------------------------------------------------------


def test_an_llm_outage_pauses_the_investigation_and_it_resumes_with_nothing_invented(
    services: Services, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    atlas = services.start()
    clock = Clock(datetime.now(UTC))
    worker = paced(atlas, clock)
    started = seeded(atlas, "coherent")
    script_parallel(llm)
    llm.script_chat(
        scout_reply(),
        ChatReply.answer(quoting(supply_claim(atlas))),
        ChatReply.error(503, "Service Unavailable"),
    )
    script_searches(searxng)

    worker.run_once()

    paused = investigation(atlas, started["id"])
    assert (paused["status"], paused["paused"]) == ("running", True)
    assert tasks(paused)["editor"]["status"] == "queued"
    assert paused["research_card"] is None
    job = atlas.get(f"/api/v1/jobs/{tasks(paused)['editor']['job_id']}")
    assert (job["status"], job["attempts"]) == ("queued", 0)
    pause = atlas.get("/api/v1/queue")["pause"]
    assert "investigation_task" in pause["kinds"]
    [paused_event] = [e for e in events(atlas, started["id"]) if e["type"] == "task_paused"]
    assert (paused_event["task_key"], paused_event["detail"]["error_class"]) == (
        "editor",
        "unavailable",
    )

    clock.advance(hours=2)
    llm.script_chat(ChatReply.answer(editing()), REVIEWED)
    worker.run_once()

    found = investigation(atlas, started["id"])
    assert (found["status"], found["stop_reason"], found["paused"]) == (
        "stopped",
        "answered",
        False,
    )
    calls = atlas.get(f"/api/v1/runs/{found['run_id']}/role-calls")["role_calls"]
    assert call_roles(calls) == [
        ("scout", "accepted"),
        ("investigator", "accepted"),
        ("skeptic", "accepted"),
        ("skeptic", "accepted"),  # its reading of the fallback's documents
        ("financial_analyst", "accepted"),
        ("editor", "failed"),
        ("editor", "accepted"),
    ]
    editor_events = [e["type"] for e in events(atlas, started["id"]) if e["task_key"] == "editor"]
    assert editor_events == [
        "task_queued",
        "task_started",
        "task_paused",
        "task_resumed",
        "task_succeeded",
    ]


# --- premises -------------------------------------------------------------------------------------


def test_a_disproven_premise_cancels_only_the_tasks_that_depend_on_it(
    services: Services, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    atlas = services.start()
    started = seeded(atlas, "coherent", "lumentum")

    response = atlas.api.post(
        f"/api/v1/investigations/{started['id']}/premises/company:lumentum/disprove",
        json={"reason": "Lumentum makes no lasers for this customer"},
    )

    assert response.status_code == 200, response.text
    disproven = response.json()
    assert statuses(disproven) == {
        "scout": "queued",
        "investigator:coherent": "pending",
        "investigator:lumentum": "cancelled",
        "skeptic": "pending",
        "financial_analyst": "pending",
        "editor": "pending",
    }
    assert tasks(disproven)["investigator:lumentum"]["detail"] == (
        "premise 'company:lumentum' was disproven: Lumentum makes no lasers for this customer"
    )
    premise = {p["key"]: p for p in disproven["premises"]}["company:lumentum"]
    assert (premise["status"], premise["disproven_by"]) == ("disproven", "local-researcher")

    script_parallel(llm)
    llm.script_chat(
        scout_reply(),
        ChatReply.answer(quoting(supply_claim(atlas))),
        ChatReply.answer(editing()),
        REVIEWED,
    )
    script_searches(searxng)
    atlas.worker_pass()

    found = investigation(atlas, started["id"])
    assert (found["status"], found["stop_reason"]) == ("stopped", "answered")
    assert found["research_card"]["disproven_premises"] == [
        "Lumentum is part of the supply chain the question is about"
    ]
    editor = next(b for b in requests(llm) if b["metadata"]["role"] == "editor")
    assert asked(editor)["request"]["disproven_premises"] == [
        "Lumentum is part of the supply chain the question is about"
    ]
    again = atlas.api.post(
        f"/api/v1/investigations/{started['id']}/premises/company:coherent/disprove",
        json={"reason": "too late"},
    )
    assert again.status_code == 409


def test_disproving_the_question_cancels_the_plan_and_stops_premise_disproven(
    services: Services, llm: FakeLiteLLM
) -> None:
    atlas = services.start(ingest=False)
    started = seeded(atlas, "coherent")

    response = atlas.api.post(
        f"/api/v1/investigations/{started['id']}/premises/question/disprove",
        json={"reason": "no laser is capacity constrained"},
    )
    atlas.worker_pass()  # the Scout's job was already queued: it now does nothing

    assert response.status_code == 200, response.text
    found = investigation(atlas, started["id"])
    assert (found["status"], found["stop_reason"]) == ("stopped", "premise_disproven")
    assert found["stop_detail"].startswith("premise 'question' was disproven")
    # No slot of the plan is skipped any more: every task is cancelled.
    assert set(statuses(found).values()) == {"cancelled"}
    assert llm.chat_requests() == []
    job = atlas.get(f"/api/v1/jobs/{tasks(found)['scout']['job_id']}")
    assert (job["status"], job["artifacts"]["ran"]) == ("succeeded", False)
    assert metric(atlas, "atlas_investigation_stops_total", reason="premise_disproven") == 1
    unknown = atlas.api.post(
        f"/api/v1/investigations/{started['id']}/premises/company:nobody/disprove",
        json={"reason": "x"},
    )
    assert unknown.status_code == 409  # the investigation has stopped
    with atlas.engine.connect() as connection:
        actions = connection.execute(
            text(
                "SELECT action FROM audit_event WHERE entity_type LIKE 'investigation%' ORDER BY id"
            )
        ).scalars()
        assert list(actions) == ["investigation.created", "investigation.premise_disproven"]


# --- failures, validation -------------------------------------------------------------------------


def test_a_role_that_keeps_failing_stops_the_investigation_needs_review(
    services: Services, llm: FakeLiteLLM
) -> None:
    atlas = services.start(ingest=False)
    started = seeded(atlas, "coherent")
    # Three attempts, each a call and its repair, all malformed: quarantined each time.
    llm.script_chat(*[ChatReply.text("Here are some queries.") for _ in range(6)])

    atlas.worker_pass()

    found = investigation(atlas, started["id"])
    assert (found["status"], found["stop_reason"]) == ("stopped", "needs_review")
    assert found["stop_detail"].startswith("the scout task failed after 3 attempts")
    assert "RoleOutputQuarantined" in found["stop_detail"]
    assert statuses(found)["scout"] == "failed"
    assert statuses(found)["investigator:coherent"] == "cancelled"
    assert statuses(found)["editor"] == "cancelled"
    assert [e["type"] for e in events(atlas, started["id"]) if e["task_key"] == "scout"] == [
        "task_queued",
        "task_started",
        "task_attempt_failed",
        "task_started",
        "task_attempt_failed",
        "task_started",
        "task_failed",
    ]
    # The run is finished with its token totals; its quarantined calls stay visible.
    calls = atlas.get(f"/api/v1/runs/{found['run_id']}/role-calls")
    assert [c["status"] for c in calls["role_calls"]] == ["quarantined"] * 3
    # Each quarantined call asked for its one repair (pilot-fixes ticket 26).
    assert calls["repairs"] == found["usage"]["repairs"] == {"scout": 3}
    tokens = "atlas_llm_tokens_total"
    assert metric(atlas, tokens, kind="investigation", direction="input") == calls["tokens_in"]


def test_a_role_s_answer_cut_off_at_its_cap_is_truncated_and_fails_as_a_quarantine_did(
    services: Services, llm: FakeLiteLLM
) -> None:
    atlas = services.start(ingest=False)
    started = seeded(atlas, "coherent")
    # Three attempts, each cut off at the Scout's cap: no repair is asked for.
    cut = ChatReply.text(
        '{"queries": [{"query": "InP sub', tokens=(900, 4096), finish_reason="length"
    )
    llm.script_chat(cut, cut, cut)

    atlas.worker_pass()

    found = investigation(atlas, started["id"])
    assert (found["status"], found["stop_reason"]) == ("stopped", "needs_review")
    assert found["stop_detail"].startswith("the scout task failed after 3 attempts")
    assert "RoleOutputTruncated: scout output cut off at its" in found["stop_detail"]
    assert statuses(found)["editor"] == "cancelled"
    assert len(llm.chat_requests()) == 3
    calls = atlas.get(f"/api/v1/runs/{found['run_id']}/role-calls")["role_calls"]
    assert [c["status"] for c in calls] == ["truncated"] * 3
    assert [len(c["attempts"]) for c in calls] == [1, 1, 1]


# Pilot investigation 1 on 0.3.0 (memory-quality ticket 16): 89 accepted Claims, an Editor
# request of about 38,000 tokens, every answer cut off in a list of Claim IDs.
MANY = 90


def cut_off_card(cap: int) -> ChatReply:
    """An Editor answer cut off at `cap` output tokens, inside its list of citations."""
    partial = '{"findings": [{"statement": "Coherent supplies NVIDIA.", "claim_refs": ["c1", "c'
    return ChatReply.text(partial, tokens=(38_000, cap), finish_reason="length")


def test_an_editor_answer_cut_off_at_its_cap_is_asked_again_with_a_larger_cap(
    services: Services, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    atlas = services.start()
    started = seeded(atlas, "coherent")
    script_parallel(llm)
    llm.script_role("editor", cut_off_card(8192), ChatReply.answer(editing(), tokens=(38_000, 900)))
    llm.script_chat(
        scout_reply(),
        ChatReply.answer(quoting(*[supply_claim(atlas)] * MANY), tokens=(9000, 9000)),
        *[REVIEWED] * 20,
    )
    script_searches(searxng)

    atlas.worker_pass()

    found = investigation(atlas, started["id"])
    accepted = atlas.get("/api/v1/claims", outcome="accepted", limit=500)["items"]
    assert len(accepted) == len(found["evidence"]) == MANY
    assert (found["status"], found["stop_reason"]) == ("stopped", "answered")
    # The cut-off call is truncated, not a schema failure: no repair, and once more with the
    # cap doubled, up to the bound (ATLAS_EDITOR_MAX_OUTPUT_TOKENS, 16,384).
    editors = [b for b in llm.chat_requests() if b["metadata"]["role"] == "editor"]
    assert [b["max_tokens"] for b in editors] == [8192, 16_384]
    assert [len(b["messages"]) for b in editors] == [2, 2]
    calls = atlas.get(f"/api/v1/runs/{found['run_id']}/role-calls")["role_calls"]
    assert [c["status"] for c in calls if c["role"] == "editor"] == ["truncated", "accepted"]
    # The Editor is sent each Claim by a short reference, never its ID.
    sent = asked(editors[1])
    assert [c["ref"] for c in sent["request"]["claims"]] == [f"c{n}" for n in range(1, MANY + 1)]
    assert [q["id"] for q in sent["retrieved_data"][:MANY]] == [f"c{n}" for n in range(1, MANY + 1)]
    assert not any(claim["id"] in editors[1]["messages"][1]["content"] for claim in accepted)
    # Code maps the references back: the finding cites every accepted Claim by its ID.
    [finding] = found["research_card"]["findings"]
    assert sorted(finding["claim_ids"]) == sorted(claim["id"] for claim in accepted)
    assert len(finding["source_spans"]) == MANY
    assert found["research_card"]["editor_failure"] is None
    assert found["research_card"]["claims_by_company"] == []


@pytest.mark.parametrize("failure", ["cut-off-at-the-bound", "quarantined"])
def test_an_editor_that_still_fails_leaves_a_card_without_findings_and_needs_review(
    services: Services, llm: FakeLiteLLM, searxng: FakeSearXNG, failure: str
) -> None:
    atlas = services.start()
    started = seeded(atlas, "coherent")
    script_parallel(llm)
    if failure == "cut-off-at-the-bound":
        llm.script_role("editor", cut_off_card(8192), cut_off_card(16_384))
    else:  # malformed, and malformed again after the repair
        llm.script_role("editor", ChatReply.text("A card."), ChatReply.text("Still a card."))
    llm.script_chat(scout_reply(), ChatReply.answer(quoting(supply_claim(atlas))), *[REVIEWED] * 2)
    script_searches(searxng)

    atlas.worker_pass()

    found = investigation(atlas, started["id"])
    calls = atlas.get(f"/api/v1/runs/{found['run_id']}/role-calls")["role_calls"]
    editor_calls = [c for c in calls if c["role"] == "editor"]
    expected = ["truncated", "truncated"] if failure == "cut-off-at-the-bound" else ["quarantined"]
    assert [c["status"] for c in editor_calls] == expected
    reason = editor_calls[-1]["error"]
    if failure == "cut-off-at-the-bound":
        assert reason.startswith("editor output cut off at its 16384-token output cap")
    else:
        assert reason.startswith("editor output quarantined after a failed repair")
    # The investigation stops needs_review, with a card that says why it has no finding.
    assert (found["status"], found["stop_reason"]) == ("stopped", "needs_review")
    assert found["stop_detail"] == (
        f"the Editor failed, so the card has no finding: {reason}" + NVIDIA_UNCHECKED
    )
    assert tasks(found)["editor"]["status"] == "succeeded"
    card = found["research_card"]
    assert (card["findings"], card["editor_verdict"], card["editor_failure"]) == (
        [],
        "needs_review",
        reason,
    )
    assert card["editor_role_call_id"] == editor_calls[-1]["id"]
    assert card["claims_considered"] == 1
    # The accepted Claims by company, what was searched and read; the Evidence tray as ever.
    [accepted] = atlas.get("/api/v1/claims", outcome="accepted")["items"]
    [company] = card["claims_by_company"]
    assert (company["company_id"], company["company_name"]) == (
        company_id(atlas, "coherent"),
        "Coherent",
    )
    [claim] = company["claims"]
    assert (claim["claim_id"], claim["predicate"], claim["object"], claim["layer"]) == (
        accepted["id"],
        "supplies",
        "NVIDIA",
        "chip-laser",
    )
    assert claim["source_version_id"] == atlas.version(COHR_10K, "coherent")["id"]
    assert [q["query"] for search in card["searched"] for q in search["queries"]] == [
        SUBSTRATE,
        SECOND_SOURCE,
        NOTHING,
    ]
    assert [r["company_name"] for r in card["read"] if r["role"] == "investigator"] == ["Coherent"]
    assert [e["claim_id"] for e in found["evidence"]] == [accepted["id"]]


def test_requests_are_validated(services: Services) -> None:
    atlas = services.start(ingest=False)

    cases: list[tuple[dict[str, Any], str]] = [
        ({"theme": "memory", "question": QUESTION}, "unknown_theme"),
        (
            {"theme": "photonics", "question": QUESTION, "seed_company_ids": [str(uuid.uuid4())]},
            "invalid_seed_companies",
        ),
        (
            {"theme": "photonics", "question": QUESTION, "as_of": "2999-01-01T00:00:00Z"},
            "invalid_as_of",
        ),
        ({"theme": "photonics", "question": "   "}, "invalid_request"),
        (
            {"theme": "photonics", "question": QUESTION, "budgets": {"max_leads": 11}},
            "invalid_request",
        ),
        (
            {"theme": "photonics", "question": QUESTION, "budgets": {"max_documents": 26}},
            "invalid_request",
        ),
        (
            {"theme": "photonics", "question": QUESTION, "budgets": {"max_rounds": 3}},
            "invalid_request",
        ),
        (
            {"theme": "photonics", "question": QUESTION, "budgets": {"max_companies": 26}},
            "invalid_request",
        ),
        (
            {"theme": "photonics", "question": QUESTION, "budgets": {"max_companies": 0}},
            "invalid_request",
        ),
    ]
    for body, code in cases:
        response = atlas.api.post("/api/v1/investigations", json=body)
        assert response.status_code == 422, (body, response.text)
        assert response.json()["error"]["code"] == code, body

    missing = str(uuid.uuid4())
    for path in [f"/api/v1/investigations/{missing}", f"/api/v1/investigations/{missing}/events"]:
        response = atlas.api.get(path)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"
    started = seeded(atlas, "coherent")
    running = atlas.api.post(
        f"/api/v1/investigations/{started['id']}/resume", json={"token_budget": 10**6}
    )
    assert running.status_code == 409
    unknown = atlas.api.post(
        f"/api/v1/investigations/{started['id']}/premises/company:nobody/disprove",
        json={"reason": "x"},
    )
    assert unknown.status_code == 404


def test_without_searxng_an_investigation_is_refused(services: Services) -> None:
    atlas = services.start(ingest=False, searxng_url=None)

    response = atlas.api.post(
        "/api/v1/investigations", json={"theme": "photonics", "question": QUESTION}
    )

    assert response.status_code == 503
    assert response.json()["error"] == {
        "code": "investigations_not_configured",
        "message": "an investigation needs ATLAS_SEARXNG_URL",
    }


def test_every_stop_reason_is_exposed_as_a_metric_before_it_happens(services: Services) -> None:
    atlas = services.start(ingest=False)

    for reason in STOP_REASONS:
        assert metric(atlas, "atlas_investigation_stops_total", reason=reason) == 0
        assert ("atlas_investigation_stops_total", frozenset({("reason", reason)})) in (
            atlas.metrics()
        )


# --- the Skeptic -------------------------------------------------------------------------------

DILUTION = "Coherent share issuance convertible notes dilution 2026"
MARKETS_WIRE = "https://markets-wire.test/2026/09/coherent-convertible-notes-equitization"
# From the recorded Coherent filings' parsed text: the 10-Q's balance sheet (dilution) and the
# 10-K's customer paragraph (customer concentration).
DILUTION_QUOTE = (
    "issued - 212,340,736 shares at March 31, 2026; 171,849,325 shares at June 30, 2025"
)
CONCENTRATION_QUOTE = (
    "We had two customers who each contributed more than 10% of revenue during fiscal 2026."
)
CHECKLIST = [
    "substitutes",
    "second_sources",
    "capacity_additions",
    "inventory_cycle",
    "dilution_financing",
    "customer_concentration",
]
COHR_10K_FILE = (
    REPO
    / "tests/fixtures/edgar/coherent/www.sec.gov/Archives/edgar/data/820318"
    / "000082031826000020/iivi-20260630.htm"
)
COPY_URL = "https://filings-mirror.test/coherent/fy2026-annual-report.htm"
MIRROR = "Coherent NVIDIA supply agreement non-exclusive purchase commitment"
# The same agreement in the 10-K's own words: it limits the supply Claim, and names NVIDIA.
NON_EXCLUSIVE_QUOTE = (
    "The non-exclusive agreement includes a multi-billion-dollar purchase commitment with NVIDIA"
)
# Hand-shaped, not a recorded filing: a later statement that limits the 10-K's supply
# agreement, naming both parties (imported by hand, so its own Evidence Family).
UPDATE_URL = "https://investors.example.test/coherent/2026-08-28-supply-agreement"
LIMIT_QUOTE = (
    "the agreement no longer commits NVIDIA to purchase from Coherent after December 31, 2027"
)
SUPPLY_UPDATE = (
    "Synthetic test fragment: a hand-shaped update, not a Coherent document.\n\n"
    "On August 28, 2026, Coherent Corp. and NVIDIA amended their multi-year supply agreement."
    f" NVIDIA may qualify a second source for advanced lasers, and {LIMIT_QUOTE}.\n"
)
# Rows of the recorded Coherent 10-Q's balance sheet (the parsed text separates cells by tabs).
INVENTORIES_ROW = "Inventories\t2,126,823\t1,437,636"
PPE_ROW = "Property, plant & equipment, net\t2,420,081\t1,877,507"
EQUITY_ROW = "Total Coherent Corp. Shareholders' Equity\t10,676,983\t5,644,514"
BALANCE_SHEET_DATES = "March 31, 2026 and June 30, 2025"
# From the recorded Lumentum FY2026 10-K's risk factors: the pilot's example of another
# company's boilerplate recorded against Coherent's Claims.
SOLE_SOURCE_QUOTE = "for certain components we have sole or limited source supply arrangements"


def skeptic_plan(*queries: tuple[str, str]) -> ChatReply:
    """The Skeptic's plan: its own web queries, each for a checklist item. (What it reads is
    not the plan's to choose: Memory points to it; memory-directed reading ticket 07.)"""
    return ChatReply.json(
        {"queries": [{"query": q, "checklist_item": item} for q, item in queries]},
        tokens=(800, 90),
    )


def memory_documents(atlas: Atlas, *version_ids: str) -> set[str]:
    """The memory documents (retained sections) of these Source Versions, by ID."""
    return {
        document["document_id"]
        for version_id in version_ids
        for document in atlas.memory(version_id)["documents"]
    }


def skeptic_pointers(found: dict[str, Any]) -> list[dict[str, Any]]:
    return [p for p in found["pointers"] if p["task_key"] == "skeptic"]


def skeptic_read(found: dict[str, Any], round_: int = 1) -> dict[str, Any]:
    """The Skeptic's row of the research card's `read`."""
    [row] = [
        r for r in found["research_card"]["read"] if r["role"] == "skeptic" and r["round"] == round_
    ]
    return row


def counter(
    quote: str,
    item: str,
    subject: str,
    *,
    version: str | None = None,
    passage_id: str | None = None,
    contradicts: bool = True,
    disproves: str | None = None,
    how: str | None = "limits",
    figure: tuple[str, str] | None = None,
) -> dict[str, Any]:
    """One counterevidence item for `countering`: quoted from the first passage sent that holds
    the quote (of `version`, if given), or cited as `passage_id` (`CLAIM`: the supporting
    Claim's ID) at offset 0. Proposed as a contradiction of every supporting Claim (`how`),
    or, with `contradicts=False`, as bear context; `figure` is a table row's name and
    period."""
    return {
        "how": how,
        "figure": figure,
        "quote": quote,
        "checklist_item": item,
        "subject_company_id": subject,
        "statement": f"{item.replace('_', ' ')}: {quote[:60]}",
        "version": version,
        "passage_id": passage_id,
        "contradicts": contradicts,
        "disproves": disproves,
    }


def countering(*items: dict[str, Any]) -> Callable[[dict[str, Any]], JsonValue]:
    """The Skeptic's reading: each item as `counter` describes it."""

    def respond(body: dict[str, Any]) -> JsonValue:
        sent = asked(body)
        supporting: list[JsonValue] = [c["claim_id"] for c in sent["request"]["supporting_claims"]]
        passages = sent["retrieved_data"]
        answered: list[JsonValue] = []
        for each in items:
            quote, passage_id, start = each["quote"], each["passage_id"], 0
            if passage_id == "CLAIM":
                passage_id = supporting[0]
            elif passage_id is None:
                holding = [
                    p
                    for p in passages
                    if quote in p["text"]
                    and (each["version"] is None or p["source"].startswith(each["version"]))
                ]
                assert holding, f"no passage sent holds {quote!r}"
                passage_id, start = holding[0]["id"], holding[0]["text"].index(quote)
            figure = each["figure"] or (None, None)
            answered.append(
                {
                    "passage_id": passage_id,
                    "kind": "contradiction" if each["contradicts"] else "bear_context",
                    "checklist_item": each["checklist_item"],
                    "subject_company_id": each["subject_company_id"],
                    "statement": each["statement"],
                    "quote": quote,
                    "quote_start": start,
                    "quote_end": start + len(quote),
                    "epistemic_type": "company_claim",
                    "contradicts_claim_ids": supporting if each["contradicts"] else [],
                    "how": each["how"] if each["contradicts"] else None,
                    "figure_name": figure[0],
                    "figure_period": figure[1],
                    "disproves_premise": each["disproves"],
                }
            )
        return {"counterevidence": answered}

    return respond


def mirror_result() -> SearchReply:
    """A hand-shaped search result: the 10-K's copy at the mirror's URL (the dilution
    fixture's first result with the URL changed; not a recorded SearXNG response)."""
    body = fixture("skeptic-dilution")
    result = body["results"][0] | {
        "title": "Coherent Corp. annual report, fiscal 2026 (mirror)",
        "content": "a strategic multi-year supply agreement with NVIDIA ...",
        "url": COPY_URL,
        "parsed_url": ["https", "filings-mirror.test", COPY_URL.split(".test")[1], "", "", ""],
    }
    return SearchReply(body=body | {"query": MIRROR, "results": [result]})


def skeptic_calls(llm: FakeLiteLLM) -> list[dict[str, Any]]:
    return [asked(b) for b in llm.chat_requests() if b["metadata"]["role"] == "skeptic"]


def by_quote(found: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {each["quote"]: each for each in found["counterevidence"]}


def family(atlas: Atlas, version_id: str) -> str:
    found = atlas.get(f"/api/v1/source-versions/{version_id}")["evidence_family"]
    return f"family:{found['evidence_family_id']}"


def import_update(atlas: Atlas) -> str:
    """Record `SUPPLY_UPDATE` as a Coherent document published after the 10-K (`atlas sources
    import`) and run its retention; its Source Version's ID."""
    path = atlas.tmp_path / "coherent-supply-update.txt"
    path.write_text(SUPPLY_UPDATE, encoding="utf-8")
    imported = atlas.cli(
        "sources",
        "import",
        "--company",
        "coherent",
        "--file",
        str(path),
        "--origin-url",
        UPDATE_URL,
        "--published-at",
        "2026-08-28T12:00:00+00:00",
        "--title",
        "Coherent supply agreement update",
    )
    assert imported.returncode == 0, imported.stderr
    atlas.worker_pass()
    return json.loads(imported.stdout)["source_version_id"]


def test_the_skeptic_searches_and_reads_on_its_own_and_its_counterevidence_reaches_the_card(
    services: Services, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    atlas = services.start(investigator_max_passages=500, investigator_passages_per_call=500)
    coherent = company_id(atlas, "coherent")
    ten_k = atlas.version(COHR_10K, "coherent")["id"]
    ten_q = atlas.version(COHR_10Q, "coherent")["id"]
    # Memory holds the 10-K's sections and nothing of the 10-Q, so no pointer leads to the
    # 10-Q: the Skeptic's own search does.
    unretained = memory_documents(atlas, ten_q)
    services.hindsight[0].report_zero_facts(lambda document_id: document_id in unretained)
    started = seeded(atlas, "coherent")
    paraphrase = "Coherent's share count rose sharply in fiscal 2026."
    llm.script_role("financial_analyst", ANALYSED)
    llm.script_chat(
        scout_reply(),
        ChatReply.answer(quoting(supply_claim(atlas))),
        # Its own query: the 10-Q comes from its search results.
        skeptic_plan((DILUTION, "dilution_financing")),
        ChatReply.answer(
            countering(
                # Proposed, as in the pilot, as a contradiction of the supply Claim (and as
                # disproving the company premise): a share count names neither Coherent nor
                # NVIDIA, so it is bear context.
                counter(
                    DILUTION_QUOTE, "dilution_financing", coherent, disproves="company:coherent"
                ),
                counter(paraphrase, "dilution_financing", coherent, passage_id="s1"),
            ),
            tokens=(6000, 500),
        ),
        ChatReply.answer(editing()),
        REVIEWED,
    )
    script_searches(searxng)
    searxng.script(DILUTION, SearchReply.of("skeptic-dilution"))

    atlas.worker_pass()

    found = investigation(atlas, started["id"])
    # The Skeptic ran between the Investigator and the Editor, beside the Analyst.
    assert statuses(found) == {
        "scout": "succeeded",
        "investigator:coherent": "succeeded",
        "skeptic": "succeeded",
        "financial_analyst": "succeeded",
        "editor": "succeeded",
    }
    assert roles(llm) == [
        "scout",
        "investigator",
        "skeptic",
        "skeptic",
        "financial_analyst",
        "editor",
        "reviewer",
    ]
    calls = atlas.get(f"/api/v1/runs/{found['run_id']}/role-calls")["role_calls"]
    assert [(c["role"], c["prompt_name"]) for c in calls if c["role"] == "skeptic"] == [
        ("skeptic", "skeptic-plan"),
        ("skeptic", "skeptic"),
    ]
    # Its plan: the checklist and the supporting Claim to challenge; no retrieved data at all
    # (no Memory), and no catalog: the plan writes queries, it chooses no document.
    plan, reading = skeptic_calls(llm)
    assert plan["retrieved_data"] == []
    assert [item["name"] for item in plan["request"]["checklist"]] == CHECKLIST
    [accepted_claim] = atlas.get("/api/v1/claims", outcome="accepted")["items"]
    [supporting] = plan["request"]["supporting_claims"]
    assert (supporting["claim_id"], supporting["subject"], supporting["object"]) == (
        accepted_claim["id"],
        "Coherent",
        "NVIDIA",
    )
    assert "catalog" not in plan["request"] and "max_documents" not in plan["request"]
    # Its own search: its query, in its own discovery of the run; the results are Tier C leads.
    artifacts = tasks(found)["skeptic"]["artifacts"]
    discovery = atlas.get(f"/api/v1/discoveries/{artifacts['discovery_id']}")
    assert (discovery["run_id"], discovery["status"]) == (found["run_id"], "completed")
    [query] = discovery["queries"]
    assert (query["query"], query["purpose"], query["status"]) == (
        DILUTION,
        "skeptic: dilution_financing",
        "searched",
    )
    assert [s["q"] for s in searxng.searches()][-1] == DILUTION
    leads = {lead["canonical_url"]: lead for lead in atlas.get("/api/v1/leads")["items"]}
    assert leads[MARKETS_WIRE]["tier"] == "C"
    # Memory pointed to the 10-K; a search result that is an archived filing (the 10-Q) is
    # read too. The Investigator read both, so the document budget isn't charged twice.
    assert (artifacts["documents"], artifacts["documents_dropped"]) == (2, 0)
    assert (artifacts["documents_from_pointers"], artifacts["documents_from_search"]) == (1, 1)
    assert artifacts["documents_fallback"] is False
    assert [
        (d["source_version_id"], d["selected_by"]) for d in skeptic_read(found)["documents"]
    ] == [(ten_k, "pointer"), (ten_q, "search")]
    assert [(d["source_version_id"], d["task_key"]) for d in found["documents"]] == [
        (ten_k, "investigator:coherent"),
        (ten_q, "investigator:coherent"),
    ]
    # It read passages of those documents only, as low-trust data; each passage says which
    # checklist items' cues its text matches (none, for some).
    sources = {p["source"].split("#")[0] for p in reading["retrieved_data"]}
    assert sources == {ten_k, ten_q}
    assert all(p["trust"] == "low" for p in reading["retrieved_data"])
    assert all(set(p["checklist_items"]) <= set(CHECKLIST) for p in reading["request"]["passages"])
    assert any(p["checklist_items"] for p in reading["request"]["passages"])
    assert reading["request"]["premises"] == [
        {
            "key": "company:coherent",
            "statement": "Coherent is part of the supply chain the question is about",
        }
    ]
    # Its counterevidence is visible on the investigation: one accepted, one rejected.
    items = by_quote(found)
    dilution = items[DILUTION_QUOTE]
    assert (dilution["outcome"], dilution["task_key"], dilution["checklist_item"]) == (
        "accepted",
        "skeptic",
        "dilution_financing",
    )
    assert dilution["source_version_id"] == ten_q
    assert atlas.parsed(ten_q)[dilution["span_start"] : dilution["span_end"]] == DILUTION_QUOTE
    # Stored as bear context, with the reason: attached to no Claim, no premise, and with no
    # independence (a contradiction's property).
    assert (dilution["kind"], dilution["contradicts_claim_ids"], dilution["how"]) == (
        "bear_context",
        [],
        None,
    )
    assert dilution["kind_reason"] == (
        "proposed as a contradiction, but its quote names neither the subject nor the object"
        " of the Claim it lists (Coherent supplies NVIDIA); bear context disproves no premise:"
        " `disproves_premise` is left out"
    )
    assert dilution["proposed"]["kind"] == "contradiction"
    assert dilution["proposed"]["contradicts_claim_ids"] == [accepted_claim["id"]]
    assert dilution["disproves_premise"] is None
    assert (dilution["independent"], dilution["evidence_family"]) == (None, family(atlas, ten_q))
    rejected = items[paraphrase]
    assert (rejected["outcome"], rejected["reason_code"]) == ("rejected", "quote_mismatch")
    assert (rejected["assertion_id"], rejected["independent"]) == (None, None)
    # An accepted item is an Assertion tagged as counterevidence, by the Skeptic.
    assertion = atlas.get(f"/api/v1/assertions/{dilution['assertion_id']}")
    assert (assertion["predicate"], assertion["created_by"], assertion["extractor_version"]) == (
        "counterevidence",
        "atlas-skeptic",
        "skeptic.v3",
    )
    assert assertion["value_json"]["checklist_item"] == "dilution_financing"
    assert assertion["value_json"]["counterevidence_id"] == dilution["id"]
    assert assertion["value_json"]["kind"] == "bear_context"
    assert (artifacts["counterevidence_accepted"], artifacts["counterevidence_rejected"]) == (1, 1)
    assert (artifacts["contradictions_accepted"], artifacts["bear_context_accepted"]) == (0, 1)
    assert artifacts["contradictions_demoted"] == 1
    assert artifacts["independent_evidence_families"] == 0
    # The Editor was sent it as bear context (its quote as low-trust data), not as a
    # contradiction; the card lists it under its checklist item and company, and the finding
    # stands uncontradicted: nothing here asks for review.
    editor = asked(requests(llm)[5])
    assert editor["request"]["contradictions"] == []
    [sent] = editor["request"]["bear_context"]
    assert (sent["counterevidence_id"], sent["checklist_item"], sent["company"]) == (
        dilution["id"],
        "dilution_financing",
        "Coherent",
    )
    quoted = {each["id"]: each for each in editor["retrieved_data"]}
    assert quoted[dilution["id"]]["text"] == DILUTION_QUOTE
    card = found["research_card"]
    [finding] = card["findings"]
    assert finding["counterevidence_ids"] == []
    assert card["contradictions"] == []
    [group] = card["bear_context"]
    assert (group["checklist_item"], group["company_id"], group["company_name"]) == (
        "dilution_financing",
        coherent,
        "Coherent",
    )
    [context] = group["items"]
    assert context["counterevidence_id"] == dilution["id"]
    assert context["source_span"]["assertion_id"] == dilution["assertion_id"]
    assert context["reason"] == dilution["kind_reason"]
    assert (found["stop_reason"], found["stop_detail"]) == (
        "answered",
        "the Editor judged the question answered by 1 findings;"
        " the Skeptic did not check NVIDIA, so nothing said of it was challenged"
        " (see the card's skeptic_coverage)",
    )
    # The chained relationship review takes the Investigator's Assertion only.
    [queued] = [e for e in events(atlas, found["id"]) if e["type"] == "relationship_review_queued"]
    assert queued["detail"]["assertions"] == 1
    assert [p["status"] for p in found["premises"]] == ["open", "open"]


# --- a finding says only what its Claims say (pilot-fixes ticket 21) -----------------------------


def test_a_finding_saying_what_its_claims_do_not_is_asked_again_once_then_kept_or_set_aside(
    services: Services, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    atlas = services.start(investigator_max_passages=500, investigator_passages_per_call=500)
    coherent = company_id(atlas, "coherent")
    ten_q = atlas.version(COHR_10Q, "coherent")["id"]
    unretained = memory_documents(atlas, ten_q)
    services.hindsight[0].report_zero_facts(lambda document_id: document_id in unretained)
    started = seeded(atlas, "coherent")
    # A share count only the Skeptic's bear context states (the 10-Q's balance sheet), and a
    # place only a lead's title names ("... capacity in Beijing").
    with_bear_figure = (
        "Coherent supplies NVIDIA with advanced lasers and issued 212,340,736 shares."
    )
    with_lead_place = "Coherent supplies NVIDIA with advanced lasers made in Beijing."
    # Grounded: the legal names stand for the display names, and the quoted phrase is the
    # quote's, through the typographic fold (curly quotation marks, a non-breaking hyphen).
    grounded = (
        "Coherent Corp. entered into a \N{LEFT DOUBLE QUOTATION MARK}strategic"
        " multi\N{NON-BREAKING HYPHEN}year supply agreement\N{RIGHT DOUBLE QUOTATION MARK}"
        " with NVIDIA Corporation."
    )

    def finding(statement: str) -> dict[str, JsonValue]:
        return {
            "statement": statement,
            "claim_refs": ["c1"],
            "limitations": ["A company's own statement."],
            "open_questions": [],
        }

    first: JsonValue = {
        "findings": [finding(with_bear_figure), finding(with_lead_place), finding(grounded)],
        "open_questions": ["Is the supply agreement exclusive?"],
        "verdict": "answered",
    }
    repaired = "Coherent supplies NVIDIA with advanced lasers."
    still_ungrounded = "Coherent supplies NVIDIA with advanced lasers made in Beijing, China."
    again: JsonValue = {
        "findings": [
            {"finding": "f1", "statement": repaired},
            {"finding": "f2", "statement": still_ungrounded},
        ]
    }
    llm.script_role("financial_analyst", ANALYSED)
    llm.script_chat(
        scout_reply(),
        ChatReply.answer(quoting(supply_claim(atlas))),
        skeptic_plan((DILUTION, "dilution_financing")),
        ChatReply.answer(
            countering(counter(DILUTION_QUOTE, "dilution_financing", coherent, contradicts=False))
        ),
        ChatReply.json(first, tokens=(3000, 400)),
        ChatReply.json(again, tokens=(800, 120)),
        REVIEWED,
    )
    script_searches(searxng)
    searxng.script(DILUTION, SearchReply.of("skeptic-dilution"))

    atlas.worker_pass()

    found = investigation(atlas, started["id"])
    # The Editor was asked once more, for the two ungrounded findings only, in one call.
    assert roles(llm) == [
        "scout",
        "investigator",
        "skeptic",
        "skeptic",
        "financial_analyst",
        "editor",
        "editor",
        "reviewer",
    ]
    card_request, again_request = (asked(body) for body in requests(llm)[5:7])
    # What it wrote came from what it was sent beside the Claim: the bear context's quote and
    # the lead's title.
    [bear] = card_request["request"]["bear_context"]
    bear_quote = {each["id"]: each["text"] for each in card_request["retrieved_data"]}
    assert "212,340,736" in bear_quote[bear["counterevidence_id"]]
    assert any("Beijing" in lead["title"] for lead in card_request["request"]["leads"])
    assert again_request["request"]["research_question"] == QUESTION
    assert again_request["request"]["findings"] == [
        {
            "finding": "f1",
            "statement": with_bear_figure,
            "claim_refs": ["c1"],
            "ungrounded": ["212,340,736"],
        },
        {
            "finding": "f2",
            "statement": with_lead_place,
            "claim_refs": ["c1"],
            "ungrounded": ["Beijing"],
        },
    ]
    assert [c["ref"] for c in again_request["request"]["claims"]] == ["c1"]
    # Only the cited Claims' quotes: no bear context, no lead.
    assert [(q["id"], q["text"]) for q in again_request["retrieved_data"]] == [("c1", SUPPLY_QUOTE)]
    calls = atlas.get(f"/api/v1/runs/{found['run_id']}/role-calls")["role_calls"]
    assert [(c["prompt_name"], c["prompt_version"]) for c in calls if c["role"] == "editor"] == [
        ("editor", 7),
        ("editor-reground", 1),
    ]
    # The repaired finding stands, the grounded one was never sent back; the one still
    # ungrounded is set aside with its terms, and is no finding.
    card = found["research_card"]
    assert [(f["claim_text"], f["grounded"]) for f in card["findings"]] == [
        (repaired, True),
        (grounded, True),
    ]
    assert [f["limitations"] for f in card["findings"]] == [["A company's own statement."]] * 2
    [accepted] = atlas.get("/api/v1/claims", outcome="accepted")["items"]
    assert card["unsupported_findings"] == [
        {
            "statement": still_ungrounded,
            "claim_ids": [accepted["id"]],
            "reason": "ungrounded: Beijing, China",
        }
    ]
    assert (found["stop_reason"], found["stop_detail"]) == (
        "needs_review",
        "1 unsupported findings were dropped" + NVIDIA_UNCHECKED,
    )
    artifacts = tasks(found)["editor"]["artifacts"]
    assert artifacts["unsupported_findings"] == 1
    assert artifacts["grounding"] == {
        "asked_again": 2,
        "repaired": 1,
        "role_call_id": calls[-1]["id"],
        "failure": None,
    }


# --- a finding checked for meaning against its quotes (bottleneck-argument ticket 04) ----------


def judged(
    verdict: str, beyond: list[str] | None = None, kinds: list[str] | None = None, reason: str = ""
) -> ChatReply:
    answer: JsonValue = {
        "verdict": verdict,
        "beyond": list[JsonValue](beyond or []),
        "kinds": list[JsonValue](kinds or []),
        "reason": reason or "c1 states it.",
    }
    return ChatReply.json(answer, tokens=(600, 80))


def test_a_misstated_finding_is_rewritten_once_then_kept_or_dropped_and_a_supported_one_kept(
    services: Services, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    atlas = services.start(
        investigator_max_passages=500,
        investigator_passages_per_call=500,
        finding_judge=True,
        finding_judge_votes=1,
    )
    coherent = company_id(atlas, "coherent")
    ten_q = atlas.version(COHR_10Q, "coherent")["id"]
    unretained = memory_documents(atlas, ten_q)
    services.hindsight[0].report_zero_facts(lambda document_id: document_id in unretained)
    started = seeded(atlas, "coherent")
    # All three pass the grounding check (every name is the quote's); only the judge reads
    # what they do with them.
    supported = (
        "Coherent entered into a strategic multi-year supply agreement with NVIDIA for advanced"
        " lasers."
    )
    as_present_supply = "Coherent supplies NVIDIA with advanced lasers."
    rewritten = (
        "Coherent entered into a supply agreement with NVIDIA for advanced lasers and optical"
        " networking products."
    )
    merged = "Coherent is expanding its Sherman, Texas, facility to supply NVIDIA."
    still_merged = "Coherent expanded its Sherman, Texas, facility for NVIDIA."

    def finding(statement: str) -> dict[str, JsonValue]:
        return {
            "statement": statement,
            "claim_refs": ["c1"],
            "limitations": ["A company's own statement."],
            "open_questions": [],
        }

    first: JsonValue = {
        "findings": [finding(supported), finding(as_present_supply), finding(merged)],
        "open_questions": ["Is the supply agreement exclusive?"],
        "verdict": "answered",
    }
    present_reason = "c1 says Coherent 'entered into a ... supply agreement'; not that it supplies."
    merged_reason = "c1 names the Sherman expansion and the NVIDIA agreement as separate facts."
    revised: JsonValue = {
        "findings": [
            {"finding": "f2", "statement": rewritten, "limitations": []},
            {"finding": "f3", "statement": still_merged, "limitations": []},
        ]
    }
    llm.script_role("financial_analyst", ANALYSED)
    llm.script_role(
        "finding_judge",
        judged("supported"),
        judged("misstated", ["supplies NVIDIA"], ["tense_or_status"], present_reason),
        judged("misstated", ["to supply NVIDIA"], ["merged"], merged_reason),
        judged("supported"),
        judged("misstated", ["for NVIDIA"], ["merged"], "c1 does not tie the two."),
    )
    llm.script_chat(
        scout_reply(),
        ChatReply.answer(quoting(supply_claim(atlas))),
        skeptic_plan((DILUTION, "dilution_financing")),
        ChatReply.answer(
            countering(counter(DILUTION_QUOTE, "dilution_financing", coherent, contradicts=False))
        ),
        ChatReply.json(first, tokens=(3000, 400)),
        ChatReply.json(revised, tokens=(800, 120)),
        REVIEWED,
    )
    script_searches(searxng)
    searxng.script(DILUTION, SearchReply.of("skeptic-dilution"))

    atlas.worker_pass()

    found = investigation(atlas, started["id"])
    # Each finding judged once, the two misstated ones rewritten in one Editor call, and each
    # rewrite judged again.
    assert roles(llm) == [
        "scout",
        "investigator",
        "skeptic",
        "skeptic",
        "financial_analyst",
        "editor",
        "finding_judge",
        "finding_judge",
        "finding_judge",
        "editor",
        "finding_judge",
        "finding_judge",
        "reviewer",
    ]
    bodies = requests(llm)
    first_judged = asked(bodies[6])
    assert first_judged["request"]["research_question"] == QUESTION
    assert first_judged["request"]["finding"] == {
        "statement": supported,
        "limitations": ["A company's own statement."],
        "claim_refs": ["c1"],
    }
    # The judge reads the cited Claim's exact quote only: no bear context, no lead.
    assert [(q["id"], q["text"]) for q in first_judged["retrieved_data"]] == [("c1", SUPPLY_QUOTE)]
    revise = asked(bodies[9])
    assert [
        (f["finding"], f["statement"], f["beyond"], f["reason"])
        for f in revise["request"]["findings"]
    ] == [
        ("f2", as_present_supply, ["supplies NVIDIA"], present_reason),
        ("f3", merged, ["to supply NVIDIA"], merged_reason),
    ]
    assert [q["id"] for q in revise["retrieved_data"]] == ["c1"]
    assert [asked(body)["request"]["finding"]["statement"] for body in bodies[10:12]] == [
        rewritten,
        still_merged,
    ]
    calls = atlas.get(f"/api/v1/runs/{found['run_id']}/role-calls")["role_calls"]
    assert [
        (c["prompt_name"], c["prompt_version"])
        for c in calls
        if c["role"] in {"editor", "finding_judge"}
    ] == [
        ("editor", 7),
        ("finding_judge", 2),
        ("finding_judge", 2),
        ("finding_judge", 2),
        ("editor-revise", 1),
        ("finding_judge", 2),
        ("finding_judge", 2),
    ]
    # The supported finding and the accepted rewrite stand, judged; the one still misstated
    # is set aside with the judge's reason.
    card = found["research_card"]
    assert [(f["claim_text"], f["grounded"], f["judged"]) for f in card["findings"]] == [
        (supported, True, True),
        (rewritten, True, True),
    ]
    assert [f["limitations"] for f in card["findings"]] == [["A company's own statement."], []]
    [accepted] = atlas.get("/api/v1/claims", outcome="accepted")["items"]
    assert card["unsupported_findings"] == [
        {
            "statement": still_merged,
            "claim_ids": [accepted["id"]],
            "reason": "misstated after a rewrite: c1 does not tie the two.",
        }
    ]
    # Every verdict is on the card, with its reasons.
    assert [
        (j["finding"], j["attempt"], j["verdict"], j["outcome"], j["judge"]) for j in card["judged"]
    ] == [
        ("f1", 1, "supported", "kept", "finding_judge.v2"),
        ("f2", 1, "misstated", "sent_back", "finding_judge.v2"),
        ("f3", 1, "misstated", "sent_back", "finding_judge.v2"),
        ("f2", 2, "supported", "kept", "finding_judge.v2"),
        ("f3", 2, "misstated", "dropped", "finding_judge.v2"),
    ]
    assert card["judged"][1]["reason"] == present_reason
    assert card["judged"][1]["kinds"] == ["tense_or_status"]
    assert card["judged"][2]["beyond"] == ["to supply NVIDIA"]
    assert all(j["claim_ids"] == [accepted["id"]] for j in card["judged"])
    assert "judge model" in card["grounding_limit"]
    assert (found["stop_reason"], found["stop_detail"]) == (
        "needs_review",
        "1 unsupported findings were dropped" + NVIDIA_UNCHECKED,
    )
    artifacts = tasks(found)["editor"]["artifacts"]
    assert artifacts["meaning"] == {
        "judged": 3,
        "supported": 1,
        "misstated": 2,
        "failed": 0,
        "failed_first": 0,
        "rewritten_kept": 1,
        "dropped": 1,
        "revise_role_call_id": calls[[c["prompt_name"] for c in calls].index("editor-revise")][
            "id"
        ],
        "revise_failure": None,
    }


# --- the Skeptic reads by pointers (memory-directed reading, ticket 07) --------------------------

ITEM_1A = "part-i-item-1a"
# From the recorded Coherent FY2026 10-K's risk factors (Item 1A, its fifth window): the
# customer-concentration statement. (The recorded 10-Qs hold a cover and financial statements
# only, so the 10-K is the recorded filing that states it.)
CONCENTRATION_STATEMENT = (
    "A small number of customers have consistently accounted for a significant portion of our"
    " revenues, with two customers each contributing more than 10% of total revenues in fiscal"
    " 2026."
)
# What Memory holds of it: the fact in Hindsight's own words (written here, the fake's
# `script_fact_text`), a paraphrase that quotes nothing.
CONCENTRATION_MEMORY = (
    "Coherent relies on a small number of large customers: two customers each contributed more"
    " than 10% of its total revenues in fiscal 2026, and it expects significant customer"
    " concentration to continue."
)
# What the Skeptic asks Memory for one checklist item about one company: the company, what
# the item asks, and the objects of the Claims that name the company.
COHERENT_CONCENTRATION_QUERY = (
    "Coherent: customer concentration, largest customers, share of revenue from a few"
    " customers; NVIDIA; advanced lasers"
)
NVIDIA_SECOND_SOURCE_QUERY = (
    "NVIDIA: second source, alternative or additional qualified suppliers, sole or single"
    " source supply; Coherent; advanced lasers"
)


ALLOCATION_FINDING = "Lumentum says its customers' demand is outpacing its current supply."


def allocation_claim(atlas: Atlas) -> dict[str, JsonValue]:
    """Lumentum's allocation statement (its recorded 10-K's Item 1) as a company-level
    Claim."""
    return {
        "subject_company_id": company_id(atlas, "lumentum"),
        "predicate": "capacity_constrained",
        "object_company_id": None,
        "object_name": None,
        "object_text": "optical components for AI and cloud data centers",
        "product": "optical components",
        "layer": "module",
        "quote": LITE_ALLOCATION,
        "epistemic_type": "company_claim",
    }


def test_the_skeptic_reads_the_window_memory_points_to_for_a_bear_checklist_item(
    services: Services, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    # The Investigator reads every candidate window of Coherent's two filings in one call (so
    # it reaches the supply agreement by search); the Skeptic has the default 24 passages.
    atlas = services.start(investigation_max_passages=200, investigator_passages_per_call=200)
    fake = services.hindsight[0]
    coherent, nvidia = company_id(atlas, "coherent"), company_id(atlas, "nvidia")
    ten_k = atlas.version(COHR_10K, "coherent")["id"]
    # Memory holds one fact: Coherent's customer concentration, in its own words, extracted
    # from the 10-K's risk factors. (The fake recalls every fact in scope whatever the query,
    # so one fact keeps this test about where a pointer leads.)
    item_1a = atlas.section(COHR_10K, "coherent", ITEM_1A)
    fake.script_fact_text(item_1a["document_id"], CONCENTRATION_MEMORY)
    fake.report_zero_facts(lambda document_id: document_id != item_1a["document_id"])
    recalls_before = len(fake.requests("POST", "memories/recall"))
    started = seeded(atlas, "coherent")
    llm.script_role("financial_analyst", ANALYSED)
    llm.script_chat(
        scout_reply(),
        ChatReply.answer(quoting(supply_claim(atlas))),
        skeptic_plan(),  # the model plans no query at all, as pilot investigation 1's did
        ChatReply.answer(
            countering(
                counter(
                    CONCENTRATION_STATEMENT,
                    "customer_concentration",
                    coherent,
                    contradicts=False,
                )
            )
        ),
        ChatReply.answer(editing()),
        REVIEWED,
    )
    script_searches(searxng)

    atlas.worker_pass()

    found = investigation(atlas, started["id"])
    assert statuses(found)["skeptic"] == "succeeded"
    [accepted_claim] = atlas.get("/api/v1/claims", outcome="accepted")["items"]
    assert accepted_claim["quote"] == SUPPLY_QUOTE

    # The Skeptic asked Memory about each bear-checklist item for each company the accepted
    # Claim names (its subject, and its object: NVIDIA is a universe company here), across
    # the theme: 2 companies x 6 items, after the Scout's four recalls. No LLM call.
    asked_by_skeptic = fake.requests("POST", "memories/recall")[recalls_before + 4 :]
    assert len(asked_by_skeptic) == 12
    assert {(tuple(r["tags"]), r["tags_match"]) for r in asked_by_skeptic} == {
        (("theme:photonics",), "any_strict")
    }
    queries = [r["query"] for r in asked_by_skeptic]
    assert queries[5] == COHERENT_CONCENTRATION_QUERY  # Coherent first, in checklist order
    assert queries[7] == NVIDIA_SECOND_SOURCE_QUERY
    assert [q.split(":")[0] for q in queries] == ["Coherent"] * 6 + ["NVIDIA"] * 6

    # What resolved is stored as the Skeptic task's reading pointers, apart from the Scout's:
    # each says which checklist item and company its query was.
    pointers = skeptic_pointers(found)
    assert len(pointers) == 12
    assert {(p["round"], p["query_kind"], p["citation_state"]) for p in pointers} == {
        (1, "bear_checklist", "resolved")
    }
    assert [(p["query_index"], p["checklist_item"], p["query_company_id"]) for p in pointers] == [
        (index + 1, item, company)
        for index, (company, item) in enumerate(
            (company, item) for company in (coherent, nvidia) for item in CHECKLIST
        )
    ]
    assert pointers[5]["query"] == COHERENT_CONCENTRATION_QUERY
    assert (pointers[5]["query_company_name"], pointers[6]["query_company_name"]) == (
        "Coherent",
        "NVIDIA",
    )
    assert {
        (p["source_version_id"], p["section_anchor"], p["rank"], p["memory_text"]) for p in pointers
    } == {(ten_k, ITEM_1A, 1, CONCENTRATION_MEMORY)}
    scouts = [p for p in found["pointers"] if p["task_key"] == "scout"]
    assert sorted(p["query_index"] for p in scouts) == [0, 1, 2, 3]
    assert {(p["query_kind"], p["checklist_item"], p["query_company_id"]) for p in scouts} == {
        ("scout", None, None)
    }
    artifacts = tasks(found)["skeptic"]["artifacts"]
    assert (artifacts["pointer_recalls"], artifacts["pointer_recalls_failed"]) == (12, 0)
    assert (artifacts["pointers"], artifacts["pointers_by_company"]) == (12, {"coherent": 12})
    recorded = [e for e in events(atlas, started["id"]) if e["type"] == "pointers_recorded"]
    assert [e["task_key"] for e in recorded] == ["scout", "skeptic"]
    with atlas.engine.connect() as connection:
        audited = connection.execute(
            text(
                "SELECT actor, entity_id FROM audit_event"
                " WHERE action = 'investigation.pointers_recorded' ORDER BY id"
            )
        ).all()
    assert [tuple(row) for row in audited] == [
        ("atlas-scout", tasks(found)["scout"]["id"]),
        ("atlas-skeptic", tasks(found)["skeptic"]["id"]),
    ]
    # An Investigator reads by the Scout's pointers only (the default of `round_reading`).
    with atlas.engine.connect() as connection:
        investigators = round_reading(
            connection, uuid.UUID(started["id"]), 1, [uuid.UUID(ten_k)]
        ).pointers
    assert sorted(p.query_index for p in investigators) == [0, 1, 2, 3]

    # Its plan answered no query: nothing was searched. It still has a document and passages:
    # the 10-K, chosen by the pointers (Coherent has a pointer, so no fallback).
    plan, reading = skeptic_calls(llm)
    assert "passages" not in plan["request"]
    assert (artifacts["discovery_id"], artifacts["queries_searched"]) == (None, 0)
    assert (artifacts["documents"], artifacts["documents_from_pointers"]) == (1, 1)
    assert (artifacts["documents_fallback"], artifacts["documents_from_fallback"]) == (False, 0)
    assert "skeptic_documents_fallback" not in [e["type"] for e in events(atlas, started["id"])]
    calls = atlas.get(f"/api/v1/runs/{found['run_id']}/role-calls")["role_calls"]
    [plan_call] = [c for c in calls if c["prompt_name"] == "skeptic-plan"]
    assert plan_call["prompt_version"] == 5

    # The first passage it was sent is the window of Item 1A that holds the statement the
    # Memory paraphrases, not the Item's opening window.
    parsed = atlas.parsed(ten_k)
    at_ = parsed.index(CONCENTRATION_STATEMENT)
    sent = reading["retrieved_data"]
    assert len(sent) == artifacts["passages"] == 24
    version_id, _, span = sent[0]["source"].partition("#")
    start, end = (int(part) for part in span.split("-"))
    assert version_id == ten_k and start <= at_ < end
    assert start > item_1a["char_start"]
    assert reading["request"]["passages"][0]["section"] == ITEM_1A
    assert "customer_concentration" in reading["request"]["passages"][0]["checklist_items"]
    assert {p["source"].split("#")[0] for p in sent} == {ten_k}
    # Memory chose what it read; no Memory was sent to it (or to any role).
    assert CONCENTRATION_MEMORY not in json.dumps(llm.chat_requests())
    assert not any(
        item["id"] == pointers[0]["memory_id"]
        for body in llm.chat_requests()
        for item in asked(body).get("retrieved_data", [])
    )
    # One pointer window; the rest of its 24 passages are the term search's (the
    # bear-checklist queries' terms).
    assert artifacts["passages_by_selection"]["pointer"] == 1
    assert artifacts["passages_by_selection"]["search"] >= 23
    row = skeptic_read(found)
    assert (row["status"], row["detail"], row["documents_fallback"]) == ("succeeded", None, False)
    [document] = row["documents"]
    assert (document["source_version_id"], document["selected_by"]) == (ten_k, "pointer")
    assert (document["passages"], row["passages"]) == (24, 24)
    assert document["selections"] == artifacts["passages_by_selection"]
    assert document["sections"][0] == ITEM_1A

    # What it found there is bear context on the card: a checklist item, the company, a span.
    [item] = found["counterevidence"]
    assert (item["outcome"], item["kind"], item["checklist_item"]) == (
        "accepted",
        "bear_context",
        "customer_concentration",
    )
    assert (item["source_version_id"], item["passage_id"]) == (ten_k, "s1")
    assert parsed[item["span_start"] : item["span_end"]] == CONCENTRATION_STATEMENT
    card = found["research_card"]
    assert card["contradictions"] == []
    [group] = card["bear_context"]
    assert (group["checklist_item"], group["company_id"], group["company_name"]) == (
        "customer_concentration",
        coherent,
        "Coherent",
    )
    [context] = group["items"]
    assert context["source_span"]["quote"] == CONCENTRATION_STATEMENT
    assert card["findings"][0]["counterevidence_ids"] == []
    assert found["stop_reason"] == "answered"


# Memory-quality ticket 08: the fake cuts each retained section into chunks of at most this
# many characters (`derive_chunks`), so the 10-K's Item 1 has several.
CHUNK_SIZE = 1200


def chunk_placed_lumentum(
    services: Services, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> tuple[Atlas, RecordedHindsight, dict[str, Any], str, int]:
    """Lumentum's recorded filings, its 10-K's Item 1 holding Memory's one fact, extracted
    (says the fake) from the chunk of Item 1 that holds the allocation statement; its text is
    the fake's default, the section's first 200 characters, whose words match Item 1's
    opening window best. Returns the Atlas, the fake, Item 1, the 10-K's ID and the chunk's
    index; nothing has run yet."""
    atlas = services.start(ingest=False, investigation_max_passages=30)
    fake = services.hindsight[0]
    fake.derive_chunks(CHUNK_SIZE)
    atlas.ingest_company("lumentum")
    ten_k = atlas.version(LITE_10K, "lumentum")["id"]
    item_1 = atlas.section(LITE_10K, "lumentum")
    fake.report_zero_facts(lambda document_id: document_id != item_1["document_id"])
    chunks = fake.derived_chunks(item_1["document_id"])
    [index] = [i for i, chunk in enumerate(chunks) if LITE_ALLOCATION in chunk]
    assert index > 0  # not the chunk the section opens with
    fake.script_fact_chunk(item_1["document_id"], index)
    return atlas, fake, item_1, ten_k, index


def test_a_pointer_reads_the_window_its_fact_s_chunk_lies_in_not_the_best_matching_one(
    services: Services, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    atlas, fake, item_1, ten_k, index = chunk_placed_lumentum(services, llm, searxng)
    started = seeded(atlas, "lumentum")
    script_parallel(llm)
    llm.script_chat(
        scout_reply(),
        ChatReply.answer(quoting(allocation_claim(atlas))),
        # The finding says only what the allocation Claim says (pilot-fixes ticket 21).
        ChatReply.answer(editing(statement=ALLOCATION_FINDING)),
        REVIEWED,
    )
    script_searches(searxng)

    atlas.worker_pass()

    found = investigation(atlas, started["id"])
    assert statuses(found)["investigator:lumentum"] == "succeeded"
    # The pointer recalls asked for the chunks of their results.
    recalls = fake.requests("POST", "memories/recall")
    assert recalls and all(
        r["include"] == {"source_facts": {"max_tokens": -1}, "chunks": {}} for r in recalls
    )
    # Every pointer, the Scout's and the Skeptic's, is placed by the fact's chunk: its span
    # in the parsed text is the chunk's text exactly (the fake's chunk, found verbatim).
    parsed = atlas.parsed(ten_k)
    chunk = fake.derived_chunks(item_1["document_id"])[index]
    pointers = found["pointers"]
    assert {p["task_key"] for p in pointers} == {"scout", "skeptic"}
    assert {(p["section_anchor"], p["placed_by"]) for p in pointers} == {(ITEM_1, "chunk")}
    for pointer in pointers:
        assert parsed[pointer["chunk_char_start"] : pointer["chunk_char_end"]] == chunk
        assert item_1["char_start"] <= pointer["chunk_char_start"] < item_1["char_end"]
    chunk_start = pointers[0]["chunk_char_start"]

    # The Investigator's pointer window is the one the chunk starts in, which holds the
    # allocation statement; not Item 1's opening window, whose words the fact matches best.
    extraction = atlas.get(
        f"/api/v1/claim-extractions/{tasks(found)['investigator:lumentum']['artifacts']['extraction_id']}"
    )
    pointed = [
        p
        for p in extraction["passages"]
        if any(tag.startswith("pointer:") for tag in p["selected_by"])
    ]
    [first] = pointed
    assert first["section_anchor"] == ITEM_1
    assert first["char_start"] <= chunk_start < first["char_end"]
    assert first["char_start"] <= parsed.index(ALLOCATION_STATEMENT) < first["char_end"]
    assert first["char_start"] > item_1["char_start"]
    # Each pointer's tag says the chunk placed it.
    assert first["selected_by"][:4] == [
        "pointer:0:chunk",
        "pointer:1:chunk",
        "pointer:2:chunk",
        "pointer:3:chunk",
    ]
    # The Claim read there says so in the Evidence tray, and the card's `read` counts it.
    [claim] = atlas.get("/api/v1/claims", outcome="accepted")["items"]
    assert claim["passage_selected_by"] == first["selected_by"]
    [evidence] = found["evidence"]
    assert evidence["passage_selected_by"] == first["selected_by"]
    [read] = [r for r in found["research_card"]["read"] if r["role"] == "investigator"]
    shown = {d["source_version_id"]: d for d in read["documents"]}
    assert shown[ten_k]["pointers_placed_by"] == {"chunk": 1}
    # The chunk located the span and went no further: no role was sent its text.
    sent = json.dumps(llm.chat_requests())
    assert all(p["memory_text"] not in sent for p in pointers)

    # The Skeptic reads the same way: its first passage is the chunk's window too.
    readings = [c for c in skeptic_calls(llm) if "passages" in c["request"]]
    assert readings
    version_id, _, span = readings[0]["retrieved_data"][0]["source"].partition("#")
    start, end = (int(part) for part in span.split("-"))
    assert version_id == ten_k and start <= chunk_start < end
    skeptic_row = skeptic_read(found)
    [document] = [d for d in skeptic_row["documents"] if d["source_version_id"] == ten_k]
    assert document["pointers_placed_by"] == {"chunk": 1}


def test_a_chunk_that_is_not_in_its_section_leaves_the_pointer_on_the_best_matching_window(
    services: Services, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    atlas, fake, item_1, ten_k, index = chunk_placed_lumentum(services, llm, searxng)
    # Hindsight's chunk of the fact is not a slice of the section (written here).
    fake.script_chunk_text(item_1["document_id"], index, "A chunk no section of Atlas holds.")
    started = seeded(atlas, "lumentum")
    script_parallel(llm)
    llm.script_chat(
        scout_reply(),
        ChatReply.answer(quoting(allocation_claim(atlas))),
        # The finding says only what the allocation Claim says (pilot-fixes ticket 21).
        ChatReply.answer(editing(statement=ALLOCATION_FINDING)),
        REVIEWED,
    )
    script_searches(searxng)

    atlas.worker_pass()

    found = investigation(atlas, started["id"])
    pointers = found["pointers"]
    assert pointers
    assert {(p["placed_by"], p["chunk_char_start"], p["chunk_char_end"]) for p in pointers} == {
        ("match", None, None)
    }
    extraction = atlas.get(
        f"/api/v1/claim-extractions/{tasks(found)['investigator:lumentum']['artifacts']['extraction_id']}"
    )
    [first] = [
        p
        for p in extraction["passages"]
        if any(tag.startswith("pointer:") for tag in p["selected_by"])
    ]
    # The window the fact's words match best: Item 1's opening one (the fact is its first
    # 200 characters), tagged as before.
    assert first["section_anchor"] == ITEM_1
    assert first["char_start"] == item_1["char_start"]
    assert first["selected_by"][:4] == ["pointer:0", "pointer:1", "pointer:2", "pointer:3"]
    [read] = [r for r in found["research_card"]["read"] if r["role"] == "investigator"]
    shown = {d["source_version_id"]: d for d in read["documents"]}
    assert shown[ten_k]["pointers_placed_by"] == {"match": 1}


def test_a_company_memory_points_to_nothing_of_is_read_through_the_fallback(
    services: Services, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    # Pilot investigation 1's seeds and archive: Coherent's and Lumentum's recorded filings.
    atlas = services.start()
    atlas.ingest_company("lumentum")
    fake = services.hindsight[0]
    coherent, lumentum = company_id(atlas, "coherent"), company_id(atlas, "lumentum")
    cohr_10k = atlas.version(COHR_10K, "coherent")["id"]
    cohr_10q = atlas.version(COHR_10Q, "coherent")["id"]
    lite = {
        name: atlas.version(url)["id"]
        for name, url in [
            ("10-K", LITE_10K),
            ("8-K", LITE_8K),
            ("EX-99.1", LITE_EX991),
            ("10-Q", LITE_10Q),
        ]
    }
    # Memory holds Coherent's filings and nothing of Lumentum's (as for a company whose
    # filings wait in the retention backfill).
    unretained = memory_documents(atlas, *lite.values())
    fake.report_zero_facts(lambda document_id: document_id in unretained)
    started = seeded(atlas, "coherent", "lumentum")
    script_parallel(llm)  # its plan writes no query; its reading proposes nothing
    llm.script_chat(
        scout_reply(),
        ChatReply.answer(quoting(supply_claim(atlas), allocation_claim(atlas))),
        ChatReply.answer(quoting(supply_claim(atlas), allocation_claim(atlas))),
        ChatReply.answer(editing()),
        REVIEWED,
    )
    script_searches(searxng)

    atlas.worker_pass()

    found = investigation(atlas, started["id"])
    assert tasks(found)["skeptic"]["status"] == "succeeded"
    # Both seed companies have an accepted Claim, so the Skeptic asks Memory about both (and
    # about NVIDIA, the supply Claim's object).
    claims = atlas.get("/api/v1/claims", outcome="accepted")["items"]
    assert {c["subject_company_id"] for c in claims} == {coherent, lumentum}
    pointers = skeptic_pointers(found)
    assert {p["query_company_name"] for p in pointers} == {"Coherent", "Lumentum", "NVIDIA"}
    assert tasks(found)["skeptic"]["artifacts"]["pointer_recalls"] == 18
    # Every pointer leads into Coherent's filings: Memory holds nothing of Lumentum's.
    assert {p["company_id"] for p in pointers} == {coherent}
    assert {p["source_version_id"] for p in pointers} == {cohr_10k, cohr_10q}

    # Coherent is read where Memory points; Lumentum, with no pointer, through the fallback:
    # its latest 10-K and 10-Q. The Investigators had read all four, so the document budget
    # isn't charged again. NVIDIA has nothing archived, so nothing to fall back to.
    expected = [cohr_10k, cohr_10q, lite["10-K"], lite["10-Q"]]
    artifacts = tasks(found)["skeptic"]["artifacts"]
    assert (artifacts["documents"], artifacts["documents_dropped"]) == (4, 0)
    assert (artifacts["documents_from_pointers"], artifacts["documents_from_fallback"]) == (2, 2)
    assert artifacts["documents_fallback"] is True
    assert {d["task_key"] for d in found["documents"]} == {
        "investigator:coherent",
        "investigator:lumentum",
    }
    # A researcher sees that Memory pointed at nothing of Lumentum's.
    [fell_back] = [
        e for e in events(atlas, found["id"]) if e["type"] == "skeptic_documents_fallback"
    ]
    assert (fell_back["round"], fell_back["task_key"]) == (1, "skeptic")
    assert fell_back["detail"] == {"company_ids": [lumentum], "documents": 2}
    # It read passages of both companies' filings: each periodic report keeps a passage.
    plan, *readings = skeptic_calls(llm)
    assert "passages" not in plan["request"]
    sent = [p for reading in readings for p in reading["retrieved_data"]]
    per_document: dict[str, int] = {}
    for passage in sent:
        version_id = passage["source"].split("#")[0]
        per_document[version_id] = per_document.get(version_id, 0) + 1
    assert set(per_document) == set(expected)
    assert artifacts["passages"] == len(sent) == 24
    # The card states what the Skeptic read, like the Investigators' rows: each document, who
    # chose it, and how its passages were selected.
    card = found["research_card"]
    assert [(r["role"], r["task_key"]) for r in card["read"]] == [
        ("investigator", "investigator:coherent"),
        ("investigator", "investigator:lumentum"),
        ("skeptic", "skeptic"),
    ]
    skeptic = card["read"][2]
    assert (skeptic["status"], skeptic["detail"], skeptic["documents_fallback"]) == (
        "succeeded",
        None,
        True,
    )
    assert [(d["source_version_id"], d["selected_by"]) for d in skeptic["documents"]] == [
        (cohr_10k, "pointer"),
        (cohr_10q, "pointer"),
        (lite["10-K"], "fallback"),
        (lite["10-Q"], "fallback"),
    ]
    titles = {d["source_version_id"]: d["title"] for d in found["documents"]}
    assert [d["title"] for d in skeptic["documents"]] == [titles[v] for v in expected]
    shown = {d["source_version_id"]: d for d in skeptic["documents"]}
    assert {key: d["passages"] for key, d in shown.items()} == per_document
    assert all(d["sections"] for d in skeptic["documents"])
    assert shown[cohr_10k]["selections"]["pointer"] >= 1
    # A fallback document has no pointer: its passages are the term search's best windows of
    # it (the bear-checklist queries' terms), not its opening windows.
    for name in ("10-K", "10-Q"):
        assert "pointer" not in shown[lite[name]]["selections"]
    assert shown[lite["10-K"]]["selections"] == {"search": per_document[lite["10-K"]]}
    assert (skeptic["passages"], skeptic["claims_proposed"], skeptic["claims_accepted"]) == (
        len(sent),
        0,
        0,
    )
    # The Editor is sent the Investigators' reading; the Skeptic's reaches it as its
    # contradictions and bear context.
    editor = asked(next(b for b in requests(llm) if b["metadata"]["role"] == "editor"))
    assert [r["company"] for r in editor["request"]["read"]] == ["Coherent", "Lumentum"]


def test_a_skeptic_plan_that_is_quarantined_still_leaves_the_skeptic_reading(
    services: Services, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    atlas = services.start()
    ten_k = atlas.version(COHR_10K, "coherent")["id"]
    ten_q = atlas.version(COHR_10Q, "coherent")["id"]
    started = seeded(atlas, "coherent")
    llm.script_role("financial_analyst", ANALYSED)
    off_schema = ChatReply.json({"documents": []})  # no `queries`: not a plan
    llm.script_chat(
        scout_reply(),
        ChatReply.answer(quoting(supply_claim(atlas))),
        off_schema,
        off_schema,  # and its one repair
        ChatReply.json({"counterevidence": []}),
        ChatReply.answer(editing()),
        REVIEWED,
    )
    script_searches(searxng)

    atlas.worker_pass()

    found = investigation(atlas, started["id"])
    skeptic = tasks(found)["skeptic"]
    assert (skeptic["status"], found["stop_reason"]) == ("succeeded", "answered")
    calls = atlas.get(f"/api/v1/runs/{found['run_id']}/role-calls")["role_calls"]
    [plan_call] = [c for c in calls if c["prompt_name"] == "skeptic-plan"]
    assert plan_call["status"] == "quarantined"
    [quarantined] = [
        e for e in events(atlas, started["id"]) if e["type"] == "skeptic_plan_quarantined"
    ]
    assert quarantined["detail"] == {"role_call_id": plan_call["id"]}
    # No query was searched; Memory's pointers still chose its documents and passages.
    artifacts = skeptic["artifacts"]
    assert (artifacts["plan_role_call_id"], artifacts["discovery_id"]) == (plan_call["id"], None)
    assert (artifacts["documents"], artifacts["documents_from_pointers"]) == (2, 2)
    assert artifacts["passages"] > 0
    assert [d["source_version_id"] for d in skeptic_read(found)["documents"]] == [ten_k, ten_q]


def test_counterevidence_sharing_an_evidence_family_with_the_investigators_is_not_independent(
    services: Services, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    # The Investigator reads four documents here; with 60 passages it reaches the 10-K's
    # supply-agreement window (the search's, after the windows Memory points to: the fake
    # recalls a fact for every retained section). The Skeptic reads the same four, every
    # candidate window in one call: the 10-K, the 10-Q and the later statement where its
    # pointers lead, and the copy because its own search finds it (Memory holds no fact of
    # the copy: its sections are the 10-K's, retained once).
    atlas = services.start(
        investigator_max_passages=500,
        investigator_passages_per_call=500,
        investigation_max_passages=60,
    )
    coherent = company_id(atlas, "coherent")
    # A byte-for-byte copy of the Coherent 10-K at another URL: a separate Source Version in
    # the 10-K's Evidence Family.
    imported = atlas.cli(
        "sources",
        "import",
        "--company",
        "coherent",
        "--file",
        str(COHR_10K_FILE),
        "--origin-url",
        COPY_URL,
        "--published-at",
        "2026-01-15T12:00:00+00:00",
    )
    assert imported.returncode == 0, imported.stderr
    copy = json.loads(imported.stdout)["source_version_id"]
    atlas.worker_pass()  # its retain
    update = import_update(atlas)  # a later statement, in its own Evidence Family
    ten_k = atlas.version(COHR_10K, "coherent")["id"]
    assert copy != ten_k and family(atlas, copy) == family(atlas, ten_k)
    started = seeded(atlas, "coherent")
    llm.script_role("financial_analyst", ANALYSED)
    llm.script_chat(
        scout_reply(),
        # The Investigator quotes the 10-K (it is sent the copy's same passage too).
        ChatReply.answer(quoting(supply_claim(atlas), version=ten_k)),
        skeptic_plan((MIRROR, "capacity_additions")),
        ChatReply.answer(
            countering(
                # From the copy: the same witness as the Investigator's 10-K, however it's
                # found; its claim to disprove the premise doesn't count.
                counter(
                    NON_EXCLUSIVE_QUOTE,
                    "capacity_additions",
                    coherent,
                    version=copy,
                    disproves="company:coherent",
                ),
                counter(LIMIT_QUOTE, "second_sources", coherent),
            )
        ),
        ChatReply.answer(editing()),
        REVIEWED,
    )
    script_searches(searxng)
    searxng.script(MIRROR, mirror_result())

    atlas.worker_pass()

    found = investigation(atlas, started["id"])
    [claim] = atlas.get("/api/v1/claims", outcome="accepted")["items"]
    assert claim["source_version_id"] == ten_k
    chosen = {d["source_version_id"]: d["selected_by"] for d in skeptic_read(found)["documents"]}
    assert (chosen[copy], chosen[ten_k], chosen[update]) == ("search", "pointer", "pointer")
    items = by_quote(found)
    shared, own = items[NON_EXCLUSIVE_QUOTE], items[LIMIT_QUOTE]
    assert (shared["kind"], own["kind"]) == ("contradiction", "contradiction")
    assert (shared["outcome"], shared["source_version_id"]) == ("accepted", copy)
    assert shared["evidence_family"] == family(atlas, ten_k)
    assert shared["independent"] is False
    assert "not an independent witness" in shared["independence_detail"]
    assert (own["outcome"], own["independent"]) == ("accepted", True)
    assert own["source_version_id"] == update
    artifacts = tasks(found)["skeptic"]["artifacts"]
    assert (artifacts["counterevidence_accepted"], artifacts["counterevidence_independent"]) == (
        2,
        1,
    )
    # Only an independent contradiction counts against a finding or a premise.
    [finding] = found["research_card"]["findings"]
    assert finding["counterevidence_ids"] == [own["id"]]
    contradictions = found["research_card"]["contradictions"]
    assert [(c["counterevidence_id"], c["independent"]) for c in contradictions] == [
        (shared["id"], False),
        (own["id"], True),
    ]
    assert {p["key"]: p["status"] for p in found["premises"]}["company:coherent"] == "open"
    assert "premise_disproven" not in [e["type"] for e in events(atlas, found["id"])]


def test_memory_and_other_roles_output_are_never_witnesses(
    services: Services,
    llm: FakeLiteLLM,
    searxng: FakeSearXNG,
) -> None:
    atlas = services.start()
    fake = services.hindsight[0]
    coherent = company_id(atlas, "coherent")
    ten_k = atlas.version(COHR_10K, "coherent")["id"]
    ten_q = atlas.version(COHR_10Q, "coherent")["id"]
    # Real Memory about Coherent: what Hindsight holds, derived from the retained filings.
    [memory, *_] = atlas.recall("Coherent customers and suppliers", company_ids=[coherent])[
        "memories"
    ]
    recalls = len(fake.requests("POST", "memories/recall"))
    started = seeded(atlas, "coherent")
    llm.script_role("financial_analyst", ANALYSED)
    llm.script_chat(
        scout_reply(),
        ChatReply.answer(quoting(supply_claim(atlas))),
        skeptic_plan(),
        ChatReply.answer(
            countering(
                counter(memory["text"], "second_sources", coherent, passage_id=memory["memory_id"]),
                counter(SUPPLY_QUOTE, "customer_concentration", coherent, passage_id="CLAIM"),
                counter(
                    "Qualified second sources are missing.",
                    "second_sources",
                    coherent,
                    passage_id="bottlenecks",
                ),
            )
        ),
        ChatReply.answer(editing()),
        REVIEWED,
    )
    script_searches(searxng)

    atlas.worker_pass()

    found = investigation(atlas, started["id"])
    # Nothing but passages of archived Source Versions were sent to the Skeptic, and no
    # Memory: Memory chose what it read and went no further. The recalls are the Scout's
    # reading pointers (the question and its three queries, across the theme), which the
    # Investigator reads by without a recall of its own (ticket 05), and the Skeptic's (ticket
    # 07): one per bear-checklist item for each company the Claim names, Coherent and NVIDIA,
    # across the theme too. The one mental-model read is the Scout's.
    plan, reading = skeptic_calls(llm)
    assert plan["retrieved_data"] == []
    assert reading["retrieved_data"]
    assert {p["source"].split("#")[0] for p in reading["retrieved_data"]} <= {ten_k, ten_q}
    assert {p["id"] for p in reading["retrieved_data"]} == {
        f"s{n}" for n in range(1, len(reading["retrieved_data"]) + 1)
    }
    asked_of_hindsight = fake.requests("POST", "memories/recall")[recalls:]
    assert [r["tags"] for r in asked_of_hindsight] == [["theme:photonics"]] * (4 + 2 * 6)
    # The pointers are an index: no role was sent a memory they name, the Skeptic's included.
    pointed = {p["memory_id"] for p in found["pointers"]}
    assert memory["memory_id"] in pointed
    assert memory["memory_id"] in {p["memory_id"] for p in skeptic_pointers(found)}
    assert not any(
        item["id"] in pointed
        for body in llm.chat_requests()
        for item in asked(body).get("retrieved_data", [])
    )
    mental_model_reads = [
        c for c in fake.calls if c.method == "GET" and "/mental-models/" in c.url.path
    ]
    assert len(mental_model_reads) == 1
    # Memory text, the Investigator's Claim and a mental model cited as witnesses: rejected.
    [claim] = atlas.get("/api/v1/claims", outcome="accepted")["items"]
    rejected = found["counterevidence"]
    assert [(c["passage_id"], c["outcome"], c["reason_code"]) for c in rejected] == [
        (memory["memory_id"], "rejected", "not_a_witness"),
        (claim["id"], "rejected", "not_a_witness"),
        ("bottlenecks", "rejected", "not_a_witness"),
    ]
    assert all(c["assertion_id"] is None and c["independent"] is None for c in rejected)
    assert "never" in rejected[0]["reason"]
    # None of it counts: the finding stands uncontradicted.
    assert found["research_card"]["contradictions"] == []
    assert found["research_card"]["findings"][0]["counterevidence_ids"] == []
    assert found["stop_reason"] == "answered"
    assert tasks(found)["skeptic"]["artifacts"]["counterevidence_independent"] == 0


def test_the_skeptic_s_independent_counterevidence_disproves_a_company_premise(
    services: Services, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    atlas = services.start()
    coherent = company_id(atlas, "coherent")
    update = import_update(atlas)  # retained, so Memory points the Skeptic to it
    started = seeded(atlas, "coherent")
    llm.script_role("financial_analyst", ANALYSED)
    llm.script_chat(
        scout_reply(),
        ChatReply.answer(quoting(supply_claim(atlas))),
        skeptic_plan(),
        ChatReply.answer(
            countering(
                counter(LIMIT_QUOTE, "second_sources", coherent, disproves="company:coherent"),
                # The question stays the researcher's to disprove.
                counter(LIMIT_QUOTE, "second_sources", coherent, disproves="question"),
            )
        ),
        NOTHING_ACCEPTED,
        REVIEWED,
    )
    script_searches(searxng)

    atlas.worker_pass()

    found = investigation(atlas, started["id"])
    first, second = found["counterevidence"]
    assert (first["outcome"], first["kind"], first["independent"]) == (
        "accepted",
        "contradiction",
        True,
    )
    assert first["source_version_id"] == update
    assert (second["outcome"], second["reason_code"]) == ("rejected", "unknown_premise")
    premises = {p["key"]: p for p in found["premises"]}
    assert premises["question"]["status"] == "open"
    disproven = premises["company:coherent"]
    assert (disproven["status"], disproven["disproven_by"]) == ("disproven", "atlas-skeptic")
    assert disproven["reason"].startswith("the Skeptic's independent counterevidence: ")
    [logged] = [e for e in events(atlas, found["id"]) if e["type"] == "premise_disproven"]
    assert (logged["detail"]["by"], logged["detail"]["counterevidence_ids"]) == (
        "atlas-skeptic",
        [first["id"]],
    )
    # Coherent's Claims no longer count: the Editor's card has no finding, and names the
    # disproven premise.
    assert tasks(found)["editor"]["status"] == "succeeded"
    assert (found["status"], found["stop_reason"]) == ("stopped", "no_new_independent_evidence")
    [editor] = [body for body in requests(llm) if body["metadata"]["role"] == "editor"]
    assert asked(editor)["request"]["claims"] == []
    card = found["research_card"]
    assert (card["findings"], card["disproven_premises"]) == ([], [disproven["statement"]])
    with atlas.engine.connect() as connection:
        actors = connection.execute(
            text("SELECT actor FROM audit_event WHERE action = 'investigation.premise_disproven'")
        ).scalars()
        assert list(actors) == ["atlas-skeptic"]


# --- contradiction or bear context (memory-directed reading, ticket 03) --------------------------


def test_one_contradiction_marks_one_finding_and_the_rest_is_bear_context_on_the_card(
    services: Services, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    # Pilot investigation 1 (0.2.5): 29 accepted items, none a contradiction, and the stop
    # "4 findings are contradicted". Here: one real contradiction and three context items.
    atlas = services.start(investigator_max_passages=500, investigator_passages_per_call=500)
    atlas.ingest_company("lumentum")
    coherent, lumentum = company_id(atlas, "coherent"), company_id(atlas, "lumentum")
    update = import_update(atlas)
    ten_k = atlas.version(COHR_10K, "coherent")["id"]
    ten_q = atlas.version(COHR_10Q, "coherent")["id"]
    lite_10k = atlas.version(LITE_10K)["id"]
    # The seed alone is read (a company budget of one): Lumentum's filings are in Memory, and
    # with room it would gain an Investigator, which is not this test's subject.
    started = seeded(atlas, "coherent", budgets={"max_companies": 1})
    llm.script_role("financial_analyst", ANALYSED)
    llm.script_chat(
        scout_reply(),
        ChatReply.answer(quoting(supply_claim(atlas))),
        # Where Memory points: Coherent's filings and the later statement, and Lumentum's
        # (in the theme, so its facts answer the theme-wide recalls too).
        skeptic_plan(),
        ChatReply.answer(
            countering(
                # A later statement limiting the supply Claim, naming both its parties.
                counter(LIMIT_QUOTE, "second_sources", coherent, how="limits"),
                # Context, proposed as such: customer concentration, and an inventories row
                # with its figure's name and period.
                counter(
                    CONCENTRATION_QUOTE,
                    "customer_concentration",
                    coherent,
                    version=ten_k,
                    contradicts=False,
                ),
                counter(
                    INVENTORIES_ROW,
                    "inventory_cycle",
                    coherent,
                    contradicts=False,
                    figure=("Inventories", BALANCE_SHEET_DATES),
                ),
                # Another company's risk factor, proposed as a contradiction of Coherent's
                # Claim (as the pilot's Skeptic did).
                counter(SOLE_SOURCE_QUOTE, "second_sources", lumentum, how="denies"),
            )
        ),
        ChatReply.answer(editing()),
        REVIEWED,
    )
    script_searches(searxng)

    atlas.worker_pass()

    found = investigation(atlas, started["id"])
    [claim] = atlas.get("/api/v1/claims", outcome="accepted")["items"]
    items = by_quote(found)
    assert {quote: (item["outcome"], item["kind"]) for quote, item in items.items()} == {
        LIMIT_QUOTE: ("accepted", "contradiction"),
        CONCENTRATION_QUOTE: ("accepted", "bear_context"),
        INVENTORIES_ROW: ("accepted", "bear_context"),
        SOLE_SOURCE_QUOTE: ("accepted", "bear_context"),
    }
    # The contradiction names its Claim and how; it alone has independence.
    limit = items[LIMIT_QUOTE]
    assert (limit["contradicts_claim_ids"], limit["how"], limit["kind_reason"]) == (
        [claim["id"]],
        "limits",
        None,
    )
    assert (limit["source_version_id"], limit["independent"]) == (update, True)
    # Bear context is attached to no Claim. What the Skeptic proposed as a contradiction and
    # code stored as context says why.
    concentration, inventories, sole_source = (
        items[CONCENTRATION_QUOTE],
        items[INVENTORIES_ROW],
        items[SOLE_SOURCE_QUOTE],
    )
    for context in (concentration, inventories, sole_source):
        assert (context["contradicts_claim_ids"], context["how"]) == ([], None)
        assert (context["independent"], context["independence_detail"]) == (None, None)
        assert context["assertion_id"] is not None
    assert (concentration["kind_reason"], inventories["kind_reason"]) == (None, None)
    assert (inventories["figure_name"], inventories["figure_period"]) == (
        "Inventories",
        BALANCE_SHEET_DATES,
    )
    assert atlas.parsed(ten_q)[inventories["span_start"] : inventories["span_end"]] == (
        INVENTORIES_ROW
    )
    assert sole_source["source_version_id"] == lite_10k
    assert sole_source["kind_reason"] == (
        "proposed as a contradiction, but its quote names neither the subject nor the object"
        " of the Claim it lists (Coherent supplies NVIDIA)"
    )
    assert sole_source["proposed"]["contradicts_claim_ids"] == [claim["id"]]
    artifacts = tasks(found)["skeptic"]["artifacts"]
    assert (artifacts["contradictions_accepted"], artifacts["bear_context_accepted"]) == (1, 3)
    assert (artifacts["contradictions_demoted"], artifacts["counterevidence_independent"]) == (1, 1)
    # The card: one finding, contradicted by the one contradiction; the context in its own
    # section, by checklist item (in checklist order) and company.
    card = found["research_card"]
    [finding] = card["findings"]
    assert finding["counterevidence_ids"] == [limit["id"]]
    assert finding["needs_review"] is True
    [contradiction] = card["contradictions"]
    assert (contradiction["counterevidence_id"], contradiction["how"]) == (limit["id"], "limits")
    assert contradiction["contradicts_claim_ids"] == [claim["id"]]
    assert contradiction["independent"] is True
    assert [
        (g["checklist_item"], g["company_id"], g["company_name"], len(g["items"]))
        for g in card["bear_context"]
    ] == [
        ("second_sources", lumentum, "Lumentum", 1),
        ("inventory_cycle", coherent, "Coherent", 1),
        ("customer_concentration", coherent, "Coherent", 1),
    ]
    by_item = {g["checklist_item"]: g["items"][0] for g in card["bear_context"]}
    assert by_item["second_sources"]["counterevidence_id"] == sole_source["id"]
    assert by_item["second_sources"]["reason"] == sole_source["kind_reason"]
    assert by_item["second_sources"]["source_span"]["quote"] == SOLE_SOURCE_QUOTE
    row = by_item["inventory_cycle"]
    assert (row["figure_name"], row["figure_period"], row["reason"]) == (
        "Inventories",
        BALANCE_SHEET_DATES,
        None,
    )
    assert row["source_span"]["assertion_id"] == inventories["assertion_id"]
    assert by_item["customer_concentration"]["source_span"]["quote"] == CONCENTRATION_QUOTE
    # The stop counts contradictions only: one finding, not four items.
    assert (found["stop_reason"], found["stop_detail"]) == (
        "needs_review",
        "1 findings are contradicted by independent counterevidence" + NVIDIA_UNCHECKED,
    )
    editor_task = tasks(found)["editor"]["artifacts"]
    assert (editor_task["contradictions"], editor_task["bear_context"]) == (1, 3)
    assert editor_task["contradicted_findings"] == 1
    # The Editor is sent the two kinds separately, each item's quote as low-trust data.
    editor = asked(next(b for b in requests(llm) if b["metadata"]["role"] == "editor"))
    [sent] = editor["request"]["contradictions"]
    assert (sent["counterevidence_id"], sent["how"], sent["contradicts_refs"]) == (
        limit["id"],
        "limits",
        ["c1"],
    )
    assert [c["ref"] for c in editor["request"]["claims"]] == ["c1"]
    assert [
        (c["counterevidence_id"], c["checklist_item"], c["company"])
        for c in editor["request"]["bear_context"]
    ] == [
        (sole_source["id"], "second_sources", "Lumentum"),
        (inventories["id"], "inventory_cycle", "Coherent"),
        (concentration["id"], "customer_concentration", "Coherent"),
    ]
    assert editor["request"]["bear_context"][1]["figure_name"] == "Inventories"
    quoted = {each["id"]: each["text"] for each in editor["retrieved_data"]}
    for item in (limit, concentration, inventories, sole_source):
        assert quoted[item["id"]] == item["quote"]
    calls = atlas.get(f"/api/v1/runs/{found['run_id']}/role-calls")["role_calls"]
    versions = {(c["prompt_name"], c["prompt_version"]) for c in calls}
    assert {("skeptic", 3), ("editor", 7)} <= versions
    # Nothing but the contradiction can disprove a premise or needs an owner's eye.
    assert [p["status"] for p in found["premises"]] == ["open", "open"]


def test_a_table_row_is_bear_context_only_with_its_figure_s_name_and_period(
    services: Services, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    atlas = services.start()
    coherent = company_id(atlas, "coherent")
    ten_q = atlas.version(COHR_10Q, "coherent")["id"]
    started = seeded(atlas, "coherent")
    llm.script_role("financial_analyst", ANALYSED)
    llm.script_chat(
        scout_reply(),
        ChatReply.answer(quoting(supply_claim(atlas))),
        skeptic_plan(),
        ChatReply.answer(
            countering(
                # The pilot's rows: a label and its figures, no words.
                counter(PPE_ROW, "capacity_additions", coherent, contradicts=False),
                counter(
                    INVENTORIES_ROW,
                    "inventory_cycle",
                    coherent,
                    contradicts=False,
                    figure=("Inventories", "  "),  # a name, but no period
                ),
                # A row naming Coherent, proposed as a contradiction with its figure stated: a
                # row states nothing that could contradict a Claim.
                counter(
                    EQUITY_ROW,
                    "dilution_financing",
                    coherent,
                    how="denies",
                    figure=("Total Coherent Corp. shareholders' equity", BALANCE_SHEET_DATES),
                ),
            )
        ),
        ChatReply.answer(editing()),
        REVIEWED,
    )
    script_searches(searxng)

    atlas.worker_pass()

    found = investigation(atlas, started["id"])
    items = by_quote(found)
    for quote in (PPE_ROW, INVENTORIES_ROW):
        rejected = items[quote]
        assert (rejected["outcome"], rejected["reason_code"]) == (
            "rejected",
            "table_row_without_figure",
        )
        assert "figure's name" in rejected["reason"] and "period" in rejected["reason"]
        assert (rejected["kind"], rejected["assertion_id"]) == ("bear_context", None)
    equity = items[EQUITY_ROW]
    assert (equity["outcome"], equity["kind"], equity["contradicts_claim_ids"]) == (
        "accepted",
        "bear_context",
        [],
    )
    assert equity["source_version_id"] == ten_q  # the 10-Q's balance sheet, where Memory points
    assert equity["kind_reason"] == (
        "proposed as a contradiction, but its quote is a table row, which states nothing that"
        " could deny, limit or date a Claim"
    )
    assert (equity["figure_name"], equity["figure_period"]) == (
        "Total Coherent Corp. shareholders' equity",
        BALANCE_SHEET_DATES,
    )
    card = found["research_card"]
    assert card["contradictions"] == []
    [group] = card["bear_context"]
    assert (group["checklist_item"], len(group["items"])) == ("dilution_financing", 1)
    assert card["findings"][0]["counterevidence_ids"] == []
    assert found["stop_reason"] == "answered"
    [skeptic] = [r for r in card["read"] if r["role"] == "skeptic"]
    assert (skeptic["claims_proposed"], skeptic["claims_accepted"], skeptic["rejected"]) == (
        3,
        1,
        {"table_row_without_figure": 2},
    )


def run_axt_agreement(
    services: Services,
    llm: FakeLiteLLM,
    searxng: FakeSearXNG,
    seeds: tuple[str, ...] = ("coherent", "lumentum"),
    **budgets: int,
) -> dict[str, Any]:
    """The AXT test's investigation (AXT's supply Claim, naming AXT and Coherent), with the
    given budgets; the stopped investigation as read."""
    atlas = services.start()
    fake = services.hindsight[0]
    import_axt_note(atlas)
    coherent, axt = atlas.company("coherent"), atlas.company("axt")
    [section] = retained_sections(atlas, AXT_NOTE_URL, "axt")
    fake.script_fact_text(section["document_id"], AXT_MEMORY)
    fake.report_zero_facts(lambda document_id: document_id != section["document_id"])
    agreement: dict[str, JsonValue] = {
        "subject_company_id": axt["id"],
        "predicate": "supplies",
        "object_company_id": coherent["id"],
        "object_name": None,
        "object_text": None,
        "product": "6-inch indium phosphide substrates",
        "layer": "substrate",
        "quote": AXT_QUOTE,
        "epistemic_type": "company_claim",
    }
    started = seeded(atlas, *seeds, **({"budgets": budgets} if budgets else {}))
    script_parallel(llm)
    llm.script_chat(
        scout_reply(),
        ChatReply.answer(quoting(agreement)),
        ChatReply.answer(quoting(agreement)),
        ChatReply.answer(editing(statement="AXT supplies Coherent with 6-inch InP substrates.")),
        REVIEWED,
    )
    script_searches(searxng)
    atlas.worker_pass()
    return investigation(atlas, started["id"])


def test_the_card_says_per_company_what_the_skeptic_read_and_the_limit_of_the_grounding_check(
    services: Services, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    found = run_axt_agreement(services, llm, searxng)

    card = found["research_card"]
    axt, coherent = card["skeptic_coverage"]
    assert (axt["company_name"], axt["outcome"], axt["claims"]) == ("AXT", "checked", 1)
    assert [(d["title"], d["passages"]) for d in axt["documents"]] == [
        ("AXT supply agreement note, hand-shaped", 2)
    ]
    assert (axt["reason_code"], axt["reason"]) == (None, None)
    assert (coherent["company_name"], coherent["outcome"]) == ("Coherent", "checked")
    assert [d["title"] for d in coherent["documents"]] == [
        "COHERENT CORP. 10-K filed 2026-08-14",
        "COHERENT CORP. 10-Q filed 2026-05-06",
    ]
    assert coherent["passages"] == 22
    # Every company was checked: the stop detail says nothing about the Skeptic.
    assert found["stop_detail"] == "the Editor judged the question answered by 1 findings"
    # The card states what its grounding check does not hold.
    limit = card["grounding_limit"]
    assert "names, figures and quoted phrases" in limit
    assert all(word in limit for word in ("Direction", "tense", "merging of two facts"))


def test_a_company_the_skeptic_was_left_no_document_for_is_listed_as_not_checked(
    services: Services, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    found = run_axt_agreement(services, llm, searxng, seeds=("lumentum",), max_documents=1)

    card = found["research_card"]
    # The Investigators spent the one document, so the Skeptic read none of Coherent's.
    axt, coherent = card["skeptic_coverage"]
    assert (axt["company_name"], axt["outcome"]) == ("AXT", "checked")
    assert (coherent["company_name"], coherent["outcome"], coherent["claims"]) == (
        "Coherent",
        "not_checked",
        1,
    )
    assert (coherent["documents"], coherent["passages"]) == ([], 0)
    assert coherent["reason_code"] == "no_budget"
    assert coherent["reason"] == (
        "the document budget (1) was spent and 2 documents were left out;"
        " none of this company's was read"
    )
    # The stop detail names it, and never implies the Skeptic looked.
    assert found["stop_reason"] == "answered"
    assert found["stop_detail"] == (
        "the Editor judged the question answered by 1 findings;"
        " the Skeptic did not check Coherent, so nothing said of it was challenged"
        " (see the card's skeptic_coverage)"
    )
