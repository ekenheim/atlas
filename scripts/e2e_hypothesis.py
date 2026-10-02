"""Seed a Hypothesis for the dossier page's Playwright test (ticket 24), used by `scripts/e2e.py`.

Everything goes through the real services, as the integration tests do
(`tests/integration/test_hypotheses.py`): Coherent is ingested from the recorded EDGAR
fixtures, an investigation runs through the API and single worker passes, the Hypothesis is
saved, drafted, given a scenario, published and corrected through the API. Only the network
boundaries are fakes served on localhost: Hindsight (the recorded fake), SearXNG (the scripted
fake) and LiteLLM, whose **every answer is written here**: the Scout's queries, the
Investigator quoting the Coherent FY2026 10-K, the Skeptic quoting a hand-shaped later
statement (imported by hand: it limits the supply agreement) as a contradiction, the Editors
citing the Claim IDs they are sent, the Reviewer confirming.

It leaves, in its own database (the dossier's Coherent and NVIDIA edges would change what
the other pages' tests count):

- version 1: the supply finding, published (its edge approved by the owner), with its Research
  Snapshot, and a researcher's scenario (FY2026 revenue from XBRL, Coherent's share from the
  supply Assertion, the rest estimated);
- version 2: a correction adding NVIDIA's investment, unpublished; its `owns` edge is not
  approved, so the publish gate holds it until the owner approves that edge.
"""

import json
import os
import subprocess
import sys
from collections.abc import Callable, Generator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import JsonValue

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:  # the test fakes and harness live in `tests/`
    sys.path.insert(0, str(REPO))

from tests.fakes.hindsight import RecordedHindsight  # noqa: E402
from tests.fakes.litellm import ChatReply, FakeLiteLLM  # noqa: E402
from tests.fakes.searxng import FakeSearXNG, SearchReply  # noqa: E402
from tests.fakes.serve import serve  # noqa: E402
from tests.harness import THEMES, Atlas  # noqa: E402

QUESTION = "Who supplies the lasers in AI data-center optics, and to whom?"
SUBSTRATE = "indium phosphide substrate capacity expansion 2026"
SECOND_SOURCE = "InP laser second source qualification hyperscaler"
# From the recorded Coherent FY2026 10-K (its parsed text).
SUPPLY_QUOTE = (
    "we announced the expansion of our Sherman, Texas, manufacturing facility, entered into a"
    " strategic multi-year supply agreement with NVIDIA for advanced lasers and optical"
    " networking products"
)
INVESTMENT_QUOTE = "NVIDIA made a $2 billion investment in the Company"
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
SUPPLY_FINDING = "Coherent supplies NVIDIA with advanced lasers under a multi-year agreement."
INVESTMENT_FINDING = "NVIDIA has invested $2 billion in Coherent."
THESIS = (
    "Demand for advanced lasers in AI optics may outgrow qualified laser capacity, favouring"
    " suppliers with long-term agreements such as Coherent."
)
THESIS_V2 = (
    "Demand for advanced lasers in AI optics may outgrow qualified laser capacity, favouring"
    " Coherent, whose largest customer is also an investor."
)
REVENUE = "RevenueFromContractWithCustomerExcludingAssessedTax"
SCENARIO_AS_OF = "2026-09-01T00:00:00Z"


@dataclass(frozen=True)
class SeededHypothesis:
    hypothesis_id: str
    archive: Path
    themes: Path


def seed_hypothesis(database_url: str, workdir: Path) -> SeededHypothesis:
    """Seed the migrated, empty database at `database_url`; files go under `workdir`."""
    workdir.mkdir(parents=True, exist_ok=True)
    themes = with_nvidia(workdir)
    with fakes() as (llm, searxng, urls):
        atlas = Atlas(
            database_url,
            workdir,
            urls["hindsight"],
            urls["litellm"],
            themes_config=themes,
            searxng_url=urls["searxng"],
            investigator_passages_per_call=50,
            # One Investigator call that reaches both quoted windows: the Hindsight fake
            # recalls a fact for every retained section, so the first passages are those
            # sections' pointer windows and the search's windows follow (ticket 05).
            investigation_max_passages=48,
        )
        try:
            atlas.apply_template()
            seed_companies(atlas, themes)
            atlas.ingest_company("coherent")
            hypothesis_id = build(atlas, llm, searxng)
        finally:
            atlas.engine.dispose()
    return SeededHypothesis(hypothesis_id, atlas.archive, themes)


@contextmanager
def fakes() -> Generator[tuple[FakeLiteLLM, FakeSearXNG, dict[str, str]]]:
    hindsight = RecordedHindsight()
    hindsight.derive_memories()
    llm = FakeLiteLLM()
    searxng = FakeSearXNG()
    with ExitStack() as stack:
        served = {
            "hindsight": stack.enter_context(serve(hindsight.transport.handle_request)),
            "litellm": stack.enter_context(serve(llm.handle)),
            "searxng": stack.enter_context(serve(searxng.handle)),
        }
        yield llm, searxng, {name: each.url for name, each in served.items()}
        for name, each in served.items():
            if each.errors:
                raise SystemExit(f"e2e: the {name} fake failed: {each.errors[0]!r}")


def with_nvidia(workdir: Path) -> Path:
    """The universe config plus NVIDIA, the counterparty of Coherent's supply agreement."""
    universe = yaml.safe_load(THEMES.read_text(encoding="utf-8"))
    universe["companies"]["nvidia"] = {
        "legal_name": "NVIDIA Corporation",
        "display_name": "NVIDIA",
        "cik": "0001045810",
        "country": "US",
        "source_path": "sec",
    }
    path = workdir / "themes.yaml"
    path.write_text(yaml.safe_dump(universe), encoding="utf-8")
    return path


def seed_companies(atlas: Atlas, themes: Path) -> None:
    seeded = subprocess.run(
        [sys.executable, "-m", "atlas", "companies", "seed"],
        cwd=atlas.tmp_path,
        env={
            "PATH": os.environ["PATH"],
            "HOME": str(atlas.tmp_path),
            "ATLAS_DATABASE_URL": atlas.database_url,
            "ATLAS_ACTOR": "local-researcher",
            "ATLAS_ARCHIVE_ROOT": str(atlas.archive),
            "ATLAS_THEMES_CONFIG": str(themes),
        },
        capture_output=True,
        text=True,
        timeout=120,
    )
    if seeded.returncode != 0:
        raise SystemExit(f"e2e: `atlas companies seed` failed:\n{seeded.stderr}")


# --- the scripted answers -----------------------------------------------------------------------


def asked(body: dict[str, Any]) -> dict[str, Any]:
    """The user message of a chat request: `{"request": ..., "retrieved_data": [...]}`."""
    return json.loads(body["messages"][1]["content"])


def claim_ids_by_quote(body: dict[str, Any]) -> dict[str, str]:
    """{quote: claim ID} of the Claims an Editor was sent (their quotes are retrieved data)."""
    sent = asked(body)
    # The Hypothesis Editor cites a Claim by its ID, the research card's by its `ref`.
    cited = {each.get("claim_id") or each["ref"] for each in sent["request"]["claims"]}
    return {each["text"]: each["id"] for each in sent["retrieved_data"] if each["id"] in cited}


def quoting(*claims: dict[str, JsonValue]) -> Callable[[dict[str, Any]], JsonValue]:
    """The Investigator: each claim, at its quote's place in a passage it was sent."""

    def respond(body: dict[str, Any]) -> JsonValue:
        passages = asked(body)["retrieved_data"]
        answered: list[JsonValue] = []
        for each in claims:
            quote = str(each["quote"])
            holding = [p for p in passages if quote in p["text"]]
            if not holding:
                raise SystemExit(f"e2e: no passage sent to the Investigator holds {quote!r}")
            start = holding[0]["text"].index(quote)
            answered.append(
                each
                | {
                    "passage_id": holding[0]["id"],
                    "quote_start": start,
                    "quote_end": start + len(quote),
                }
            )
        return {"claims": answered}

    return respond


def statement(quote: str) -> str:
    return SUPPLY_FINDING if quote == SUPPLY_QUOTE else INVESTMENT_FINDING


def card_editor(body: dict[str, Any]) -> JsonValue:
    """The research card: one finding per Claim it is sent (cited by reference)."""
    findings: list[JsonValue] = [
        {
            "statement": statement(quote),
            "claim_refs": [claim_id],
            "limitations": ["A company's own statement."],
            "open_questions": [],
        }
        for quote, claim_id in claim_ids_by_quote(body).items()
    ]
    return {
        "findings": findings,
        "open_questions": ["Is InP substrate capacity a constraint for 2027?"],
        "verdict": "answered",
    }


def reviewing(body: dict[str, Any]) -> JsonValue:
    """The Reviewer confirms every edge it is sent."""
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
    """Version 1: the supply finding only (the investment waits for a correction)."""
    ids = claim_ids_by_quote(body)
    return {
        "thesis_statement": THESIS,
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
                "statement": SUPPLY_FINDING,
                "claim_ids": [ids[SUPPLY_QUOTE]],
                "limitations": ["One filing only."],
                "open_questions": ["Are the volumes disclosed anywhere?"],
            }
        ],
    }


def limiting_skeptic(atlas: Atlas, company: Callable[[str], str]) -> tuple[ChatReply, ...]:
    """Records `SUPPLY_UPDATE` as a later Coherent document (`atlas sources import`, retained,
    so Memory points the Skeptic to it: memory-directed reading ticket 07);
    the Skeptic reads it and quotes it as a contradiction of every supporting Claim: it limits
    the supply agreement, and names both companies (so it passes the contradiction check for
    the supply Claim and for the investment Claim)."""
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
    if imported.returncode != 0:
        raise SystemExit(f"e2e: the supply update wasn't imported: {imported.stderr}")
    atlas.worker_pass()

    def reading(body: dict[str, Any]) -> JsonValue:
        sent = asked(body)
        [passage] = [p for p in sent["retrieved_data"] if LIMIT_QUOTE in p["text"]]
        start = passage["text"].index(LIMIT_QUOTE)
        return {
            "counterevidence": [
                {
                    "passage_id": passage["id"],
                    "kind": "contradiction",
                    "checklist_item": "second_sources",
                    "subject_company_id": company("coherent"),
                    "statement": "NVIDIA is no longer committed to buy from Coherent after 2027.",
                    "quote": LIMIT_QUOTE,
                    "quote_start": start,
                    "quote_end": start + len(LIMIT_QUOTE),
                    "epistemic_type": "company_claim",
                    "contradicts_claim_ids": [
                        c["claim_id"] for c in sent["request"]["supporting_claims"]
                    ],
                    "how": "limits",
                    "figure_name": None,
                    "figure_period": None,
                    "disproves_premise": None,
                }
            ]
        }

    # Its plan writes no query; what it reads is where Memory points.
    return ChatReply.json({"queries": []}), ChatReply.answer(reading)


# --- the Hypothesis -----------------------------------------------------------------------------


def build(atlas: Atlas, llm: FakeLiteLLM, searxng: FakeSearXNG) -> str:
    def company(slug: str) -> str:
        return atlas.company(slug)["id"]

    def post(path: str, body: dict[str, Any], expected: int) -> Any:
        response = atlas.api.post(path, json=body)
        if response.status_code != expected:
            raise SystemExit(f"e2e: POST {path} answered {response.status_code}: {response.text}")
        return response.json()

    common: dict[str, JsonValue] = {
        "object_name": None,
        "object_text": None,
        "product": None,
        "epistemic_type": "company_claim",
    }
    supply: dict[str, JsonValue] = common | {
        "subject_company_id": company("coherent"),
        "predicate": "supplies",
        "object_company_id": company("nvidia"),
        "product": "advanced lasers",
        "layer": "chip-laser",
        "quote": SUPPLY_QUOTE,
    }
    investment: dict[str, JsonValue] = common | {
        "subject_company_id": company("nvidia"),
        "predicate": "owns",
        "object_company_id": company("coherent"),
        "layer": "system",
        "quote": INVESTMENT_QUOTE,
        "epistemic_type": "direct_source_statement",
    }

    # The investigation, to its stop (the chained machine review of its Claims included).
    searxng.script(SUBSTRATE, SearchReply.of("inp-substrate-capacity"))
    searxng.script(SECOND_SOURCE, SearchReply.of("inp-laser-second-source"))
    queries: list[JsonValue] = [
        {"query": SUBSTRATE, "purpose": "InP substrate capacity"},
        {"query": SECOND_SOURCE, "purpose": "second sources"},
    ]
    llm.script_role("skeptic", *limiting_skeptic(atlas, company))
    llm.script_role("financial_analyst", ChatReply.json({"scenarios": []}, tokens=(1500, 200)))
    llm.script_chat(
        ChatReply.json({"queries": queries}, tokens=(900, 120)),
        ChatReply.answer(quoting(supply, investment), tokens=(9000, 700)),
        ChatReply.answer(card_editor, tokens=(3000, 400)),
        ChatReply.answer(reviewing, tokens=(800, 100)),
    )
    started = post(
        "/api/v1/investigations",
        {"theme": "photonics", "question": QUESTION, "seed_company_ids": [company("coherent")]},
        202,
    )
    atlas.worker_pass()
    investigation = atlas.get(f"/api/v1/investigations/{started['id']}")
    if investigation["status"] != "stopped" or investigation["research_card"] is None:
        raise SystemExit(f"e2e: the investigation didn't stop with a card: {investigation}")
    card_claims = {
        finding["claim_text"]: finding["claim_ids"]
        for finding in investigation["research_card"]["findings"]
    }

    # Saved as a Hypothesis; the Editor drafts version 1.
    saved = post("/api/v1/hypotheses", {"investigation_id": investigation["id"]}, 202)
    hypothesis_id: str = saved["id"]
    llm.script_chat(ChatReply.answer(hypothesis_editor, tokens=(4000, 600)))
    atlas.worker_pass()
    hypothesis = atlas.get(f"/api/v1/hypotheses/{hypothesis_id}")
    if hypothesis["draft_status"] != "drafted":
        raise SystemExit(f"e2e: the Hypothesis wasn't drafted: {hypothesis['draft_error']}")
    [finding] = hypothesis["versions"][0]["content"]["findings"]
    [supply_span] = finding["source_spans"]

    # A researcher's scenario on version 1.
    post(
        f"/api/v1/hypotheses/{hypothesis_id}/scenarios",
        {
            "version": 1,
            "as_of": SCENARIO_AS_OF,
            "note": "seeded by scripts/e2e.py",
            "assumptions": scenario_table(atlas, company("coherent"), supply_span),
        },
        201,
    )

    # Evidence-ready; the owner approves the supply edge; version 1 is published.
    post(f"/api/v1/hypotheses/{hypothesis_id}/transitions", {"to": "evidence_ready"}, 200)
    edges = atlas.get("/api/v1/relationships", limit=500)["items"]
    by_predicate = {edge["predicate"]: edge for edge in edges}
    if set(by_predicate) != {"supplies", "owns"}:
        raise SystemExit(f"e2e: expected the supplies and owns edges, got {edges}")
    post(
        f"/api/v1/relationships/{by_predicate['supplies']['id']}/review",
        {"review_state": "approved", "note": "seeded by scripts/e2e.py"},
        200,
    )
    post(f"/api/v1/hypotheses/{hypothesis_id}/publish-version", {"version": 1}, 200)

    # Version 2: a correction adding NVIDIA's investment, whose edge isn't approved.
    post(
        f"/api/v1/hypotheses/{hypothesis_id}/versions",
        {
            "based_on_version": 1,
            "note": "adds NVIDIA's investment in Coherent",
            "thesis_statement": THESIS_V2,
            "findings": [
                {"claim_text": SUPPLY_FINDING, "claim_ids": card_claims[SUPPLY_FINDING]},
                {
                    "claim_text": INVESTMENT_FINDING,
                    "claim_ids": card_claims[INVESTMENT_FINDING],
                    "limitations": ["The size, not the terms."],
                },
            ],
        },
        201,
    )
    gate = atlas.get(f"/api/v1/hypotheses/{hypothesis_id}/publish-gate")
    held = [(f["code"], f["relationship_ids"]) for f in gate["failures"]]
    if held != [("relationship_not_approved", [by_predicate["owns"]["id"]])]:
        raise SystemExit(f"e2e: version 2's gate isn't held by the owns edge alone: {gate}")
    return hypothesis_id


def scenario_table(atlas: Atlas, company_id: str, supply_span: dict[str, Any]) -> dict[str, Any]:
    """FY2026 revenue from the 10-K's XBRL, Coherent's share sourced from the supply
    Assertion, the rest estimated."""
    observations = atlas.get(
        f"/api/v1/companies/{company_id}/financial-observations",
        as_of=SCENARIO_AS_OF,
        concept=REVENUE,
        limit=500,
    )["items"]
    [revenue] = [
        each
        for each in observations
        if (each["period_start"], each["period_end"]) == ("2025-07-01", "2026-06-30")
    ]

    def guess(low: str, base: str, high: str) -> dict[str, str]:
        return {"kind": "estimated", "basis": "a guess", "low": low, "base": base, "high": high}

    return {
        "company_id": company_id,
        "product": "advanced lasers",
        "currency": "USD",
        "inputs": {
            "addressable_units": guess("8000000", "10000000", "12000000"),
            "company_share": {
                "kind": "sourced",
                "source": {"type": "assertion", "assertion_id": supply_span["assertion_id"]},
                "low": "0.2",
                "base": "0.25",
                "high": "0.3",
            },
            "downstream_unit_price": guess("900", "1000", "1100"),
            "bom_share": guess("0.15", "0.2", "0.25"),
            "operating_margin": guess("0.25", "0.3", "0.35"),
            "reported_revenue": {
                "kind": "sourced",
                "source": {"type": "xbrl_observation", "observation_id": revenue["id"]},
                "low": revenue["value"],
                "base": revenue["value"],
                "high": revenue["value"],
            },
        },
    }
