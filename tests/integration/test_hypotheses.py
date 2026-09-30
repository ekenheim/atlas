"""Hypotheses: an investigation's result saved as a versioned, falsifiable research object
(Phase 3-6a ticket 16; spec §5.6, §8.1; Phase 4 "Thesis lifecycle", "dossier export").

Seams: an investigation runs through `POST /api/v1/investigations` and single worker passes;
`POST /api/v1/hypotheses` saves it and a worker pass runs the Editor's draft; everything is
observed through `/api/v1` (the Hypothesis, its diff and export, runs' role calls, the audit
log through the database's own tables) and the requests the fakes received. The Source
Versions are the recorded Coherent EDGAR filings; Hindsight is the recorded fake, SearXNG the
scripted fake. LiteLLM is the scripted chat fake: **every role's answer is written here**
(the Investigator quotes the recorded Coherent 10-K; the Skeptic reads nothing, or quotes the
10-Q as counterevidence; the Editors cite the Claim IDs they are sent; the Reviewer, chained
after the investigation, confirms what it is sent). Nothing live is called.
"""

import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import sqlalchemy.exc
import yaml
from pydantic import JsonValue
from sqlalchemy import text

from tests.fakes.hindsight import RecordedHindsight
from tests.fakes.litellm import ChatReply, FakeLiteLLM
from tests.fakes.searxng import FakeSearXNG, SearchReply
from tests.fakes.serve import Served, serve
from tests.harness import THEMES, Atlas, at

QUESTION = "Who supplies the lasers in AI data-center optics, and to whom?"
SUBSTRATE = "indium phosphide substrate capacity expansion 2026"
SECOND_SOURCE = "InP laser second source qualification hyperscaler"
COHR_10K = "https://www.sec.gov/Archives/edgar/data/820318/000082031826000020/iivi-20260630.htm"
COHR_10Q = "https://www.sec.gov/Archives/edgar/data/820318/000082031826000013/iivi-20260331.htm"
# From the Coherent 10-Q's balance sheet (the recorded fixture's parsed text).
DILUTION_QUOTE = (
    "issued - 212,340,736 shares at March 31, 2026; 171,849,325 shares at June 30, 2025"
)
# From the Coherent FY2026 10-K (the recorded fixture's parsed text).
SUPPLY_QUOTE = (
    "we announced the expansion of our Sherman, Texas, manufacturing facility, entered into a"
    " strategic multi-year supply agreement with NVIDIA for advanced lasers and optical"
    " networking products"
)
INVESTMENT_QUOTE = "NVIDIA made a $2 billion investment in the Company"
SUPPLY_FINDING = "Coherent supplies NVIDIA with advanced lasers under a multi-year agreement."
INVESTMENT_FINDING = "NVIDIA has invested $2 billion in Coherent."
THESIS = (
    "Demand for advanced lasers in AI optics may outgrow qualified laser capacity, favouring"
    " suppliers with long-term agreements such as Coherent."
)
# The Bottlenecks mental model's content once Hindsight has refreshed it: the Scout's gaps.
GAPS = "Open gap: whether qualified InP laser capacity binds 800G optics supply in 2027."
TEN_K_ACCESSION = "0000820318-26-000020"  # Coherent FY2026, filed 2026-08-14
REVENUE = "RevenueFromContractWithCustomerExcludingAssessedTax"
SCENARIO_AS_OF = "2026-09-01T00:00:00Z"


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
    """Atlas with the template applied, the universe seeded and Coherent's filings ingested."""
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


def asked(body: dict[str, Any]) -> dict[str, Any]:
    """The user message of a chat request: `{"request": ..., "retrieved_data": [...]}`."""
    return json.loads(body["messages"][1]["content"])


def claim(**fields: JsonValue) -> dict[str, JsonValue]:
    return {
        "object_company_id": None,
        "object_name": None,
        "object_text": None,
        "product": None,
        "layer": "chip-laser",
        "epistemic_type": "company_claim",
        **fields,
    }


def supply(atlas: Atlas) -> dict[str, JsonValue]:
    return claim(
        subject_company_id=company_id(atlas, "coherent"),
        predicate="supplies",
        object_company_id=company_id(atlas, "nvidia"),
        product="advanced lasers",
        quote=SUPPLY_QUOTE,
    )


def investment(atlas: Atlas) -> dict[str, JsonValue]:
    return claim(
        subject_company_id=company_id(atlas, "nvidia"),
        predicate="owns",
        object_company_id=company_id(atlas, "coherent"),
        layer="system",
        quote=INVESTMENT_QUOTE,
        epistemic_type="direct_source_statement",
    )


def quoting(*claims: dict[str, JsonValue]) -> Callable[[dict[str, Any]], JsonValue]:
    """An Investigator answer proposing each claim whose quote a passage it was sent holds."""

    def respond(body: dict[str, Any]) -> JsonValue:
        passages = asked(body)["retrieved_data"]
        answered: list[JsonValue] = []
        for each in claims:
            quote = str(each["quote"])
            holding = [p for p in passages if quote in p["text"]]
            assert holding, f"no passage sent holds {quote!r}"
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


def claim_ids_by_quote(body: dict[str, Any]) -> dict[str, str]:
    """{quote: claim ID} of the Claims an Editor was sent (their quotes are retrieved data)."""
    sent = asked(body)
    claim_ids = {each["claim_id"] for each in sent["request"]["claims"]}
    return {each["text"]: each["id"] for each in sent["retrieved_data"] if each["id"] in claim_ids}


def card_editor(body: dict[str, Any]) -> JsonValue:
    """The research card: one finding per Claim it is sent."""
    ids = claim_ids_by_quote(body)
    findings: list[JsonValue] = [
        {
            "statement": SUPPLY_FINDING if quote == SUPPLY_QUOTE else INVESTMENT_FINDING,
            "claim_ids": [claim_id],
            "limitations": ["A company's own statement."],
            "open_questions": [],
        }
        for quote, claim_id in ids.items()
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
                "verdict": "confirmed",
                "direction": "as_proposed",
                "layer": "correct",
                "suggested_layer": None,
                "reasoning": "the quote states it",
            }
            for item in asked(body)["request"]["items"]
        ]
    }


def hypothesis_editor(
    *,
    falsifiers: list[JsonValue] | None = None,
    unresolved: list[JsonValue] | None = None,
    extra: list[dict[str, JsonValue]] | None = None,
) -> Callable[[dict[str, Any]], JsonValue]:
    """A Hypothesis draft with one finding per Claim it is sent (cited by ID), plus `extra`."""

    def respond(body: dict[str, Any]) -> JsonValue:
        ids = claim_ids_by_quote(body)
        findings: list[JsonValue] = [
            {
                "statement": SUPPLY_FINDING if quote == SUPPLY_QUOTE else INVESTMENT_FINDING,
                "claim_ids": [claim_id],
                "limitations": ["One filing only."],
                "open_questions": ["Are the volumes disclosed anywhere?"],
            }
            for quote, claim_id in ids.items()
        ]
        draft: dict[str, JsonValue] = {
            "thesis_statement": THESIS,
            "mechanism": {
                "demand_driver": "AI data-center optical interconnect deployments",
                "possible_constraint": "Qualified advanced-laser capacity",
                "economic_capture_question": None,
            },
            "measurable_predictions": ["Laser lead times stay elevated in 2027 filings"],
            "catalysts": ["New multi-year supply agreements"],
            "falsifiers": ["Verified laser capacity exceeds plausible demand"]
            if falsifiers is None
            else falsifiers,
            "required_evidence": ["An original document naming a second laser source"],
            "alternative_explanations": ["Inventory build-up mimics demand"],
            "unresolved_questions": ["Does NVIDIA qualify a second laser source?"]
            if unresolved is None
            else unresolved,
            "findings": [*findings, *(extra or [])],
        }
        return draft

    return respond


def finding_nothing(body: dict[str, Any]) -> JsonValue:
    """The Skeptic finding nothing: its plan chooses no query and no document, and its reading
    of what code's fallback then chose (pilot fix 06) proposes nothing."""
    if "catalog" in asked(body)["request"]:
        return {"queries": [], "documents": []}
    return {"counterevidence": []}


# Enough answers for the plan and every reading call (the unused ones are never asked for).
NOTHING_TO_READ = (ChatReply.answer(finding_nothing, tokens=(500, 50)),) * 8


def dilution_skeptic(atlas: Atlas) -> tuple[ChatReply, ...]:
    """The Skeptic reads the 10-Q and quotes its share count against every supporting Claim."""
    ten_q = atlas.version(COHR_10Q, "coherent")["id"]

    def reading(body: dict[str, Any]) -> JsonValue:
        sent = asked(body)
        [passage] = [p for p in sent["retrieved_data"] if DILUTION_QUOTE in p["text"]]
        start = passage["text"].index(DILUTION_QUOTE)
        return {
            "counterevidence": [
                {
                    "passage_id": passage["id"],
                    "checklist_item": "dilution_financing",
                    "subject_company_id": company_id(atlas, "coherent"),
                    "statement": "Coherent's issued share count rose in fiscal 2026.",
                    "quote": DILUTION_QUOTE,
                    "quote_start": start,
                    "quote_end": start + len(DILUTION_QUOTE),
                    "epistemic_type": "company_claim",
                    "contradicts_claim_ids": [
                        c["claim_id"] for c in sent["request"]["supporting_claims"]
                    ],
                    "disproves_premise": None,
                }
            ]
        }

    plan: dict[str, JsonValue] = {
        "queries": [],
        "documents": [{"source_version_id": ten_q, "checklist_item": "dilution_financing"}],
    }
    return ChatReply.json(plan), ChatReply.answer(reading)


def investigate(
    atlas: Atlas,
    llm: FakeLiteLLM,
    searxng: FakeSearXNG,
    *claims: dict[str, JsonValue],
    skeptic: tuple[ChatReply, ...] = NOTHING_TO_READ,
) -> dict[str, Any]:
    """Run an investigation of Coherent to its stop (with the chained relationship review)."""
    searxng.script(SUBSTRATE, SearchReply.of("inp-substrate-capacity"))
    searxng.script(SECOND_SOURCE, SearchReply.of("inp-laser-second-source"))
    queries: list[JsonValue] = [
        {"query": SUBSTRATE, "purpose": "InP substrate capacity"},
        {"query": SECOND_SOURCE, "purpose": "second sources"},
    ]
    # The Skeptic's and the Financial Analyst's jobs run in parallel, in either order: their
    # answers are scripted by role.
    # This investigation's Skeptic answers only: an earlier one's unused answers are dropped.
    llm.role_replies.pop("skeptic", None)
    llm.script_role("skeptic", *skeptic)
    llm.script_role("financial_analyst", ChatReply.json({"scenarios": []}, tokens=(1500, 200)))
    llm.script_chat(
        ChatReply.json({"queries": queries}, tokens=(900, 120)),
        ChatReply.answer(quoting(*claims), tokens=(9000, 700)),
        ChatReply.answer(card_editor, tokens=(3000, 400)),
        ChatReply.answer(reviewing, tokens=(800, 100)),
    )
    response = atlas.api.post(
        "/api/v1/investigations",
        json={
            "theme": "photonics",
            "question": QUESTION,
            "seed_company_ids": [company_id(atlas, "coherent")],
        },
    )
    assert response.status_code == 202, response.text
    atlas.worker_pass()
    found = atlas.get(f"/api/v1/investigations/{response.json()['id']}")
    assert found["status"] == "stopped", found["stop_detail"]
    return found


def save(atlas: Atlas, investigation_id: str) -> dict[str, Any]:
    response = atlas.api.post("/api/v1/hypotheses", json={"investigation_id": investigation_id})
    assert response.status_code == 202, response.text
    return response.json()


def drafted(
    atlas: Atlas,
    llm: FakeLiteLLM,
    searxng: FakeSearXNG,
    *claims: dict[str, JsonValue],
    skeptic: tuple[ChatReply, ...] = NOTHING_TO_READ,
    **editor: Any,
) -> dict[str, Any]:
    """An investigation saved as a Hypothesis, with the Editor's draft (version 1) written."""
    found = investigate(atlas, llm, searxng, *(claims or (supply(atlas),)), skeptic=skeptic)
    saved = save(atlas, found["id"])
    llm.script_chat(ChatReply.answer(hypothesis_editor(**editor), tokens=(4000, 600)))
    atlas.worker_pass()
    hypothesis = get(atlas, saved["id"])
    assert hypothesis["draft_status"] == "drafted", hypothesis["draft_error"]
    return hypothesis


def get(atlas: Atlas, hypothesis_id: str) -> dict[str, Any]:
    return atlas.get(f"/api/v1/hypotheses/{hypothesis_id}")


def move(atlas: Atlas, hypothesis_id: str, to: str, **body: Any) -> Any:
    return atlas.api.post(
        f"/api/v1/hypotheses/{hypothesis_id}/transitions", json={"to": to, **body}
    )


def publish(atlas: Atlas, hypothesis_id: str, version: int, **body: Any) -> Any:
    return atlas.api.post(
        f"/api/v1/hypotheses/{hypothesis_id}/publish-version", json={"version": version, **body}
    )


def correct(atlas: Atlas, hypothesis_id: str, **body: Any) -> Any:
    return atlas.api.post(f"/api/v1/hypotheses/{hypothesis_id}/versions", json=body)


def owner_review(atlas: Atlas, relationship_id: str, state: str) -> None:
    response = atlas.api.post(
        f"/api/v1/relationships/{relationship_id}/review", json={"review_state": state}
    )
    assert response.status_code == 200, response.text


def approve_relationships(atlas: Atlas) -> list[str]:
    """The owner approves every Relationship not yet approved; their IDs."""
    edges = atlas.get("/api/v1/relationships", limit=500)["items"]
    pending = [edge["id"] for edge in edges if edge["review_state"] != "approved"]
    for relationship_id in pending:
        owner_review(atlas, relationship_id, "approved")
    return pending


def audit_actions(atlas: Atlas, entity_type: str) -> list[str]:
    with atlas.engine.connect() as connection:
        return list(
            connection.execute(
                text("SELECT action FROM audit_event WHERE entity_type = :type ORDER BY id"),
                {"type": entity_type},
            ).scalars()
        )


# The Skeptic and the Financial Analyst run in parallel, in either order: compared in plan order.
PARALLEL_ORDER = {"skeptic": 0, "financial_analyst": 1}


def roles(llm: FakeLiteLLM) -> list[str]:
    """The roles of the chat requests, oldest first, with each run of consecutive Skeptic and
    Analyst requests in plan order (the Skeptic's first)."""
    ordered: list[str] = []
    run: list[str] = []
    for role in [*(body["metadata"]["role"] for body in llm.chat_requests()), None]:
        if role in PARALLEL_ORDER:
            run.append(role)
            continue
        ordered.extend(sorted(run, key=PARALLEL_ORDER.__getitem__))
        run = []
        if role is not None:
            ordered.append(role)
    return ordered


# --- the gate test: an investigation reaches a reviewable Hypothesis ------------------------------


def test_an_investigation_is_saved_as_a_reviewable_hypothesis_with_a_source_trail(
    atlas: Atlas, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    found = investigate(atlas, llm, searxng, supply(atlas))
    assert found["stop_reason"] == "answered"

    saved = save(atlas, found["id"])

    assert (saved["status"], saved["draft_status"], saved["versions"]) == ("draft", "queued", [])
    assert saved["investigation_id"] == found["id"]
    assert saved["theme_id"] == "photonics"
    assert saved["related_company_ids"] == [company_id(atlas, "coherent")]
    assert saved["author"] == "local-researcher"
    assert atlas.get(f"/api/v1/jobs/{saved['draft_job_id']}")["kind"] == "draft_hypothesis"

    # The Editor's draft: one finding cites the accepted Claim; one cites a lead, one nothing.
    lead_id = found["leads"][0]["lead_id"]
    unsupported: list[dict[str, JsonValue]] = [
        {
            "statement": "AXT is expanding InP substrate capacity.",
            "claim_ids": [lead_id],
            "limitations": [],
            "open_questions": [],
        },
        {
            "statement": "Coherent is the only qualified laser supplier.",
            "claim_ids": [],
            "limitations": [],
            "open_questions": [],
        },
    ]
    llm.script_chat(ChatReply.answer(hypothesis_editor(extra=unsupported), tokens=(4000, 600)))
    atlas.worker_pass()

    hypothesis = get(atlas, saved["id"])
    assert (hypothesis["draft_status"], hypothesis["latest_version"]) == ("drafted", 1)
    [version] = hypothesis["versions"]
    assert (version["version"], version["origin"], version["published"]) == (
        1,
        "editor_draft",
        False,
    )
    assert version["created_by"] == "atlas-editor"
    content = version["content"]
    assert content["thesis_statement"] == THESIS
    assert content["mechanism"] == {
        "demand_driver": "AI data-center optical interconnect deployments",
        "possible_constraint": "Qualified advanced-laser capacity",
        "economic_capture_question": None,
    }
    # Reviewable: at least one falsifier and one unresolved question.
    assert content["falsifiers"] == ["Verified laser capacity exceeds plausible demand"]
    assert content["unresolved_questions"] == ["Does NVIDIA qualify a second laser source?"]
    assert content["measurable_predictions"] == ["Laser lead times stay elevated in 2027 filings"]
    assert content["catalysts"] == ["New multi-year supply agreements"]
    assert content["required_evidence"] == ["An original document naming a second laser source"]
    assert content["alternative_explanations"] == ["Inventory build-up mimics demand"]
    # The source trail: the finding's span is the accepted Claim's, in the archived parse.
    [accepted] = atlas.get("/api/v1/claims", outcome="accepted")["items"]
    [finding] = content["findings"]
    assert finding["claim_text"] == SUPPLY_FINDING
    assert finding["claim_ids"] == [accepted["id"]]
    [span] = finding["source_spans"]
    ten_k = atlas.version(COHR_10K, "coherent")["id"]
    assert (span["assertion_id"], span["source_version_id"], span["quote"]) == (
        accepted["assertion_id"],
        ten_k,
        SUPPLY_QUOTE,
    )
    assert atlas.parsed(ten_k)[span["span_start"] : span["span_end"]] == SUPPLY_QUOTE
    assert finding["needs_review"] is True
    # No unsupported claim is promoted: they are recorded, never findings.
    assert content["unsupported_findings"] == [
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
    assert len(version["content_sha256"]) == 64
    # The Editor was sent the research card, the accepted Claims and their quotes as data.
    assert roles(llm) == [
        "scout",
        "investigator",
        "skeptic",
        "skeptic",  # its reading of what code's fallback chose (its plan chose nothing)
        "financial_analyst",
        "editor",
        "reviewer",
        "editor",
    ]
    assert content["contradictions"] == []
    assert finding["counterevidence_ids"] == []
    body = llm.chat_requests()[-1]
    sent = asked(body)
    assert sent["request"]["research_question"] == QUESTION
    assert [f["statement"] for f in sent["request"]["card_findings"]] == [SUPPLY_FINDING]
    assert sent["request"]["card_open_questions"] == [
        "Is InP substrate capacity a constraint for 2027?"
    ]
    assert [c["claim_id"] for c in sent["request"]["claims"]] == [accepted["id"]]
    assert [(q["id"], q["text"], q["trust"]) for q in sent["retrieved_data"]] == [
        (accepted["id"], SUPPLY_QUOTE, "low")
    ]
    # Provenance: the investigation's run and the draft's own run, finished with its tokens.
    provenance = version["provenance"]
    assert provenance["investigation_id"] == found["id"]
    assert provenance["investigation_run_id"] == found["run_id"]
    assert provenance["research_card_role_call_id"] == found["research_card"]["editor_role_call_id"]
    draft_run = hypothesis["draft_run_id"]
    assert provenance["draft_run_id"] == draft_run != found["run_id"]
    assert body["metadata"]["run_id"] == draft_run
    calls = atlas.get(f"/api/v1/runs/{draft_run}/role-calls")
    [call] = calls["role_calls"]
    assert (call["id"], call["role"], call["prompt_name"], call["status"]) == (
        provenance["editor_role_call_id"],
        "editor",
        "editor-hypothesis",
        "accepted",
    )
    assert (calls["tokens_in"], calls["tokens_out"]) == (4000, 600)
    assert audit_actions(atlas, "hypothesis") == ["hypothesis.created", "hypothesis.drafted"]
    assert audit_actions(atlas, "hypothesis_version") == ["hypothesis.version_drafted"]
    # A second worker pass drafts nothing again.
    atlas.worker_pass()
    assert len(get(atlas, saved["id"])["versions"]) == 1


def test_the_dossier_exports_as_json_and_markdown_with_citations_and_run_metadata(
    atlas: Atlas, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    hypothesis = drafted(atlas, llm, searxng)
    [version] = hypothesis["versions"]

    exported = atlas.get(f"/api/v1/hypotheses/{hypothesis['id']}/export")
    markdown = atlas.api.get(
        f"/api/v1/hypotheses/{hypothesis['id']}/export", params={"format": "markdown"}
    )

    assert (exported["format"], exported["format_version"]) == ("atlas.hypothesis-dossier", 1)
    assert exported["hypothesis_id"] == hypothesis["id"]
    assert exported["version"]["content_sha256"] == version["content_sha256"]
    assert [c["slug"] for c in exported["related_companies"]] == ["coherent"]
    [finding] = exported["findings"]
    assert (finding["claim_text"], finding["citations"]) == (SUPPLY_FINDING, [1])
    [citation] = exported["citations"]
    ten_k = atlas.version(COHR_10K, "coherent")
    [span] = version["content"]["findings"][0]["source_spans"]
    assert citation["number"] == 1
    assert citation["quote"] == SUPPLY_QUOTE
    assert (citation["assertion_id"], citation["source_version_id"]) == (
        span["assertion_id"],
        ten_k["id"],
    )
    assert (citation["span_start"], citation["span_end"]) == (span["span_start"], span["span_end"])
    assert citation["url"] == COHR_10K
    assert citation["source_tier"] == "A"
    assert at(citation["available_at"]) == at(ten_k["available_at"])
    assert citation["verification_status"] == citation["verification_status_now"] == "unreviewed"
    meta = exported["run_metadata"]
    assert meta["investigation"]["question"] == QUESTION
    assert meta["investigation"]["stop_reason"] == "answered"
    assert [run["kind"] for run in meta["runs"]] == ["investigation", "hypothesis_draft"]
    assert [run["id"] for run in meta["runs"]] == [
        version["provenance"]["investigation_run_id"],
        version["provenance"]["draft_run_id"],
    ]
    assert all(run["finished_at"] is not None for run in meta["runs"])
    assert meta["runs"][1]["tokens_in"] == 4000
    assert [(c["role"], c["prompt_name"], c["prompt_version"]) for c in meta["role_calls"]] == [
        ("editor", "editor", 4),
        ("editor", "editor-hypothesis", 3),
    ]
    assert all(len(c["prompt_sha256"]) == 64 for c in meta["role_calls"])

    assert markdown.status_code == 200
    assert markdown.headers["content-type"].startswith("text/markdown")
    doc = markdown.text
    assert doc.startswith(f"# Hypothesis: {THESIS}\n")
    for section in (
        "## Mechanism",
        "## Measurable predictions",
        "## Catalysts",
        "## Falsifiers",
        "## Required evidence",
        "## Alternative explanations",
        "## Unresolved questions",
        "## Findings",
        "## Citations",
        "## Run metadata",
    ):
        assert f"\n{section}\n" in doc, section
    assert "- Verified laser capacity exceeds plausible demand" in doc
    assert f"1. {SUPPLY_FINDING} [1]" in doc
    assert f'[1] "{SUPPLY_QUOTE}"' in doc
    assert f"<{COHR_10K}>" in doc
    assert version["content_sha256"] in doc
    assert version["provenance"]["draft_run_id"] in doc
    assert "- Economic capture question: not established" in doc

    missing = atlas.api.get(f"/api/v1/hypotheses/{hypothesis['id']}/export", params={"version": 9})
    assert missing.status_code == 404


# --- lifecycle and immutability -------------------------------------------------------------------


def test_the_lifecycle_is_enforced_and_a_published_version_is_immutable(
    atlas: Atlas, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    hypothesis = drafted(atlas, llm, searxng)
    hypothesis_id = hypothesis["id"]
    assert hypothesis["allowed_transitions"] == [
        "researching",
        "evidence_ready",
        "needs_more_evidence",
        "rejected",
    ]

    # `reviewed` only by publishing; nothing skips ahead; a draft can't be published.
    for to in ("reviewed", "paper_tracking", "closed"):
        refused = move(atlas, hypothesis_id, to)
        assert refused.status_code == 409, to
        assert refused.json()["error"]["code"] == "invalid_transition"
    early = publish(atlas, hypothesis_id, 1)
    assert early.status_code == 409
    assert early.json()["error"]["code"] == "invalid_transition"
    assert (
        move(atlas, hypothesis_id, "researching", note="checking second sources").status_code == 200
    )
    ready = move(atlas, hypothesis_id, "evidence_ready")
    assert ready.status_code == 200, ready.text
    assert ready.json()["status"] == "evidence_ready"
    assert publish(atlas, hypothesis_id, 2).status_code == 409  # not the latest version
    approve_relationships(atlas)

    published = publish(atlas, hypothesis_id, 1, note="owner approved")

    assert published.status_code == 200, published.text
    after = published.json()
    assert after["status"] == "reviewed"
    [version] = after["versions"]
    assert (version["published"], version["published_by"]) == (True, "local-researcher")
    assert at(after["first_published_at"]) == at(version["published_at"])
    assert version["content_sha256"] == hypothesis["versions"][0]["content_sha256"]
    assert [
        (t["from_status"], t["to_status"], t["action"], t["version"]) for t in after["transitions"]
    ] == [
        ("draft", "researching", "transition", None),
        ("researching", "evidence_ready", "transition", None),
        ("evidence_ready", "reviewed", "publish", 1),
    ]
    assert after["transitions"][0]["note"] == "checking second sources"
    again = publish(atlas, hypothesis_id, 1)
    assert again.status_code == 409
    # The database refuses to change or delete a published version, whoever asks.
    for statement in (
        "UPDATE hypothesis_version SET note = 'rewritten' WHERE id = :id",
        "UPDATE hypothesis_version SET content = content || '{\"falsifiers\": []}' WHERE id = :id",
        "UPDATE hypothesis_version SET published_at = now() WHERE id = :id",
        "DELETE FROM hypothesis_version WHERE id = :id",
    ):
        with pytest.raises(sqlalchemy.exc.DBAPIError, match="hypothesis"):
            with atlas.engine.begin() as connection:
                connection.execute(text(statement), {"id": version["id"]})
    with pytest.raises(sqlalchemy.exc.DBAPIError, match="insert-only"):
        with atlas.engine.begin() as connection:
            connection.execute(text("DELETE FROM hypothesis_transition"))
    assert get(atlas, hypothesis_id)["versions"] == after["versions"]
    # Paper tracking, then closed: final.
    assert move(atlas, hypothesis_id, "paper_tracking").status_code == 200
    assert move(atlas, hypothesis_id, "closed").json()["allowed_transitions"] == []
    assert move(atlas, hypothesis_id, "researching").status_code == 409
    assert audit_actions(atlas, "hypothesis") == [
        "hypothesis.created",
        "hypothesis.drafted",
        "hypothesis.transitioned",
        "hypothesis.transitioned",
        "hypothesis.transitioned",
        "hypothesis.transitioned",
    ]
    assert audit_actions(atlas, "hypothesis_version") == [
        "hypothesis.version_drafted",
        "hypothesis.version_published",
    ]


def test_the_publish_gate_needs_a_falsifier_an_unresolved_question_and_approved_relationships(
    atlas: Atlas, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    hypothesis = drafted(atlas, llm, searxng, falsifiers=[], unresolved=[])
    hypothesis_id = hypothesis["id"]
    assert move(atlas, hypothesis_id, "evidence_ready").status_code == 200
    # The version's one finding rests on the supply Assertion, which the chained machine
    # review made into a Relationship the owner hasn't decided on.
    [span] = hypothesis["versions"][0]["content"]["findings"][0]["source_spans"]
    [edge] = atlas.get("/api/v1/relationships")["items"]
    evidence = atlas.get(f"/api/v1/relationships/{edge['id']}")
    assert [e["assertion"]["id"] for e in evidence["evidence"]] == [span["assertion_id"]]
    assert edge["review_state"] != "approved"

    refused = publish(atlas, hypothesis_id, 1)

    assert refused.status_code == 422
    error = refused.json()["error"]
    assert error["code"] == "publish_gate_failed"
    assert "no_falsifier" in error["message"]
    assert "no_unresolved_question" in error["message"]
    assert [(f["code"], f["relationship_ids"], f["assertion_ids"]) for f in error["failures"]] == [
        ("no_falsifier", [], []),
        ("no_unresolved_question", [], []),
        ("relationship_not_approved", [edge["id"]], []),
    ]
    assert get(atlas, hypothesis_id)["versions"][0]["published"] is False
    assert atlas.get("/api/v1/snapshots", hypothesis_id=hypothesis_id)["items"] == []

    # A correction adds them as a new version; version 1 stays as it was.
    corrected = correct(
        atlas,
        hypothesis_id,
        based_on_version=1,
        note="add a falsifier and the open question",
        falsifiers=["A second laser source is qualified at NVIDIA"],
        unresolved_questions=["What share of Coherent's laser output goes to NVIDIA?"],
    )
    assert corrected.status_code == 201, corrected.text
    v1, v2 = corrected.json()["versions"]
    assert (v2["version"], v2["based_on_version"], v2["origin"], v2["note"]) == (
        2,
        1,
        "correction",
        "add a falsifier and the open question",
    )
    assert v2["content"]["thesis_statement"] == v1["content"]["thesis_statement"]
    assert v2["content"]["findings"] == v1["content"]["findings"]
    assert v1["content"]["falsifiers"] == []
    assert v2["content_sha256"] != v1["content_sha256"]
    assert publish(atlas, hypothesis_id, 1).status_code == 409  # only the latest
    # Still not approved: a rejected edge never is.
    owner_review(atlas, edge["id"], "rejected")
    still = publish(atlas, hypothesis_id, 2)
    assert still.status_code == 422
    [failure] = still.json()["error"]["failures"]
    assert (failure["code"], failure["relationship_ids"]) == (
        "relationship_not_approved",
        [edge["id"]],
    )
    assert f"{edge['id']} (rejected)" in failure["message"]
    owner_review(atlas, edge["id"], "approved")
    published = publish(atlas, hypothesis_id, 2)
    assert published.status_code == 200, published.text
    versions = published.json()["versions"]
    assert [v["published"] for v in versions] == [False, True]
    [snapshot] = atlas.get("/api/v1/snapshots", hypothesis_id=hypothesis_id)["items"]
    assert (snapshot["hypothesis_version"], snapshot["hypothesis_version_id"]) == (
        2,
        versions[1]["id"],
    )


def test_the_publish_gate_reads_what_publishing_would_meet_without_publishing(
    atlas: Atlas, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    hypothesis = drafted(atlas, llm, searxng, unresolved=[])
    hypothesis_id = hypothesis["id"]
    [edge] = atlas.get("/api/v1/relationships")["items"]

    def gate() -> dict[str, Any]:
        return atlas.get(f"/api/v1/hypotheses/{hypothesis_id}/publish-gate")

    def failures(read: dict[str, Any]) -> list[tuple[str, list[str], list[str]]]:
        return [(f["code"], f["relationship_ids"], f["assertion_ids"]) for f in read["failures"]]

    # A draft can't be published whatever the checks say; they are listed all the same.
    draft = gate()
    assert (draft["version"], draft["status"], draft["blocked"], draft["publishable"]) == (
        1,
        "draft",
        "status_not_publishable",
        False,
    )
    assert failures(draft) == [
        ("no_unresolved_question", [], []),
        ("relationship_not_approved", [edge["id"]], []),
    ]

    # Evidence-ready: only the checks hold it, exactly as a refused publish lists them.
    assert move(atlas, hypothesis_id, "evidence_ready").status_code == 200
    ready = gate()
    assert (ready["blocked"], ready["publishable"]) == (None, False)
    refused = publish(atlas, hypothesis_id, 1).json()["error"]["failures"]
    assert failures(ready) == failures({"failures": refused})
    assert atlas.get("/api/v1/snapshots", hypothesis_id=hypothesis_id)["items"] == []

    # Corrected and approved: publishable; once published, blocked as already published.
    corrected = correct(
        atlas,
        hypothesis_id,
        based_on_version=1,
        note="add the open question",
        unresolved_questions=["What share of Coherent's laser output goes to NVIDIA?"],
    )
    assert corrected.status_code == 201, corrected.text
    owner_review(atlas, edge["id"], "approved")
    assert gate() == {
        "version": 2,
        "status": "evidence_ready",
        "blocked": None,
        "publishable": True,
        "failures": [],
    }
    assert publish(atlas, hypothesis_id, 2).status_code == 200
    published = gate()
    assert (published["version"], published["status"], published["blocked"]) == (
        2,
        "reviewed",
        "already_published",
    )
    assert published["publishable"] is False
    missing = atlas.api.get(f"/api/v1/hypotheses/{uuid4()}/publish-gate")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"


# --- corrections and the diff ---------------------------------------------------------------------


def test_a_correction_is_a_new_version_and_the_diff_classifies_its_claims(
    atlas: Atlas, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    hypothesis = drafted(atlas, llm, searxng, supply(atlas), investment(atlas))
    hypothesis_id = hypothesis["id"]
    [v1] = hypothesis["versions"]
    by_text = {f["claim_text"]: f for f in v1["content"]["findings"]}
    assert set(by_text) == {SUPPLY_FINDING, INVESTMENT_FINDING}
    supply_claim = by_text[SUPPLY_FINDING]["claim_ids"][0]
    investment_claim = by_text[INVESTMENT_FINDING]["claim_ids"][0]
    investment_assertion = by_text[INVESTMENT_FINDING]["source_spans"][0]["assertion_id"]
    assert move(atlas, hypothesis_id, "evidence_ready").status_code == 200
    approve_relationships(atlas)
    assert publish(atlas, hypothesis_id, 1).status_code == 200
    # Later, the researcher disputes the investment Assertion.
    disputed = atlas.api.post(
        f"/api/v1/assertions/{investment_assertion}/review", json={"review_state": "disputed"}
    )
    assert disputed.status_code == 200, disputed.text

    # Findings in a correction must cite accepted Claims of the investigation.
    unsupported = correct(
        atlas,
        hypothesis_id,
        based_on_version=1,
        note="add a claim",
        findings=[{"claim_text": "Coherent sells to AMD.", "claim_ids": [investment_assertion]}],
    )
    assert unsupported.status_code == 422
    assert unsupported.json()["error"]["code"] == "unsupported_finding"
    stale = correct(atlas, hypothesis_id, based_on_version=2, note="x", catalysts=["y"])
    assert stale.status_code == 409

    corrected = correct(
        atlas,
        hypothesis_id,
        based_on_version=1,
        note="the investment is disputed; restate the supply agreement's scope",
        thesis_statement=THESIS.replace("may outgrow", "could outgrow"),
        findings=[
            {"claim_text": SUPPLY_FINDING, "claim_ids": [supply_claim]},
            {
                "claim_text": "Coherent's 10-K names a $2 billion NVIDIA investment.",
                "claim_ids": [investment_claim],
                "limitations": ["Disputed by the researcher."],
            },
            {
                "claim_text": "The supply agreement covers optical networking products too.",
                "claim_ids": [supply_claim],
            },
        ],
    )
    assert corrected.status_code == 201, corrected.text
    after = corrected.json()
    assert after["status"] == "reviewed"  # a correction doesn't change the status
    assert [v["published"] for v in after["versions"]] == [True, False]
    assert after["versions"][0] == get(atlas, hypothesis_id)["versions"][0]

    diff = atlas.get(f"/api/v1/hypotheses/{hypothesis_id}/diff")

    assert (diff["from_version"], diff["to_version"]) == (1, 2)
    assert (diff["from_sha256"], diff["to_sha256"]) == (
        v1["content_sha256"],
        after["versions"][1]["content_sha256"],
    )
    changes = {claim["claim_text"]: claim["change"] for claim in diff["claims"]}
    assert changes == {
        SUPPLY_FINDING: "unchanged",
        INVESTMENT_FINDING: "contradicted",
        "Coherent's 10-K names a $2 billion NVIDIA investment.": "new",
        "The supply agreement covers optical networking products too.": "new",
    }
    [contradicted] = [c for c in diff["claims"] if c["change"] == "contradicted"]
    assert contradicted["contradictions"] == [
        {
            "assertion_id": investment_assertion,
            "verification_status": "disputed",
            "counterevidence_id": None,
        }
    ]
    assert diff["counts"] == {"new": 2, "contradicted": 1, "unchanged": 1, "removed": 0}
    assert diff["fields_changed"] == ["thesis_statement"]
    # A claim dropped without a contradiction is `removed`.
    third = correct(
        atlas,
        hypothesis_id,
        based_on_version=2,
        note="drop the scope claim",
        findings=[{"claim_text": SUPPLY_FINDING, "claim_ids": [supply_claim]}],
    )
    assert third.status_code == 201, third.text
    later = atlas.get(f"/api/v1/hypotheses/{hypothesis_id}/diff", from_version=2, to_version=3)
    assert later["counts"] == {"new": 0, "contradicted": 1, "unchanged": 1, "removed": 1}
    wrong = atlas.api.get(
        f"/api/v1/hypotheses/{hypothesis_id}/diff", params={"from_version": 3, "to_version": 1}
    )
    assert wrong.status_code == 422
    assert audit_actions(atlas, "hypothesis_version") == [
        "hypothesis.version_drafted",
        "hypothesis.version_published",
        "hypothesis.corrected",
        "hypothesis.version_created",
    ]


# --- saving: refusals and failures ----------------------------------------------------------------


def test_saving_needs_a_stopped_investigation_with_a_research_card(
    atlas: Atlas, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    running = atlas.api.post(
        "/api/v1/investigations",
        json={
            "theme": "photonics",
            "question": QUESTION,
            "seed_company_ids": [company_id(atlas, "coherent")],
        },
    ).json()
    cases = [
        (running["id"], 409),
        ("00000000-0000-4000-8000-000000000000", 404),
    ]
    for investigation_id, status in cases:
        response = atlas.api.post("/api/v1/hypotheses", json={"investigation_id": investigation_id})
        assert response.status_code == status, response.text
    # Stopped with a card with no finding (the Investigator accepted nothing): nothing to save.
    searxng.script(SUBSTRATE, SearchReply.of("inp-substrate-capacity"))
    llm.script_chat(
        ChatReply.json({"queries": [{"query": SUBSTRATE, "purpose": None}]}),
        ChatReply.json({"claims": []}),  # nothing accepted: the Skeptic has nothing to challenge
        # The Editor still writes a card, with no finding (pilot fix 01).
        ChatReply.json({"findings": [], "open_questions": [], "verdict": "needs_review"}),
    )
    atlas.worker_pass()
    empty = atlas.get(f"/api/v1/investigations/{running['id']}")
    assert empty["stop_reason"] == "no_new_independent_evidence"
    refused = atlas.api.post("/api/v1/hypotheses", json={"investigation_id": running["id"]})
    assert refused.status_code == 409
    assert empty["research_card"]["findings"] == []
    assert "without a research card finding" in refused.json()["error"]["message"]

    found = investigate(atlas, llm, searxng, supply(atlas))
    saved = save(atlas, found["id"])
    twice = atlas.api.post("/api/v1/hypotheses", json={"investigation_id": found["id"]})
    assert twice.status_code == 409
    assert saved["id"] in twice.json()["error"]["message"]
    missing = atlas.api.get("/api/v1/hypotheses/00000000-0000-4000-8000-000000000000")
    assert missing.status_code == 404
    listed = atlas.get("/api/v1/hypotheses", theme_id="photonics")
    assert [h["id"] for h in listed["items"]] == [saved["id"]]
    assert atlas.get("/api/v1/hypotheses", status="reviewed")["items"] == []


def test_a_draft_the_editor_keeps_failing_is_marked_failed_with_nothing_invented(
    atlas: Atlas, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    found = investigate(atlas, llm, searxng, supply(atlas))
    saved = save(atlas, found["id"])
    # Three attempts, each a call and its repair, all malformed: quarantined each time.
    llm.script_chat(*[ChatReply.text("A thesis, in prose.") for _ in range(6)])

    atlas.worker_pass()

    hypothesis = get(atlas, saved["id"])
    assert hypothesis["draft_status"] == "failed"
    assert "RoleOutputQuarantined" in hypothesis["draft_error"]
    assert hypothesis["versions"] == []
    calls = atlas.get(f"/api/v1/runs/{hypothesis['draft_run_id']}/role-calls")
    assert [c["status"] for c in calls["role_calls"]] == ["quarantined"] * 3
    with atlas.engine.connect() as connection:
        finished = connection.execute(
            text("SELECT finished_at FROM run WHERE id = :id"), {"id": hypothesis["draft_run_id"]}
        ).scalar_one()
    assert finished is not None
    assert move(atlas, saved["id"], "evidence_ready").status_code == 409


def test_without_litellm_a_hypothesis_is_not_saved(
    database_url: str, tmp_path: Path, hindsight: tuple[RecordedHindsight, Served]
) -> None:
    atlas = Atlas(database_url, tmp_path, hindsight[1].url)

    response = atlas.api.post(
        "/api/v1/hypotheses", json={"investigation_id": "00000000-0000-4000-8000-000000000000"}
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "hypotheses_not_configured"
    atlas.engine.dispose()


# --- the Skeptic's counterevidence (ticket 15) ----------------------------------------------------


def test_the_skeptic_s_counterevidence_reaches_the_hypothesis_as_contradictions(
    atlas: Atlas, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    found = investigate(atlas, llm, searxng, supply(atlas), skeptic=dilution_skeptic(atlas))
    assert found["stop_reason"] == "needs_review"  # the card's finding is contradicted
    [against] = found["research_card"]["contradictions"]
    assert against["independent"] is True
    saved = save(atlas, found["id"])
    llm.script_chat(ChatReply.answer(hypothesis_editor(), tokens=(4000, 600)))

    atlas.worker_pass()

    hypothesis = get(atlas, saved["id"])
    [version] = hypothesis["versions"]
    content = version["content"]
    # The version carries the card's contradictions; its finding lists the counterevidence
    # against its Claim, and needs review.
    assert content["contradictions"] == found["research_card"]["contradictions"]
    [finding] = content["findings"]
    assert finding["counterevidence_ids"] == [against["counterevidence_id"]]
    assert finding["needs_review"] is True
    # The Editor was sent them (the quote as low-trust data), never as citable Claims.
    sent = asked(llm.chat_requests()[-1])
    [contradiction] = sent["request"]["contradictions"]
    assert (contradiction["counterevidence_id"], contradiction["checklist_item"]) == (
        against["counterevidence_id"],
        "dilution_financing",
    )
    assert contradiction["independent"] is True
    quoted = {each["id"]: each["text"] for each in sent["retrieved_data"]}
    assert quoted[against["counterevidence_id"]] == DILUTION_QUOTE
    assert against["counterevidence_id"] not in [c["claim_id"] for c in sent["request"]["claims"]]
    # A correction keeps them, and re-resolves its findings' counterevidence.
    [accepted] = atlas.get("/api/v1/claims", outcome="accepted")["items"]
    corrected = correct(
        atlas,
        saved["id"],
        based_on_version=1,
        findings=[{"claim_text": SUPPLY_FINDING, "claim_ids": [accepted["id"]]}],
        note="restated",
    )
    assert corrected.status_code == 201, corrected.text
    second = get(atlas, saved["id"])["versions"][-1]["content"]
    assert second["contradictions"] == content["contradictions"]
    assert second["findings"][0]["counterevidence_ids"] == [against["counterevidence_id"]]
    # The dossier shows them.
    markdown = atlas.api.get(
        f"/api/v1/hypotheses/{saved['id']}/export", params={"format": "markdown"}
    ).text
    assert "\n## Contradictions (the Skeptic's counterevidence)\n" in markdown
    assert f'"{DILUTION_QUOTE}"' in markdown
    assert f"Contradicted by independent counterevidence: `{against['counterevidence_id']}`" in (
        markdown
    )


# --- the Research Snapshot (ticket 20) ------------------------------------------------------------


def canonical(value: Any) -> bytes:
    """Canonical JSON (spec §5.7's content-addressed object): sorted keys, no spaces, UTF-8."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def snapshots(atlas: Atlas, hypothesis_id: str) -> list[dict[str, Any]]:
    return atlas.get("/api/v1/snapshots", hypothesis_id=hypothesis_id)["items"]


def fy2026_revenue(atlas: Atlas) -> dict[str, Any]:
    """Coherent's FY2026 revenue as of the scenario's cutoff (from the 10-K's XBRL)."""
    observations = atlas.get(
        f"/api/v1/companies/{company_id(atlas, 'coherent')}/financial-observations",
        as_of=SCENARIO_AS_OF,
        concept=REVENUE,
        limit=500,
    )["items"]
    [revenue] = [
        each
        for each in observations
        if (each["period_start"], each["period_end"]) == ("2025-07-01", "2026-06-30")
    ]
    assert revenue["accession"] == TEN_K_ACCESSION
    return revenue


def researcher_scenario(atlas: Atlas, hypothesis_id: str) -> dict[str, Any]:
    """A researcher's scenario on version 1: sourced FY2026 revenue, the rest estimated."""
    revenue = fy2026_revenue(atlas)

    def guess(low: str, base: str, high: str) -> dict[str, str]:
        return {"kind": "estimated", "basis": "a guess", "low": low, "base": base, "high": high}

    table = {
        "company_id": company_id(atlas, "coherent"),
        "product": "advanced lasers",
        "currency": "USD",
        "inputs": {
            "addressable_units": guess("8000000", "10000000", "12000000"),
            "company_share": guess("0.2", "0.25", "0.3"),
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
    response = atlas.api.post(
        f"/api/v1/hypotheses/{hypothesis_id}/scenarios",
        json={"version": 1, "as_of": SCENARIO_AS_OF, "assumptions": table},
    )
    assert response.status_code == 201, response.text
    [scenario] = response.json()["items"]
    return scenario


def test_publishing_freezes_a_research_snapshot_of_what_the_version_was_built_from(
    atlas: Atlas,
    llm: FakeLiteLLM,
    searxng: FakeSearXNG,
    hindsight: tuple[RecordedHindsight, Served],
) -> None:
    # Hindsight has refreshed the Bottlenecks model: the Scout is sent its content as gaps.
    hindsight[0].apply_refresh("bottlenecks", GAPS, [], refreshed_at=at("2026-09-01T06:30:00Z"))
    hypothesis = drafted(atlas, llm, searxng, supply(atlas), skeptic=dilution_skeptic(atlas))
    hypothesis_id = hypothesis["id"]
    [version] = hypothesis["versions"]
    scenario = researcher_scenario(atlas, hypothesis_id)
    assert move(atlas, hypothesis_id, "evidence_ready").status_code == 200
    [edge_id] = approve_relationships(atlas)
    assert snapshots(atlas, hypothesis_id) == []

    published = publish(atlas, hypothesis_id, 1)

    assert published.status_code == 200, published.text
    [published_version] = published.json()["versions"]
    [record] = snapshots(atlas, hypothesis_id)
    snapshot = atlas.get(f"/api/v1/snapshots/{record['id']}")
    content = snapshot["content"]
    # Content-addressed: the archived object is the snapshot's canonical JSON, and its hash.
    frozen = canonical(content)
    sha256 = hashlib.sha256(frozen).hexdigest()
    assert (snapshot["verified"], snapshot["sha256"], snapshot["byte_size"]) == (
        True,
        sha256,
        len(frozen),
    )
    assert snapshot["object_uri"] == f"archive://snapshots/sha256/{sha256}"
    assert (atlas.archive / "snapshots" / "sha256" / sha256).read_bytes() == frozen
    assert {k: v for k, v in snapshot.items() if k not in ("verified", "content")} == record
    assert (record["hypothesis_version"], record["hypothesis_version_id"]) == (1, version["id"])
    assert record["created_by"] == "local-researcher"
    # The version and its cutoff.
    investigation = atlas.get(f"/api/v1/investigations/{hypothesis['investigation_id']}")
    assert content["format"] == "atlas.research_snapshot.v1"
    frozen_version = content["hypothesis"]
    assert (frozen_version["id"], frozen_version["version"], frozen_version["version_id"]) == (
        hypothesis_id,
        1,
        version["id"],
    )
    assert frozen_version["content_sha256"] == version["content_sha256"]
    assert frozen_version["published_by"] == "local-researcher"
    assert at(frozen_version["published_at"]) == at(published_version["published_at"])
    assert (
        at(content["cutoff"]["as_of"])
        == at(investigation["request"]["as_of_utc"])
        == at(record["as_of"])
    )
    assert content["cutoff"]["question"] == QUESTION
    # The Source Versions considered: the 10-K the Investigator read, the 10-Q the Skeptic
    # read, the companyfacts the scenario's revenue came from; each with its hashes and
    # availability as the ledger has them.
    ten_k = atlas.version(COHR_10K, "coherent")
    ten_q = atlas.version(COHR_10Q, "coherent")
    revenue = fy2026_revenue(atlas)
    companyfacts = atlas.get(f"/api/v1/source-versions/{revenue['source_version_id']}")
    considered = {each["id"]: each for each in content["source_versions"]}
    assert set(considered) == {ten_k["id"], ten_q["id"], companyfacts["id"]}
    for ledger in (ten_k, ten_q, companyfacts):
        frozen_source = considered[ledger["id"]]
        for field in ("raw_sha256", "content_sha256", "available_at_basis"):
            assert frozen_source[field] == ledger[field], field
        assert at(frozen_source["available_at"]) == at(ledger["available_at"])
    # Memory exactly as returned to the run: the Scout's gaps; and the sections a recall chose
    # for the Investigator (Atlas keeps the choice, not the recall's text).
    [scout_call] = [c for c in content["role_calls"] if c["role"] == "scout"]
    assert content["memory"]["used"] is True
    assert content["memory"]["items"] == [
        {
            "role_call_id": scout_call["id"],
            "role": "scout",
            "id": "bottlenecks",
            "source": "mental-model:bottlenecks",
            "text": GAPS,
        }
    ]
    recalled = content["memory"]["recall_selections"]
    assert recalled
    assert all("recall" in each["selected_by"] for each in recalled)
    # Since pilot fix 10 the passage budget is spread across the documents taken, so the
    # recall's hits in the 10-Q get a share beside the 10-K's.
    assert {(each["source_version_id"], each["question"]) for each in recalled} == {
        (ten_k["id"], QUESTION),
        (ten_q["id"], QUESTION),
    }
    # The Assertions with their spans: the finding's and the counterevidence's.
    by_predicate = {each["predicate"]: each for each in content["assertions"]}
    assert set(by_predicate) == {"supplies", "counterevidence"}
    [span] = version["content"]["findings"][0]["source_spans"]
    backing = by_predicate["supplies"]
    assert (backing["id"], backing["source_version_id"], backing["quote"]) == (
        span["assertion_id"],
        ten_k["id"],
        SUPPLY_QUOTE,
    )
    assert atlas.parsed(ten_k["id"])[backing["span_start"] : backing["span_end"]] == SUPPLY_QUOTE
    assert backing["relationship_id"] == edge_id
    against = by_predicate["counterevidence"]
    assert (against["source_version_id"], against["quote"]) == (ten_q["id"], DILUTION_QUOTE)
    assert atlas.parsed(ten_q["id"])[against["span_start"] : against["span_end"]] == (
        DILUTION_QUOTE
    )
    # The Relationship it depends on, with the owner's approval.
    [edge] = content["relationships"]
    assert (edge["id"], edge["review_state"], edge["reviewed_by"]) == (
        edge_id,
        "approved",
        "local-researcher",
    )
    assert edge["supporting_assertion_ids"] == [span["assertion_id"]]
    # The scenario and the financial dataset its inputs cite.
    [frozen_scenario] = content["scenarios"]
    assert frozen_scenario["id"] == scenario["id"]
    assert frozen_scenario["assumptions_sha256"] == scenario["assumptions_sha256"]
    assert frozen_scenario["outputs_sha256"] == scenario["outputs_sha256"]
    assert frozen_scenario["outputs"] == scenario["outputs_json"]
    outputs_sha256 = hashlib.sha256(frozen_scenario["outputs"].encode()).hexdigest()
    assert outputs_sha256 == scenario["outputs_sha256"]
    dataset = content["financial_dataset"]
    [observation] = dataset["observations"]
    assert (observation["id"], observation["accession"], observation["value"]) == (
        revenue["id"],
        TEN_K_ACCESSION,
        revenue["value"],
    )
    assert dataset["sha256"] == hashlib.sha256(canonical(dataset["observations"])).hexdigest()
    # Prompts and models: every role call behind the version, its prompt version and hash,
    # and the model each attempt was routed to.
    assert sorted((c["role"], c["prompt_name"]) for c in content["role_calls"]) == [
        ("editor", "editor"),
        ("editor", "editor-hypothesis"),
        ("financial_analyst", "financial-analyst"),
        ("investigator", "investigator"),
        ("reviewer", "reviewer"),
        ("scout", "scout"),
        ("skeptic", "skeptic"),
        ("skeptic", "skeptic-plan"),
    ]
    recorded = atlas.get(f"/api/v1/runs/{investigation['run_id']}/role-calls")["role_calls"]
    frozen_calls = {c["id"]: c for c in content["role_calls"]}
    for call in recorded:
        frozen_call = frozen_calls[call["id"]]
        assert (frozen_call["prompt_version"], frozen_call["prompt_sha256"]) == (
            call["prompt_version"],
            call["prompt_sha256"],
        )
        assert [a["response_model"] for a in frozen_call["attempts"]] == [
            a["response_model"] for a in call["attempts"]
        ]
    assert sorted(run["kind"] for run in content["runs"]) == [
        "hypothesis_draft",
        "investigation",
        "relationship_review",
    ]
    assert content["hindsight"]["versions"] == ["0.10.1"]  # the recorded server's version
    # The outputs: the version's content as published.
    assert content["outputs"] == {
        "content": version["content"],
        "content_sha256": version["content_sha256"],
    }
    # Audited with the hash, and counted.
    with atlas.engine.connect() as connection:
        events = connection.execute(
            text(
                "SELECT action, entity_id, new_hash FROM audit_event"
                " WHERE entity_type = 'research_snapshot'"
            )
        ).all()
    assert [tuple(event) for event in events] == [
        ("research_snapshot.created", record["id"], sha256)
    ]
    assert atlas.metrics()[("atlas_research_snapshots_total", frozenset())] == 1


def test_a_published_snapshot_can_t_be_altered(
    atlas: Atlas, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    hypothesis = drafted(atlas, llm, searxng)
    hypothesis_id = hypothesis["id"]
    assert move(atlas, hypothesis_id, "evidence_ready").status_code == 200
    approve_relationships(atlas)
    assert publish(atlas, hypothesis_id, 1).status_code == 200
    [record] = snapshots(atlas, hypothesis_id)
    before = atlas.get(f"/api/v1/snapshots/{record['id']}")

    # The database refuses to change or remove a snapshot, whoever asks.
    for statement in (
        "UPDATE research_snapshot SET sha256 = repeat('0', 64) WHERE id = :id",
        "UPDATE research_snapshot SET created_by = 'someone-else' WHERE id = :id",
        "DELETE FROM research_snapshot WHERE id = :id",
        "TRUNCATE research_snapshot CASCADE",
    ):
        with pytest.raises(sqlalchemy.exc.DBAPIError, match="insert-only"):
            with atlas.engine.begin() as connection:
                connection.execute(text(statement), {"id": record["id"]})
    # Nor snapshots an unpublished version.
    corrected = correct(atlas, hypothesis_id, based_on_version=1, note="later", catalysts=["x"])
    assert corrected.status_code == 201, corrected.text
    unpublished = corrected.json()["versions"][1]["id"]
    with pytest.raises(sqlalchemy.exc.DBAPIError, match="published version"):
        with atlas.engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO research_snapshot (id, hypothesis_id, hypothesis_version_id,"
                    " sha256, object_uri, byte_size, as_of, created_by) VALUES"
                    " (gen_random_uuid(), :hypothesis, :version, :sha, :uri, 1, now(), 'x')"
                ),
                {
                    "hypothesis": hypothesis_id,
                    "version": unpublished,
                    "sha": "0" * 64,
                    "uri": f"archive://snapshots/sha256/{'0' * 64}",
                },
            )
    assert snapshots(atlas, hypothesis_id) == [record]

    # Every read re-hashes the archived object: an altered one is an integrity error.
    path = atlas.archive / "snapshots" / "sha256" / record["sha256"]
    original = path.read_bytes()
    altered = original.replace(
        b'"published_by":"local-researcher"', b'"published_by":"someone-else"'
    )
    assert altered != original
    path.chmod(0o644)
    path.write_bytes(altered)
    tampered = atlas.api.get(f"/api/v1/snapshots/{record['id']}")
    assert tampered.status_code == 500
    error = tampered.json()["error"]
    assert error["code"] == "snapshot_integrity_failed"
    assert "altered" in error["message"]
    assert "someone-else" not in tampered.text
    path.unlink()
    missing = atlas.api.get(f"/api/v1/snapshots/{record['id']}")
    assert missing.status_code == 500
    assert missing.json()["error"]["code"] == "snapshot_integrity_failed"
    assert "missing" in missing.json()["error"]["message"]
    # Restored byte for byte, it verifies again.
    path.write_bytes(original)
    assert atlas.get(f"/api/v1/snapshots/{record['id']}") == before
    assert atlas.api.get(f"/api/v1/snapshots/{uuid4()}").status_code == 404
