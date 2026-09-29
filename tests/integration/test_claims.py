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
from tests.harness import THEMES, Atlas, Clock, at

COHR_10K = "https://www.sec.gov/Archives/edgar/data/820318/000082031826000020/iivi-20260630.htm"
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
]
LAYERS = ["substrate", "epi", "chip_laser", "dsp", "module", "contract_manufacturing", "system"]


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
        "country": "US",
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
        "object_text": None,
        "product": None,
        "layer": "chip_laser",
        "epistemic_type": "company_claim",
        **fields,
    }


def quoting(*claims: dict[str, JsonValue]) -> Callable[[dict[str, Any]], JsonValue]:
    """An Investigator answer quoting the passages it is sent: each claim without a
    `passage_id` gets the passage whose text holds its quote and the quote's offsets there
    (`shift` moves both offsets, to propose a wrong span)."""

    def respond(body: dict[str, Any]) -> JsonValue:
        passages = asked(body)["retrieved_data"]
        answered: list[JsonValue] = []
        for each in claims:
            proposed = dict(each)
            shift = int(str(proposed.pop("shift", 0)))
            if "passage_id" not in proposed:
                quote = str(proposed["quote"])
                holding = [p for p in passages if quote in p["text"]]
                assert holding, f"no passage sent holds {quote!r}"
                start = holding[0]["text"].index(quote) + shift
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
        assert assertion["extractor_version"] == "investigator.v1"
        assert assertion["created_by"] == "atlas-investigator"
        assert assertion["value_json"]["claim_id"] == accepted["id"]
    supplied = atlas.get(f"/api/v1/assertions/{supplies['assertion_id']}")
    assert (supplied["subject_company_id"], supplied["predicate"]) == (coherent, "supplies")
    assert supplied["object_company_id"] == nvidia
    assert supplied["epistemic_type"] == "company_claim"
    assert supplied["value_json"]["layer"] == "chip_laser"
    assert supplied["value_json"]["product"] == "advanced lasers"
    assert supplies["directional_cue"] == "supply"
    owned = atlas.get(f"/api/v1/assertions/{owns['assertion_id']}")
    assert (owned["subject_company_id"], owned["predicate"]) == (nvidia, "owns")
    assert owned["object_company_id"] == coherent
    # Direction is never inferred: one Claim, one Assertion, with the predicate proposed.
    all_assertions = atlas.get("/api/v1/assertions", source_version_id=version_id)["items"]
    assert sorted(a["predicate"] for a in all_assertions) == ["owns", "supplies"]
    assert audit_actions(atlas, "claim") == ["claim.accepted", "claim.accepted"]


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


def test_recall_hits_for_a_question_add_their_sections_after_the_entity_tagged_ones(
    atlas: Atlas, llm: FakeLiteLLM, fake: RecordedHindsight
) -> None:
    version_id = ten_k(atlas)
    llm.script_chat(ChatReply.json({"claims": []}))

    job = extract(
        atlas, "cohr-question", source_version_ids=[version_id], question="Who buys lasers?"
    )

    (recall,) = fake.requests("POST", "memories/recall")
    assert recall["tags"] == [f"company:{company_id(atlas, 'coherent')}"]
    assert recall["tags_match"] == "any_strict"
    extraction = atlas.get(f"/api/v1/claim-extractions/{job['artifacts']['extraction_id']}")
    assert extraction["question"] == "Who buys lasers?"
    selected = [p["selected_by"] for p in extraction["passages"]]
    tagged = [s for s in selected if any(tag.startswith("entity:") for tag in s)]
    recalled_only = [s for s in selected if s == ["recall"]]
    assert tagged and recalled_only
    assert selected == tagged + recalled_only
    # At most the configured number of passages; the rest are counted, not sent.
    assert len(selected) == 24
    assert extraction["passages_dropped"] > 0


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
                supply | {"shift": -3},
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
    assert rejected[1]["proposed"]["predicate"] == "partners with"
    # A wrong span is never moved to where the quote really is: the reason says where.
    mismatch = rejected[7]
    assert "it occurs at" in mismatch["reason"]
    assert atlas.parsed(version_id)[mismatch["span_start"] : mismatch["span_end"]] != SUPPLY_QUOTE
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
    clock = Clock(at("2026-10-01T12:00:00+00:00"))
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
