"""Scenarios and the Financial Analyst (Phase 3-6a ticket 19; spec Phase 5 "Scenario", §5.7,
§8.2): deterministic low/base/high scenarios on as-of XBRL figures and sourced or estimated
inputs, attached to a Hypothesis version.

Seams: an investigation runs through `POST /api/v1/investigations` and single worker passes;
`POST /api/v1/hypotheses` saves it and a worker pass drafts version 1; scenarios are made and
read through `/api/v1/hypotheses/{id}/scenarios`; everything else is observed through
`/api/v1` (the investigation's tasks, runs' role calls, financial observations) and the
requests the fakes received. The Source Versions are the recorded Coherent EDGAR filings (the
FY2026 10-K and its companyfacts, normalized at ingest); Hindsight is the recorded fake,
SearXNG the scripted fake. LiteLLM is the scripted chat fake: **every role's answer is written
here**, the Financial Analyst's citing the observation and Assertion IDs it is sent.

Expected figures are the companyfacts fixture's (FY2026 revenue $7,118,181,000 and cash
$1,162,018,000 at 2026-06-30, from the 10-K 0000820318-26-000020 filed 2026-08-14) and the
scenario lines are worked by hand from §8.2; nothing is recomputed the way the code does.
"""

import hashlib
import json
import os
import subprocess
import sys
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy.exc
import yaml
from pydantic import JsonValue
from sqlalchemy import text

from tests.fakes.hindsight import RecordedHindsight
from tests.fakes.litellm import ChatReply, FakeLiteLLM
from tests.fakes.searxng import FakeSearXNG, SearchReply
from tests.fakes.serve import Served, serve
from tests.harness import THEMES, Atlas

QUESTION = "Who supplies the lasers in AI data-center optics, and to whom?"
SUBSTRATE = "indium phosphide substrate capacity expansion 2026"
AS_OF = "2026-09-01T00:00:00Z"
# From the Coherent FY2026 10-K (the recorded fixture's parsed text).
SUPPLY_QUOTE = (
    "we announced the expansion of our Sherman, Texas, manufacturing facility, entered into a"
    " strategic multi-year supply agreement with NVIDIA for advanced lasers and optical"
    " networking products"
)
TEN_K = "0000820318-26-000020"  # FY2026, filed 2026-08-14
Q3_10Q = "0000820318-26-000013"  # Q3 FY2026, filed 2026-05-06
FY2026_REVENUE = "7118181000"
FY2026_CASH = "1162018000"  # 2026-06-30
FY2025_CASH = "909200000"  # 2025-06-30, in both the Q3 10-Q and the 10-K
UNSENT = "00000000-0000-4000-8000-000000000001"


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


@pytest.fixture
def atlas(
    database_url: str,
    tmp_path: Path,
    hindsight: tuple[RecordedHindsight, Served],
    litellm: Served,
    searxng_served: Served,
    themes: Path,
) -> Iterator[Atlas]:
    """Atlas with the template applied, the universe seeded and Coherent's filings ingested
    (its companyfacts normalized)."""
    started = start(
        database_url, tmp_path, hindsight[1].url, litellm.url, searxng_served.url, themes
    )
    started.ingest_company("coherent")
    yield started
    started.engine.dispose()


@pytest.fixture
def lumentum_atlas(
    database_url: str,
    tmp_path: Path,
    hindsight: tuple[RecordedHindsight, Served],
    litellm: Served,
    searxng_served: Served,
    themes: Path,
) -> Iterator[Atlas]:
    """Atlas with Lumentum's filings ingested instead (its companyfacts normalized). No
    Lumentum passage names another company, so they reach the Investigator as recall hits:
    every one fits in one call."""
    started = start(
        database_url,
        tmp_path,
        hindsight[1].url,
        litellm.url,
        searxng_served.url,
        themes,
        investigator_max_passages=1000,
        investigator_passages_per_call=1000,
    )
    started.ingest_company("lumentum")
    yield started
    started.engine.dispose()


def start(
    database_url: str,
    tmp_path: Path,
    hindsight_url: str,
    litellm_url: str,
    searxng_url: str,
    themes: Path,
    **overrides: Any,
) -> Atlas:
    """Atlas with the template applied and the universe seeded."""
    started = Atlas(
        database_url,
        tmp_path,
        hindsight_url,
        litellm_url,
        **(
            {
                "themes_config": themes,
                "searxng_url": searxng_url,
                "investigator_passages_per_call": 50,
            }
            | overrides
        ),
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
    return started


# --- helpers --------------------------------------------------------------------------------------


def company_id(atlas: Atlas, slug: str) -> str:
    return atlas.company(slug)["id"]


def asked(body: dict[str, Any]) -> dict[str, Any]:
    """The user message of a chat request: `{"request": ..., "retrieved_data": [...]}`."""
    return json.loads(body["messages"][1]["content"])


def finding_nothing(body: dict[str, Any]) -> JsonValue:
    """The Skeptic finding nothing: its plan chooses no query and no document, and its reading
    of what code's fallback then chose (pilot fix 06) proposes nothing."""
    if "catalog" in asked(body)["request"]:
        return {"queries": [], "documents": []}
    return {"counterevidence": []}


def quoting(atlas: Atlas) -> Callable[[dict[str, Any]], JsonValue]:
    """The Investigator proposes the 10-K's supply Claim from the passage holding it."""

    def respond(body: dict[str, Any]) -> JsonValue:
        passages = asked(body)["retrieved_data"]
        holding = [p for p in passages if SUPPLY_QUOTE in p["text"]]
        assert holding, "no passage sent holds the supply quote"
        start_at = holding[0]["text"].index(SUPPLY_QUOTE)
        claim: dict[str, JsonValue] = {
            "subject_company_id": company_id(atlas, "coherent"),
            "predicate": "supplies",
            "object_company_id": company_id(atlas, "nvidia"),
            "object_name": None,
            "object_text": None,
            "product": "advanced lasers",
            "layer": "chip-laser",
            "quote": SUPPLY_QUOTE,
            "epistemic_type": "company_claim",
            "passage_id": holding[0]["id"],
            "quote_start": start_at,
            "quote_end": start_at + len(SUPPLY_QUOTE),
        }
        return {"claims": [claim]}

    return respond


def estimate(name: str, low: str, base: str, high: str) -> dict[str, JsonValue]:
    return {
        "name": name,
        "kind": "estimated",
        "observation_id": None,
        "assertion_id": None,
        "basis": f"an illustrative range for {name}",
        "low": low,
        "base": base,
        "high": high,
    }


def same(value: str) -> dict[str, JsonValue]:
    return {"low": value, "base": value, "high": value}


def figure(request: dict[str, Any], metric: str) -> dict[str, Any]:
    [company] = request["companies"]
    return next(each for each in company["figures"] if each["metric"] == metric)


def analysing(body: dict[str, Any]) -> JsonValue:
    """The Financial Analyst's answer: estimates with bases, the FY revenue and cash from the
    figures it is sent, the company share from the supply Claim's Assertion, and two inputs
    that must not stand: a multiple with no basis, and debt citing an observation it wasn't
    sent."""
    request = asked(body)["request"]
    [company] = request["companies"]
    revenue, cash = figure(request, "revenue"), figure(request, "cash")
    inputs: list[JsonValue] = [
        estimate("addressable_units", "8000000", "10000000", "12000000"),
        {
            "name": "company_share",
            "kind": "sourced",
            "observation_id": None,
            "assertion_id": request["claims"][0]["assertion_id"],
            "basis": None,
            "low": "0.2",
            "base": "0.25",
            "high": "0.3",
        },
        estimate("downstream_unit_price", "900", "1000", "1100"),
        estimate("bom_share", "0.15", "0.2", "0.25"),
        estimate("operating_margin", "0.25", "0.3", "0.35"),
        estimate("ev_multiple", "15", "20", "25") | {"basis": None},
        {
            "name": "reported_revenue",
            "kind": "sourced",
            "observation_id": revenue["observation_id"],
            "assertion_id": None,
            "basis": None,
            **same(revenue["value"]),
        },
        {
            "name": "cash",
            "kind": "sourced",
            "observation_id": cash["observation_id"],
            "assertion_id": None,
            "basis": None,
            **same(cash["value"]),
        },
        {
            "name": "total_debt",
            "kind": "sourced",
            "observation_id": UNSENT,
            "assertion_id": None,
            "basis": None,
            **same("3000000000"),
        },
        estimate("diluted_shares", "150000000", "150000000", "150000000"),
    ]
    return {
        "scenarios": [
            {
                "company_id": company["company_id"],
                "product": "advanced lasers for AI optical interconnects",
                "currency": "USD",
                "inputs": inputs,
            }
        ]
    }


def card_editor(body: dict[str, Any]) -> JsonValue:
    request = asked(body)["request"]
    return {
        "findings": [
            {
                "statement": "Coherent supplies NVIDIA with advanced lasers.",
                "claim_ids": [each["claim_id"] for each in request["claims"]],
                "limitations": ["A company's own statement."],
                "open_questions": [],
            }
        ],
        "open_questions": ["Does NVIDIA qualify a second laser source?"],
        "verdict": "answered",
    }


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


def hypothesis_editor(body: dict[str, Any]) -> JsonValue:
    request = asked(body)["request"]
    return {
        "thesis_statement": "Demand for advanced lasers may outgrow qualified capacity.",
        "mechanism": {
            "demand_driver": "AI data-center optical interconnect deployments",
            "possible_constraint": "Qualified advanced-laser capacity",
            "economic_capture_question": None,
        },
        "measurable_predictions": ["Laser lead times stay elevated in 2027 filings"],
        "catalysts": ["New multi-year supply agreements"],
        "falsifiers": ["Verified laser capacity exceeds plausible demand"],
        "required_evidence": ["An original document naming a second laser source"],
        "alternative_explanations": ["Inventory build-up mimics demand"],
        "unresolved_questions": ["Does NVIDIA qualify a second laser source?"],
        "findings": [
            {
                "statement": "Coherent supplies NVIDIA with advanced lasers.",
                "claim_ids": [each["claim_id"] for each in request["claims"]],
                "limitations": ["One filing only."],
                "open_questions": [],
            }
        ],
    }


def investigate(
    atlas: Atlas,
    llm: FakeLiteLLM,
    searxng: FakeSearXNG,
    analyst: ChatReply | None = None,
) -> dict[str, Any]:
    """An investigation of Coherent as of `AS_OF`, run to its stop."""
    searxng.script(SUBSTRATE, SearchReply.of("inp-substrate-capacity"))
    # The Skeptic (searching and reading nothing) and the Analyst run in parallel, in either
    # order: their answers are scripted by role.
    llm.script_role("skeptic", *[ChatReply.answer(finding_nothing)] * 8)
    llm.script_role("financial_analyst", analyst or ChatReply.answer(analysing, tokens=(2500, 600)))
    llm.script_chat(
        ChatReply.json({"queries": [{"query": SUBSTRATE, "purpose": None}]}, tokens=(900, 120)),
        ChatReply.answer(quoting(atlas), tokens=(9000, 700)),
        ChatReply.answer(card_editor, tokens=(3000, 400)),
        ChatReply.answer(reviewing, tokens=(800, 100)),
    )
    response = atlas.api.post(
        "/api/v1/investigations",
        json={
            "theme": "photonics",
            "question": QUESTION,
            "seed_company_ids": [company_id(atlas, "coherent")],
            "as_of": AS_OF,
        },
    )
    assert response.status_code == 202, response.text
    atlas.worker_pass()
    found = atlas.get(f"/api/v1/investigations/{response.json()['id']}")
    assert found["status"] == "stopped", found["stop_detail"]
    return found


def drafted(
    atlas: Atlas, llm: FakeLiteLLM, searxng: FakeSearXNG, analyst: ChatReply | None = None
) -> dict[str, Any]:
    """An investigation saved as a Hypothesis with version 1 drafted."""
    found = investigate(atlas, llm, searxng, analyst)
    response = atlas.api.post("/api/v1/hypotheses", json={"investigation_id": found["id"]})
    assert response.status_code == 202, response.text
    llm.script_chat(ChatReply.answer(hypothesis_editor, tokens=(4000, 600)))
    atlas.worker_pass()
    hypothesis = atlas.get(f"/api/v1/hypotheses/{response.json()['id']}")
    assert hypothesis["draft_status"] == "drafted", hypothesis["draft_error"]
    return hypothesis


def analyst_task(found: dict[str, Any]) -> dict[str, Any]:
    return next(task for task in found["tasks"] if task["key"] == "financial_analyst")


def create(atlas: Atlas, hypothesis_id: str, **body: Any) -> Any:
    return atlas.api.post(f"/api/v1/hypotheses/{hypothesis_id}/scenarios", json=body)


def lines(scenario: dict[str, Any], case: str) -> dict[str, str | None]:
    return {name: line["value"] for name, line in scenario["outputs"]["cases"][case].items()}


def observation(atlas: Atlas, concept: str, end: str, accession: str) -> dict[str, Any]:
    """The observation of `concept` for the instant/period ending `end` in filing
    `accession` (from its period key's history)."""
    selected = atlas.get(
        f"/api/v1/companies/{company_id(atlas, 'coherent')}/financial-observations",
        as_of=AS_OF,
        concept=concept,
        limit=500,
    )["items"]
    key = next(each for each in selected if each["period_end"] == end)
    history = atlas.get(f"/api/v1/financial-observations/{key['id']}")["history"]
    return next(each for each in history if each["accession"] == accession)


def researcher_table(atlas: Atlas, **inputs: Any) -> dict[str, Any]:
    """A researcher's table for Coherent: sourced FY2026 revenue and cash, the rest estimated
    (or as `inputs` says; None leaves an input out)."""
    revenue = observation(
        atlas, "RevenueFromContractWithCustomerExcludingAssessedTax", "2026-06-30", TEN_K
    )
    cash = observation(atlas, "CashAndCashEquivalentsAtCarryingValue", "2026-06-30", TEN_K)

    def xbrl(found: dict[str, Any]) -> dict[str, Any]:
        value = found["value"]
        return {
            "kind": "sourced",
            "source": {"type": "xbrl_observation", "observation_id": found["id"]},
            "low": value,
            "base": value,
            "high": value,
        }

    def guess(low: str, base: str, high: str) -> dict[str, Any]:
        return {"kind": "estimated", "basis": "a guess", "low": low, "base": base, "high": high}

    table: dict[str, Any] = {
        "addressable_units": guess("8000000", "10000000", "12000000"),
        "company_share": guess("0.2", "0.25", "0.3"),
        "downstream_unit_price": guess("900", "1000", "1100"),
        "bom_share": guess("0.15", "0.2", "0.25"),
        "operating_margin": guess("0.25", "0.3", "0.35"),
        "ev_multiple": guess("15", "20", "25"),
        "reported_revenue": xbrl(revenue),
        "total_debt": guess("3000000000", "3000000000", "3000000000"),
        "cash": xbrl(cash),
        "diluted_shares": guess("150000000", "150000000", "150000000"),
    } | inputs
    return {
        "company_id": company_id(atlas, "coherent"),
        "product": "advanced lasers",
        "currency": "USD",
        "inputs": {name: value for name, value in table.items() if value is not None},
    }


# --- the Financial Analyst in the investigation ------------------------------------------------


def test_the_financial_analyst_proposes_inputs_and_only_sourced_or_estimated_ones_stand(
    atlas: Atlas, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    found = investigate(atlas, llm, searxng)

    assert found["stop_reason"] == "answered"
    roles = [body["metadata"]["role"] for body in llm.chat_requests()]
    assert roles[:2] == ["scout", "investigator"]
    # In parallel, either order; the Skeptic plans, then reads what code's fallback chose.
    assert sorted(roles[2:5]) == ["financial_analyst", "skeptic", "skeptic"]
    assert roles[5:] == ["editor", "reviewer"]
    task = analyst_task(found)
    assert task["status"] == "succeeded"
    assert task["depends_on"] == ["investigator:coherent"]
    # What the Analyst was sent: Coherent's as-of FY2026 figures, each an observation ID, and
    # the accepted Claim by its Assertion ID, its quote as low-trust retrieved data.
    [sent] = [asked(b) for b in llm.chat_requests() if b["metadata"]["role"] == "financial_analyst"]
    request = sent["request"]
    assert [c["company_id"] for c in request["companies"]] == [company_id(atlas, "coherent")]
    revenue, cash = figure(request, "revenue"), figure(request, "cash")
    assert (revenue["value"], revenue["period_start"], revenue["period_end"]) == (
        FY2026_REVENUE,
        "2025-07-01",
        "2026-06-30",
    )
    assert (cash["value"], cash["period_end"], cash["unit"]) == (FY2026_CASH, "2026-06-30", "USD")
    [claim] = request["claims"]
    assert (claim["predicate"], claim["product"]) == ("supplies", "advanced lasers")
    assert sent["retrieved_data"] == [
        {
            "id": claim["assertion_id"],
            "source": sent["retrieved_data"][0]["source"],
            "text": SUPPLY_QUOTE,
            "trust": "low",
        }
    ]
    assert {each["name"] for each in request["inputs"]} >= {"bom_share", "reported_revenue"}
    # What stands: sourced and estimated inputs; the source-free multiple and the debt citing
    # what the Analyst wasn't sent are rejected and missing.
    [proposal] = task["artifacts"]["scenario_proposals"]
    inputs = proposal["inputs"]
    assert inputs["reported_revenue"] == {
        "kind": "sourced",
        "source": {"type": "xbrl_observation", "observation_id": revenue["observation_id"]},
        "low": FY2026_REVENUE,
        "base": FY2026_REVENUE,
        "high": FY2026_REVENUE,
    }
    assert inputs["company_share"]["source"] == {
        "type": "assertion",
        "assertion_id": claim["assertion_id"],
    }
    assert inputs["bom_share"] == {
        "kind": "estimated",
        "basis": "an illustrative range for bom_share",
        "low": "0.15",
        "base": "0.2",
        "high": "0.25",
    }
    assert inputs["ev_multiple"]["kind"] == inputs["total_debt"]["kind"] == "missing"
    rejected = {each["input"]: each["reason"] for each in task["artifacts"]["rejected_inputs"]}
    assert set(rejected) == {"ev_multiple", "total_debt"}
    assert "basis" in rejected["ev_multiple"]
    assert rejected["total_debt"] == f"XBRL observation {UNSENT} doesn't exist"
    # The call is recorded in the investigation's run.
    calls = atlas.get(f"/api/v1/runs/{found['run_id']}/role-calls")["role_calls"]
    analyst = [each for each in calls if each["role"] == "financial_analyst"]
    assert len(analyst) == 1 and analyst[0]["status"] == "accepted"
    assert task["artifacts"]["role_call_id"] == analyst[0]["id"]


def test_without_an_accepted_claim_the_analyst_is_skipped_without_an_llm_call(
    atlas: Atlas, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    searxng.script(SUBSTRATE, SearchReply.of("inp-substrate-capacity"))
    llm.script_chat(
        ChatReply.json({"queries": [{"query": SUBSTRATE, "purpose": None}]}),
        ChatReply.json({"claims": []}),
        # The Editor still writes a card, with no finding (pilot fix 01).
        ChatReply.json({"findings": [], "open_questions": [], "verdict": "needs_review"}),
    )
    response = atlas.api.post(
        "/api/v1/investigations",
        json={
            "theme": "photonics",
            "question": QUESTION,
            "seed_company_ids": [company_id(atlas, "coherent")],
            "as_of": AS_OF,
        },
    )
    atlas.worker_pass()

    found = atlas.get(f"/api/v1/investigations/{response.json()['id']}")
    task = analyst_task(found)
    assert task["status"] == "skipped"
    assert task["detail"] == "nothing to quantify: the Investigators accepted no Claims"
    assert [body["metadata"]["role"] for body in llm.chat_requests()] == [
        "scout",
        "investigator",
        "editor",
    ]


# Pilot-fixes ticket 07: Lumentum's FY2026 10-K (0001628280-26-057358, filed 2026-08-17) as its
# companyfacts fixture tags it: the research note's §2 values, and cash from the fixture.
# Two sentences, as production's accepted Claim quoted it: the second alone names no product
# (pilot fix 09's `object_not_in_quote`).
LITE_ALLOCATION = (
    "we have seen increasing demand from AI and cloud customers as they continue to expand"
    " their data centers, driven in part by the continued advances in cloud and AI"
    " infrastructure. This demand is outpacing our current supply which has required us to"
    " make decisions on supply allocation."
)
LITE_FY2026 = ("2025-06-29", "2026-06-27")
LITE_REVENUE = "3014000000"
LITE_CASH = "2043500000"
LITE_DEBT = "1637400000"
LITE_DILUTED_SHARES = "74600000"
XBRL_INPUTS = {
    "reported_revenue": "revenue",
    "cash": "cash",
    "total_debt": "total_debt",
    "diluted_shares": "diluted_shares",
}


def lumentum_allocation(atlas: Atlas) -> Callable[[dict[str, Any]], JsonValue]:
    """The Investigator proposes Lumentum's allocation statement (pilot investigation 1's
    saved `capacity_constrained` Claim) from the passage holding it."""

    def respond(body: dict[str, Any]) -> JsonValue:
        passages = asked(body)["retrieved_data"]
        holding = [p for p in passages if LITE_ALLOCATION in p["text"]]
        assert holding, "no passage sent holds the allocation statement"
        start_at = holding[0]["text"].index(LITE_ALLOCATION)
        claim: dict[str, JsonValue] = {
            "subject_company_id": company_id(atlas, "lumentum"),
            "predicate": "capacity_constrained",
            "object_company_id": None,
            "object_name": None,
            "object_text": "optical components for AI and cloud data centers",
            "product": "optical components",
            "layer": "module",
            "quote": LITE_ALLOCATION,
            "epistemic_type": "company_claim",
            "passage_id": holding[0]["id"],
            "quote_start": start_at,
            "quote_end": start_at + len(LITE_ALLOCATION),
        }
        return {"claims": [claim]}

    return respond


def sourcing_every_figure(body: dict[str, Any]) -> JsonValue:
    """The Analyst sources every XBRL-measurable input from the figure it is sent for it and
    estimates the rest."""
    request = asked(body)["request"]
    [company] = request["companies"]
    sourced: list[JsonValue] = []
    for name, metric in XBRL_INPUTS.items():
        sent = figure(request, metric)
        sourced.append(
            {
                "name": name,
                "kind": "sourced",
                "observation_id": sent["observation_id"],
                "assertion_id": None,
                "basis": None,
                **same(sent["value"]),
            }
        )
    return {
        "scenarios": [
            {
                "company_id": company["company_id"],
                "product": "optical components for AI data centers",
                "currency": "USD",
                "inputs": [
                    estimate("addressable_units", "8000000", "10000000", "12000000"),
                    estimate("company_share", "0.1", "0.15", "0.2"),
                    estimate("downstream_unit_price", "900", "1000", "1100"),
                    estimate("bom_share", "0.15", "0.2", "0.25"),
                    estimate("operating_margin", "0.15", "0.2", "0.25"),
                    estimate("ev_multiple", "15", "20", "25"),
                    *sourced,
                ],
            }
        ]
    }


def test_the_analyst_is_sent_lumentum_s_as_of_figures_and_sources_its_inputs_from_them(
    lumentum_atlas: Atlas, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    # Pilot investigation 1's re-run sent `figures: []` for Lumentum and Coherent: production
    # had no observation, since their companyfacts were never normalized. Once they are, the
    # Analyst gets the as-of FY2026 figures and inputs sourced from them stand.
    atlas = lumentum_atlas
    lumentum = company_id(atlas, "lumentum")
    searxng.script(SUBSTRATE, SearchReply.of("inp-substrate-capacity"))
    # The Skeptic's plan chooses nothing; code's fallback (pilot fix 06) then has it read the
    # 10-K and 10-Q, and it proposes nothing.
    llm.script_role("skeptic", *[ChatReply.answer(finding_nothing)] * 8)
    llm.script_role("financial_analyst", ChatReply.answer(sourcing_every_figure))
    llm.script_chat(
        ChatReply.json({"queries": [{"query": SUBSTRATE, "purpose": None}]}),
        ChatReply.answer(lumentum_allocation(atlas)),
        ChatReply.answer(card_editor),
        ChatReply.answer(reviewing),
    )
    response = atlas.api.post(
        "/api/v1/investigations",
        json={
            "theme": "photonics",
            "question": "Is laser supply for 800G/1.6T transceivers constrained?",
            "seed_company_ids": [lumentum],
            "as_of": AS_OF,
        },
    )
    assert response.status_code == 202, response.text
    atlas.worker_pass()
    found = atlas.get(f"/api/v1/investigations/{response.json()['id']}")
    assert found["status"] == "stopped", found["stop_detail"]

    [sent] = [asked(b) for b in llm.chat_requests() if b["metadata"]["role"] == "financial_analyst"]
    request = sent["request"]
    assert [c["company_id"] for c in request["companies"]] == [lumentum]
    got = {
        metric: (each["value"], each["period_start"], each["period_end"], each["unit"])
        for metric in XBRL_INPUTS.values()
        for each in [figure(request, metric)]
    }
    assert got == {
        "revenue": (LITE_REVENUE, *LITE_FY2026, "USD"),
        "cash": (LITE_CASH, None, LITE_FY2026[1], "USD"),
        "total_debt": (LITE_DEBT, None, LITE_FY2026[1], "USD"),
        "diluted_shares": (LITE_DILUTED_SHARES, *LITE_FY2026, "shares"),
    }
    task = analyst_task(found)
    assert task["status"] == "succeeded"
    assert task["artifacts"]["rejected_inputs"] == []
    [proposal] = task["artifacts"]["scenario_proposals"]
    assert proposal["company_id"] == lumentum
    for name, metric in XBRL_INPUTS.items():
        value = figure(request, metric)["value"]
        assert proposal["inputs"][name] == {
            "kind": "sourced",
            "source": {
                "type": "xbrl_observation",
                "observation_id": figure(request, metric)["observation_id"],
            },
            "low": value,
            "base": value,
            "high": value,
        }, name


# --- scenarios on a Hypothesis version ----------------------------------------------------------


def test_a_scenario_on_a_hypothesis_version_computes_low_base_high_from_the_analyst_s_inputs(
    atlas: Atlas, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    hypothesis = drafted(atlas, llm, searxng)
    found = atlas.get(f"/api/v1/investigations/{hypothesis['investigation_id']}")
    task = analyst_task(found)

    response = create(atlas, hypothesis["id"], version=1)

    assert response.status_code == 201, response.text
    [scenario] = response.json()["items"]
    assert scenario["hypothesis_version"] == 1
    assert scenario["hypothesis_version_id"] == hypothesis["versions"][0]["id"]
    assert scenario["company_id"] == company_id(atlas, "coherent")
    assert (scenario["origin"], scenario["model_version"]) == ("financial_analyst", "scenario-v1")
    assert scenario["investigation_task_id"] == task["id"]
    assert scenario["role_call_id"] == task["artifacts"]["role_call_id"]
    assert scenario["as_of"].startswith("2026-09-01T00:00:00")
    assert scenario["currency"] == "USD"
    # §8.2 by hand: price 1000 x BOM share 0.2 = 200; revenue 10M x 0.25 x 200 = 500M;
    # contribution x 0.3 = 150M; exposure 500M / 7,118.181M = 0.070243. The multiple and the
    # debt are missing, so the valuation lines are blocked.
    assert lines(scenario, "base") == {
        "component_price": "200",
        "incremental_revenue": "500000000",
        "incremental_contribution": "150000000",
        "scenario_enterprise_value": None,
        "net_debt": None,
        "illustrative_equity_value": None,
        "equity_value_per_share": None,
        "revenue_exposure": "0.070243",
    }
    assert lines(scenario, "low")["incremental_revenue"] == "216000000"  # 8M x .2 x 900 x .15
    assert lines(scenario, "low")["revenue_exposure"] == "0.030345"
    assert lines(scenario, "high")["incremental_contribution"] == "346500000"
    assert lines(scenario, "high")["revenue_exposure"] == "0.13908"
    blocked = scenario["outputs"]["cases"]["base"]
    assert blocked["equity_value_per_share"]["missing"] == ["ev_multiple", "total_debt"]
    assert blocked["net_debt"]["missing"] == ["total_debt"]
    # ±20% on one input at a time, from the base case.
    share_up = next(
        row
        for row in scenario["outputs"]["sensitivity"]
        if (row["input"], row["change"]) == ("company_share", "+20%")
    )
    assert share_up["input_value"] == "0.3"
    assert share_up["lines"]["incremental_revenue"] == "600000000"
    # Every input with its provenance.
    inputs = {each["name"]: each for each in scenario["inputs"]}
    revenue = inputs["reported_revenue"]
    assert (revenue["kind"], revenue["base"]) == ("sourced", FY2026_REVENUE)
    source = revenue["source"]["observation"]
    assert (source["accession"], source["concept"], source["unit"]) == (
        TEN_K,
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "USD",
    )
    assert (source["period_start"], source["period_end"]) == ("2025-07-01", "2026-06-30")
    assert source["available_at"].startswith("2026-08-14")
    share = inputs["company_share"]
    assert share["source"]["quote"] == SUPPLY_QUOTE
    assert inputs["bom_share"]["basis"] == "an illustrative range for bom_share"
    assert inputs["ev_multiple"]["kind"] == "missing"
    assert inputs["ev_multiple"]["reason"].startswith("rejected: ")
    assert atlas.get(f"/api/v1/hypotheses/{hypothesis['id']}/scenarios")["items"] == [scenario]


def test_scenarios_recompute_byte_identically(
    atlas: Atlas, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    hypothesis = drafted(atlas, llm, searxng)
    first = create(atlas, hypothesis["id"], version=1).json()["items"][0]

    again = create(atlas, hypothesis["id"], version=1).json()["items"][0]
    # The researcher sends the same table back (missing inputs with their reasons): the same
    # bytes again.
    table = first["assumptions"]
    researcher = create(atlas, hypothesis["id"], version=1, assumptions=table)

    assert researcher.status_code == 201, researcher.text
    third = researcher.json()["items"][0]
    assert third["origin"] == "researcher"
    assert again["id"] != first["id"]
    for each in (again, third):
        assert each["outputs_json"] == first["outputs_json"]
        assert each["outputs_sha256"] == first["outputs_sha256"]
    # The hash is the stored bytes' hash, and recomputing now gives the same bytes.
    assert first["outputs_sha256"] == hashlib.sha256(first["outputs_json"].encode()).hexdigest()
    read = atlas.get(f"/api/v1/hypotheses/{hypothesis['id']}/scenarios/{first['id']}")
    assert read["recomputes_identically"] is True
    assert read["recomputed_outputs_sha256"] == first["outputs_sha256"]
    assert read["outputs_json"] == first["outputs_json"]
    assert len(atlas.get(f"/api/v1/hypotheses/{hypothesis['id']}/scenarios")["items"]) == 3
    # A stored scenario never changes.
    with atlas.engine.begin() as connection:
        with pytest.raises(sqlalchemy.exc.DBAPIError, match="insert-only"):
            connection.execute(
                text("UPDATE scenario SET outputs = '{}' WHERE id = :id"), {"id": first["id"]}
            )
    with atlas.engine.connect() as connection:
        actions = list(
            connection.execute(
                text("SELECT action FROM audit_event WHERE entity_type = 'scenario'")
            ).scalars()
        )
    assert actions == ["scenario.created"] * 3


def test_no_source_free_financial_figure_passes_validation(
    atlas: Atlas, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    hypothesis = drafted(atlas, llm, searxng, ChatReply.json({"scenarios": []}))
    hypothesis_id = hypothesis["id"]
    # The Analyst proposed nothing: a scenario needs the researcher's table.
    refused = create(atlas, hypothesis_id, version=1)
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "no_analyst_proposal"

    restated = observation(atlas, "CashAndCashEquivalentsAtCarryingValue", "2025-06-30", Q3_10Q)
    assert restated["value"] == FY2025_CASH
    wrong_value = researcher_table(atlas)
    wrong_value["inputs"]["reported_revenue"] |= {"high": "8000000000"}
    euro = researcher_table(atlas) | {"currency": "EUR"}
    xbrl_units = researcher_table(atlas)
    xbrl_units["inputs"]["addressable_units"] = xbrl_units["inputs"]["cash"]
    invalid_request = {
        "an estimate with no basis": researcher_table(
            atlas, ev_multiple={"kind": "estimated", "low": "1", "base": "2", "high": "3"}
        ),
        "a figure with no source": researcher_table(
            atlas, total_debt={"kind": "sourced", "low": "1", "base": "1", "high": "1"}
        ),
        "a missing input with a value": researcher_table(
            atlas, total_debt={"kind": "missing", "reason": None, "base": "1"}
        ),
    }
    invalid_scenario = {
        "a value that isn't the observation's": (wrong_value, "must equal XBRL observation"),
        "an observation of a filing a later one superseded": (
            researcher_table(
                atlas,
                cash={
                    "kind": "sourced",
                    "source": {"type": "xbrl_observation", "observation_id": restated["id"]},
                    "low": FY2025_CASH,
                    "base": FY2025_CASH,
                    "high": FY2025_CASH,
                },
            ),
            "isn't the as-of value",
        ),
        "an unknown observation": (
            researcher_table(
                atlas,
                total_debt={
                    "kind": "sourced",
                    "source": {"type": "xbrl_observation", "observation_id": UNSENT},
                    "low": "1",
                    "base": "1",
                    "high": "1",
                },
            ),
            "doesn't exist",
        ),
        "an unknown Assertion": (
            researcher_table(
                atlas,
                company_share={
                    "kind": "sourced",
                    "source": {"type": "assertion", "assertion_id": UNSENT},
                    "low": "0.2",
                    "base": "0.25",
                    "high": "0.3",
                },
            ),
            f"Assertion {UNSENT} doesn't exist",
        ),
        "another currency without an FX basis": (euro, "never mixed without an FX basis"),
        "an XBRL fact for a unit count": (
            xbrl_units,
            "an XBRL fact can't source addressable_units",
        ),
    }

    for case, table in invalid_request.items():
        response = create(atlas, hypothesis_id, version=1, assumptions=table)
        assert response.status_code == 422, case
        assert response.json()["error"]["code"] == "invalid_request", case
    for case, (table, reason) in invalid_scenario.items():
        response = create(atlas, hypothesis_id, version=1, assumptions=table)
        assert response.status_code == 422, case
        error = response.json()["error"]
        assert (error["code"], reason in error["message"]) == ("invalid_scenario", True), case
    # A cutoff before the 10-K was available: its FY2026 figures weren't there yet.
    early = create(
        atlas,
        hypothesis_id,
        version=1,
        assumptions=researcher_table(atlas),
        as_of="2026-07-01T00:00:00Z",
    )
    assert early.status_code == 422
    assert "wasn't available at 2026-07-01T00:00:00+00:00" in early.json()["error"]["message"]
    # Only the Hypothesis's own companies, versions and Hypotheses.
    lumentum = researcher_table(atlas) | {"company_id": company_id(atlas, "lumentum")}
    assert create(atlas, hypothesis_id, version=1, assumptions=lumentum).status_code == 422
    assert create(atlas, hypothesis_id, version=9).status_code == 404
    assert create(atlas, str(uuid.uuid4()), version=1).status_code == 404
    assert atlas.api.get(f"/api/v1/hypotheses/{uuid.uuid4()}/scenarios").status_code == 404
    # Nothing was stored; a table whose every figure has a source or a basis is.
    assert atlas.get(f"/api/v1/hypotheses/{hypothesis_id}/scenarios")["items"] == []
    stored = create(atlas, hypothesis_id, version=1, assumptions=researcher_table(atlas))
    assert stored.status_code == 201, stored.text
    scenario = stored.json()["items"][0]
    # By hand: EV 150M x 20 = 3bn; net debt 3bn - 1,162.018M = 1,837.982M; equity 1,162.018M;
    # per share / 150M = 7.746787 (7.74678666...).
    assert lines(scenario, "base")["net_debt"] == "1837982000"
    assert lines(scenario, "base")["illustrative_equity_value"] == "1162018000"
    assert lines(scenario, "base")["equity_value_per_share"] == "7.746787"
