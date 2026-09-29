"""Hypotheses: an investigation's result saved as a versioned, falsifiable research object
(Phase 3-6a ticket 16; spec §5.6, §8.1; Phase 4 "Thesis lifecycle", "dossier export").

Seams: an investigation runs through `POST /api/v1/investigations` and single worker passes;
`POST /api/v1/hypotheses` saves it and a worker pass runs the Editor's draft; everything is
observed through `/api/v1` (the Hypothesis, its diff and export, runs' role calls, the audit
log through the database's own tables) and the requests the fakes received. The Source
Versions are the recorded Coherent EDGAR filings; Hindsight is the recorded fake, SearXNG the
scripted fake. LiteLLM is the scripted chat fake: **every role's answer is written here**
(the Investigator quotes the recorded Coherent 10-K; the Editors cite the Claim IDs they are
sent; the Reviewer, chained after the investigation, confirms what it is sent). Nothing live
is called.
"""

import json
import os
import subprocess
import sys
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
from tests.harness import THEMES, Atlas, at

QUESTION = "Who supplies the lasers in AI data-center optics, and to whom?"
SUBSTRATE = "indium phosphide substrate capacity expansion 2026"
SECOND_SOURCE = "InP laser second source qualification hyperscaler"
COHR_10K = "https://www.sec.gov/Archives/edgar/data/820318/000082031826000020/iivi-20260630.htm"
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


def investigate(
    atlas: Atlas, llm: FakeLiteLLM, searxng: FakeSearXNG, *claims: dict[str, JsonValue]
) -> dict[str, Any]:
    """Run an investigation of Coherent to its stop (with the chained relationship review)."""
    searxng.script(SUBSTRATE, SearchReply.of("inp-substrate-capacity"))
    searxng.script(SECOND_SOURCE, SearchReply.of("inp-laser-second-source"))
    queries: list[JsonValue] = [
        {"query": SUBSTRATE, "purpose": "InP substrate capacity"},
        {"query": SECOND_SOURCE, "purpose": "second sources"},
    ]
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
    **editor: Any,
) -> dict[str, Any]:
    """An investigation saved as a Hypothesis, with the Editor's draft (version 1) written."""
    found = investigate(atlas, llm, searxng, *(claims or (supply(atlas),)))
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


def audit_actions(atlas: Atlas, entity_type: str) -> list[str]:
    with atlas.engine.connect() as connection:
        return list(
            connection.execute(
                text("SELECT action FROM audit_event WHERE entity_type = :type ORDER BY id"),
                {"type": entity_type},
            ).scalars()
        )


def roles(llm: FakeLiteLLM) -> list[str]:
    return [body["metadata"]["role"] for body in llm.chat_requests()]


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
    assert roles(llm) == ["scout", "investigator", "editor", "reviewer", "editor"]
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
        ("editor", "editor", 1),
        ("editor", "editor-hypothesis", 1),
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


def test_the_publish_gate_needs_a_falsifier_and_an_unresolved_question(
    atlas: Atlas, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    hypothesis = drafted(atlas, llm, searxng, falsifiers=[], unresolved=[])
    hypothesis_id = hypothesis["id"]
    assert move(atlas, hypothesis_id, "evidence_ready").status_code == 200

    refused = publish(atlas, hypothesis_id, 1)

    assert refused.status_code == 422
    error = refused.json()["error"]
    assert error["code"] == "publish_gate_failed"
    assert "no_falsifier" in error["message"]
    assert "no_unresolved_question" in error["message"]
    assert get(atlas, hypothesis_id)["versions"][0]["published"] is False

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
    published = publish(atlas, hypothesis_id, 2)
    assert published.status_code == 200, published.text
    versions = published.json()["versions"]
    assert [v["published"] for v in versions] == [False, True]


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
    # Stopped without a card (the Investigator accepted nothing): nothing to save.
    searxng.script(SUBSTRATE, SearchReply.of("inp-substrate-capacity"))
    llm.script_chat(
        ChatReply.json({"queries": [{"query": SUBSTRATE, "purpose": None}]}),
        ChatReply.json({"claims": []}),
    )
    atlas.worker_pass()
    empty = atlas.get(f"/api/v1/investigations/{running['id']}")
    assert empty["stop_reason"] == "no_new_independent_evidence"
    refused = atlas.api.post("/api/v1/hypotheses", json={"investigation_id": running["id"]})
    assert refused.status_code == 409
    assert "without a research card" in refused.json()["error"]["message"]

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
