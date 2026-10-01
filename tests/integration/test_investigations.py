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
Coherent 10-K; the Skeptic's quote the passages it is sent; the Analyst proposes no scenario;
the Editor's cite the Claim IDs it is sent; the Reviewer, chained after a final stop, confirms
what it is sent). The Skeptic's and the Analyst's jobs run in parallel, in either order, so
their answers are scripted by role (`script_role`) and their calls compared in plan order.
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

from atlas.jobs import JobQueue, Pacing, Worker, builtin_registry
from tests.fakes.hindsight import RecordedHindsight
from tests.fakes.litellm import ChatReply, FakeLiteLLM
from tests.fakes.searxng import FakeSearXNG, SearchReply
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
    """The Skeptic finding nothing: its plan chooses no query and no document (as pilot
    investigation 1's did), and its reading of what code's fallback then chose proposes
    nothing."""
    if "catalog" in asked(body)["request"]:
        return {"queries": [], "documents": []}
    return {"counterevidence": []}


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


def quoting(*claims: dict[str, JsonValue]) -> Callable[[dict[str, Any]], JsonValue]:
    """An Investigator answer proposing each claim whose quote a passage it was sent holds
    (with that passage's ID and the quote's offsets there), and nothing else."""

    def respond(body: dict[str, Any]) -> JsonValue:
        passages = asked(body)["retrieved_data"]
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
) -> Callable[[dict[str, Any]], JsonValue]:
    """An Editor answer with one finding citing every Claim it was sent, plus `extra`."""

    def respond(body: dict[str, Any]) -> JsonValue:
        request = asked(body)["request"]
        finding: dict[str, JsonValue] = {
            "statement": "Coherent supplies NVIDIA with advanced lasers under a multi-year"
            " supply agreement.",
            "claim_ids": [claim["claim_id"] for claim in request["claims"]],
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
                "verdict": "confirmed",
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
        "token_budget": 200_000,
    }
    assert request["available_budget"] == started["budgets"]
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
    assert found["stop_detail"] == "the Editor judged the question answered by 1 findings"
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
    # The Skeptic's plan chose no search and no document, so code's fallback chose Coherent's
    # filings (pilot fix 06); it read them and found no counterevidence.
    skeptic = tasks(found)["skeptic"]["artifacts"]
    assert skeptic["supporting_claims"] == 1
    assert (skeptic["documents_fallback"], skeptic["documents"]) == (True, 2)
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
        "tokens_in": 15_400,
        "tokens_out": 1_520,
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
    assert editor["request"]["counterevidence"] == []
    [sent] = editor["request"]["claims"]
    [accepted] = atlas.get("/api/v1/claims", outcome="accepted")["items"]
    assert sent["claim_id"] == accepted["id"]
    assert (sent["subject"], sent["predicate"], sent["object"]) == (
        "Coherent",
        "supplies",
        "NVIDIA",
    )
    assert [lead["title"] for lead in editor["request"]["leads"]] == [
        lead["title"] for lead in found["leads"]
    ]
    quoted = {each["id"]: each for each in editor["retrieved_data"]}
    assert quoted[accepted["id"]]["text"] == SUPPLY_QUOTE
    assert all(each["trust"] == "low" for each in editor["retrieved_data"])
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
    assert card["contradictions"] == []
    assert finding["limitations"] == ["A company's own statement; no volumes or prices."]
    assert card["editor_role_call_id"] == calls["role_calls"][-1]["id"]
    # The event log tells the story in order, ending with the stop and its reason.
    log = events(atlas, started["id"])
    assert [(e["type"], e["task_key"]) for e in log if e["task_key"] == "scout"] == [
        ("task_queued", "scout"),
        ("task_started", "scout"),
        ("pointers_recorded", "scout"),  # what Memory was asked, and what it pointed at
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
        "claim_ids": ["LEAD"],
        "limitations": [],
        "open_questions": [],
    }
    invented: dict[str, JsonValue] = {
        "statement": "Coherent is the only qualified laser supplier.",
        "claim_ids": [],
        "limitations": [],
        "open_questions": [],
    }

    def cite_a_lead(body: dict[str, Any]) -> JsonValue:
        lead_id = asked(body)["request"]["leads"][0]["lead_id"]
        citing: dict[str, JsonValue] = {**lead_citing, "claim_ids": [lead_id]}
        return editing(extra=[citing, invented])(body)

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
    assert found["stop_detail"] == "2 unsupported findings were dropped"
    card = found["research_card"]
    assert [f["claim_text"][:25] for f in card["findings"]] == ["Coherent supplies NVIDIA "]
    lead_id = found["leads"][0]["lead_id"]
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
    assert (article["query"], article["ranking_version"]) == (EML, 2)
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
    ) == (17, 2, 0, 15, 2)
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


def script_two_queries(llm: FakeLiteLLM, searxng: FakeSearXNG) -> None:
    """The Scout writes two queries; the Investigator proposes nothing; the Editor's card has
    no finding."""
    llm.script_chat(
        ChatReply.json({"queries": TWO_QUERIES}), ChatReply.json({"claims": []}), NOTHING_ACCEPTED
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
    release = retained_sections(atlas, LITE_EX991, "lumentum")[0]
    # What Hindsight holds: a fact per retained section (the fake's derivation) and one
    # observation consolidated from a fact of each company's filing.
    observation = fake.derive_observation([cohr_item_1["document_id"], release["document_id"]])
    facts = fake.bank_facts(BANK)
    assert len(facts) == len(available) + len(later)
    started = seeded(atlas, "coherent", as_of=as_of)
    script_two_queries(llm, searxng)

    atlas.worker_pass()

    found = investigation(atlas, started["id"])
    assert statuses(found)["scout"] == "succeeded"
    # One recall for the question and one per Scout query, each across the theme; the fourth
    # recall is the Investigator's own, scoped to its company.
    recalls = fake.requests("POST", "memories/recall")
    assert [(r["query"], (r["tags"], r["tags_match"])) for r in recalls[:3]] == [
        (QUESTION, THEME_SCOPE),
        (SUBSTRATE, THEME_SCOPE),
        (SECOND_SOURCE, THEME_SCOPE),
    ]
    assert [r["tags"] for r in recalls[3:]] == [[f"company:{coherent['id']}"]]
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
    # Nothing reads the pointers yet: only the seed company got an Investigator.
    assert [t["key"] for t in found["tasks"] if t["role"] == "investigator"] == [
        "investigator:coherent"
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


def test_the_passage_budget_is_spread_across_the_documents_the_investigator_took(
    services: Services, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    # Pilot fix 10: in the re-run each Investigator's 24 passages all came from its 10-K. The
    # recorded Lumentum filings: the FY2026 10-K (August 17), the Q4 results 8-K with its press
    # release, EX-99.1 (August 11), and the Q3 10-Q (May); the 10-K alone has far more than 24
    # windows its recall hits select.
    atlas = services.start(ingest=False)
    atlas.ingest_company("lumentum")
    started = seeded(atlas, "lumentum")
    llm.script_chat(scout_reply(), ChatReply.json({"claims": []}), NOTHING_ACCEPTED)
    script_searches(searxng)

    atlas.worker_pass()

    found = investigation(atlas, started["id"])
    task = tasks(found)["investigator:lumentum"]["artifacts"]
    extraction = atlas.get(f"/api/v1/claim-extractions/{task['extraction_id']}")
    ids = {
        name: atlas.version(url, "lumentum")["id"]
        for name, url in [
            ("10-K", LITE_10K),
            ("8-K", LITE_8K),
            ("EX-99.1", LITE_EX991),
            ("10-Q", LITE_10Q),
        ]
    }
    per_document: dict[str, int] = {}
    for passage in extraction["passages"]:
        per_document[passage["source_version_id"]] = (
            per_document.get(passage["source_version_id"], 0) + 1
        )
    # The default budget, 24 passages, spread over the four documents (6 each): the recorded
    # 8-K and 10-Q have only 3 and 5 windows with text (all recall hits here), and the share
    # they can't use passes on to the 10-K and the press release. (Before the fix: 24 of the
    # 10-K.)
    assert len(found["documents"]) == 4
    assert {name: per_document.get(id_) for name, id_ in ids.items()} == {
        "10-K": 8,
        "8-K": 3,
        "EX-99.1": 8,
        "10-Q": 5,
    }
    # The first round deals one passage to each document, newest first.
    newest_first = [d["source_version_id"] for d in found["documents"]]
    first_round = [p["source_version_id"] for p in extraction["passages"][: len(per_document)]]
    assert first_round == [each for each in newest_first if each in per_document]
    # The task's and the extraction's artifacts count the passages per document.
    assert task["passages_by_document"] == per_document
    # The card's `read` shows the passages sent of each document.
    # (Since pilot fix 06 the Skeptic has a row of its own.)
    [read] = [r for r in found["research_card"]["read"] if r["role"] == "investigator"]
    shown = {d["source_version_id"]: d["passages"] for d in read["documents"]}
    assert {key: n for key, n in shown.items() if n} == per_document
    assert read["passages"] == sum(shown.values()) == 24


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
    tokens = "atlas_llm_tokens_total"
    assert metric(atlas, tokens, kind="investigation", direction="input") == calls["tokens_in"]


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


def skeptic_plan(
    *, queries: tuple[tuple[str, str], ...] = (), documents: tuple[tuple[str, str], ...] = ()
) -> ChatReply:
    """The Skeptic's plan: its own queries and the catalog documents it reads."""
    return ChatReply.json(
        {
            "queries": [{"query": q, "checklist_item": item} for q, item in queries],
            "documents": [
                {"source_version_id": v, "checklist_item": item} for v, item in documents
            ],
        },
        tokens=(800, 90),
    )


def counter(
    quote: str,
    item: str,
    subject: str,
    *,
    version: str | None = None,
    passage_id: str | None = None,
    contradicts: bool = True,
    disproves: str | None = None,
) -> dict[str, Any]:
    """One counterevidence item for `countering`: quoted from the first passage sent that holds
    the quote (of `version`, if given), or cited as `passage_id` (`CLAIM`: the supporting
    Claim's ID) at offset 0."""
    return {
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
            answered.append(
                {
                    "passage_id": passage_id,
                    "checklist_item": each["checklist_item"],
                    "subject_company_id": each["subject_company_id"],
                    "statement": each["statement"],
                    "quote": quote,
                    "quote_start": start,
                    "quote_end": start + len(quote),
                    "epistemic_type": "company_claim",
                    "contradicts_claim_ids": supporting if each["contradicts"] else [],
                    "disproves_premise": each["disproves"],
                }
            )
        return {"counterevidence": answered}

    return respond


def skeptic_calls(llm: FakeLiteLLM) -> list[dict[str, Any]]:
    return [asked(b) for b in llm.chat_requests() if b["metadata"]["role"] == "skeptic"]


def by_quote(found: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {each["quote"]: each for each in found["counterevidence"]}


def family(atlas: Atlas, version_id: str) -> str:
    found = atlas.get(f"/api/v1/source-versions/{version_id}")["evidence_family"]
    return f"family:{found['evidence_family_id']}"


def test_the_skeptic_searches_and_reads_on_its_own_and_its_counterevidence_reaches_the_card(
    services: Services, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    atlas = services.start(investigator_max_passages=500, investigator_passages_per_call=500)
    coherent = company_id(atlas, "coherent")
    ten_k = atlas.version(COHR_10K, "coherent")["id"]
    ten_q = atlas.version(COHR_10Q, "coherent")["id"]
    started = seeded(atlas, "coherent")
    paraphrase = "Coherent's share count rose sharply in fiscal 2026."
    llm.script_role("financial_analyst", ANALYSED)
    llm.script_chat(
        scout_reply(),
        ChatReply.answer(quoting(supply_claim(atlas))),
        # Its own query, and no catalog document: the 10-Q comes from its search results.
        skeptic_plan(queries=((DILUTION, "dilution_financing"),)),
        ChatReply.answer(
            countering(
                counter(DILUTION_QUOTE, "dilution_financing", coherent),
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
    # Its plan: the checklist, the supporting Claim to challenge, the archived catalog; no
    # retrieved data at all (no Memory).
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
    assert {d["source_version_id"] for d in plan["request"]["catalog"]} == {ten_k, ten_q}
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
    # A result that is an archived filing (the 10-Q) is read; the Investigator read it too,
    # so the document budget isn't charged twice.
    assert (artifacts["documents"], artifacts["documents_from_search"]) == (1, 1)
    assert artifacts["documents_dropped"] == 0
    assert [(d["source_version_id"], d["task_key"]) for d in found["documents"]] == [
        (ten_k, "investigator:coherent"),
        (ten_q, "investigator:coherent"),
    ]
    # It read passages of that document only, as low-trust data, picked by the checklist.
    assert reading["retrieved_data"]
    assert all(p["source"].startswith(f"{ten_q}#") for p in reading["retrieved_data"])
    assert all(p["trust"] == "low" for p in reading["retrieved_data"])
    assert all(p["checklist_items"] for p in reading["request"]["passages"])
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
    assert dilution["contradicts_claim_ids"] == [accepted_claim["id"]]
    assert (dilution["independent"], dilution["evidence_family"]) == (True, family(atlas, ten_q))
    rejected = items[paraphrase]
    assert (rejected["outcome"], rejected["reason_code"]) == ("rejected", "quote_mismatch")
    assert (rejected["assertion_id"], rejected["independent"]) == (None, None)
    # An accepted item is an Assertion tagged as counterevidence, by the Skeptic.
    assertion = atlas.get(f"/api/v1/assertions/{dilution['assertion_id']}")
    assert (assertion["predicate"], assertion["created_by"], assertion["extractor_version"]) == (
        "counterevidence",
        "atlas-skeptic",
        "skeptic.v2",
    )
    assert assertion["value_json"]["checklist_item"] == "dilution_financing"
    assert assertion["value_json"]["counterevidence_id"] == dilution["id"]
    assert (artifacts["counterevidence_accepted"], artifacts["counterevidence_rejected"]) == (1, 1)
    assert artifacts["independent_evidence_families"] == 1
    # The Editor was sent it (its quote as low-trust data); the card shows it as a
    # contradiction of the finding, which needs review, and so does the investigation.
    editor = asked(requests(llm)[5])
    [sent] = editor["request"]["counterevidence"]
    assert (sent["counterevidence_id"], sent["independent"], sent["subject"]) == (
        dilution["id"],
        True,
        "Coherent",
    )
    quoted = {each["id"]: each for each in editor["retrieved_data"]}
    assert quoted[dilution["id"]]["text"] == DILUTION_QUOTE
    card = found["research_card"]
    [finding] = card["findings"]
    assert finding["counterevidence_ids"] == [dilution["id"]]
    assert finding["needs_review"] is True
    [contradiction] = card["contradictions"]
    assert contradiction["counterevidence_id"] == dilution["id"]
    assert contradiction["source_span"]["assertion_id"] == dilution["assertion_id"]
    assert contradiction["independent"] is True
    assert (found["stop_reason"], found["stop_detail"]) == (
        "needs_review",
        "1 findings are contradicted by independent counterevidence",
    )
    # The chained relationship review takes the Investigator's Assertion only.
    [queued] = [e for e in events(atlas, found["id"]) if e["type"] == "relationship_review_queued"]
    assert queued["detail"]["assertions"] == 1
    assert [p["status"] for p in found["premises"]] == ["open", "open"]


def test_a_skeptic_plan_that_chooses_no_document_falls_back_to_each_seed_company_s_filings(
    services: Services, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    # Pilot investigation 1's seeds and archive: Coherent's and Lumentum's recorded filings.
    atlas = services.start()
    atlas.ingest_company("lumentum")
    coherent, lumentum = company_id(atlas, "coherent"), company_id(atlas, "lumentum")
    started = seeded(atlas, "coherent", "lumentum")
    script_parallel(llm)  # its plan answers `"documents": []`, as the pilot's did
    llm.script_chat(
        scout_reply(),
        ChatReply.answer(quoting(supply_claim(atlas))),
        ChatReply.answer(quoting(supply_claim(atlas))),
        ChatReply.answer(editing()),
        REVIEWED,
    )
    script_searches(searxng)

    atlas.worker_pass()

    found = investigation(atlas, started["id"])
    assert tasks(found)["skeptic"]["status"] == "succeeded"
    plan, *readings = skeptic_calls(llm)
    assert plan["request"]["catalog"]  # it had archived documents to choose from
    calls = atlas.get(f"/api/v1/runs/{found['run_id']}/role-calls")["role_calls"]
    [plan_call] = [c for c in calls if c["prompt_name"] == "skeptic-plan"]
    assert plan_call["prompt_version"] == 3
    # Code chose for it: each seed company's latest 10-K and 10-Q, in seed order; the
    # Investigators had read them, so the document budget isn't charged again.
    expected = [
        atlas.version(COHR_10K, "coherent")["id"],
        atlas.version(COHR_10Q, "coherent")["id"],
        atlas.version(LITE_10K)["id"],
        atlas.version(LITE_10Q)["id"],
    ]
    artifacts = tasks(found)["skeptic"]["artifacts"]
    assert (artifacts["documents_fallback"], artifacts["documents_from_fallback"]) == (True, 4)
    assert (artifacts["documents"], artifacts["documents_dropped"]) == (4, 0)
    assert {d["task_key"] for d in found["documents"]} == {
        "investigator:coherent",
        "investigator:lumentum",
    }
    # A researcher sees that the model chose nothing.
    [fell_back] = [
        e for e in events(atlas, found["id"]) if e["type"] == "skeptic_documents_fallback"
    ]
    assert (fell_back["round"], fell_back["task_key"]) == (1, "skeptic")
    assert fell_back["detail"] == {
        "plan_documents": 0,
        "seed_company_ids": [coherent, lumentum],
        "documents": 4,
    }
    # It read passages of at least one archived Source Version of each seed company.
    sent = [p for reading in readings for p in reading["retrieved_data"]]
    read_versions = {p["source"].split("#")[0] for p in sent}
    assert read_versions & set(expected[:2])
    assert read_versions & set(expected[2:])
    assert artifacts["passages"] == len(sent)
    # The card states what the Skeptic read, like the Investigators' rows.
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
    assert [d["source_version_id"] for d in skeptic["documents"]] == expected
    assert {d["selected_by"] for d in skeptic["documents"]} == {"fallback"}
    titles = {d["source_version_id"]: d["title"] for d in found["documents"]}
    assert [d["title"] for d in skeptic["documents"]] == [titles[v] for v in expected]
    for document in skeptic["documents"]:  # sections where it was sent passages
        assert bool(document["sections"]) == (document["source_version_id"] in read_versions)
    assert (skeptic["passages"], skeptic["claims_proposed"], skeptic["claims_accepted"]) == (
        len(sent),
        0,
        0,
    )
    # The Editor is sent the Investigators' reading; the Skeptic's reaches it as counterevidence.
    editor = asked(next(b for b in requests(llm) if b["metadata"]["role"] == "editor"))
    assert [r["company"] for r in editor["request"]["read"]] == ["Coherent", "Lumentum"]


def test_counterevidence_sharing_an_evidence_family_with_the_investigators_is_not_independent(
    services: Services, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    atlas = services.start(investigator_max_passages=500, investigator_passages_per_call=500)
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
    ten_k = atlas.version(COHR_10K, "coherent")["id"]
    ten_q = atlas.version(COHR_10Q, "coherent")["id"]
    assert copy != ten_k and family(atlas, copy) == family(atlas, ten_k)
    started = seeded(atlas, "coherent")
    llm.script_role("financial_analyst", ANALYSED)
    llm.script_chat(
        scout_reply(),
        ChatReply.answer(quoting(supply_claim(atlas))),
        skeptic_plan(documents=((copy, "customer_concentration"), (ten_q, "dilution_financing"))),
        ChatReply.answer(
            countering(
                # From the copy: the same witness as the Investigator's 10-K, however it's
                # found; its claim to disprove the premise doesn't count.
                counter(
                    CONCENTRATION_QUOTE,
                    "customer_concentration",
                    coherent,
                    version=copy,
                    disproves="company:coherent",
                ),
                counter(DILUTION_QUOTE, "dilution_financing", coherent),
            )
        ),
        ChatReply.answer(editing()),
        REVIEWED,
    )
    script_searches(searxng)

    atlas.worker_pass()

    found = investigation(atlas, started["id"])
    [claim] = atlas.get("/api/v1/claims", outcome="accepted")["items"]
    assert claim["source_version_id"] == ten_k
    items = by_quote(found)
    shared, own = items[CONCENTRATION_QUOTE], items[DILUTION_QUOTE]
    assert (shared["outcome"], shared["source_version_id"]) == ("accepted", copy)
    assert shared["evidence_family"] == family(atlas, ten_k)
    assert shared["independent"] is False
    assert "not an independent witness" in shared["independence_detail"]
    assert (own["outcome"], own["independent"]) == ("accepted", True)
    artifacts = tasks(found)["skeptic"]["artifacts"]
    assert (artifacts["counterevidence_accepted"], artifacts["counterevidence_independent"]) == (
        2,
        1,
    )
    # Only independent counterevidence counts against a finding or a premise.
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
        skeptic_plan(documents=((ten_q, "dilution_financing"),)),
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
    # Nothing but passages of the Source Versions it chose were sent, and no Memory was read
    # for the Skeptic: the recalls are the Scout's reading pointers (the question and its
    # three queries, across the theme) and the Investigator's one; the one mental-model read
    # is the Scout's.
    plan, reading = skeptic_calls(llm)
    assert plan["retrieved_data"] == []
    assert all(p["source"].startswith(f"{ten_q}#") for p in reading["retrieved_data"])
    asked_of_hindsight = fake.requests("POST", "memories/recall")[recalls:]
    assert [r["tags"] for r in asked_of_hindsight] == [
        *(["theme:photonics"],) * 4,
        [f"company:{coherent}"],
    ]
    # The pointers are an index: no role was sent a memory they name.
    pointed = {p["memory_id"] for p in found["pointers"]}
    assert memory["memory_id"] in pointed
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
    ten_q = atlas.version(COHR_10Q, "coherent")["id"]
    started = seeded(atlas, "coherent")
    llm.script_role("financial_analyst", ANALYSED)
    llm.script_chat(
        scout_reply(),
        ChatReply.answer(quoting(supply_claim(atlas))),
        skeptic_plan(documents=((ten_q, "dilution_financing"),)),
        ChatReply.answer(
            countering(
                counter(
                    DILUTION_QUOTE,
                    "dilution_financing",
                    coherent,
                    disproves="company:coherent",
                ),
                # The question stays the researcher's to disprove.
                counter(DILUTION_QUOTE, "dilution_financing", coherent, disproves="question"),
            )
        ),
        NOTHING_ACCEPTED,
        REVIEWED,
    )
    script_searches(searxng)

    atlas.worker_pass()

    found = investigation(atlas, started["id"])
    first, second = found["counterevidence"]
    assert (first["outcome"], first["independent"]) == ("accepted", True)
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
