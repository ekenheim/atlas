"""Investigator Claims → Assertions (Phase 3-6a ticket 10; spec "Relationships", §5.5).

Seam: the `atlas` CLI seeds the universe and enqueues `extract_claims` jobs, single worker
passes run them, and everything is observed through `/api/v1` (claims, claim extractions,
assertions, runs' role calls, metrics) and the audit trail. The Source Versions are the
recorded Coherent EDGAR filings (ingested and retained through the fixture path, Hindsight
the recorded fake with `derive_memories`). LiteLLM is the scripted chat fake: **the
Investigator's answers are written here**, quoting the recorded Coherent FY2026 10-K; a
`ChatReply.answer` finds each quote in the passages it was sent, the way a model would, and
answers with that passage's ID and the quote's offsets in it (or with deliberately wrong
ones). The test universe is the repo's plus NVIDIA, which the 10-K names.
"""

import json
import os
import subprocess
import sys
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
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
from tests.fakes.serve import Served, serve
from tests.harness import THEMES, Atlas, Clock

COHR_10K = "https://www.sec.gov/Archives/edgar/data/820318/000082031826000020/iivi-20260630.htm"
COHR_10Q = "https://www.sec.gov/Archives/edgar/data/820318/000082031826000013/iivi-20260331.htm"
# Lumentum's Q4 FY2026 results press release, the 8-K's EX-99.1.
LITE_EX991 = (
    "https://www.sec.gov/Archives/edgar/data/1633978/000162828026055726/lite_ex991xq4fy26.htm"
)
LITE_10K = "https://www.sec.gov/Archives/edgar/data/1633978/000162828026057358/lite-20260627.htm"
# From the Coherent FY2026 10-K (the recorded fixture's parsed text).
SUPPLY_QUOTE = (
    "we announced the expansion of our Sherman, Texas, manufacturing facility, entered into a"
    " strategic multi-year supply agreement with NVIDIA for advanced lasers and optical"
    " networking products"
)
INVESTMENT_QUOTE = "NVIDIA made a $2 billion investment in the Company"
# The co-mention-only fixture: Lumentum and Coherent named together in the stock
# performance graph's peer group, which states no relation between them.
PEER_GROUP_QUOTE = (
    "The Company\N{RIGHT SINGLE QUOTATION MARK}s peer group includes IPG Photonics Corp.,"
    " Wolfspeed Inc., Lumentum Holdings, Inc., Corning, Inc., MKS Instruments, Inc., and"
    " Honeywell International, Inc."
)
# The live smoke run's third kind of answer: the relation in the model's words, not the filing's.
PARAPHRASE = "Coherent signed a multi-year agreement to supply NVIDIA with lasers"
# A word the supply agreement's passage uses more than once.
REPEATED = "optical"
WHITELIST = [
    "manufactures",
    "supplies",
    "buys_from",
    "uses_material",
    "owns",
    "competes_with",
    "substitutes_for",
    "expands_capacity_for",
    "depends_on",
    "capacity_constrained",
    "sole_sources",
    "vertically_integrates",
    "qualified_for",
]
LAYERS = ["substrate", "epi", "chip-laser", "dsp", "module", "contract-manufacturing", "system"]


# --- fixtures -----------------------------------------------------------------------------------


@pytest.fixture
def hindsight_fake() -> RecordedHindsight:
    fake = RecordedHindsight()
    fake.derive_memories()
    return fake


@pytest.fixture
def fake(hindsight: tuple[RecordedHindsight, Served]) -> RecordedHindsight:
    return hindsight[0]


@pytest.fixture
def llm() -> FakeLiteLLM:
    return FakeLiteLLM()


@pytest.fixture
def litellm(llm: FakeLiteLLM) -> Iterator[Served]:
    with serve(llm.handle) as served:
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


def start_atlas(
    database_url: str,
    tmp_path: Path,
    hindsight: tuple[RecordedHindsight, Served],
    litellm: Served,
    themes: Path,
    **overrides: Any,
) -> Atlas:
    settings: dict[str, Any] = {
        "themes_config": themes,
        "investigator_passages_per_call": 50,  # one call per extraction unless a test says
    }
    harness = Atlas(database_url, tmp_path, hindsight[1].url, litellm.url, **(settings | overrides))
    harness.apply_template()
    seeded = subprocess.run(
        [sys.executable, "-m", "atlas", "companies", "seed"],
        cwd=tmp_path,
        env={
            "PATH": os.environ["PATH"],
            "HOME": str(tmp_path),
            "ATLAS_DATABASE_URL": database_url,
            "ATLAS_ACTOR": "local-researcher",
            "ATLAS_ARCHIVE_ROOT": str(harness.archive),
            "ATLAS_THEMES_CONFIG": str(themes),
        },
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert seeded.returncode == 0, seeded.stderr
    harness.ingest_company("coherent")
    return harness


@pytest.fixture
def atlas(
    database_url: str,
    tmp_path: Path,
    hindsight: tuple[RecordedHindsight, Served],
    litellm: Served,
    themes: Path,
) -> Iterator[Atlas]:
    harness = start_atlas(database_url, tmp_path, hindsight, litellm, themes)
    yield harness
    harness.engine.dispose()


# --- helpers ------------------------------------------------------------------------------------


def company_id(atlas: Atlas, slug: str) -> str:
    return atlas.company(slug)["id"]


def ten_k(atlas: Atlas) -> str:
    return atlas.version(COHR_10K, "coherent")["id"]


def asked(body: dict[str, Any]) -> dict[str, Any]:
    """The user message of a chat request: `{"request": ..., "retrieved_data": [...]}`."""
    return json.loads(body["messages"][1]["content"])


def claim(**fields: JsonValue) -> dict[str, JsonValue]:
    """A proposed Claim; `passage_id` and the offsets are filled in from the passages sent."""
    return {
        "object_company_id": None,
        "object_name": None,
        "object_text": None,
        "product": None,
        "layer": "chip-laser",
        "epistemic_type": "company_claim",
        **fields,
    }


def quoting(
    *claims: dict[str, JsonValue], read: Callable[[str], str] = str
) -> Callable[[dict[str, Any]], JsonValue]:
    """An Investigator answer quoting the passages it is sent: each claim without a
    `passage_id` gets the passage whose text holds its quote and the quote's offsets there
    (`shift` moves both offsets, to propose a wrong span). `read` is how the model spells the
    passages' text (a model that writes ASCII hyphens for typographic ones, say)."""

    def respond(body: dict[str, Any]) -> JsonValue:
        passages = asked(body)["retrieved_data"]
        answered: list[JsonValue] = []
        for each in claims:
            proposed = dict(each)
            shift = int(str(proposed.pop("shift", 0)))
            if "passage_id" not in proposed:
                quote = str(proposed["quote"])
                holding = [p for p in passages if quote in read(p["text"])]
                assert holding, f"no passage sent holds {quote!r}"
                start = read(holding[0]["text"]).index(quote) + shift
                proposed |= {
                    "passage_id": holding[0]["id"],
                    "quote_start": start,
                    "quote_end": start + len(quote),
                }
            answered.append(proposed)
        return {"claims": answered}

    return respond


def extract(atlas: Atlas, key: str, **payload: JsonValue) -> dict[str, Any]:
    """Enqueue an `extract_claims` job through the CLI, run one worker pass, return the job."""
    job_id = atlas.enqueue(
        "jobs", "enqueue", "extract_claims", "--key", key, "--payload", json.dumps(payload)
    )
    atlas.worker_pass()
    return atlas.get(f"/api/v1/jobs/{job_id}")


def claims_of(atlas: Atlas, extraction_id: str, **params: Any) -> list[dict[str, Any]]:
    return atlas.get("/api/v1/claims", extraction_id=extraction_id, limit=500, **params)["items"]


def audit_actions(atlas: Atlas, entity_type: str) -> list[str]:
    with atlas.engine.connect() as connection:
        return list(
            connection.execute(
                text("SELECT action FROM audit_event WHERE entity_type = :type ORDER BY id"),
                {"type": entity_type},
            ).scalars()
        )


# --- accepted Claims ------------------------------------------------------------------------------


def test_a_claim_whose_span_validates_becomes_an_assertion_at_that_exact_span(
    atlas: Atlas, llm: FakeLiteLLM
) -> None:
    coherent, nvidia = company_id(atlas, "coherent"), company_id(atlas, "nvidia")
    version_id = ten_k(atlas)
    llm.script_chat(
        ChatReply.answer(
            quoting(
                claim(
                    subject_company_id=coherent,
                    predicate="supplies",
                    object_company_id=nvidia,
                    product="advanced lasers",
                    quote=SUPPLY_QUOTE,
                ),
                claim(
                    subject_company_id=nvidia,
                    predicate="owns",
                    object_company_id=coherent,
                    layer="system",
                    quote=INVESTMENT_QUOTE,
                    epistemic_type="direct_source_statement",
                ),
            ),
            tokens=(9000, 700),
        )
    )

    job = extract(atlas, "cohr-10k", source_version_ids=[version_id])

    assert job["status"] == "succeeded", job["failures"]
    artifacts = job["artifacts"]
    assert (artifacts["status"], artifacts["accepted"], artifacts["rejected"]) == (
        "completed",
        2,
        0,
    )
    supplies, owns = claims_of(atlas, artifacts["extraction_id"])
    # Each Claim says which selections chose its passage: here the window names NVIDIA.
    extraction = atlas.get(f"/api/v1/claim-extractions/{artifacts['extraction_id']}")
    selected = {p["id"]: p["selected_by"] for p in extraction["passages"]}
    for accepted in (supplies, owns):
        assert accepted["passage_selected_by"] == selected[accepted["passage_id"]]
        assert f"entity:{nvidia}" in accepted["passage_selected_by"]
    assert (
        atlas.get(f"/api/v1/claims/{supplies['id']}")["passage_selected_by"]
        == (supplies["passage_selected_by"])
    )
    assert artifacts["passages_by_selection"] == {"entity": len(extraction["passages"])}
    parsed = atlas.parsed(version_id)
    for accepted, quote in [(supplies, SUPPLY_QUOTE), (owns, INVESTMENT_QUOTE)]:
        assert (accepted["outcome"], accepted["reason_code"]) == ("accepted", None)
        assertion = atlas.get(f"/api/v1/assertions/{accepted['assertion_id']}")
        assert parsed[assertion["span_start"] : assertion["span_end"]] == quote
        assert (assertion["span_start"], assertion["span_end"]) == (
            accepted["span_start"],
            accepted["span_end"],
        )
        assert assertion["source_version_id"] == version_id
        assert assertion["review_state"] == "unreviewed"
        assert assertion["extractor_version"] == "investigator.v7"
        assert assertion["created_by"] == "atlas-investigator"
        assert assertion["value_json"]["claim_id"] == accepted["id"]
    supplied = atlas.get(f"/api/v1/assertions/{supplies['assertion_id']}")
    assert (supplied["subject_company_id"], supplied["predicate"]) == (coherent, "supplies")
    assert supplied["object_company_id"] == nvidia
    assert supplied["epistemic_type"] == "company_claim"
    assert supplied["value_json"]["layer"] == "chip-laser"
    assert supplied["value_json"]["product"] == "advanced lasers"
    assert supplies["directional_cue"] == "supply"
    # The layer is kept for the words that name it ("advanced lasers").
    assert (supplies["layer"], supplies["layer_term"], supplies["layer_reason"]) == (
        "chip-laser",
        "lasers",
        None,
    )
    owned = atlas.get(f"/api/v1/assertions/{owns['assertion_id']}")
    assert (owned["subject_company_id"], owned["predicate"]) == (nvidia, "owns")
    assert owned["object_company_id"] == coherent
    # Direction is never inferred: one Claim, one Assertion, with the predicate proposed.
    all_assertions = atlas.get("/api/v1/assertions", source_version_id=version_id)["items"]
    assert sorted(a["predicate"] for a in all_assertions) == ["owns", "supplies"]
    assert audit_actions(atlas, "claim") == ["claim.accepted", "claim.accepted"]


# --- locating quotes (owner decision 2026-09-29: "Claim quotes are located, not trusted") ------


def supply_passage(body: dict[str, Any]) -> dict[str, Any]:
    """The passage sent that holds the supply agreement quote."""
    [passage] = [p for p in asked(body)["retrieved_data"] if SUPPLY_QUOTE in p["text"]]
    return passage


def test_a_quote_at_wrong_offsets_that_occurs_once_in_its_passage_is_located(
    atlas: Atlas, llm: FakeLiteLLM
) -> None:
    coherent, nvidia = company_id(atlas, "coherent"), company_id(atlas, "nvidia")
    version_id = ten_k(atlas)
    supply = claim(
        subject_company_id=coherent,
        predicate="supplies",
        object_company_id=nvidia,
        quote=SUPPLY_QUOTE,
    )
    llm.script_chat(ChatReply.answer(quoting(supply, supply | {"shift": -3})))

    job = extract(atlas, "located", source_version_ids=[version_id])

    assert job["status"] == "succeeded", job["failures"]
    exact, located = claims_of(atlas, job["artifacts"]["extraction_id"])
    assert (exact["outcome"], exact["offset_source"]) == ("accepted", "model")
    assert (located["outcome"], located["offset_source"]) == ("accepted", "located")
    # The model's offsets stay in `proposed`; the Claim and its Assertion hold the located span,
    # an exact span of the archived parsed text.
    assert located["proposed"]["quote_start"] == exact["proposed"]["quote_start"] - 3
    assert located["proposed"]["quote_end"] == exact["proposed"]["quote_end"] - 3
    assert (located["span_start"], located["span_end"]) == (exact["span_start"], exact["span_end"])
    assertion = atlas.get(f"/api/v1/assertions/{located['assertion_id']}")
    assert (assertion["span_start"], assertion["span_end"]) == (
        located["span_start"],
        located["span_end"],
    )
    parsed = atlas.parsed(version_id)
    assert parsed[assertion["span_start"] : assertion["span_end"]] == SUPPLY_QUOTE
    assert atlas.get(f"/api/v1/claims/{located['id']}")["offset_source"] == "located"


def test_a_quote_at_wrong_offsets_that_occurs_more_than_once_in_its_passage_is_ambiguous(
    atlas: Atlas, llm: FakeLiteLLM
) -> None:
    coherent, nvidia = company_id(atlas, "coherent"), company_id(atlas, "nvidia")

    def respond(body: dict[str, Any]) -> JsonValue:
        passage = supply_passage(body)
        assert passage["text"].count(REPEATED) >= 2
        wrong = passage["text"].index(SUPPLY_QUOTE)  # not where REPEATED is
        proposed = claim(
            subject_company_id=coherent,
            predicate="supplies",
            object_company_id=nvidia,
            quote=REPEATED,
            passage_id=passage["id"],
            quote_start=wrong,
            quote_end=wrong + len(REPEATED),
        )
        return {"claims": [proposed]}

    llm.script_chat(ChatReply.answer(respond))

    job = extract(atlas, "ambiguous", source_version_ids=[ten_k(atlas)])

    assert job["status"] == "succeeded", job["failures"]
    [ambiguous] = claims_of(atlas, job["artifacts"]["extraction_id"])
    assert (ambiguous["outcome"], ambiguous["reason_code"]) == ("rejected", "quote_ambiguous")
    assert "occurrences" in ambiguous["reason"]
    assert (ambiguous["assertion_id"], ambiguous["offset_source"]) == (None, None)
    assert audit_actions(atlas, "assertion") == []


def test_a_paraphrased_quote_is_a_quote_mismatch(atlas: Atlas, llm: FakeLiteLLM) -> None:
    coherent, nvidia = company_id(atlas, "coherent"), company_id(atlas, "nvidia")

    def respond(body: dict[str, Any]) -> JsonValue:
        passage = supply_passage(body)
        start = passage["text"].index(SUPPLY_QUOTE)
        proposed = claim(
            subject_company_id=coherent,
            predicate="supplies",
            object_company_id=nvidia,
            quote=PARAPHRASE,
            passage_id=passage["id"],
            quote_start=start,
            quote_end=start + len(PARAPHRASE),
        )
        return {"claims": [proposed]}

    llm.script_chat(ChatReply.answer(respond))

    job = extract(atlas, "paraphrase", source_version_ids=[ten_k(atlas)])

    [paraphrase] = claims_of(atlas, job["artifacts"]["extraction_id"])
    assert (paraphrase["outcome"], paraphrase["reason_code"]) == ("rejected", "quote_mismatch")
    assert (paraphrase["assertion_id"], paraphrase["offset_source"]) == (None, None)
    assert atlas.get("/api/v1/claims", reason_code="quote_mismatch")["total"] == 1


def test_the_investigator_is_sent_entity_tagged_passages_the_whitelist_and_the_layers(
    atlas: Atlas, llm: FakeLiteLLM
) -> None:
    version_id = ten_k(atlas)
    llm.script_chat(ChatReply.json({"claims": []}))

    job = extract(atlas, "cohr-10k", source_version_ids=[version_id])

    [body] = llm.chat_requests()
    assert body["response_format"]["json_schema"]["name"] == "investigator"
    assert body["metadata"]["role"] == "investigator"
    request, passages = asked(body)["request"], asked(body)["retrieved_data"]
    assert [p["name"] for p in request["predicates"]] == WHITELIST
    objects = {p["name"]: p["object"] for p in request["predicates"]}
    assert objects["supplies"] == objects["buys_from"] == "company"
    assert objects["manufactures"] == "product"
    assert [layer["name"] for layer in request["layers"]] == LAYERS
    names = {c["company_id"]: c["names"] for c in request["companies"]}
    assert "NVIDIA" in names[company_id(atlas, "nvidia")]
    assert "Lumentum" in names[company_id(atlas, "lumentum")]
    # Every passage names another company than Coherent (whose document it is), in capitals:
    # the 10-K's "coherent" optics never tag a passage.
    assert passages
    parsed = atlas.parsed(version_id)
    extraction = atlas.get(f"/api/v1/claim-extractions/{job['artifacts']['extraction_id']}")
    assert [p["id"] for p in extraction["passages"]] == [p["id"] for p in passages]
    for sent, stored in zip(passages, extraction["passages"], strict=True):
        assert sent["trust"] == "low"
        assert sent["text"] == parsed[stored["char_start"] : stored["char_end"]]
        assert len(sent["text"]) <= 3000
        assert "NVIDIA" in sent["text"] or "Lumentum" in sent["text"]
        assert all(tag.startswith("entity:") for tag in stored["selected_by"])
    assert any(PEER_GROUP_QUOTE in p["text"] for p in passages)
    assert any(SUPPLY_QUOTE in p["text"] for p in passages)
    assert {p["filer_company_id"] for p in request["passages"]} == {company_id(atlas, "coherent")}
    assert extraction["status"] == "completed"
    run = atlas.get(f"/api/v1/runs/{extraction['run_id']}/role-calls")
    [call] = run["role_calls"]
    assert (call["role"], call["prompt_name"], call["status"]) == (
        "investigator",
        "investigator",
        "accepted",
    )


# The question's terms, as the peer-group sentence of the 10-K's Item 5 spells them.
PEER_GROUP_QUESTION = (
    "Which companies are in the peer group: IPG Photonics, Wolfspeed, Corning, MKS Instruments"
    " or Honeywell?"
)


def test_without_pointers_the_search_selection_reads_the_window_that_best_matches_the_question(
    atlas: Atlas, llm: FakeLiteLLM, fake: RecordedHindsight
) -> None:
    version_id = ten_k(atlas)
    lumentum = company_id(atlas, "lumentum")
    llm.script_chat(ChatReply.json({"claims": []}))

    job = extract(
        atlas, "cohr-question", source_version_ids=[version_id], question=PEER_GROUP_QUESTION
    )

    # The standalone job asks Memory nothing (memory-directed reading ticket 05: no pointers
    # outside an investigation, and the Investigator's own recall is gone).
    assert fake.requests("POST", "memories/recall") == []
    extraction = atlas.get(f"/api/v1/claim-extractions/{job['artifacts']['extraction_id']}")
    assert extraction["question"] == PEER_GROUP_QUESTION
    parsed = atlas.parsed(version_id)
    best, *rest = extraction["passages"]
    # Best first: the window holding the sentence the question's rare terms come from, which
    # also names Lumentum (one passage, both selections).
    assert PEER_GROUP_QUOTE in parsed[best["char_start"] : best["char_end"]]
    assert best["selected_by"] == ["search", f"entity:{lumentum}"]
    # Every passage was chosen by the search or an entity tag; the windows that only name a
    # company (no term of the question) come after every search window.
    kinds = [{tag.split(":")[0] for tag in p["selected_by"]} for p in extraction["passages"]]
    assert all(kind <= {"search", "entity"} for kind in kinds)
    searched = ["search" in kind for kind in kinds]
    assert searched == sorted(searched, reverse=True)
    assert len(rest) == 23  # the budget; the other candidates are counted, not sent
    assert extraction["passages_dropped"] > 0
    counted = job["artifacts"]["passages_by_selection"]
    assert counted["search"] == sum(searched)
    assert counted["entity"] == sum(1 for kind in kinds if "entity" in kind)


def test_the_ceiling_stops_one_document_taking_more_than_its_share_and_reports_keep_one_passage(
    database_url: str,
    tmp_path: Path,
    hindsight: tuple[RecordedHindsight, Served],
    litellm: Served,
    llm: FakeLiteLLM,
    themes: Path,
) -> None:
    # Six passages over four documents: one document may take a third of them, two. Each
    # 10-K alone has more windows naming lasers than the whole budget.
    atlas = start_atlas(
        database_url, tmp_path, hindsight, litellm, themes, investigator_max_passages=6
    )
    atlas.ingest_company("lumentum")
    llm.script_chat(ChatReply.json({"claims": []}))
    ten_q = atlas.version(COHR_10Q, "coherent")["id"]
    lite_ten_k = atlas.version(LITE_10K, "lumentum")["id"]
    release = atlas.version(LITE_EX991, "lumentum")["id"]

    job = extract(
        atlas,
        "shared",
        source_version_ids=[ten_k(atlas), ten_q, lite_ten_k, release],
        question="Who buys lasers?",
    )

    extraction = atlas.get(f"/api/v1/claim-extractions/{job['artifacts']['extraction_id']}")
    by_document = job["artifacts"]["passages_by_document"]
    assert sum(by_document.values()) == len(extraction["passages"]) == 6
    assert by_document[ten_k(atlas)] == by_document[lite_ten_k] == 2  # the ceiling
    assert extraction["passages_dropped"] > 0  # their other matching windows
    # The floor: the 10-Q (a periodic report) and the press release (the EX-99.1 of an 8-K
    # with Item 2.02) each keep a passage. The recorded 10-Q names no laser and no other
    # company, so its passage is a lead window.
    assert (by_document[ten_q], by_document[release]) == (1, 1)
    [kept] = [p for p in extraction["passages"] if p["source_version_id"] == ten_q]
    assert kept["selected_by"] == ["lead"]
    assert all(
        "search" in p["selected_by"]
        for p in extraction["passages"]
        if p["source_version_id"] != ten_q
    )


def test_a_document_with_no_other_candidate_is_read_from_its_lead_windows(
    atlas: Atlas, llm: FakeLiteLLM
) -> None:
    # Lumentum's Q4 FY2026 press release (EX-99.1) names no other known company, and without a
    # question nothing is searched: before pilot fix 10 it was never read.
    atlas.ingest_company("lumentum")
    release = atlas.version(LITE_EX991, "lumentum")["id"]
    llm.script_chat(ChatReply.json({"claims": []}))

    job = extract(atlas, "lead", source_version_ids=[ten_k(atlas), release])

    extraction = atlas.get(f"/api/v1/claim-extractions/{job['artifacts']['extraction_id']}")
    released = [p for p in extraction["passages"] if p["source_version_id"] == release]
    assert released
    assert all(p["selected_by"] == ["lead"] for p in released)
    # The release is short enough to be read whole: its chunks, in text order.
    assert [p["char_start"] for p in released] == sorted(p["char_start"] for p in released)
    assert released[0]["char_start"] == 0
    assert released[-1]["char_end"] == len(atlas.parsed(release))
    # The 10-K's passages are its entity-tagged windows, as before; none were left out.
    others = [p for p in extraction["passages"] if p["source_version_id"] != release]
    assert others
    assert all(any(t.startswith("entity:") for t in p["selected_by"]) for p in others)
    assert extraction["passages_dropped"] == 0
    assert job["artifacts"]["passages_by_document"] == {
        ten_k(atlas): len(others),
        release: len(released),
    }


# --- rejected Claims ------------------------------------------------------------------------------


def test_claims_that_fail_a_check_are_rejected_with_the_reason_and_become_no_assertion(
    atlas: Atlas, llm: FakeLiteLLM
) -> None:
    coherent, nvidia = company_id(atlas, "coherent"), company_id(atlas, "nvidia")
    lumentum = company_id(atlas, "lumentum")
    version_id = ten_k(atlas)
    supply = claim(
        subject_company_id=coherent,
        predicate="supplies",
        object_company_id=nvidia,
        quote=SUPPLY_QUOTE,
    )
    llm.script_chat(
        ChatReply.answer(
            quoting(
                supply | {"predicate": "works_with"},
                supply | {"predicate": "partners with"},
                supply | {"layer": "optics"},
                supply | {"passage_id": "p999", "quote_start": 0, "quote_end": 10},
                supply | {"subject_company_id": str(uuid.uuid4())},
                supply | {"object_company_id": None},
                supply | {"object_company_id": coherent},
                supply
                | {"quote": PARAPHRASE, "passage_id": "p1", "quote_start": 0, "quote_end": 5},
                supply | {"passage_id": "p1", "quote_start": 0, "quote_end": 5000},
                supply | {"subject_company_id": lumentum},
                claim(subject_company_id=coherent, predicate="manufactures", quote=SUPPLY_QUOTE),
            )
        )
    )

    job = extract(atlas, "cohr-10k", source_version_ids=[version_id])

    assert job["status"] == "succeeded", job["failures"]
    assert (job["artifacts"]["accepted"], job["artifacts"]["rejected"]) == (0, 11)
    rejected = claims_of(atlas, job["artifacts"]["extraction_id"])
    assert [c["reason_code"] for c in rejected] == [
        "predicate_not_whitelisted",
        "predicate_not_whitelisted",
        "unknown_layer",
        "unknown_passage",
        "unknown_company",
        "missing_object",
        "self_relationship",
        "quote_mismatch",
        "quote_outside_passage",
        "party_not_in_quote",
        "missing_object",
    ]
    assert all(c["outcome"] == "rejected" and c["assertion_id"] is None for c in rejected)
    assert "maps to no predicate" in rejected[0]["reason"]
    # A rejected Claim says how its passage was selected too; one naming no passage sent, none.
    assert all(tag.startswith("entity:") for tag in rejected[0]["passage_selected_by"])
    assert rejected[0]["passage_selected_by"] and rejected[3]["passage_selected_by"] == []
    assert rejected[1]["proposed"]["predicate"] == "partners with"
    # A quote that isn't in its passage (a paraphrase) is never placed anywhere.
    mismatch = rejected[7]
    assert "does not occur" in mismatch["reason"]
    assert mismatch["offset_source"] is None
    assert "Lumentum" in rejected[9]["reason"]
    assert atlas.get("/api/v1/assertions", source_version_id=version_id)["total"] == 0
    assert audit_actions(atlas, "claim") == ["claim.rejected"] * 11
    assert audit_actions(atlas, "assertion") == []
    only_layers = atlas.get("/api/v1/claims", outcome="rejected", reason_code="unknown_layer")[
        "items"
    ]
    assert [c["proposed"]["layer"] for c in only_layers] == ["optics"]


def test_gate_a_co_mention_only_fixture_never_produces_a_relationship_eligible_assertion(
    atlas: Atlas, llm: FakeLiteLLM
) -> None:
    coherent, lumentum = company_id(atlas, "coherent"), company_id(atlas, "lumentum")
    version_id = ten_k(atlas)
    # Whatever the model makes of two companies named side by side, in either direction.
    proposals = [
        claim(
            subject_company_id=subject,
            predicate=predicate,
            object_company_id=target,
            quote=PEER_GROUP_QUOTE,
            epistemic_type="direct_source_statement",
        )
        for predicate in ["supplies", "buys_from", "competes_with", "depends_on", "owns"]
        for subject, target in [(coherent, lumentum), (lumentum, coherent)]
    ]
    proposals.append(
        claim(
            subject_company_id=coherent,
            predicate="partners_with",
            object_company_id=lumentum,
            quote=PEER_GROUP_QUOTE,
        )
    )
    llm.script_chat(ChatReply.answer(quoting(*proposals)))

    job = extract(atlas, "co-mention", source_version_ids=[version_id])

    assert job["status"] == "succeeded", job["failures"]
    outcomes = claims_of(atlas, job["artifacts"]["extraction_id"])
    assert len(outcomes) == 11
    assert all(c["outcome"] == "rejected" for c in outcomes)
    # The span itself is verbatim: it is the form of the statement that is refused.
    assert {c["reason_code"] for c in outcomes[:10]} == {"no_directional_language"}
    assert outcomes[10]["reason_code"] == "predicate_not_whitelisted"
    parsed = atlas.parsed(version_id)
    assert all(parsed[c["span_start"] : c["span_end"]] == PEER_GROUP_QUOTE for c in outcomes)
    assert atlas.get("/api/v1/assertions", company_id=lumentum)["total"] == 0
    assert atlas.get("/api/v1/assertions", source_version_id=version_id)["total"] == 0


# --- batches: outage, budget, quarantine ---------------------------------------------------


def test_an_llm_outage_pauses_the_queue_and_the_job_resumes_at_its_next_batch_in_the_same_run(
    database_url: str,
    tmp_path: Path,
    hindsight: tuple[RecordedHindsight, Served],
    litellm: Served,
    llm: FakeLiteLLM,
    themes: Path,
) -> None:
    atlas = start_atlas(
        database_url,
        tmp_path,
        hindsight,
        litellm,
        themes,
        investigator_passages_per_call=1,
        investigator_max_passages=2,
    )
    # The API reads the pause by the real clock, so the worker's clock starts there too.
    clock = Clock(datetime.now(UTC).replace(microsecond=0))
    worker = Worker(
        JobQueue(atlas.engine, pacing=Pacing(), clock=clock), builtin_registry(atlas.settings())
    )
    job_id = atlas.enqueue(
        "jobs",
        "enqueue",
        "extract_claims",
        "--key",
        "outage",
        "--payload",
        json.dumps({"source_version_ids": [ten_k(atlas)]}),
    )
    llm.script_chat(ChatReply.json({"claims": []}), ChatReply.error(503, "Service Unavailable"))

    worker.run_once()

    job = atlas.get(f"/api/v1/jobs/{job_id}")
    assert (job["status"], job["attempts"]) == ("queued", 0)
    assert atlas.get("/api/v1/queue")["pause"]["paused"] is True
    (extraction_id,) = extraction_ids(atlas)
    extraction = atlas.get(f"/api/v1/claim-extractions/{extraction_id}")
    assert (extraction["status"], extraction["batches_done"]) == ("running", 1)

    clock.advance(hours=2)
    llm.script_chat(ChatReply.json({"claims": []}))
    worker.run_once()

    job = atlas.get(f"/api/v1/jobs/{job_id}")
    assert job["status"] == "succeeded", job["failures"]
    assert job["artifacts"]["extraction_id"] == extraction_id
    extraction = atlas.get(f"/api/v1/claim-extractions/{extraction_id}")
    assert (extraction["status"], extraction["batches_done"]) == ("completed", 2)
    calls = atlas.get(f"/api/v1/runs/{extraction['run_id']}/role-calls")["role_calls"]
    assert [c["status"] for c in calls] == ["accepted", "failed", "accepted"]
    # The resumed call sent the second passage, not the first again.
    sent = [asked(body)["retrieved_data"][0]["id"] for body in llm.chat_requests()]
    assert sent == ["p1", "p2", "p2"]
    atlas.engine.dispose()


def extraction_ids(atlas: Atlas) -> list[str]:
    with atlas.engine.connect() as connection:
        return [
            str(i) for i in connection.execute(text("SELECT id FROM claim_extraction")).scalars()
        ]


def test_a_spent_token_budget_stops_the_extraction_and_keeps_what_it_found(
    database_url: str,
    tmp_path: Path,
    hindsight: tuple[RecordedHindsight, Served],
    litellm: Served,
    llm: FakeLiteLLM,
    themes: Path,
) -> None:
    atlas = start_atlas(
        database_url,
        tmp_path,
        hindsight,
        litellm,
        themes,
        investigator_passages_per_call=1,
        investigator_max_passages=3,
        run_token_budget=1000,
    )
    llm.script_chat(ChatReply.json({"claims": []}, tokens=(900, 150)))

    job = extract(atlas, "budget", source_version_ids=[ten_k(atlas)])

    assert job["status"] == "succeeded", job["failures"]
    assert job["artifacts"]["status"] == "budget_exhausted"
    extraction = atlas.get(f"/api/v1/claim-extractions/{job['artifacts']['extraction_id']}")
    assert (extraction["batches_done"], extraction["batches_total"]) == (1, 3)
    assert extraction["finished_at"] is not None
    calls = atlas.get(f"/api/v1/runs/{extraction['run_id']}/role-calls")
    assert [c["status"] for c in calls["role_calls"]] == ["accepted", "budget_exhausted"]
    assert len(llm.chat_requests()) == 1
    atlas.engine.dispose()


def test_a_quarantined_answer_is_a_batch_with_no_claims(atlas: Atlas, llm: FakeLiteLLM) -> None:
    llm.script_chat(ChatReply.text("Coherent supplies NVIDIA."), ChatReply.text("{}"))

    job = extract(atlas, "quarantine", source_version_ids=[ten_k(atlas)])

    assert job["status"] == "succeeded", job["failures"]
    extraction = atlas.get(f"/api/v1/claim-extractions/{job['artifacts']['extraction_id']}")
    assert (extraction["status"], extraction["batches_quarantined"]) == ("completed", 1)
    assert (extraction["accepted"], extraction["rejected"]) == (0, 0)
    [call] = atlas.get(f"/api/v1/runs/{extraction['run_id']}/role-calls")["role_calls"]
    assert call["status"] == "quarantined"


# --- skipped versions, API, metrics, immutability ------------------------------------------


def test_versions_that_are_unknown_or_have_no_parsed_text_are_skipped_with_the_reason(
    atlas: Atlas, llm: FakeLiteLLM
) -> None:
    missing = str(uuid.uuid4())
    llm.script_chat(ChatReply.json({"claims": []}))

    job = extract(atlas, "skip", source_version_ids=[missing, ten_k(atlas)])

    extraction = atlas.get(f"/api/v1/claim-extractions/{job['artifacts']['extraction_id']}")
    assert extraction["skipped"] == [{"source_version_id": missing, "reason": "not found"}]
    assert extraction["source_version_ids"] == [missing, ten_k(atlas)]
    assert extraction["passages"]


def test_unknown_claims_and_extractions_are_not_found(atlas: Atlas) -> None:
    for path in [f"/api/v1/claims/{uuid.uuid4()}", f"/api/v1/claim-extractions/{uuid.uuid4()}"]:
        response = atlas.api.get(path)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"


def test_metrics_count_claims_accepted_and_rejected_by_reason(
    atlas: Atlas, llm: FakeLiteLLM
) -> None:
    coherent, nvidia = company_id(atlas, "coherent"), company_id(atlas, "nvidia")
    before = atlas.metrics()
    assert before[("atlas_claims_total", frozenset({("outcome", "accepted")}))] == 0
    assert before[("atlas_claims_total", frozenset({("outcome", "rejected")}))] == 0
    supply = claim(
        subject_company_id=coherent,
        predicate="supplies",
        object_company_id=nvidia,
        quote=SUPPLY_QUOTE,
    )
    llm.script_chat(
        ChatReply.answer(quoting(supply, supply | {"layer": "optics"}, supply | {"layer": "?"}))
    )

    extract(atlas, "metrics", source_version_ids=[ten_k(atlas)])

    after = atlas.metrics()
    assert after[("atlas_claims_total", frozenset({("outcome", "accepted")}))] == 1
    assert after[("atlas_claims_total", frozenset({("outcome", "rejected")}))] == 2
    assert after[("atlas_claims_rejected_total", frozenset({("reason", "unknown_layer")}))] == 2


def test_a_claim_s_outcome_is_insert_only(atlas: Atlas, llm: FakeLiteLLM) -> None:
    llm.script_chat(
        ChatReply.answer(
            quoting(claim(subject_company_id="nobody", predicate="supplies", quote=SUPPLY_QUOTE))
        )
    )
    job = extract(atlas, "immutable", source_version_ids=[ten_k(atlas)])
    (rejected,) = claims_of(atlas, job["artifacts"]["extraction_id"])

    for statement in [
        "UPDATE claim SET outcome = 'accepted' WHERE id = :id",
        "DELETE FROM claim WHERE id = :id",
    ]:
        with pytest.raises(DBAPIError, match="insert-only"), atlas.engine.begin() as connection:
            connection.execute(text(statement), {"id": rejected["id"]})


# --- claim precision (pilot-fixes ticket 09) ------------------------------------------------------

# Two generic risk-factor sentences from Lumentum's FY2026 10-K (as the pilot's Claims quoted
# them), a specific one, and the Coherent 10-K's VCSEL sentence, in a hand-written Coherent
# document; its last line names NVIDIA, so the Investigator is sent it (an entity tag).
GENERIC_LIMITED = (
    "We purchase raw materials, packages and components from a limited number of suppliers."
)
GENERIC_SOLE = (
    "Additionally, some of our suppliers are our sole sources for certain materials, equipment"
    " and components."
)
SPECIFIC = "We purchase InP substrates from a limited number of suppliers."
VCSEL = (
    "We continue to expand our global 6-inch InP manufacturing capacity in the United States and"
    " Europe to support increasing customer demand, while also operating multiple 6-inch GaAs"
    " VCSEL manufacturing facilities."
)
PRECISION_DOCUMENT = f"""<html><head><title>Coherent supply notes</title></head><body>
<h1>Coherent supply notes</h1>
<p>{GENERIC_LIMITED}</p>
<p>{GENERIC_SOLE}</p>
<p>{SPECIFIC}</p>
<p>{VCSEL}</p>
<p>We also supply 800G transceivers to NVIDIA.</p>
</body></html>
"""


def precision_document(atlas: Atlas) -> str:
    path = atlas.tmp_path / "coherent-supply-notes.html"
    path.write_text(PRECISION_DOCUMENT, encoding="utf-8")
    imported = atlas.cli(
        "sources",
        "import",
        "--company",
        "coherent",
        "--file",
        str(path),
        "--origin-url",
        "https://www.coherent.com/news/supply-notes",
        "--published-at",
        "2026-08-14T08:00-04:00",
    )
    assert imported.returncode == 0, imported.stderr
    return json.loads(imported.stdout)["source_version_id"]


def test_a_generic_sentence_is_no_substrate_claim_and_a_cue_must_share_the_object_s_clause(
    atlas: Atlas, llm: FakeLiteLLM
) -> None:
    coherent = company_id(atlas, "coherent")
    version_id = precision_document(atlas)

    def fact(predicate: str, object_text: str, quote: str, layer: str) -> dict[str, JsonValue]:
        return claim(
            subject_company_id=coherent,
            predicate=predicate,
            object_text=object_text,
            layer=layer,
            quote=quote,
        )

    llm.script_chat(
        ChatReply.answer(
            quoting(
                fact(
                    "sole_sources",
                    "raw materials, packages and components",
                    GENERIC_LIMITED,
                    "substrate",
                ),
                fact(
                    "sole_sources",
                    "certain materials, equipment and components",
                    GENERIC_SOLE,
                    "substrate",
                ),
                fact("sole_sources", "InP substrates", SPECIFIC, "substrate"),
                fact("sole_sources", "indium phosphide substrates", SPECIFIC, "substrate"),
                fact(
                    "expands_capacity_for",
                    "6-inch GaAs VCSEL manufacturing facilities",
                    VCSEL,
                    "chip-laser",
                ),
                fact(
                    "expands_capacity_for", "6-inch InP manufacturing capacity", VCSEL, "chip-laser"
                ),
            )
        )
    )

    job = extract(atlas, "precision", source_version_ids=[version_id])

    assert job["status"] == "succeeded", job["failures"]
    outcomes = claims_of(atlas, job["artifacts"]["extraction_id"])
    assert [(c["outcome"], c["reason_code"]) for c in outcomes] == [
        ("rejected", "generic_object"),
        ("rejected", "generic_object"),
        ("accepted", None),
        ("rejected", "object_not_in_quote"),
        ("rejected", "cue_in_other_clause"),
        ("accepted", None),
    ]
    # The generic sentences' rejections name the layer they were tagged with.
    assert all("'substrate'" in c["reason"] for c in outcomes[:2])
    specific = atlas.get(f"/api/v1/assertions/{outcomes[2]['assertion_id']}")
    assert specific["value_json"]["layer"] == "substrate"
    assert specific["value_json"]["object_text"] == "InP substrates"
    assert outcomes[2]["directional_cue"] == "limited number of suppliers"
    assert "VCSEL" in outcomes[4]["reason"]
    assert outcomes[5]["directional_cue"] == "expand"
    assert audit_actions(atlas, "claim") == [
        "claim.rejected",
        "claim.rejected",
        "claim.accepted",
        "claim.rejected",
        "claim.rejected",
        "claim.accepted",
    ]


# --- claim checks (memory-directed reading ticket 02) -------------------------------------------

# Hand-shaped fragments of the documents pilot investigation 1 read on 0.2.5 (the recorded
# fixtures hold only the last): Coherent's 8-K filed 2026-03-02 (the NVIDIA agreement), its
# 10-Q filed 2026-05-06 (the share issuance), its EX-99.2 slides (bullets with U+2011, a
# non-breaking hyphen) and its FY2026 10-K (the expansion sentence). TWO_OTHERS, OTHER_MAKER
# and CONSTRAINED are written for the tests: sentences naming other companies and not the
# filer, and a constraint that names no product.
NBH = "\N{NON-BREAKING HYPHEN}"
NVIDIA_COMMITMENT = (
    "The non-exclusive agreement includes an NVIDIA multi-billion-dollar purchase commitment and"
    " future access and capacity rights for advanced laser and optical networking products."
)
TWO_OTHERS = (
    "NVIDIA also entered into a multi-billion-dollar purchase commitment with Lumentum for"
    " advanced laser components."
)
OTHER_MAKER = "Lumentum produces EML chips on 3-inch and 4-inch InP wafers."
ISSUANCE = (
    "On March 2, 2026, the Company issued and sold 7,788,161 shares of Common Stock to NVIDIA"
    " for an aggregate purchase price of $2.0 billion."
)
SLIDE_PLATFORM = (
    f"6{NBH}inch platform producing EMLs, CW lasers, and photodiodes, with higher yields than"
    f" 3{NBH}inch lines"
)
SLIDE_LINE = f"New 6{NBH}inch line begins production in Sherman"
EXPANSION = (
    "we remain disciplined in our capital allocation, prioritizing investments to expand"
    " manufacturing capacity so we can efficiently fulfill the ongoing acceleration in customer"
    " demand."
)
CONSTRAINED = "We are experiencing supply constraints due to constrained manufacturing capacity."
FILER_DOCUMENT = f"""<html><head><meta charset="utf-8"><title>Coherent agreement and slides</title>
</head><body>
<h1>Coherent: the NVIDIA agreement, the share issuance and the slides</h1>
<p>{NVIDIA_COMMITMENT}</p>
<p>{TWO_OTHERS}</p>
<p>{OTHER_MAKER}</p>
<p>{ISSUANCE}</p>
<ul><li>{SLIDE_PLATFORM}</li><li>{SLIDE_LINE}</li></ul>
<p>In fiscal 2026 {EXPANSION}</p>
<p>{CONSTRAINED}</p>
</body></html>
"""
THIRD_PARTY_DOCUMENT = f"""<html><head><title>Lumentum agreement</title></head><body>
<h1>Lumentum: the NVIDIA agreement</h1>
<p>{NVIDIA_COMMITMENT}</p>
</body></html>
"""


def import_document(atlas: Atlas, company: str, name: str, document: str) -> str:
    """`document` imported by hand as `company`'s own (so `company` is its filer)."""
    path = atlas.tmp_path / f"{name}.html"
    path.write_text(document, encoding="utf-8")
    imported = atlas.cli(
        "sources",
        "import",
        "--company",
        company,
        "--file",
        str(path),
        "--origin-url",
        f"https://example.com/{company}/{name}",
        "--published-at",
        "2026-08-14T08:00-04:00",
    )
    assert imported.returncode == 0, imported.stderr
    return json.loads(imported.stdout)["source_version_id"]


def test_the_filer_s_impersonal_sentence_is_a_claim_about_the_filer_and_co_mention_is_not(
    atlas: Atlas, llm: FakeLiteLLM
) -> None:
    coherent, nvidia = company_id(atlas, "coherent"), company_id(atlas, "nvidia")
    lumentum = company_id(atlas, "lumentum")
    version_id = import_document(atlas, "coherent", "agreement-and-slides", FILER_DOCUMENT)
    supply = claim(
        subject_company_id=coherent,
        predicate="supplies",
        object_company_id=nvidia,
        product="advanced laser and optical networking products",
        quote=NVIDIA_COMMITMENT,
    )
    llm.script_chat(
        ChatReply.answer(
            quoting(
                supply,
                # NVIDIA is the buyer: the commitment is NVIDIA's.
                supply | {"predicate": "buys_from"},
                # Two other companies named and not the filer: co-mention, for either object.
                supply | {"quote": TWO_OTHERS},
                supply | {"quote": TWO_OTHERS, "object_company_id": lumentum},
                claim(
                    subject_company_id=coherent,
                    predicate="manufactures",
                    object_text="EML chips",
                    quote=OTHER_MAKER,
                ),
            )
        )
    )

    job = extract(atlas, "filer", source_version_ids=[version_id])

    assert job["status"] == "succeeded", job["failures"]
    filer, reversed_, *co_mentions = claims_of(atlas, job["artifacts"]["extraction_id"])
    assert (filer["outcome"], filer["reason_code"]) == ("accepted", None)
    assert (filer["party_basis"], filer["offset_source"]) == ("filer", "model")
    assert filer["directional_cue"] == "purchase commitment"
    assertion = atlas.get(f"/api/v1/assertions/{filer['assertion_id']}")
    assert (assertion["subject_company_id"], assertion["predicate"]) == (coherent, "supplies")
    assert assertion["object_company_id"] == nvidia
    assert assertion["quote"] == NVIDIA_COMMITMENT
    assert (reversed_["outcome"], reversed_["reason_code"]) == ("rejected", "wrong_direction")
    assert "buyer" in reversed_["reason"]
    assert [(c["outcome"], c["reason_code"]) for c in co_mentions] == [
        ("rejected", "party_not_in_quote")
    ] * 3
    assert "Lumentum" in co_mentions[0]["reason"]
    assert "NVIDIA" in co_mentions[1]["reason"]
    assert "Lumentum" in co_mentions[2]["reason"]
    assert all("co-mention" in c["reason"] for c in co_mentions)
    assert [c["party_basis"] for c in (reversed_, *co_mentions)] == [None] * 4

    # The same sentence in another company's document says nothing about Coherent; it is
    # that company's own impersonal sentence.
    third_party = import_document(atlas, "lumentum", "agreement", THIRD_PARTY_DOCUMENT)
    llm.script_chat(ChatReply.answer(quoting(supply, supply | {"subject_company_id": lumentum})))

    job = extract(atlas, "third-party", source_version_ids=[third_party])

    assert job["status"] == "succeeded", job["failures"]
    not_its_filer, its_filer = claims_of(atlas, job["artifacts"]["extraction_id"])
    assert (not_its_filer["outcome"], not_its_filer["reason_code"]) == (
        "rejected",
        "party_not_in_quote",
    )
    assert "Coherent" in not_its_filer["reason"]
    assert (its_filer["outcome"], its_filer["party_basis"]) == ("accepted", "filer")
    assert its_filer["subject_company_id"] == lumentum


def ascii_hyphens(text: str) -> str:
    """The text as a model that writes "-" for a non-breaking hyphen copies it."""
    return text.replace(NBH, "-")


def test_a_quote_differing_only_by_typographic_characters_is_placed_through_the_fold(
    atlas: Atlas, llm: FakeLiteLLM
) -> None:
    coherent = company_id(atlas, "coherent")
    version_id = import_document(atlas, "coherent", "agreement-and-slides", FILER_DOCUMENT)
    written = "6-inch platform producing EMLs, CW lasers, and photodiodes"
    archived = f"6{NBH}inch platform producing EMLs, CW lasers, and photodiodes"
    bullet = claim(
        subject_company_id=coherent,
        predicate="manufactures",
        object_text="EMLs",
        product="EMLs",
        quote=written,
    )
    another_word = written.replace("EMLs", "DMLs")
    llm.script_chat(
        ChatReply.answer(
            quoting(
                bullet,
                bullet | {"shift": 7},
                bullet
                | {
                    "quote": another_word,
                    "passage_id": "p1",
                    "quote_start": 0,
                    "quote_end": len(another_word),
                },
                # Two bullets write "6-inch" (with U+2011), and the offsets point at neither.
                bullet | {"quote": "6-inch", "shift": 2},
                read=ascii_hyphens,
            )
        )
    )

    job = extract(atlas, "fold", source_version_ids=[version_id])

    assert job["status"] == "succeeded", job["failures"]
    at_offsets, searched, mismatch, ambiguous = claims_of(atlas, job["artifacts"]["extraction_id"])
    parsed = atlas.parsed(version_id)
    assert archived in parsed
    assert written not in parsed
    for folded in (at_offsets, searched):
        assert (folded["outcome"], folded["reason_code"]) == ("accepted", None)
        assert (folded["offset_source"], folded["party_basis"]) == ("folded", "filer")
        # The Claim and its Assertion hold the archived text at the span, never the model's
        # spelling, which stays in `proposed`.
        assert folded["quote"] == archived
        assert folded["proposed"]["quote"] == written
        assert parsed[folded["span_start"] : folded["span_end"]] == archived
        assert folded["directional_cue"] == "producing"
        assertion = atlas.get(f"/api/v1/assertions/{folded['assertion_id']}")
        assert assertion["quote"] == archived
        assert (assertion["span_start"], assertion["span_end"]) == (
            folded["span_start"],
            folded["span_end"],
        )
        assert (assertion["subject_company_id"], assertion["predicate"]) == (
            coherent,
            "manufactures",
        )
    assert searched["proposed"]["quote_start"] == at_offsets["proposed"]["quote_start"] + 7
    assert (mismatch["outcome"], mismatch["reason_code"]) == ("rejected", "quote_mismatch")
    assert (ambiguous["outcome"], ambiguous["reason_code"]) == ("rejected", "quote_ambiguous")
    assert "2 occurrences" in ambiguous["reason"]
    assert [c["offset_source"] for c in (mismatch, ambiguous)] == [None, None]


def test_an_expansion_is_no_constraint_and_owns_runs_from_the_holder_to_the_issuer(
    atlas: Atlas, llm: FakeLiteLLM
) -> None:
    coherent, nvidia = company_id(atlas, "coherent"), company_id(atlas, "nvidia")
    version_id = import_document(atlas, "coherent", "agreement-and-slides", FILER_DOCUMENT)

    def constrained(quote: str) -> dict[str, JsonValue]:
        return claim(
            subject_company_id=coherent,
            predicate="capacity_constrained",
            object_text="manufacturing capacity",
            layer="module",
            quote=quote,
        )

    owns = claim(
        subject_company_id=nvidia,
        predicate="owns",
        object_company_id=coherent,
        quote=ISSUANCE,
        epistemic_type="direct_source_statement",
    )
    llm.script_chat(
        ChatReply.answer(
            quoting(
                constrained(EXPANSION),
                constrained(CONSTRAINED),
                owns,
                owns | {"subject_company_id": coherent, "object_company_id": nvidia},
            )
        )
    )

    job = extract(atlas, "cues", source_version_ids=[version_id])

    assert job["status"] == "succeeded", job["failures"]
    expansion, no_product, holder, issuer = claims_of(atlas, job["artifacts"]["extraction_id"])
    # "capital allocation" and "expand manufacturing capacity" are no language of constraint.
    assert (expansion["outcome"], expansion["reason_code"]) == (
        "rejected",
        "no_directional_language",
    )
    # A real constraint, of no particular product.
    assert (no_product["outcome"], no_product["reason_code"]) == ("rejected", "generic_object")
    assert (holder["outcome"], holder["reason_code"]) == ("accepted", None)
    assert (holder["party_basis"], holder["directional_cue"]) == ("named", "shares")
    owned = atlas.get(f"/api/v1/assertions/{holder['assertion_id']}")
    assert (owned["subject_company_id"], owned["object_company_id"]) == (nvidia, coherent)
    assert (issuer["outcome"], issuer["reason_code"]) == ("rejected", "wrong_direction")
    assert "holder" in issuer["reason"]
    assert "NVIDIA" in issuer["reason"]
    assert atlas.get("/api/v1/claims", reason_code="wrong_direction")["total"] == 1


# --- a layer only when the quote supports one (memory-directed reading ticket 08) ---------------

# The Coherent FY2026 10-K's sentence (in the recorded fixture) that pilot investigation 1 on
# 0.2.5 tagged `substrate`, with ISSUANCE (hand-shaped, above) and SPECIFIC in a hand-written
# Coherent document; ISSUANCE names NVIDIA, so the Investigator is sent it (an entity tag).
SHERMAN = (
    "We are investing in manufacturing capacity for the Datacenter and Communications markets,"
    " including expanding our indium phosphide capacity in Sherman, Texas, to address our"
    " increased customer demand and industry-wide shortage."
)
LAYER_DOCUMENT = f"""<html><head><title>Coherent capacity and capital</title></head><body>
<h1>Coherent: capacity and capital</h1>
<p>{ISSUANCE}</p>
<p>{SHERMAN}</p>
<p>{SPECIFIC}</p>
</body></html>
"""


def test_a_claim_keeps_its_layer_only_when_the_quote_or_the_object_names_it(
    atlas: Atlas, llm: FakeLiteLLM
) -> None:
    coherent, nvidia = company_id(atlas, "coherent"), company_id(atlas, "nvidia")
    version_id = import_document(atlas, "coherent", "capacity-and-capital", LAYER_DOCUMENT)
    assert SHERMAN in atlas.parsed(ten_k(atlas))  # the recorded filing's own sentence

    def expands(object_text: str, layer: str | None) -> dict[str, JsonValue]:
        return claim(
            subject_company_id=coherent,
            predicate="expands_capacity_for",
            object_text=object_text,
            layer=layer,
            quote=SHERMAN,
        )

    llm.script_chat(
        ChatReply.answer(
            quoting(
                # The question's layer on an ownership stake: the quote names no layer.
                claim(
                    subject_company_id=nvidia,
                    predicate="owns",
                    object_company_id=coherent,
                    layer="chip-laser",
                    quote=ISSUANCE,
                    epistemic_type="direct_source_statement",
                ),
                # InP is a substrate, an epitaxial wafer and a laser chip alike: no layer.
                expands("indium phosphide capacity in Sherman, Texas", "substrate"),
                # The object names the layer.
                claim(
                    subject_company_id=coherent,
                    predicate="sole_sources",
                    object_text="InP substrates",
                    layer="substrate",
                    quote=SPECIFIC,
                ),
                # No layer proposed at all, and another layer than the object names.
                expands("indium phosphide capacity", None),
                claim(
                    subject_company_id=coherent,
                    predicate="sole_sources",
                    object_text="InP substrates",
                    layer="epi",
                    quote=SPECIFIC,
                ),
            )
        )
    )

    job = extract(atlas, "layers", source_version_ids=[version_id])

    assert job["status"] == "succeeded", job["failures"]
    owns, sherman, substrates, unproposed, other = claims_of(
        atlas, job["artifacts"]["extraction_id"]
    )
    assert [c["outcome"] for c in (owns, sherman, substrates, unproposed, other)] == [
        "accepted"
    ] * 5
    layers = [
        (c["layer"], c["layer_term"], c["layer_reason"], c["proposed"]["layer"])
        for c in (owns, sherman, substrates, unproposed, other)
    ]
    assert layers == [
        (None, None, "layer_unsupported", "chip-laser"),
        (None, None, "layer_unsupported", "substrate"),
        ("substrate", "substrates", None, "substrate"),
        (None, None, None, None),
        (None, None, "layer_unsupported", "epi"),
    ]
    # The Assertion carries the layer the Claim kept, or none.
    for accepted in (owns, sherman, substrates, unproposed, other):
        assertion = atlas.get(f"/api/v1/assertions/{accepted['assertion_id']}")
        assert assertion["value_json"]["layer"] == accepted["layer"]
    # The layers are sent as before; the response schema lets `layer` be null.
    [body] = llm.chat_requests()
    schema = body["response_format"]["json_schema"]["schema"]
    assert schema["$defs"]["ProposedClaim"]["properties"]["layer"]["anyOf"] == [
        {"type": "string"},
        {"type": "null"},
    ]
    sent_layers = asked(body)["request"]["layers"]
    assert [layer["name"] for layer in sent_layers] == LAYERS
    # ... each with the words Atlas takes as naming it, so the model knows what keeps a layer.
    assert sent_layers[0]["terms"] == ["substrate", "bare wafer", "boule", "ingot"]
    assert all(layer["terms"] for layer in sent_layers)
    # A layer that is no layer at all is still a rejection.
    llm.script_chat(ChatReply.answer(quoting(expands("indium phosphide capacity", "optics"))))
    again = extract(atlas, "unknown", source_version_ids=[version_id])
    (unknown,) = claims_of(atlas, again["artifacts"]["extraction_id"])
    assert (unknown["outcome"], unknown["reason_code"]) == ("rejected", "unknown_layer")
    assert (unknown["layer"], unknown["layer_reason"]) == ("optics", None)
