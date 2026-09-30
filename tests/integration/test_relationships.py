"""Relationships and review (Phase 3-6a ticket 12; spec "Relationships", "Review"; §5.5).

Seam: the `atlas` CLI seeds the universe and enqueues `extract_claims` and
`review_relationships` jobs, single worker passes run them, and everything is observed
through `/api/v1` (relationships, their exceptions queue and owner review, assertions,
source-version content, runs' role calls, metrics) and the audit trail. The Source Versions
are the recorded Coherent EDGAR filings; the Tier B copy of the 10-K is inserted by the test,
since no adapter records a non-Tier A source yet. LiteLLM is the scripted chat fake: **the
Investigator's and the Reviewer's answers are written here**, computed from what each call
was sent. The test universe is the repo's plus NVIDIA, which the 10-K names.
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
# "supplier" and both names, but NVLink is NVIDIA's technology, not a purchase by NVIDIA.
NVLINK_QUOTE = (
    "Coherent is a leading supplier of optical transceivers for AI datacenter and networking"
    " applications, offering a comprehensive, protocol-agnostic portfolio supporting Ethernet,"
    " InfiniBand, NVIDIA NVLink, and other AI networking architectures."
)
HEDGED_QUOTE = (
    "Any loss, cancellation, reduction, or delay in purchases by these large customers could"
    " harm the longevity of our business."
)
PEER_GROUP_QUOTE = (
    "The Company\N{RIGHT SINGLE QUOTATION MARK}s peer group includes IPG Photonics Corp.,"
    " Wolfspeed Inc., Lumentum Holdings, Inc., Corning, Inc., MKS Instruments, Inc., and"
    " Honeywell International, Inc."
)
STATES = ["machine_reviewed", "needs_human_review", "approved", "rejected"]


# --- fixtures -----------------------------------------------------------------------------------


@pytest.fixture
def hindsight_fake() -> RecordedHindsight:
    fake = RecordedHindsight()
    fake.derive_memories()
    return fake


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
    settings: dict[str, Any] = {"themes_config": themes, "investigator_passages_per_call": 50}
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
    return {
        "object_company_id": None,
        "object_name": None,
        "object_text": None,
        "product": None,
        "layer": "chip-laser",
        "epistemic_type": "company_claim",
        **fields,
    }


def quoting(*claims: dict[str, JsonValue]) -> Callable[[dict[str, Any]], JsonValue]:
    """An Investigator answer quoting the passages it is sent (the passage holding each
    quote, and the quote's offsets in it)."""

    def respond(body: dict[str, Any]) -> JsonValue:
        passages = asked(body)["retrieved_data"]
        answered: list[JsonValue] = []
        for each in claims:
            quote = str(each["quote"])
            holding = [p for p in passages if quote in p["text"]]
            assert holding, f"no passage sent holds {quote!r}"
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


def verdict(
    verdict: str = "confirmed",
    direction: str = "as_proposed",
    layer: str = "correct",
    suggested_layer: str | None = None,
) -> dict[str, JsonValue]:
    return {
        "verdict": verdict,
        "direction": direction,
        "layer": layer,
        "suggested_layer": suggested_layer,
        "reasoning": f"{verdict}; direction {direction}; layer {layer}",
    }


CONFIRMED = verdict()


def reviewing(
    by_quote: dict[str, dict[str, JsonValue]] | None = None,
    *,
    expect: int | None = None,
) -> Callable[[dict[str, Any]], JsonValue]:
    """A Reviewer answer for every item it is sent: the verdict for the item's quoted text
    (from `retrieved_data`), `CONFIRMED` for any other. `expect`: how many items it must get."""

    def respond(body: dict[str, Any]) -> JsonValue:
        sent = asked(body)
        quotes = {q["id"]: q["text"] for q in sent["retrieved_data"]}
        items = sent["request"]["items"]
        if expect is not None:
            assert len(items) == expect, items
        reviews: list[JsonValue] = []
        for item in items:
            quote = quotes[f"{item['item_id']}:quote"]
            reviews.append({"item_id": item["item_id"], **(by_quote or {}).get(quote, CONFIRMED)})
        return {"reviews": reviews}

    return respond


def extract(atlas: Atlas, llm: FakeLiteLLM, key: str, *claims: dict[str, JsonValue]) -> None:
    llm.script_chat(ChatReply.answer(quoting(*claims)))
    payload = json.dumps({"source_version_ids": [ten_k(atlas)]})
    job_id = atlas.enqueue("jobs", "enqueue", "extract_claims", "--key", key, "--payload", payload)
    atlas.worker_pass()
    job = atlas.get(f"/api/v1/jobs/{job_id}")
    assert job["status"] == "succeeded", job["failures"]
    assert job["artifacts"]["accepted"] == len(claims), atlas.get("/api/v1/claims")


def review(atlas: Atlas, key: str, **payload: JsonValue) -> dict[str, Any]:
    """Enqueue `review_relationships` through the CLI, run one worker pass, return the job."""
    job_id = atlas.enqueue(
        "jobs", "enqueue", "review_relationships", "--key", key, "--payload", json.dumps(payload)
    )
    atlas.worker_pass()
    return atlas.get(f"/api/v1/jobs/{job_id}")


def relationships(atlas: Atlas, **params: Any) -> list[dict[str, Any]]:
    return atlas.get("/api/v1/relationships", limit=500, **params)["items"]


def owner_review(atlas: Atlas, relationship_id: str, state: str, note: str | None = None) -> Any:
    return atlas.api.post(
        f"/api/v1/relationships/{relationship_id}/review",
        json={"review_state": state, "note": note},
    )


def audit_trail(atlas: Atlas, entity_type: str) -> list[tuple[str, str]]:
    with atlas.engine.connect() as connection:
        return [
            (row.actor, row.action)
            for row in connection.execute(
                text("SELECT actor, action FROM audit_event WHERE entity_type = :type ORDER BY id"),
                {"type": entity_type},
            )
        ]


def supply(atlas: Atlas, quote: str = SUPPLY_QUOTE, **fields: JsonValue) -> dict[str, JsonValue]:
    values: dict[str, JsonValue] = {"product": "advanced lasers", **fields}
    return claim(
        subject_company_id=company_id(atlas, "coherent"),
        predicate="supplies",
        object_company_id=company_id(atlas, "nvidia"),
        quote=quote,
        **values,
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


def tier_b_copy(atlas: Atlas) -> str:
    """A Tier B copy of the 10-K (the same parse at a trade-press URL), put into its Evidence
    Family by `atlas ledger assign-families`. No adapter records a Tier B source yet."""
    copy_document, copy_version = uuid.uuid4(), uuid.uuid4()
    with atlas.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO source_document (id, company_id, provider, canonical_url, origin_url,"
                " source_type, title, publisher, source_tier, license_class, first_seen_at)"
                " SELECT :id, d.company_id, 'trade-press', 'https://press.example.com/cohr-10k',"
                " 'https://press.example.com/cohr-10k', 'article', 'Coherent 10-K (copy)',"
                " 'Example Press', 'B', 'synthetic_fixture', now()"
                " FROM source_document d JOIN source_version v ON v.source_document_id = d.id"
                " WHERE v.id = :version"
            ),
            {"id": copy_document, "version": ten_k(atlas)},
        )
        connection.execute(
            text(
                "INSERT INTO source_version (id, source_document_id, version_number, raw_sha256,"
                " comparison_sha256, comparison_rule, object_uri, byte_size, media_type,"
                " content_sha256, parsed_object_uri, parser_version, parse_status,"
                " available_at, available_at_basis, fetched_at, fetch_status)"
                " SELECT :id, :document, 1, raw_sha256, comparison_sha256, comparison_rule,"
                " object_uri, byte_size, media_type, content_sha256, parsed_object_uri,"
                " parser_version, parse_status, available_at, 'observed_discovery', fetched_at,"
                " fetch_status FROM source_version WHERE id = :version"
            ),
            {"id": copy_version, "document": copy_document, "version": ten_k(atlas)},
        )
    assigned = atlas.cli("ledger", "assign-families")
    assert assigned.returncode == 0, assigned.stderr
    return str(copy_version)


def manual_assertion(
    atlas: Atlas,
    version_id: str,
    quote: str,
    *,
    subject: str,
    predicate: str,
    target: str,
    layer: str | None,
) -> str:
    parsed = atlas.parsed(version_id)
    start = parsed.index(quote)
    response = atlas.api.post(
        "/api/v1/assertions",
        json={
            "subject_company_id": company_id(atlas, subject),
            "predicate": predicate,
            "object_company_id": company_id(atlas, target),
            "value_json": None if layer is None else {"layer": layer, "product": None},
            "source_version_id": version_id,
            "quote": quote,
            "span_start": start,
            "span_end": start + len(quote),
            "epistemic_type": "third_party_report",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["assertion"]["id"]


# --- the gate -----------------------------------------------------------------------------------


def test_gate_a_reviewer_establishes_a_directed_supplier_edge_and_opens_its_source_span(
    atlas: Atlas, llm: FakeLiteLLM
) -> None:
    coherent, nvidia = company_id(atlas, "coherent"), company_id(atlas, "nvidia")
    extract(atlas, llm, "cohr-10k", supply(atlas))
    llm.script_chat(ChatReply.answer(reviewing(expect=1)))

    job = review(atlas, "sweep-1")

    assert job["status"] == "succeeded", job["failures"]
    artifacts = job["artifacts"]
    assert (artifacts["considered"], artifacts["machine_reviewed"]) == (1, 1)
    assert (artifacts["needs_human_review"], artifacts["not_eligible"]) == (0, 0)
    (edge,) = relationships(atlas)
    assert (edge["subject_company_id"], edge["predicate"], edge["object_company_id"]) == (
        coherent,
        "supplies",
        nvidia,
    )
    assert (edge["subject_name"], edge["object_name"], edge["object_text"]) == (
        "Coherent",
        "NVIDIA",
        None,
    )
    assert (edge["layer"], edge["products"]) == ("chip-laser", ["advanced lasers"])
    assert edge["review_state"] == "machine_reviewed"
    assert (edge["evidence_count"], edge["family_count"]) == (1, 1)
    assert artifacts["relationship_ids"] == [edge["id"]]

    # Open the edge, then its source span.
    detail = atlas.get(f"/api/v1/relationships/{edge['id']}")
    (evidence,) = detail["evidence"]
    assertion = atlas.get(f"/api/v1/assertions/{evidence['assertion']['id']}")
    assert assertion["predicate"] == "supplies"
    assert (evidence["source_tier"], evidence["source_title"]) == ("A", assertion_title(atlas))
    assert evidence["evidence_family_id"] is not None
    span = evidence["assertion"]
    parsed = atlas.parsed(span["source_version_id"])
    assert parsed[span["span_start"] : span["span_end"]] == SUPPLY_QUOTE
    machine = evidence["review"]
    assert (machine["verbatim_span"], machine["tier_a"]) == (True, True)
    assert (machine["directional_language"], machine["directional_cue"]) == ("explicit", "supply")
    assert (machine["reviewer_status"], machine["reviewer_verdict"]) == ("answered", "confirmed")
    assert (machine["reviewer_direction"], machine["reviewer_layer"]) == ("as_proposed", "correct")
    assert (machine["outcome"], machine["reasons"]) == ("machine_reviewed", [])
    assert machine["run_id"] == artifacts["run_id"]

    # The owner approves it (a material link a published Hypothesis may depend on).
    approved = owner_review(atlas, edge["id"], "approved", "checked the 10-K")
    assert approved.status_code == 200, approved.text
    body = approved.json()
    assert body["relationship"]["review_state"] == "approved"
    assert body["relationship"]["reviewed_by"] == "local-researcher"
    assert body["relationship"]["review_note"] == "checked the 10-K"
    assert body["audit_event_id"] > 0
    assert audit_trail(atlas, "relationship") == [
        ("atlas-reviewer", "relationship.created"),
        ("local-researcher", "relationship.approved"),
    ]
    assert audit_trail(atlas, "relationship_review") == [
        ("atlas-reviewer", "relationship_review.recorded")
    ]

    # A second sweep finds nothing new and calls no model.
    again = review(atlas, "sweep-2")
    assert again["status"] == "succeeded", again["failures"]
    assert again["artifacts"]["considered"] == 0
    assert len(llm.chat_requests()) == 2


def assertion_title(atlas: Atlas) -> str:
    return atlas.version(COHR_10K, "coherent")["source_document"]["title"]


def test_the_reviewer_is_sent_each_edge_with_its_quote_and_context_as_low_trust_data(
    atlas: Atlas, llm: FakeLiteLLM
) -> None:
    extract(atlas, llm, "cohr-10k", supply(atlas))
    llm.script_chat(ChatReply.answer(reviewing()))

    job = review(atlas, "sweep")

    _, body = llm.chat_requests()
    assert body["response_format"]["json_schema"]["name"] == "reviewer"
    assert body["metadata"] == {"run_id": job["artifacts"]["run_id"], "role": "reviewer"}
    sent = asked(body)
    (item,) = sent["request"]["items"]
    assert item["predicate"] == "supplies"
    assert "the object is the subject's customer" in item["reads"]
    assert item["subject"]["company_id"] == company_id(atlas, "coherent")
    assert "Coherent" in item["subject"]["names"]
    assert item["object_company"]["company_id"] == company_id(atlas, "nvidia")
    assert (item["object_text"], item["product"], item["layer"]) == (
        None,
        "advanced lasers",
        "chip-laser",
    )
    assert item["source"]["filer_company_id"] == company_id(atlas, "coherent")
    assert item["source"]["source_tier"] == "A"
    assert "chip-laser" in [layer["name"] for layer in sent["request"]["layers"]]
    # The source's words go only in retrieved_data, quoted and low-trust.
    quoted = {q["id"]: q for q in sent["retrieved_data"]}
    assert quoted[f"{item['item_id']}:quote"]["text"] == SUPPLY_QUOTE
    context = quoted[f"{item['item_id']}:context"]["text"]
    assert SUPPLY_QUOTE in context and len(context) > len(SUPPLY_QUOTE)
    assert {q["trust"] for q in quoted.values()} == {"low"}
    assert SUPPLY_QUOTE not in json.dumps(sent["request"])
    calls = atlas.get(f"/api/v1/runs/{job['artifacts']['run_id']}/role-calls")["role_calls"]
    assert [(c["role"], c["prompt_name"], c["status"]) for c in calls] == [
        ("reviewer", "reviewer", "accepted")
    ]


# --- the exceptions queue -------------------------------------------------------------------------


def test_rejected_uncertain_misdirected_or_mislayered_proposals_go_to_the_exceptions_queue(
    atlas: Atlas, llm: FakeLiteLLM
) -> None:
    extract(
        atlas,
        llm,
        "cohr-10k",
        supply(atlas),
        investment(atlas),
        supply(atlas, NVLINK_QUOTE, layer="module", product="optical transceivers"),
    )
    llm.script_chat(
        ChatReply.answer(
            reviewing(
                {
                    SUPPLY_QUOTE: verdict(layer="wrong", suggested_layer="module"),
                    INVESTMENT_QUOTE: verdict("uncertain"),
                    NVLINK_QUOTE: verdict("rejected", direction="not_stated"),
                },
                expect=3,
            )
        )
    )

    job = review(atlas, "sweep")

    assert job["status"] == "succeeded", job["failures"]
    assert (job["artifacts"]["machine_reviewed"], job["artifacts"]["needs_human_review"]) == (0, 3)
    assert relationships(atlas, review_state="machine_reviewed") == []
    queue = atlas.get("/api/v1/relationships/exceptions")
    assert queue["total"] == 3
    reasons = {(e["predicate"], e["layer"]): e["review_reasons"] for e in queue["items"]}
    assert reasons == {
        ("supplies", "chip-laser"): ["layer_not_confirmed"],
        ("owns", "system"): ["reviewer_uncertain"],
        ("supplies", "module"): ["reviewer_rejected", "direction_not_confirmed"],
    }
    assert {e["review_state"] for e in queue["items"]} == {"needs_human_review"}
    wrong_layer = next(e for e in queue["items"] if e["layer"] == "chip-laser")
    (evidence,) = atlas.get(f"/api/v1/relationships/{wrong_layer['id']}")["evidence"]
    assert evidence["review"]["reviewer_suggested_layer"] == "module"

    # The owner settles exceptions either way; settled ones leave the queue.
    owns = next(e for e in queue["items"] if e["predicate"] == "owns")
    assert owner_review(atlas, owns["id"], "approved").status_code == 200
    assert (
        owner_review(atlas, wrong_layer["id"], "rejected", "a laser, not a module").status_code
        == 200
    )
    left = atlas.get("/api/v1/relationships/exceptions")["items"]
    assert [(e["predicate"], e["layer"]) for e in left] == [("supplies", "module")]
    assert [a for _, a in audit_trail(atlas, "relationship")] == [
        "relationship.created",
        "relationship.created",
        "relationship.created",
        "relationship.approved",
        "relationship.rejected",
    ]


def test_tier_b_hedged_and_co_mention_evidence_is_checked_without_the_reviewer(
    atlas: Atlas, llm: FakeLiteLLM
) -> None:
    extract(atlas, llm, "cohr-10k", supply(atlas))
    copy = tier_b_copy(atlas)
    copied = manual_assertion(
        atlas,
        copy,
        SUPPLY_QUOTE,
        subject="coherent",
        predicate="supplies",
        target="nvidia",
        layer="chip-laser",
    )
    hedged = manual_assertion(
        atlas,
        ten_k(atlas),
        HEDGED_QUOTE,
        subject="coherent",
        predicate="supplies",
        target="lumentum",
        layer="module",
    )
    co_mention = manual_assertion(
        atlas,
        ten_k(atlas),
        PEER_GROUP_QUOTE,
        subject="coherent",
        predicate="supplies",
        target="lumentum",
        layer="module",
    )
    no_layer = manual_assertion(
        atlas,
        ten_k(atlas),
        SUPPLY_QUOTE,
        subject="coherent",
        predicate="supplies",
        target="nvidia",
        layer=None,
    )
    # Only the Tier A, verbatim, explicit Assertion reaches the Reviewer.
    llm.script_chat(ChatReply.answer(reviewing(expect=1)))

    job = review(atlas, "sweep")

    assert job["status"] == "succeeded", job["failures"]
    artifacts = job["artifacts"]
    assert (artifacts["considered"], artifacts["machine_reviewed"]) == (5, 1)
    assert (artifacts["needs_human_review"], artifacts["not_eligible"]) == (2, 2)
    assert len(llm.chat_requests()) == 2
    # The Tier B copy is a second piece of Evidence in the same family: one witness.
    (supplied,) = relationships(atlas, layer="chip-laser")
    assert supplied["review_state"] == "machine_reviewed"
    assert (supplied["evidence_count"], supplied["family_count"]) == (2, 1)
    evidence = {
        e["assertion"]["id"]: e
        for e in atlas.get(f"/api/v1/relationships/{supplied['id']}")["evidence"]
    }
    assert evidence[copied]["source_tier"] == "B"
    assert (evidence[copied]["review"]["outcome"], evidence[copied]["review"]["reasons"]) == (
        "needs_human_review",
        ["not_tier_a"],
    )
    assert evidence[copied]["review"]["reviewer_status"] == "skipped"
    assert len({e["evidence_family_id"] for e in evidence.values()}) == 1
    # Hedged language is a Relationship for a human; co-mention and a missing layer are none.
    (hedged_edge,) = relationships(atlas, review_state="needs_human_review")
    assert hedged_edge["object_company_id"] == company_id(atlas, "lumentum")
    assert hedged_edge["review_reasons"] == ["hedged_language"]
    (hedged_evidence,) = atlas.get(f"/api/v1/relationships/{hedged_edge['id']}")["evidence"]
    assert hedged_evidence["assertion"]["id"] == hedged
    assert hedged_evidence["review"]["hedge"] == "could"
    refused = {
        each["assertion_id"]: each["reason"] for each in artifacts["not_eligible_assertions"]
    }
    assert refused == {co_mention: "no_directional_language", no_layer: "unknown_layer"}
    assert len(relationships(atlas)) == 2


# --- the edge-table list --------------------------------------------------------------------------


def test_relationships_sort_and_filter_by_layer_review_state_and_company(
    atlas: Atlas, llm: FakeLiteLLM
) -> None:
    extract(
        atlas,
        llm,
        "cohr-10k",
        supply(atlas),
        investment(atlas),
        supply(atlas, NVLINK_QUOTE, layer="module", product="optical transceivers"),
    )
    copy = tier_b_copy(atlas)
    manual_assertion(
        atlas,
        copy,
        SUPPLY_QUOTE,
        subject="coherent",
        predicate="supplies",
        target="nvidia",
        layer="chip-laser",
    )
    llm.script_chat(ChatReply.answer(reviewing({NVLINK_QUOTE: verdict("rejected")})))
    review(atlas, "sweep")

    assert [e["layer"] for e in relationships(atlas, sort="layer")] == [
        "chip-laser",
        "module",
        "system",
    ]
    assert [e["layer"] for e in relationships(atlas, sort="layer", order="desc")] == [
        "system",
        "module",
        "chip-laser",
    ]
    by_evidence = relationships(atlas, sort="evidence_count", order="desc")
    assert [e["evidence_count"] for e in by_evidence] == [2, 1, 1]
    assert by_evidence[0]["layer"] == "chip-laser"
    assert [e["subject_name"] for e in relationships(atlas, sort="subject")] == [
        "Coherent",
        "Coherent",
        "NVIDIA",
    ]
    assert [e["object_name"] for e in relationships(atlas, sort="object")] == [
        "Coherent",
        "NVIDIA",
        "NVIDIA",
    ]
    assert [e["layer"] for e in relationships(atlas, layer="module")] == ["module"]
    machine = relationships(atlas, review_state="machine_reviewed", sort="layer")
    assert [e["layer"] for e in machine] == ["chip-laser", "system"]
    assert relationships(atlas, predicate="owns")[0]["subject_name"] == "NVIDIA"
    assert len(relationships(atlas, company_id=company_id(atlas, "nvidia"))) == 3
    assert relationships(atlas, company_id=company_id(atlas, "lumentum")) == []
    page = atlas.get("/api/v1/relationships", limit=1, offset=1, sort="layer")
    assert (page["total"], [e["layer"] for e in page["items"]]) == (3, ["module"])
    for bad in [{"sort": "quote"}, {"layer": "optics"}, {"review_state": "unreviewed"}]:
        response = atlas.api.get("/api/v1/relationships", params=bad)
        assert response.status_code == 422, bad
        assert response.json()["error"]["code"] == "invalid_request"


# --- owner review -------------------------------------------------------------------------------


def test_the_owner_can_approve_or_reject_any_relationship_and_each_change_is_audited(
    atlas: Atlas, llm: FakeLiteLLM
) -> None:
    extract(atlas, llm, "cohr-10k", supply(atlas))
    llm.script_chat(ChatReply.answer(reviewing()))
    review(atlas, "sweep")
    (edge,) = relationships(atlas)

    assert owner_review(atlas, edge["id"], "rejected", "not material").status_code == 200
    assert owner_review(atlas, edge["id"], "approved").status_code == 200
    again = owner_review(atlas, edge["id"], "approved")
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "invalid_transition"
    machine = owner_review(atlas, edge["id"], "machine_reviewed")
    assert machine.status_code == 422
    missing = owner_review(atlas, str(uuid.uuid4()), "approved")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"
    assert atlas.api.get(f"/api/v1/relationships/{uuid.uuid4()}").status_code == 404

    final = atlas.get(f"/api/v1/relationships/{edge['id']}")
    assert (final["review_state"], final["review_note"]) == ("approved", None)
    assert [a for _, a in audit_trail(atlas, "relationship")] == [
        "relationship.created",
        "relationship.rejected",
        "relationship.approved",
    ]
    verified = atlas.cli("audit", "verify")
    assert verified.returncode == 0, verified.stdout + verified.stderr


def test_new_evidence_never_overrides_the_owner_but_lifts_an_exception(
    atlas: Atlas, llm: FakeLiteLLM
) -> None:
    extract(atlas, llm, "first", investment(atlas))
    llm.script_chat(ChatReply.answer(reviewing({INVESTMENT_QUOTE: verdict("uncertain")})))
    review(atlas, "sweep-1")
    (owns,) = relationships(atlas)
    assert owns["review_state"] == "needs_human_review"

    # A second, confirmed witness of the same edge makes it machine-reviewed.
    manual_assertion(
        atlas,
        ten_k(atlas),
        INVESTMENT_QUOTE,
        subject="nvidia",
        predicate="owns",
        target="coherent",
        layer="system",
    )
    llm.script_chat(ChatReply.answer(reviewing(expect=1)))
    review(atlas, "sweep-2")
    lifted = atlas.get(f"/api/v1/relationships/{owns['id']}")
    assert (lifted["review_state"], lifted["evidence_count"]) == ("machine_reviewed", 2)

    # After the owner rejects it, further evidence is added but the decision stands.
    assert owner_review(atlas, owns["id"], "rejected").status_code == 200
    manual_assertion(
        atlas,
        ten_k(atlas),
        INVESTMENT_QUOTE,
        subject="nvidia",
        predicate="owns",
        target="coherent",
        layer="system",
    )
    llm.script_chat(ChatReply.answer(reviewing(expect=1)))
    review(atlas, "sweep-3")
    kept = atlas.get(f"/api/v1/relationships/{owns['id']}")
    assert (kept["review_state"], kept["evidence_count"]) == ("rejected", 3)
    assert [a for _, a in audit_trail(atlas, "relationship")] == [
        "relationship.created",
        "relationship.evidence_added",
        "relationship.machine_reviewed",
        "relationship.rejected",
        "relationship.evidence_added",
    ]


# --- failures: quarantine, outage -----------------------------------------------------------------


def test_a_quarantined_reviewer_answer_sends_its_edges_to_the_exceptions_queue(
    atlas: Atlas, llm: FakeLiteLLM
) -> None:
    extract(atlas, llm, "cohr-10k", supply(atlas))
    llm.script_chat(ChatReply.text("looks fine"), ChatReply.text("{}"))

    job = review(atlas, "sweep")

    assert job["status"] == "succeeded", job["failures"]
    (edge,) = relationships(atlas)
    assert (edge["review_state"], edge["review_reasons"]) == (
        "needs_human_review",
        ["reviewer_quarantined"],
    )
    (evidence,) = atlas.get(f"/api/v1/relationships/{edge['id']}")["evidence"]
    assert evidence["review"]["reviewer_status"] == "quarantined"
    assert evidence["review"]["role_call_id"] is not None


def test_an_llm_outage_pauses_the_queue_and_the_review_resumes_in_the_same_run(
    database_url: str,
    tmp_path: Path,
    hindsight: tuple[RecordedHindsight, Served],
    litellm: Served,
    llm: FakeLiteLLM,
    themes: Path,
) -> None:
    atlas = start_atlas(
        database_url, tmp_path, hindsight, litellm, themes, reviewer_assertions_per_call=1
    )
    extract(atlas, llm, "cohr-10k", supply(atlas), investment(atlas))
    clock = Clock(at("2026-10-01T12:00:00+00:00"))
    worker = Worker(
        JobQueue(atlas.engine, pacing=Pacing(), clock=clock), builtin_registry(atlas.settings())
    )
    job_id = atlas.enqueue(
        "jobs", "enqueue", "review_relationships", "--key", "outage", "--payload", "{}"
    )
    llm.script_chat(
        ChatReply.answer(reviewing(expect=1)), ChatReply.error(503, "Service Unavailable")
    )

    worker.run_once()

    job = atlas.get(f"/api/v1/jobs/{job_id}")
    assert (job["status"], job["attempts"]) == ("queued", 0)
    assert atlas.get("/api/v1/queue")["pause"]["paused"] is True
    assert len(relationships(atlas)) == 1  # the first batch is recorded

    clock.advance(hours=2)
    llm.script_chat(ChatReply.answer(reviewing(expect=1)))
    worker.run_once()

    job = atlas.get(f"/api/v1/jobs/{job_id}")
    assert job["status"] == "succeeded", job["failures"]
    assert job["artifacts"]["considered"] == 2
    assert {e["review_state"] for e in relationships(atlas)} == {"machine_reviewed"}
    calls = atlas.get(f"/api/v1/runs/{job['artifacts']['run_id']}/role-calls")["role_calls"]
    assert [c["status"] for c in calls] == ["accepted", "failed", "accepted"]
    atlas.engine.dispose()


# --- metrics, immutability ------------------------------------------------------------------------


def test_metrics_count_relationships_by_review_state(atlas: Atlas, llm: FakeLiteLLM) -> None:
    before = atlas.metrics()
    for state in STATES:
        assert before[("atlas_relationships", frozenset({("review_state", state)}))] == 0
    extract(atlas, llm, "cohr-10k", supply(atlas), investment(atlas))
    llm.script_chat(ChatReply.answer(reviewing({INVESTMENT_QUOTE: verdict("uncertain")})))
    review(atlas, "sweep")
    (supplied,) = relationships(atlas, predicate="supplies")
    owner_review(atlas, supplied["id"], "approved")

    after = atlas.metrics()

    counts = {
        state: after[("atlas_relationships", frozenset({("review_state", state)}))]
        for state in STATES
    }
    assert counts == {
        "machine_reviewed": 0,
        "needs_human_review": 1,
        "approved": 1,
        "rejected": 0,
    }
    reviews = {
        outcome: after[("atlas_relationship_reviews_total", frozenset({("outcome", outcome)}))]
        for outcome in ["machine_reviewed", "needs_human_review", "not_eligible"]
    }
    assert reviews == {"machine_reviewed": 1, "needs_human_review": 1, "not_eligible": 0}


def test_review_records_and_evidence_links_are_insert_only_and_an_edge_keeps_its_identity(
    atlas: Atlas, llm: FakeLiteLLM
) -> None:
    extract(atlas, llm, "cohr-10k", supply(atlas))
    llm.script_chat(ChatReply.answer(reviewing()))
    review(atlas, "sweep")
    (edge,) = relationships(atlas)

    for statement in [
        "UPDATE relationship_review SET outcome = 'needs_human_review'",
        "DELETE FROM relationship_review",
        "UPDATE relationship SET predicate = 'buys_from' WHERE id = :id",
        "DELETE FROM relationship WHERE id = :id",
    ]:
        with pytest.raises(DBAPIError), atlas.engine.begin() as connection:
            connection.execute(text(statement), {"id": edge["id"]})


# --- company-level bottleneck predicates (pilot-fixes ticket 03) ------------------------------

# A Coherent-style supply update (hand-written): four facts Coherent states about itself and a
# product, with no counterparty named, and one sentence naming NVIDIA (so the Investigator is
# sent it: an entity-tagged passage).
OWN_SUBSTRATES = "We manufacture our own indium phosphide substrates for our datacom lasers."
DEMAND_EXCEEDED = "Demand for our 200G EML lasers exceeded our supply throughout fiscal 2026."
SINGLE_SUPPLIER = "We purchase germanium for our infrared optics from a single supplier."
QUALIFIED = "Our 1.6T transceivers were qualified at two hyperscale customers during fiscal 2026."
SUPPLY_UPDATE = f"""<html><head><title>Coherent supply update</title></head><body>
<h1>Coherent fiscal 2026 supply update</h1>
<p>{OWN_SUBSTRATES}</p>
<p>{DEMAND_EXCEEDED}</p>
<p>{SINGLE_SUPPLIER}</p>
<p>{QUALIFIED}</p>
<p>We also supply 800G transceivers to NVIDIA.</p>
</body></html>
"""
BOTTLENECK_FACTS = [
    ("vertically_integrates", "indium phosphide substrates", "substrate", OWN_SUBSTRATES),
    ("capacity_constrained", "200G EML lasers", "chip-laser", DEMAND_EXCEEDED),
    ("sole_sources", "germanium", "substrate", SINGLE_SUPPLIER),
    ("qualified_for", "1.6T transceivers", "module", QUALIFIED),
]


def supply_update(atlas: Atlas) -> str:
    """The supply update, imported by hand for Coherent (a Tier A `manual_import`)."""
    path = atlas.tmp_path / "coherent-supply-update.html"
    path.write_text(SUPPLY_UPDATE, encoding="utf-8")
    imported = atlas.cli(
        "sources",
        "import",
        "--company",
        "coherent",
        "--file",
        str(path),
        "--origin-url",
        "https://www.coherent.com/news/fiscal-2026-supply-update",
        "--published-at",
        "2026-08-14T08:00-04:00",
    )
    assert imported.returncode == 0, imported.stderr
    return json.loads(imported.stdout)["source_version_id"]


def test_a_company_s_own_bottleneck_facts_become_assertions_and_edges_to_product_nodes(
    atlas: Atlas, llm: FakeLiteLLM
) -> None:
    coherent = company_id(atlas, "coherent")
    version_id = supply_update(atlas)
    proposals = [
        claim(
            subject_company_id=coherent,
            predicate=predicate,
            object_text=product,
            layer=layer,
            quote=quote,
        )
        for predicate, product, layer, quote in BOTTLENECK_FACTS
    ]
    llm.script_chat(ChatReply.answer(quoting(*proposals)))
    payload = json.dumps({"source_version_ids": [version_id]})
    job_id = atlas.enqueue(
        "jobs", "enqueue", "extract_claims", "--key", "update", "--payload", payload
    )
    atlas.worker_pass()

    job = atlas.get(f"/api/v1/jobs/{job_id}")
    assert job["status"] == "succeeded", job["failures"]
    [body] = llm.chat_requests()
    objects = {p["name"]: p["object"] for p in asked(body)["request"]["predicates"]}
    predicates = [predicate for predicate, *_ in BOTTLENECK_FACTS]
    assert [objects[name] for name in predicates] == ["product"] * 4
    claims = atlas.get("/api/v1/claims", extraction_id=job["artifacts"]["extraction_id"])["items"]
    assert [(c["predicate"], c["outcome"], c["reason_code"]) for c in claims] == [
        (predicate, "accepted", None) for predicate in predicates
    ]
    assert [c["directional_cue"] for c in claims] == [
        "our own",
        "exceeded our supply",
        "single supplier",
        "qualified",
    ]
    parsed = atlas.parsed(version_id)
    for accepted, (predicate, product, layer, quote) in zip(claims, BOTTLENECK_FACTS, strict=True):
        assertion = atlas.get(f"/api/v1/assertions/{accepted['assertion_id']}")
        assert parsed[assertion["span_start"] : assertion["span_end"]] == quote
        assert (assertion["subject_company_id"], assertion["predicate"]) == (coherent, predicate)
        assert assertion["object_company_id"] is None
        assert assertion["value_json"]["object_text"] == product
        assert assertion["value_json"]["layer"] == layer
        assert assertion["extractor_version"] == "investigator.v5"

    llm.script_chat(ChatReply.answer(reviewing(expect=len(BOTTLENECK_FACTS))))
    reviewed = review(atlas, "sweep")

    assert reviewed["status"] == "succeeded", reviewed["failures"]
    assert reviewed["artifacts"]["machine_reviewed"] == len(BOTTLENECK_FACTS)
    edges = {edge["predicate"]: edge for edge in relationships(atlas)}
    assert sorted(edges) == sorted(predicates)
    for predicate, product, layer, _ in BOTTLENECK_FACTS:
        edge = edges[predicate]
        assert (edge["subject_company_id"], edge["object_company_id"]) == (coherent, None)
        assert (edge["object_text"], edge["layer"]) == (product, layer)
        assert edge["review_state"] == "machine_reviewed"
    reviewer_request = asked(llm.chat_requests()[-1])["request"]
    assert {item["predicate"] for item in reviewer_request["items"]} == set(predicates)


# --- a cue from another clause (pilot-fixes ticket 09) -------------------------------------------

# The recorded Coherent 10-K's sentence: "expand" is in the InP clause, not the VCSEL one.
VCSEL = (
    "We continue to expand our global 6-inch InP manufacturing capacity in the United States and"
    " Europe to support increasing customer demand, while also operating multiple 6-inch GaAs"
    " VCSEL manufacturing facilities."
)


def product_assertion(atlas: Atlas, quote: str, predicate: str, object_text: str) -> str:
    version_id = ten_k(atlas)
    start = atlas.parsed(version_id).index(quote)
    response = atlas.api.post(
        "/api/v1/assertions",
        json={
            "subject_company_id": company_id(atlas, "coherent"),
            "predicate": predicate,
            "object_company_id": None,
            "value_json": {"layer": "chip-laser", "product": None, "object_text": object_text},
            "source_version_id": version_id,
            "quote": quote,
            "span_start": start,
            "span_end": start + len(quote),
            "epistemic_type": "company_claim",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["assertion"]["id"]


def test_a_cue_in_another_clause_than_the_object_forms_no_edge(
    atlas: Atlas, llm: FakeLiteLLM
) -> None:
    vcsel = product_assertion(
        atlas, VCSEL, "expands_capacity_for", "6-inch GaAs VCSEL manufacturing facilities"
    )
    inp = product_assertion(
        atlas, VCSEL, "expands_capacity_for", "6-inch InP manufacturing capacity"
    )
    llm.script_chat(ChatReply.answer(reviewing(expect=1)))

    job = review(atlas, "clauses")

    assert job["status"] == "succeeded", job["failures"]
    artifacts = job["artifacts"]
    assert (artifacts["machine_reviewed"], artifacts["not_eligible"]) == (1, 1)
    assert artifacts["not_eligible_assertions"] == [
        {"assertion_id": vcsel, "reason": "cue_in_other_clause"}
    ]
    (edge,) = relationships(atlas)
    assert (edge["predicate"], edge["object_text"]) == (
        "expands_capacity_for",
        "6-inch InP manufacturing capacity",
    )
    (evidence,) = atlas.get(f"/api/v1/relationships/{edge['id']}")["evidence"]
    assert evidence["assertion"]["id"] == inp
