"""Investigations: a theme question run as a fixed, visible plan on the job queue, within
per-run budgets, every stop's reason recorded (Phase 3-6a ticket 14; spec "Research
workflow", §7.2-§7.4).

Seams: `POST /api/v1/investigations` starts one, single worker passes run its tasks, and
everything is observed through `/api/v1` (the investigation, its events, runs' role calls,
discoveries, claim extractions, `/metrics`) and the requests the fakes received. The
Source Versions are the recorded Coherent EDGAR filings (a 10-K and a 10-Q), ingested and
retained through the fixture path, Hindsight the recorded fake with `derive_memories`.
LiteLLM is the scripted chat fake: **the Scout's, Investigator's and Editor's answers are
written here** (the Investigator's quote the recorded Coherent 10-K; the Editor's cite the
Claim IDs it is sent; the Reviewer, chained after a final stop, confirms what it is sent).
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

from atlas.jobs import JobQueue, Pacing, Worker, builtin_registry
from tests.fakes.hindsight import RecordedHindsight
from tests.fakes.litellm import ChatReply, FakeLiteLLM
from tests.fakes.searxng import FakeSearXNG, SearchReply
from tests.fakes.serve import Served, serve
from tests.harness import THEMES, Atlas, Clock, at

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


def roles(llm: FakeLiteLLM) -> list[str]:
    return [body["metadata"]["role"] for body in llm.chat_requests()]


def scout_reply(tokens: tuple[int, int] = (900, 120)) -> ChatReply:
    return ChatReply.json({"queries": QUERIES}, tokens=tokens)


def script_searches(searxng: FakeSearXNG) -> None:
    searxng.script(SUBSTRATE, SearchReply.of("inp-substrate-capacity"))
    searxng.script(SECOND_SOURCE, SearchReply.of("inp-laser-second-source"))
    searxng.script(NOTHING, SearchReply.of("no-results"))


def supply_claim(atlas: Atlas) -> dict[str, JsonValue]:
    return {
        "subject_company_id": company_id(atlas, "coherent"),
        "predicate": "supplies",
        "object_company_id": company_id(atlas, "nvidia"),
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
    for slot in ("skeptic", "financial_analyst"):
        assert plan[slot]["status"] == "skipped"
        assert "not built yet" in plan[slot]["detail"]
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
        ("task_skipped", "skeptic"),
        ("task_skipped", "financial_analyst"),
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
        "skeptic": "skipped",
        "financial_analyst": "skipped",
        "editor": "succeeded",
    }
    # Lumentum has nothing archived: its Investigator task makes no LLM call.
    assert "no parsed Source Version" in tasks(found)["investigator:lumentum"]["detail"]
    assert roles(llm) == ["scout", "investigator", "editor", "reviewer"]
    # Every role call is in the investigation's run, which the stop finished (the chained
    # relationship review has its own).
    run_id = found["run_id"]
    assert run_id is not None and found["request"]["run_id"] == run_id
    assert {body["metadata"]["run_id"] for body in llm.chat_requests()[:3]} == {run_id}
    calls = atlas.get(f"/api/v1/runs/{run_id}/role-calls")
    assert [(c["role"], c["status"]) for c in calls["role_calls"]] == [
        ("scout", "accepted"),
        ("investigator", "accepted"),
        ("editor", "accepted"),
    ]
    assert (calls["tokens_in"], calls["tokens_out"]) == (12_900, 1_220)
    assert found["usage"] == {
        "rounds": 1,
        "leads": 3,
        "documents": 2,
        "tokens_in": 12_900,
        "tokens_out": 1_220,
    }
    tokens = "atlas_llm_tokens_total"
    assert metric(atlas, tokens, kind="investigation", direction="input") == 12_900
    assert metric(atlas, tokens, kind="investigation", direction="output") == 1_220
    discovery = atlas.get(
        f"/api/v1/discoveries/{tasks(found)['scout']['artifacts']['discovery_id']}"
    )
    assert (discovery["run_id"], discovery["status"]) == (run_id, "completed")
    extraction = atlas.get(
        "/api/v1/claim-extractions/"
        f"{tasks(found)['investigator:coherent']['artifacts']['extraction_id']}"
    )
    assert (extraction["run_id"], extraction["question"]) == (run_id, QUESTION)
    # The leads, in the order the queries found them (never Evidence), and the documents.
    assert [(lead["rank"], lead["canonical_url"], lead["tier"]) for lead in found["leads"]] == [
        (1, AXT, "C"),
        (2, SUMITOMO, "C"),
        (3, BLOG, "C"),
    ]
    ten_k = atlas.version(COHR_10K, "coherent")["id"]
    ten_q = atlas.version(COHR_10Q, "coherent")["id"]
    assert [d["source_version_id"] for d in found["documents"]] == [ten_k, ten_q]
    assert extraction["source_version_ids"] == [ten_k, ten_q]
    # The Editor was sent the accepted Claim (its quote as low-trust data) and the leads.
    editor = asked(llm.chat_requests()[2])
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
    assert finding["limitations"] == ["A company's own statement; no volumes or prices."]
    assert card["editor_role_call_id"] == calls["role_calls"][2]["id"]
    # The event log tells the story in order, ending with the stop and its reason.
    log = events(atlas, started["id"])
    assert [(e["type"], e["task_key"]) for e in log if e["task_key"] == "scout"] == [
        ("task_queued", "scout"),
        ("task_started", "scout"),
        ("task_succeeded", "scout"),
    ]
    assert log[-1]["type"] == "stopped"
    assert log[-1]["detail"] == {
        "reason": "answered",
        "detail": found["stop_detail"],
        "tokens_in": 12_900,
        "tokens_out": 1_220,
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
    llm.script_chat(scout_reply(), ChatReply.json({"claims": []}))
    script_searches(searxng)

    atlas.worker_pass()

    found = investigation(atlas, started["id"])
    assert [lead["canonical_url"] for lead in found["leads"]] == [AXT, SUMITOMO]
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
    # No accepted Claim: no new independent Evidence, and the Editor isn't called.
    assert roles(llm)[-1] != "editor"
    assert (found["status"], found["stop_reason"]) == ("stopped", "no_new_independent_evidence")
    assert tasks(found)["editor"]["status"] == "skipped"
    assert found["research_card"] is None
    assert (
        metric(atlas, "atlas_investigation_stops_total", reason="no_new_independent_evidence") == 1
    )


def test_the_document_budget_is_shared_by_the_investigator_tasks(
    services: Services, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    atlas = services.start()
    started = seeded(atlas, "coherent", budgets={"max_documents": 1})
    llm.script_chat(scout_reply(), ChatReply.json({"claims": []}))
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


def test_budget_exhaustion_stops_resumably_and_resuming_continues_in_the_same_run(
    services: Services, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    atlas = services.start(investigator_passages_per_call=1, investigator_max_passages=3)
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
        "skeptic": "skipped",
        "financial_analyst": "skipped",
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
    llm.script_chat(ChatReply.json({"claims": []}), ChatReply.json({"claims": []}))
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
    sent = [asked(body)["retrieved_data"][0]["id"] for body in llm.chat_requests()[1:]]
    assert sent == ["p1", "p2", "p3"]
    second = tasks(found)["investigator:coherent"]["artifacts"]["extraction_id"]
    continuation = atlas.get(f"/api/v1/claim-extractions/{second}")
    assert (continuation["continues_id"], continuation["run_id"]) == (first, run_id)
    assert (continuation["status"], continuation["batches_total"]) == ("completed", 2)
    calls = atlas.get(f"/api/v1/runs/{run_id}/role-calls")
    assert [(c["role"], c["status"]) for c in calls["role_calls"]] == [
        ("scout", "accepted"),
        ("investigator", "accepted"),
        ("investigator", "budget_exhausted"),
        ("investigator", "accepted"),
        ("investigator", "accepted"),
    ]
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


def test_a_budget_spent_before_the_editor_resumes_into_the_editor(
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
    assert (stopped["stop_reason"], tasks(stopped)["editor"]["status"]) == (
        "budget_exhausted",
        "budget_exhausted",
    )
    assert "before the editor's call" in stopped["stop_detail"]
    assert stopped["research_card"] is None
    assert roles(llm) == ["scout", "investigator"]

    # A resumable stop doesn't chain the relationship review: the run isn't over.
    assert "relationship_review_queued" not in [e["type"] for e in events(atlas, started["id"])]

    llm.script_chat(ChatReply.answer(editing()), REVIEWED)
    resumed = atlas.api.post(
        f"/api/v1/investigations/{started['id']}/resume", json={"token_budget": 20_000}
    )
    assert resumed.status_code == 200, resumed.text
    atlas.worker_pass()

    found = investigation(atlas, started["id"])
    assert found["stop_reason"] == "answered"
    assert len(found["research_card"]["findings"]) == 1
    assert roles(llm) == ["scout", "investigator", "editor", "reviewer"]


# --- an LLM outage --------------------------------------------------------------------------------


def test_an_llm_outage_pauses_the_investigation_and_it_resumes_with_nothing_invented(
    services: Services, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    atlas = services.start()
    clock = Clock(datetime.now(UTC))
    worker = paced(atlas, clock)
    started = seeded(atlas, "coherent")
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
    assert [(c["role"], c["status"]) for c in calls] == [
        ("scout", "accepted"),
        ("investigator", "accepted"),
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
        "skeptic": "skipped",
        "financial_analyst": "skipped",
        "editor": "pending",
    }
    assert tasks(disproven)["investigator:lumentum"]["detail"] == (
        "premise 'company:lumentum' was disproven: Lumentum makes no lasers for this customer"
    )
    premise = {p["key"]: p for p in disproven["premises"]}["company:lumentum"]
    assert (premise["status"], premise["disproven_by"]) == ("disproven", "local-researcher")

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
    assert asked(llm.chat_requests()[2])["request"]["disproven_premises"] == [
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
    assert set(statuses(found).values()) == {"cancelled", "skipped"}
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
