"""Proposed updates (Phase 3-6a ticket 21; spec §5.6, §5.7 "Contradiction flow", Phase 6a
gate "a later contradictory source leaves it untouched").

Seams: a Hypothesis is investigated, drafted, approved and published through `/api/v1` and
single worker passes (as in test_hypotheses); later Evidence arrives the way it does in
production: a re-run ingest of revised recorded EDGAR bytes, a hand-imported document
(`atlas sources import`) with the owner's Assertion superseding a cited one, the owner's
rejection of an edge, a later investigation's Skeptic (reading a hand-shaped later
statement, imported by hand). Everything is observed through
`/api/v1` (proposed updates, the Hypothesis, its snapshot) and, for what must not change, the
database rows and the archived bytes themselves. Hindsight is the recorded fake, SearXNG and
LiteLLM the scripted fakes; nothing live is called.
"""

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import yaml
from pydantic import JsonValue
from sqlalchemy import text

from tests.fakes.hindsight import RecordedHindsight
from tests.fakes.litellm import ChatReply, FakeLiteLLM
from tests.fakes.searxng import FakeSearXNG, SearchReply
from tests.fakes.serve import Served, serve
from tests.harness import EDGAR_FIXTURES, THEMES, Atlas

QUESTION = "Who supplies the lasers in AI data-center optics, and to whom?"
SUBSTRATE = "indium phosphide substrate capacity expansion 2026"
SECOND_SOURCE = "InP laser second source qualification hyperscaler"
COHR_10K = "https://www.sec.gov/Archives/edgar/data/820318/000082031826000020/iivi-20260630.htm"
COHR_10Q = "https://www.sec.gov/Archives/edgar/data/820318/000082031826000013/iivi-20260331.htm"
# From the Coherent 10-Q's balance sheet (the recorded fixture's parsed text).
DILUTION_QUOTE = (
    "issued - 212,340,736 shares at March 31, 2026; 171,849,325 shares at June 30, 2025"
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
# From the Coherent FY2026 10-K (the recorded fixture's parsed text).
SUPPLY_QUOTE = (
    "we announced the expansion of our Sherman, Texas, manufacturing facility, entered into a"
    " strategic multi-year supply agreement with NVIDIA for advanced lasers and optical"
    " networking products"
)
SUPPLY_FINDING = "Coherent supplies NVIDIA with advanced lasers under a multi-year agreement."
THESIS = (
    "Demand for advanced lasers in AI optics may outgrow qualified laser capacity, favouring"
    " suppliers with long-term agreements such as Coherent."
)
# A later statement, in a document the owner imports by hand.
LATER_ORIGIN = "https://investors.example.com/news/2026-09-21-nvidia-agreement"
LATER_QUOTE = "Coherent and NVIDIA ended their multi-year laser supply agreement"


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
    from an editable copy of the recorded EDGAR fixtures (so a test can revise a filing)."""
    started = Atlas(
        database_url,
        tmp_path,
        hindsight[1].url,
        litellm.url,
        themes_config=themes,
        searxng_url=searxng_served.url,
        investigator_passages_per_call=50,
    )
    started.fixtures = tmp_path / "edgar"
    shutil.copytree(EDGAR_FIXTURES, started.fixtures)
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


# --- helpers: an investigation published as a Hypothesis ---------------------------------------


def company_id(atlas: Atlas, slug: str) -> str:
    return atlas.company(slug)["id"]


def asked(body: dict[str, Any]) -> dict[str, Any]:
    """The user message of a chat request: `{"request": ..., "retrieved_data": [...]}`."""
    return json.loads(body["messages"][1]["content"])


def supply(atlas: Atlas) -> dict[str, JsonValue]:
    return {
        "subject_company_id": company_id(atlas, "coherent"),
        "predicate": "supplies",
        "object_company_id": company_id(atlas, "nvidia"),
        "object_name": None,
        "object_text": None,
        "product": "advanced lasers",
        "layer": "chip-laser",
        "epistemic_type": "company_claim",
        "quote": SUPPLY_QUOTE,
    }


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


def claim_ids(body: dict[str, Any]) -> list[str]:
    """The Claims an Editor was sent."""
    return [each["claim_id"] for each in asked(body)["request"]["claims"]]


def card_editor(body: dict[str, Any]) -> JsonValue:
    findings: list[JsonValue] = [
        {
            "statement": SUPPLY_FINDING,
            "claim_ids": [claim_id],
            "limitations": ["A company's own statement."],
            "open_questions": [],
        }
        for claim_id in claim_ids(body)
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
    findings: list[JsonValue] = [
        {
            "statement": SUPPLY_FINDING,
            "claim_ids": [claim_id],
            "limitations": ["One filing only."],
            "open_questions": ["Are the volumes disclosed anywhere?"],
        }
        for claim_id in claim_ids(body)
    ]
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
        "findings": findings,
    }


def finding_nothing(body: dict[str, Any]) -> JsonValue:
    """The Skeptic finding nothing: its plan chooses no query and no document, and its reading
    of what code's fallback then chose (pilot fix 06) proposes nothing."""
    if "catalog" in asked(body)["request"]:
        return {"queries": [], "documents": []}
    return {"counterevidence": []}


# Enough answers for the plan and every reading call (the unused ones are never asked for).
NOTHING_TO_READ = (ChatReply.answer(finding_nothing, tokens=(500, 50)),) * 8


def limiting_skeptic(atlas: Atlas) -> tuple[ChatReply, ...]:
    """Records `SUPPLY_UPDATE` as a later Coherent document (`atlas sources import`, retained);
    the Skeptic reads it and the 10-Q, and proposes two contradictions of every supporting
    Claim: the later statement, which limits the supply agreement and names both its parties,
    and the 10-Q's share count."""
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
    update = json.loads(imported.stdout)["source_version_id"]
    ten_q = atlas.version(COHR_10Q, "coherent")["id"]

    def reading(body: dict[str, Any]) -> JsonValue:
        sent = asked(body)
        [passage] = [p for p in sent["retrieved_data"] if LIMIT_QUOTE in p["text"]]
        [dilution] = [p for p in sent["retrieved_data"] if DILUTION_QUOTE in p["text"]]
        start = passage["text"].index(LIMIT_QUOTE)
        return {
            "counterevidence": [
                {
                    "passage_id": passage["id"],
                    "kind": "contradiction",
                    "checklist_item": "second_sources",
                    "subject_company_id": company_id(atlas, "coherent"),
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
                },
                # The 10-Q's share count, as the pilot's Skeptic proposed such rows: a
                # contradiction of the same Claims. It names neither party: bear context.
                {
                    "passage_id": dilution["id"],
                    "kind": "contradiction",
                    "checklist_item": "dilution_financing",
                    "subject_company_id": company_id(atlas, "coherent"),
                    "statement": "Coherent's issued share count rose in fiscal 2026.",
                    "quote": DILUTION_QUOTE,
                    "quote_start": dilution["text"].index(DILUTION_QUOTE),
                    "quote_end": dilution["text"].index(DILUTION_QUOTE) + len(DILUTION_QUOTE),
                    "epistemic_type": "company_claim",
                    "contradicts_claim_ids": [
                        c["claim_id"] for c in sent["request"]["supporting_claims"]
                    ],
                    "how": "limits",
                    "figure_name": None,
                    "figure_period": None,
                    "disproves_premise": None,
                },
            ]
        }

    plan: dict[str, JsonValue] = {
        "queries": [],
        "documents": [
            {"source_version_id": update, "checklist_item": "second_sources"},
            {"source_version_id": ten_q, "checklist_item": "dilution_financing"},
        ],
    }
    return ChatReply.json(plan), ChatReply.answer(reading)


def investigate(
    atlas: Atlas,
    llm: FakeLiteLLM,
    searxng: FakeSearXNG,
    skeptic: tuple[ChatReply, ...] = NOTHING_TO_READ,
) -> dict[str, Any]:
    """Run an investigation of Coherent's supply of NVIDIA to its stop (with the chained
    relationship review)."""
    searxng.script(SUBSTRATE, SearchReply.of("inp-substrate-capacity"))
    searxng.script(SECOND_SOURCE, SearchReply.of("inp-laser-second-source"))
    queries: list[JsonValue] = [
        {"query": SUBSTRATE, "purpose": "InP substrate capacity"},
        {"query": SECOND_SOURCE, "purpose": "second sources"},
    ]
    # This investigation's Skeptic answers only: an earlier one's unused answers are dropped.
    llm.role_replies.pop("skeptic", None)
    llm.script_role("skeptic", *skeptic)
    llm.script_role("financial_analyst", ChatReply.json({"scenarios": []}, tokens=(1500, 200)))
    llm.script_chat(
        ChatReply.json({"queries": queries}, tokens=(900, 120)),
        ChatReply.answer(quoting(supply(atlas)), tokens=(9000, 700)),
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


def published(atlas: Atlas, llm: FakeLiteLLM, searxng: FakeSearXNG) -> dict[str, Any]:
    """A Hypothesis whose version 1 (one finding, on the 10-K's supply quote) is published,
    its Relationship approved by the owner."""
    found = investigate(atlas, llm, searxng)
    saved = atlas.api.post("/api/v1/hypotheses", json={"investigation_id": found["id"]})
    assert saved.status_code == 202, saved.text
    hypothesis_id = saved.json()["id"]
    llm.script_chat(ChatReply.answer(hypothesis_editor, tokens=(4000, 600)))
    atlas.worker_pass()
    moved = atlas.api.post(
        f"/api/v1/hypotheses/{hypothesis_id}/transitions", json={"to": "evidence_ready"}
    )
    assert moved.status_code == 200, moved.text
    for edge in atlas.get("/api/v1/relationships", limit=500)["items"]:
        if edge["review_state"] != "approved":
            owner_review(atlas, edge["id"], "approved")
    response = atlas.api.post(
        f"/api/v1/hypotheses/{hypothesis_id}/publish-version", json={"version": 1}
    )
    assert response.status_code == 200, response.text
    hypothesis = response.json()
    assert hypothesis["open_proposed_updates"] == 0
    return hypothesis


def owner_review(atlas: Atlas, relationship_id: str, state: str) -> None:
    response = atlas.api.post(
        f"/api/v1/relationships/{relationship_id}/review", json={"review_state": state}
    )
    assert response.status_code == 200, response.text


def updates(atlas: Atlas, hypothesis_id: str, **params: Any) -> list[dict[str, Any]]:
    return atlas.get(f"/api/v1/hypotheses/{hypothesis_id}/proposed-updates", **params)["items"]


def frozen(atlas: Atlas, hypothesis_id: str) -> dict[str, Any]:
    """Everything that must never change once version 1 is published: its row, its snapshot's
    row and archived bytes, and the snapshot as the API verifies it."""
    with atlas.engine.connect() as connection:
        version = connection.execute(
            text("SELECT * FROM hypothesis_version WHERE hypothesis_id = :id AND version = 1"),
            {"id": hypothesis_id},
        ).mappings()
        rows = connection.execute(
            text("SELECT * FROM research_snapshot WHERE hypothesis_id = :id ORDER BY created_at"),
            {"id": hypothesis_id},
        ).mappings()
        version_row, snapshot_rows = dict(next(iter(version))), [dict(row) for row in rows]
    [snapshot] = snapshot_rows
    served = atlas.get(f"/api/v1/snapshots/{snapshot['id']}")
    assert served["verified"] is True
    return {
        "version": version_row,
        "snapshots": snapshot_rows,
        "bytes": (atlas.archive / "snapshots" / "sha256" / snapshot["sha256"]).read_bytes(),
        "served": served,
    }


def revise_ten_k(atlas: Atlas, old: bytes, new: bytes, last_modified: str) -> None:
    """Serve revised bytes for Coherent's recorded 10-K, with a new Last-Modified."""
    path = atlas.fixtures / "coherent" / "manifest.json"
    manifest = json.loads(path.read_text())
    entry = next(entry for entry in manifest["responses"] if entry["url"] == COHR_10K)
    entry["headers"]["last-modified"] = last_modified
    path.write_text(json.dumps(manifest, indent=2))
    body = atlas.fixtures / "coherent" / entry["file"]
    original = body.read_bytes()
    assert original.count(old) == 1
    body.write_bytes(original.replace(old, new))


def audit(atlas: Atlas, entity_type: str) -> list[tuple[str, str]]:
    with atlas.engine.connect() as connection:
        rows = connection.execute(
            text("SELECT action, actor FROM audit_event WHERE entity_type = :type ORDER BY id"),
            {"type": entity_type},
        )
        return [(row.action, row.actor) for row in rows]


# --- the gate test ----------------------------------------------------------------------------


def test_a_later_contradictory_source_proposes_one_update_and_leaves_the_snapshot_untouched(
    atlas: Atlas, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    hypothesis = published(atlas, llm, searxng)
    hypothesis_id = hypothesis["id"]
    [version] = hypothesis["versions"]
    [finding] = version["content"]["findings"]
    [span] = finding["source_spans"]
    ten_k = atlas.version(COHR_10K, "coherent")
    assert span["source_version_id"] == ten_k["id"]
    # A Candidate the owner committed for Coherent in the theme: the update concerns it too.
    candidate_id = str(uuid4())
    with atlas.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO candidate (id, theme, identity_key, name, cik, tier, source_path,"
                " resolution, state, company_id, decided_by, decided_at) VALUES (:id,"
                " 'photonics', 'cik:0000820318', 'Coherent Corp.', '0000820318', 'exact',"
                " 'sec', '{}', 'investigating', :company, 'local-researcher', now())"
            ),
            {"id": candidate_id, "company": company_id(atlas, "coherent")},
        )
    before = frozen(atlas, hypothesis_id)

    # A revision that still states the quote contradicts nothing.
    revise_ten_k(
        atlas,
        b"received a $50 million preliminary memorandum",
        b"received a $51 million preliminary memorandum",
        "Mon, 21 Sep 2026 12:00:00 GMT",
    )
    job = atlas.ingest("coherent-rerun-1", "coherent")  # collection runs again
    assert job["status"] == "succeeded", job["failures"]
    assert len(atlas.versions(COHR_10K, "coherent")) == 2
    assert updates(atlas, hypothesis_id) == []

    # The later contradictory source: the filing, revised, no longer states the agreement.
    revise_ten_k(
        atlas,
        b"strategic multi-year supply agreement with NVIDIA",
        b"non-binding memorandum of understanding with NVIDIA",
        "Tue, 29 Sep 2026 12:00:00 GMT",
    )
    job = atlas.ingest("coherent-rerun-2", "coherent")

    assert job["status"] == "succeeded", job["failures"]
    first, _, revised = atlas.versions(COHR_10K, "coherent")
    assert first["id"] == ten_k["id"]
    assert SUPPLY_QUOTE not in atlas.parsed(revised["id"])
    [update] = updates(atlas, hypothesis_id)
    assert (update["trigger"], update["state"], update["hypothesis_version"]) == (
        "source_revised",
        "open",
        1,
    )
    assert update["hypothesis_version_id"] == version["id"]
    assert "no longer states 1 quote version 1 cites" in update["summary"]
    [evidence] = update["evidence"]
    assert (evidence["kind"], evidence["id"], evidence["source_version_id"]) == (
        "source_version",
        revised["id"],
        revised["id"],
    )
    assert evidence["revises_source_version_id"] == ten_k["id"]
    assert evidence["contradicts_assertion_ids"] == [span["assertion_id"]]
    assert SUPPLY_QUOTE in evidence["description"]
    assert update["affected_findings"] == [
        {"index": 0, "claim_text": SUPPLY_FINDING, "assertion_ids": [span["assertion_id"]]}
    ]
    assert update["candidate_ids"] == [candidate_id]
    assert atlas.get(f"/api/v1/proposed-updates/{update['id']}") == update
    assert atlas.get("/api/v1/proposed-updates", candidate_id=candidate_id)["items"] == [update]
    assert atlas.get("/api/v1/proposed-updates", state="dismissed")["items"] == []
    assert audit(atlas, "proposed_update") == [("proposed_update.created", "atlas-contradictions")]
    # The flag is on the Hypothesis; the published version and its snapshot are untouched:
    # the same rows, the same archived bytes (so the same hash), still verified.
    flagged = atlas.get(f"/api/v1/hypotheses/{hypothesis_id}")
    assert flagged["open_proposed_updates"] == 1
    assert flagged["versions"] == [version]
    assert frozen(atlas, hypothesis_id) == before

    # Collecting again, and re-running the check, propose nothing more.
    job = atlas.ingest("coherent-rerun-3", "coherent")
    assert job["status"] == "succeeded", job["failures"]
    rerun = atlas.enqueue(
        "jobs",
        "enqueue",
        "check_contradictions",
        "--key",
        "rerun",
        "--payload",
        json.dumps({"trigger": "source_revised", "id": revised["id"], "state": None}),
    )
    atlas.worker_pass()
    assert atlas.get(f"/api/v1/jobs/{rerun}")["status"] == "succeeded"
    assert updates(atlas, hypothesis_id) == [update]
    assert frozen(atlas, hypothesis_id) == before


# --- the owner's decision -----------------------------------------------------------------------


def test_the_owner_accepts_an_update_as_a_correction_or_dismisses_it_with_a_reason(
    atlas: Atlas, llm: FakeLiteLLM, searxng: FakeSearXNG, tmp_path: Path
) -> None:
    hypothesis = published(atlas, llm, searxng)
    hypothesis_id = hypothesis["id"]
    [version] = hypothesis["versions"]
    [span] = version["content"]["findings"][0]["source_spans"]
    [edge] = atlas.get("/api/v1/relationships", limit=500)["items"]
    before = frozen(atlas, hypothesis_id)

    # A later document, imported by hand; the owner's Assertion on it supersedes the cited one.
    later = tmp_path / "later.html"
    later.write_text(
        f"<html><body><p>September 21, 2026. {LATER_QUOTE}.</p></body></html>", encoding="utf-8"
    )
    imported = atlas.cli(
        "sources",
        "import",
        "--company",
        "coherent",
        "--file",
        str(later),
        "--origin-url",
        LATER_ORIGIN,
        "--published-at",
        "2026-09-21T09:00:00+00:00",
    )
    assert imported.returncode == 0, imported.stderr
    later_version = json.loads(imported.stdout)["source_version_id"]
    atlas.worker_pass()  # its retention
    start = atlas.parsed(later_version).index(LATER_QUOTE)
    created = atlas.api.post(
        "/api/v1/assertions",
        json={
            "subject_company_id": company_id(atlas, "coherent"),
            "predicate": "supplies",
            "object_company_id": company_id(atlas, "nvidia"),
            "source_version_id": later_version,
            "quote": LATER_QUOTE,
            "span_start": start,
            "span_end": start + len(LATER_QUOTE),
            "epistemic_type": "company_claim",
        },
    )
    assert created.status_code == 201, created.text
    successor = created.json()["assertion"]["id"]
    assert updates(atlas, hypothesis_id) == []  # a new Assertion alone contradicts nothing
    reviewed = atlas.api.post(
        f"/api/v1/assertions/{span['assertion_id']}/review",
        json={"review_state": "superseded", "superseded_by": successor},
    )
    assert reviewed.status_code == 200, reviewed.text
    atlas.worker_pass()
    # And the owner rejects the edge the version depends on.
    owner_review(atlas, edge["id"], "rejected")
    atlas.worker_pass()

    superseded, rejected = updates(atlas, hypothesis_id)
    assert (superseded["trigger"], rejected["trigger"]) == (
        "assertion_reviewed",
        "relationship_rejected",
    )
    [evidence] = superseded["evidence"]
    assert (evidence["kind"], evidence["id"], evidence["state"]) == (
        "assertion",
        span["assertion_id"],
        "superseded",
    )
    assert (evidence["assertion_id"], evidence["source_version_id"], evidence["quote"]) == (
        successor,
        later_version,
        LATER_QUOTE,
    )
    [evidence] = rejected["evidence"]
    assert (evidence["kind"], evidence["id"], evidence["state"]) == (
        "relationship",
        edge["id"],
        "rejected",
    )
    assert evidence["contradicts_assertion_ids"] == [span["assertion_id"]]
    assert "Coherent supplies NVIDIA" in rejected["summary"]
    assert atlas.get(f"/api/v1/hypotheses/{hypothesis_id}")["open_proposed_updates"] == 2

    # Dismissing needs a reason, and resolves the update once.
    base = f"/api/v1/proposed-updates/{rejected['id']}"
    assert atlas.api.post(f"{base}/dismiss", json={}).status_code == 422
    assert atlas.api.post(f"{base}/dismiss", json={"reason": "  "}).status_code == 422
    dismissed = atlas.api.post(f"{base}/dismiss", json={"reason": "Rejected by mistake."})
    assert dismissed.status_code == 200, dismissed.text
    body = dismissed.json()
    assert (body["state"], body["dismiss_reason"], body["resolved_by"]) == (
        "dismissed",
        "Rejected by mistake.",
        "local-researcher",
    )
    assert body["correction_version"] is None
    again = atlas.api.post(f"{base}/dismiss", json={"reason": "again"})
    assert again.status_code == 409
    assert atlas.api.post(f"{base}/accept", json={}).status_code == 409

    # Accepting starts a correction: a new draft version, the contradicted finding flagged.
    accepted = atlas.api.post(f"/api/v1/proposed-updates/{superseded['id']}/accept", json={})
    assert accepted.status_code == 200, accepted.text
    body = accepted.json()
    assert (body["state"], body["correction_version"], body["resolved_by"]) == (
        "accepted",
        2,
        "local-researcher",
    )
    corrected = atlas.get(f"/api/v1/hypotheses/{hypothesis_id}")
    assert corrected["open_proposed_updates"] == 0
    assert corrected["status"] == "reviewed"
    first, second = corrected["versions"]
    assert first == version
    assert (second["version"], second["origin"], second["based_on_version"]) == (
        2,
        "correction",
        1,
    )
    assert second["published"] is False
    assert second["created_by"] == "local-researcher"
    assert superseded["id"] in second["note"]
    [finding] = second["content"]["findings"]
    assert finding["needs_review"] is True
    assert finding["limitations"][-1] == (
        f"Proposed update {superseded['id']}: {superseded['summary']}"
    )
    assert finding["source_spans"] == version["content"]["findings"][0]["source_spans"]
    assert (
        atlas.api.post(f"/api/v1/proposed-updates/{superseded['id']}/accept", json={}).status_code
        == 409
    )
    assert atlas.api.post(f"/api/v1/proposed-updates/{uuid4()}/accept", json={}).status_code == 404
    assert atlas.api.get(f"/api/v1/hypotheses/{uuid4()}/proposed-updates").status_code == 404
    assert [u["state"] for u in updates(atlas, hypothesis_id)] == ["accepted", "dismissed"]
    assert updates(atlas, hypothesis_id, state="open") == []
    # Audited; and the published version and its snapshot never changed.
    assert audit(atlas, "proposed_update") == [
        ("proposed_update.created", "atlas-contradictions"),
        ("proposed_update.created", "atlas-contradictions"),
        ("proposed_update.dismissed", "local-researcher"),
        ("proposed_update.accepted", "local-researcher"),
    ]
    assert ("hypothesis.corrected", "local-researcher") in audit(atlas, "hypothesis_version")
    assert frozen(atlas, hypothesis_id) == before
    # The correction is published like any other, behind the gate, with its own snapshot.
    assert (
        atlas.api.post(
            f"/api/v1/hypotheses/{hypothesis_id}/publish-version", json={"version": 2}
        ).status_code
        == 422  # the owner rejected the Relationship it still depends on
    )
    with pytest.raises(Exception, match="already"):
        with atlas.engine.begin() as connection:
            connection.execute(
                text("UPDATE proposed_update SET state = 'open' WHERE id = :id"),
                {"id": superseded["id"]},
            )
    with pytest.raises(Exception, match="never deleted"):
        with atlas.engine.begin() as connection:
            connection.execute(
                text("DELETE FROM proposed_update WHERE id = :id"), {"id": superseded["id"]}
            )


# --- counterevidence (ticket 15's rules) ----------------------------------------------------------


def test_later_independent_counterevidence_against_a_cited_statement_proposes_an_update(
    atlas: Atlas, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    hypothesis = published(atlas, llm, searxng)
    hypothesis_id = hypothesis["id"]
    [version] = hypothesis["versions"]
    [span] = version["content"]["findings"][0]["source_spans"]
    before = frozen(atlas, hypothesis_id)

    # A later investigation reads the same statement, and its Skeptic finds an independent
    # contradiction of it in a later document (and bear context in the 10-Q).
    later = investigate(atlas, llm, searxng, skeptic=limiting_skeptic(atlas))

    [contradiction] = later["research_card"]["contradictions"]
    assert contradiction["independent"] is True
    # Only the contradiction proposes an update: the share count, proposed as one too, is
    # bear context, and bear context contradicts nothing a published version cites.
    [group] = later["research_card"]["bear_context"]
    assert [item["source_span"]["quote"] for item in group["items"]] == [DILUTION_QUOTE]
    [update] = updates(atlas, hypothesis_id)
    assert update["trigger"] == "counterevidence"
    [evidence] = update["evidence"]
    later_statement = atlas.version(UPDATE_URL, "coherent")
    assert (evidence["kind"], evidence["id"]) == (
        "counterevidence",
        contradiction["counterevidence_id"],
    )
    assert (evidence["source_version_id"], evidence["quote"]) == (
        later_statement["id"],
        LIMIT_QUOTE,
    )
    assert evidence["assertion_id"] == contradiction["source_span"]["assertion_id"]
    # It bears on the published version's own Assertion (the same span), not the later one's.
    assert evidence["contradicts_assertion_ids"] == [span["assertion_id"]]
    assert "second_sources" in update["summary"]
    assert frozen(atlas, hypothesis_id) == before
