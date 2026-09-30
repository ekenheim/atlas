"""Retention triage: read first, retain only what adds durable value (ticket 30).

Seam: the `atlas` CLI enqueues ingests, single worker passes run the ingest, retain, triage
and poll jobs, and everything is observed through `/api/v1` (triage decisions, memory,
assertions, runs' role calls), `/metrics`, the requests Hindsight received and the chat
completions LiteLLM was asked for. Hindsight is the recorded fake with `derive_retains`;
LiteLLM is the scripted chat fake, and **the Triage role's answers are written here**
(`triage_answer`, a stand-in for the model): it retains a 10-K's Business section (the one
that names suppliers and customers: Coherent's names its NVIDIA supply agreement), an
8-K's results item and a press release's first chunk, and skips everything else as
`other`. Expected sections come from the recorded EDGAR fixtures' Item headings.
"""

import json
import shutil
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from pydantic import JsonValue
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from atlas.api.app import create_app
from atlas.jobs import JobQueue, Pacing, Worker, builtin_registry
from tests.fakes.hindsight import RecordedHindsight
from tests.fakes.litellm import ChatReply, FakeLiteLLM
from tests.fakes.serve import Served, serve
from tests.harness import EDGAR_FIXTURES, LITE_10K, TEN_K_ANCHORS, Atlas, Clock

LITE = "https://www.sec.gov/Archives/edgar/data/1633978"
LITE_8K = f"{LITE}/000162828026055726/lite-20260811.htm"
LITE_EX991 = f"{LITE}/000162828026055726/lite_ex991xq4fy26.htm"
LITE_10Q = f"{LITE}/000162828026030777/lite-20260328.htm"
COHR_10K = "https://www.sec.gov/Archives/edgar/data/820318/000082031826000020/iivi-20260630.htm"
# From the Coherent FY2026 10-K's Item 1 (the recorded fixture's parsed text).
NVIDIA_SUPPLY = "strategic multi-year supply agreement with NVIDIA"

# Sections the pre-filter skips without a call: 10-K Items 1B ("None."), 4 (mine safety) and
# 6 ("[RESERVED]"). An exhibit index is read by the role (rules v2): it can name a contract.
TEN_K_RULE_SKIPS = {"part-i-item-1b", "part-i-item-4", "part-ii-item-6"}
TEN_K_ASKED = [anchor for anchor in TEN_K_ANCHORS if anchor not in TEN_K_RULE_SKIPS]
# What the model retains, by heading (or chunk anchor), with the value category.
RETAINED_HEADINGS = {
    "ITEM 1. BUSINESS": "supplier_customer",
    "Item 1. BUSINESS": "supplier_customer",
    "Item 2.02. Results of Operations and Financial Condition.": "segment_guidance",
}
RETAINED_CHUNKS = {"chunk-001": "segment_guidance"}
EXCERPT_CHARS = 1500
# Windows overlap by 200 characters (the default), so each starts 1300 after the last.
OVERLAP_CHARS = 200
STRIDE = EXCERPT_CHARS - OVERLAP_CHARS


def triage_answer(body: dict[str, Any]) -> JsonValue:
    """The stand-in model's answer to a Triage request."""
    user = json.loads(body["messages"][1]["content"])
    decisions: list[JsonValue] = []
    for section in user["request"]["sections"]:
        anchor, heading = section["anchor"], section["heading"]
        category = RETAINED_HEADINGS.get(heading or "") or RETAINED_CHUNKS.get(anchor)
        decisions.append(
            {
                "anchor": anchor,
                "decision": "retain" if category else "skip",
                "category": category or "other",
                "reason": f"{'names' if category else 'no'} bottleneck content in {anchor}",
            }
        )
    return {"decisions": decisions}


def asked(llm: FakeLiteLLM) -> list[dict[str, Any]]:
    """The user message of each chat completion requested so far."""
    return [json.loads(body["messages"][1]["content"]) for body in llm.chat_requests()]


def asked_anchors(llm: FakeLiteLLM) -> list[list[str]]:
    return [[s["anchor"] for s in message["request"]["sections"]] for message in asked(llm)]


# --- fixtures -----------------------------------------------------------------------------------


@pytest.fixture
def llm() -> FakeLiteLLM:
    return FakeLiteLLM().script_chat(*[ChatReply.answer(triage_answer)] * 12)


@pytest.fixture
def litellm(llm: FakeLiteLLM) -> Iterator[Served]:
    with serve(llm.handle) as served:
        yield served
        served.raise_errors()


@pytest.fixture
def atlas(
    database_url: str,
    tmp_path: Path,
    hindsight: tuple[RecordedHindsight, Served],
    litellm: Served,
) -> Iterator[Atlas]:
    harness = Atlas(
        database_url,
        tmp_path,
        hindsight[1].url,
        litellm.url,
        retention_triage="on",
        # One window per section: these tests pin the calls' anchors and reply count as
        # written for the opening-only reader; windows are tested on their own below.
        triage_windows_per_section=1,
        # Lets an investigation be created (its tasks never run here, so nothing is searched).
        searxng_url="http://127.0.0.1:9",
    )
    harness.fixtures = editable_fixtures(tmp_path)
    harness.apply_template()
    yield harness
    harness.engine.dispose()


def triage(atlas: Atlas, **params: Any) -> list[dict[str, Any]]:
    return atlas.get("/api/v1/triage", limit=500, **params)["items"]


def effective(atlas: Atlas, version_id: str) -> dict[str, dict[str, Any]]:
    decisions = triage(atlas, source_version_id=version_id, effective="true")
    return {decision["section_anchor"]: decision for decision in decisions}


def retained_anchors(fake: RecordedHindsight, version_id: str) -> list[list[str]]:
    """The anchors of each retain batch Hindsight received for the version."""
    prefix = f"srcv:{version_id}:"
    return [
        [str(item["document_id"]).removeprefix(prefix) for item in batch]
        for batch in fake.retained()
        if all(str(item["document_id"]).startswith(prefix) for item in batch)
    ]


# --- triage before retain -----------------------------------------------------------------------


def test_boilerplate_is_skipped_by_rule_without_a_call_and_the_rest_is_asked_of_the_role(
    atlas: Atlas, fake: RecordedHindsight, llm: FakeLiteLLM
) -> None:
    job = atlas.ingest("lumentum")

    assert job["status"] == "succeeded", job["failures"]
    ten_k = atlas.version(LITE_10K)
    decisions = effective(atlas, ten_k["id"])
    assert sorted(decisions) == sorted(TEN_K_ANCHORS)
    for anchor in TEN_K_RULE_SKIPS:
        decision = decisions[anchor]
        assert decision["decision"] == "skip"
        assert decision["method"] == "rule"
        assert decision["category"] == "boilerplate"
        assert decision["role_call_id"] is None
        assert decision["rules_version"] == "triage-rules-v2"
    assert decisions["part-ii-item-6"]["reason"].startswith("boilerplate heading (reserved)")
    assert decisions["part-i-item-1b"]["reason"].startswith("no content past its heading")

    # One call per version, never naming a rule-skipped section.
    calls = asked_anchors(llm)
    assert len(calls) == 4  # the 10-K, the 10-Q, the 8-K and its EX-99.1
    assert TEN_K_ASKED in calls
    assert not {anchor for call in calls for anchor in call} & TEN_K_RULE_SKIPS
    # The role sees each section's opening as quoted, low-trust data, and the metadata.
    parsed = atlas.parsed(ten_k["id"])
    message = next(m for m in asked(llm) if m["request"]["sections"][0]["anchor"] == "cover")
    assert message["request"]["document"]["source_version_id"] == ten_k["id"]
    assert message["request"]["document"]["form_type"] == "10-K"
    assert message["request"]["document"]["company"] == "Lumentum"
    assert [theme["theme_id"] for theme in message["request"]["themes"]] == ["photonics"]
    (item_1,) = [d for d in atlas.memory(ten_k["id"])["documents"]]
    opening = next(r for r in message["retrieved_data"] if r["id"] == "part-i-item-1")
    assert opening["trust"] == "low"
    assert opening["text"] == parsed[item_1["char_start"] :][:EXCERPT_CHARS]
    assert (llm.chat_requests()[0]["response_format"]["json_schema"]["name"]) == "triage"


def test_only_the_sections_triage_retains_reach_hindsight_and_the_rest_stay_citable(
    atlas: Atlas, fake: RecordedHindsight, llm: FakeLiteLLM
) -> None:
    atlas.ingest("lumentum")

    ten_k = atlas.version(LITE_10K)
    decisions = effective(atlas, ten_k["id"])
    item_1 = decisions["part-i-item-1"]
    assert item_1["decision"] == "retain"
    assert item_1["method"] == "role"
    assert item_1["category"] == "supplier_customer"
    assert item_1["rubric_version"] == "triage.v3"
    # The role read the opening only (one window per section here) of a 22-window Item.
    assert item_1["reason"].startswith("part 1/")
    assert item_1["reason"].endswith(": names bottleneck content in part-i-item-1")
    assert decisions["part-i-item-2"]["decision"] == "skip"
    assert decisions["part-i-item-2"]["category"] == "other"
    # Only the retained sections are recorded and submitted, as one batch per version.
    assert retained_anchors(fake, ten_k["id"]) == [["part-i-item-1"]]
    memory = atlas.memory(ten_k["id"])
    assert [d["section_anchor"] for d in memory["documents"]] == ["part-i-item-1"]
    assert memory["counts"]["completed"] == 1
    eight_k = atlas.version(LITE_8K)
    assert retained_anchors(fake, eight_k["id"]) == [["item-2-02"]]
    assert retained_anchors(fake, atlas.version(LITE_EX991)["id"]) == [["chunk-001"]]
    # Every section of the 10-Q was skipped: nothing was submitted for it.
    ten_q = atlas.version(LITE_10Q)
    assert retained_anchors(fake, ten_q["id"]) == []
    assert atlas.memory(ten_q["id"])["documents"] == []
    assert len(fake.retained()) == 3

    # The decision names the role call that made it, recorded under a `triage` run.
    role_call = item_1["role_call_id"]
    with atlas.engine.connect() as connection:
        run_id, role = connection.execute(
            text("SELECT run_id, role FROM role_call WHERE id = :id"), {"id": role_call}
        ).one()
    calls = atlas.get(f"/api/v1/runs/{run_id}/role-calls")
    assert role == "triage"
    assert any(call["id"] == role_call for call in calls["role_calls"])

    # A skipped section is still archived and citable: an Assertion quotes Item 2.
    parsed = atlas.parsed(ten_k["id"])
    properties = decisions["part-i-item-2"]
    quote = "We own and lease various properties"
    start = parsed.index(quote, properties["char_start"])
    assert start < properties["char_end"]
    response = atlas.api.post(
        "/api/v1/assertions",
        json={
            "subject_company_id": atlas.company("lumentum")["id"],
            "predicate": "owns",
            "source_version_id": ten_k["id"],
            "quote": quote,
            "span_start": start,
            "span_end": start + len(quote),
            "page_or_anchor": "part-i-item-2",
            "epistemic_type": "direct_source_statement",
        },
    )
    assert response.status_code == 201, response.text


def test_a_supplier_naming_section_is_retained(
    atlas: Atlas, fake: RecordedHindsight, llm: FakeLiteLLM
) -> None:
    atlas.ingest_company("coherent")

    ten_k = atlas.version(COHR_10K, "coherent")
    item_1 = effective(atlas, ten_k["id"])["part-i-item-1"]
    parsed = atlas.parsed(ten_k["id"])
    assert NVIDIA_SUPPLY in parsed[item_1["char_start"] : item_1["char_end"]]
    assert item_1["decision"] == "retain"
    assert item_1["category"] == "supplier_customer"
    (batch,) = [
        batch
        for batch in fake.retained()
        if all(str(i["document_id"]).startswith(f"srcv:{ten_k['id']}:") for i in batch)
    ]
    assert [item["document_id"] for item in batch] == [f"srcv:{ten_k['id']}:part-i-item-1"]
    assert NVIDIA_SUPPLY in str(batch[0]["content"])


def test_an_unchanged_section_of_a_revised_source_inherits_its_decision_without_a_call(
    atlas: Atlas, fake: RecordedHindsight, llm: FakeLiteLLM
) -> None:
    atlas.ingest("before")
    (v1,) = atlas.versions(LITE_8K)
    first = effective(atlas, v1["id"])
    calls_before = len(llm.chat_requests())
    change_recorded_document(
        atlas.fixtures,
        LITE_8K,
        b"fourth quarter and full fiscal year",
        b"third quarter",
        "Wed, 12 Aug 2026 09:00:00 GMT",
    )

    job = atlas.ingest("after")

    assert job["status"] == "succeeded", job["failures"]
    _, v2 = atlas.versions(LITE_8K)
    second = effective(atlas, v2["id"])
    for anchor in ("cover", "item-9-01"):
        assert second[anchor]["method"] == "inherited"
        assert second[anchor]["inherited_from_id"] == first[anchor]["id"]
        assert second[anchor]["decision"] == first[anchor]["decision"]
        assert second[anchor]["content_sha256"] == first[anchor]["content_sha256"]
    # Only the changed section was asked about.
    assert asked_anchors(llm)[calls_before:] == [["item-2-02"]]
    assert second["item-2-02"]["method"] == "role"
    assert second["item-2-02"]["content_sha256"] != first["item-2-02"]["content_sha256"]
    assert retained_anchors(fake, v2["id"]) == [["item-2-02"]]


def test_an_exhibit_index_is_read_by_the_role_not_skipped_by_rule(
    atlas: Atlas, fake: RecordedHindsight, llm: FakeLiteLLM
) -> None:
    # The first live audits (2026-09-30) found a 10-Q's "Item 6. Exhibits" skipped by rule
    # while its index named a Master Development and Supply Agreement with Coherent.
    atlas.ingest("lumentum")

    eight_k = atlas.version(LITE_8K)
    exhibits = effective(atlas, eight_k["id"])["item-9-01"]
    assert exhibits["section_heading"] == "Item 9.01. Financial Statements and Exhibits."
    assert exhibits["method"] == "role"
    assert exhibits["role_call_id"] is not None
    assert exhibits["rules_version"] == "triage-rules-v2"
    assert exhibits["rubric_version"] == "triage.v3"
    message = next(
        m for m in asked(llm) if m["request"]["document"]["source_version_id"] == eight_k["id"]
    )
    assert "item-9-01" in [s["anchor"] for s in message["request"]["sections"]]
    parsed = atlas.parsed(eight_k["id"])
    sent = next(r for r in message["retrieved_data"] if r["id"] == "item-9-01")
    assert sent["text"] == parsed[exhibits["char_start"] : exhibits["char_end"]]
    # The rubric the role is given retains an exhibit index that names an agreement.
    system = llm.chat_requests()[0]["messages"][0]["content"]
    assert "triage rubric v3" in system
    assert "An exhibit index that lists such an agreement" in system


# --- windows: the role reads the whole section, not its opening ----------------------------------


def later_window_answer(body: dict[str, Any]) -> JsonValue:
    """A stand-in model that retains only a section's later windows (never its opening):
    what the opening-only reader could never have retained."""
    user = json.loads(body["messages"][1]["content"])
    decisions: list[JsonValue] = []
    for section in user["request"]["sections"]:
        later = "~" in section["anchor"]
        decisions.append(
            {
                "anchor": section["anchor"],
                "decision": "retain" if later else "skip",
                "category": "capacity" if later else "other",
                "reason": f"{'capacity detail' if later else 'nothing'} in {section['anchor']}",
            }
        )
    return {"decisions": decisions}


def test_a_long_section_is_read_in_windows_and_retained_when_a_later_window_is(
    database_url: str,
    tmp_path: Path,
    hindsight: tuple[RecordedHindsight, Served],
) -> None:
    llm = FakeLiteLLM().script_chat(*[ChatReply.answer(later_window_answer)] * 40)
    with serve(llm.handle) as litellm:
        atlas = Atlas(
            database_url,
            tmp_path,
            hindsight[1].url,
            litellm.url,
            retention_triage="on",
            triage_excerpt_chars=EXCERPT_CHARS,
            triage_windows_per_section=3,
            triage_window_overlap_chars=OVERLAP_CHARS,
            searxng_url="http://127.0.0.1:9",
        )
        atlas.fixtures = editable_fixtures(tmp_path)
        atlas.apply_template()
        job = atlas.ingest("lumentum")
        assert job["status"] == "succeeded", job["failures"]
        litellm.raise_errors()

    ten_k = atlas.version(LITE_10K)
    parsed = atlas.parsed(ten_k["id"])
    decisions = effective(atlas, ten_k["id"])
    assert sorted(decisions) == sorted(TEN_K_ANCHORS)  # one decision per section, still
    # The 10-K's calls only: the 10-Q's sections share its anchors.
    calls = [m for m in asked(llm) if m["request"]["document"]["source_version_id"] == ten_k["id"]]
    by_anchor = {s["anchor"]: s for m in calls for s in m["request"]["sections"]}
    texts = {r["id"]: r for m in calls for r in m["retrieved_data"]}
    long = [a for a in TEN_K_ANCHORS if a in by_anchor and by_anchor[a]["parts"] > 3]
    short = [a for a in TEN_K_ANCHORS if a in by_anchor and by_anchor[a]["parts"] == 1]
    assert long and short
    for anchor in long:
        decision = decisions[anchor]
        first = by_anchor[anchor]
        assert (first["part"], first["length"]) == (
            1,
            decision["char_end"] - decision["char_start"],
        )
        # The role saw three windows: the opening, one from the middle and the last.
        parts = sorted(s["part"] for s in by_anchor.values() if s["anchor"].split("~")[0] == anchor)
        assert parts == [1, 1 + round((first["parts"] - 1) / 2), first["parts"]]
        last = texts[f"{anchor}~{first['parts']}"]
        assert last["trust"] == "low"
        # The last window ends at the section's end and starts one stride after the one before.
        assert (
            last["text"]
            == parsed[decision["char_start"] + (first["parts"] - 1) * STRIDE : decision["char_end"]]
        )
        # Retained because a later window was, and the decision says which.
        assert decision["decision"] == "retain"
        assert decision["category"] == "capacity"
        assert decision["reason"].startswith(f"part {parts[1]}/{first['parts']}: capacity detail")
        assert decision["role_call_id"] is not None
    for anchor in short:
        if decisions[anchor]["method"] == "role":
            assert decisions[anchor]["decision"] == "skip"
            assert not decisions[anchor]["reason"].startswith("part ")
    # Every window's text is a slice of its section, sent as low-trust data by its anchor;
    # consecutive windows overlap by OVERLAP_CHARS.
    for anchor, entry in by_anchor.items():
        section = decisions[anchor.split("~")[0]]
        offset = section["char_start"] + (entry["part"] - 1) * STRIDE
        assert (
            texts[anchor]["text"]
            == parsed[offset : min(offset + EXCERPT_CHARS, section["char_end"])]
        )


def test_by_default_a_12k_section_is_read_in_full(
    database_url: str,
    tmp_path: Path,
    hindsight: tuple[RecordedHindsight, Served],
) -> None:
    # The first live audit (2026-09-30) missed a footnote in the EX-99.1's second chunk
    # (11,948 characters, ten windows) when triage read six of them. The default reads ten.
    llm = FakeLiteLLM().script_chat(*[ChatReply.answer(later_window_answer)] * 40)
    with serve(llm.handle) as litellm:
        atlas = Atlas(
            database_url,
            tmp_path,
            hindsight[1].url,
            litellm.url,
            retention_triage="on",
            searxng_url="http://127.0.0.1:9",
        )
        atlas.fixtures = editable_fixtures(tmp_path)
        atlas.apply_template()
        job = atlas.ingest("lumentum")
        assert job["status"] == "succeeded", job["failures"]
        litellm.raise_errors()

    ex991 = atlas.version(LITE_EX991)
    parsed = atlas.parsed(ex991["id"])
    chunk = effective(atlas, ex991["id"])["chunk-002"]
    assert chunk["char_end"] - chunk["char_start"] == 11_948
    calls = [m for m in asked(llm) if m["request"]["document"]["source_version_id"] == ex991["id"]]
    entries = [s for m in calls for s in m["request"]["sections"]]
    parts = sorted(s["part"] for s in entries if s["anchor"].split("~")[0] == "chunk-002")
    assert parts == list(range(1, 11))  # every window, none sampled out
    texts = {r["id"]: r["text"] for m in calls for r in m["retrieved_data"]}
    read = "".join(texts["chunk-002" if p == 1 else f"chunk-002~{p}"][:STRIDE] for p in parts)
    last = texts["chunk-002~10"][STRIDE:]
    assert read + last == parsed[chunk["char_start"] : chunk["char_end"]]


# --- retain on demand ---------------------------------------------------------------------------


def test_a_skipped_section_is_retained_on_demand_recorded_with_who_asked_and_why(
    atlas: Atlas, fake: RecordedHindsight, llm: FakeLiteLLM
) -> None:
    atlas.ingest("lumentum")
    ten_k = atlas.version(LITE_10K)
    skipped = effective(atlas, ten_k["id"])["part-i-item-2"]
    assert skipped["decision"] == "skip"
    batches_before = len(fake.retained())
    calls_before = len(llm.chat_requests())

    response = atlas.api.post(
        f"/api/v1/source-versions/{ten_k['id']}/sections/part-i-item-2/retain",
        json={"reason": "the fab locations matter for the capacity question"},
    )

    assert response.status_code == 202, response.text
    requested = response.json()
    decision = requested["decision"]
    assert decision["method"] == "on_demand"
    assert decision["decision"] == "retain"
    assert decision["requested_by"] == "local-researcher"
    assert decision["reason"] == "the fab locations matter for the capacity question"
    assert decision["investigation_id"] is None
    assert decision["effective"] is True
    assert (decision["char_start"], decision["char_end"]) == (
        skipped["char_start"],
        skipped["char_end"],
    )
    atlas.worker_pass()

    assert atlas.get(f"/api/v1/jobs/{requested['retain_job_id']}")["status"] == "succeeded"
    (batch,) = fake.retained()[batches_before:]
    assert [item["document_id"] for item in batch] == [f"srcv:{ten_k['id']}:part-i-item-2"]
    memory = atlas.memory(ten_k["id"])
    assert [d["section_anchor"] for d in memory["documents"]] == [
        "part-i-item-1",
        "part-i-item-2",
    ]
    assert memory["counts"]["completed"] == 2
    assert len(llm.chat_requests()) == calls_before  # no new triage
    # Both decisions stay listed; the on-demand one is the section's effective decision.
    history = triage(atlas, source_version_id=ten_k["id"], method="on_demand")
    assert [d["id"] for d in history] == [decision["id"]]
    listed = {d["id"]: d for d in triage(atlas, source_version_id=ten_k["id"])}
    assert listed[skipped["id"]]["effective"] is False
    assert effective(atlas, ten_k["id"])["part-i-item-2"]["id"] == decision["id"]

    # A retained section can't be asked for again; unknown sections are 404.
    again = atlas.api.post(
        f"/api/v1/source-versions/{ten_k['id']}/sections/part-i-item-2/retain",
        json={"reason": "again"},
    )
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "already_retained"
    unknown = atlas.api.post(
        f"/api/v1/source-versions/{ten_k['id']}/sections/part-ix-item-99/retain",
        json={"reason": "no such section"},
    )
    assert unknown.status_code == 404
    blank = atlas.api.post(
        f"/api/v1/source-versions/{ten_k['id']}/sections/part-i-item-3/retain",
        json={"reason": ""},
    )
    assert blank.status_code == 422


def test_an_investigation_asking_for_a_section_is_recorded(
    atlas: Atlas, fake: RecordedHindsight, llm: FakeLiteLLM
) -> None:
    atlas.ingest("lumentum")
    ten_k = atlas.version(LITE_10K)
    missing = atlas.api.post(
        f"/api/v1/source-versions/{ten_k['id']}/sections/part-i-item-3/retain",
        json={
            "reason": "legal exposure",
            "investigation_id": "00000000-0000-4000-8000-000000000000",
        },
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["message"] == "investigation not found"
    investigation = start_investigation(atlas)

    response = atlas.api.post(
        f"/api/v1/source-versions/{ten_k['id']}/sections/part-i-item-3/retain",
        json={"reason": "legal exposure to a supplier dispute", "investigation_id": investigation},
    )

    assert response.status_code == 202, response.text
    decision = response.json()["decision"]
    assert decision["investigation_id"] == investigation
    assert decision["requested_by"] == "local-researcher"
    listed = triage(atlas, method="on_demand")
    assert [d["investigation_id"] for d in listed] == [investigation]


# --- visibility and invariants --------------------------------------------------------------------


def test_decisions_are_filterable_audited_insert_only_and_counted_in_metrics(
    atlas: Atlas, fake: RecordedHindsight, llm: FakeLiteLLM
) -> None:
    atlas.ingest("lumentum")
    lumentum = atlas.company("lumentum")

    everything = atlas.get("/api/v1/triage", limit=500)
    # 10-K 11 sections, 10-Q 2, 8-K 3, EX-99.1 3 chunks.
    assert everything["total"] == 19
    assert atlas.get("/api/v1/triage", company_id=lumentum["id"])["total"] == 19
    assert atlas.get("/api/v1/triage", company_id=str(uuid.uuid4()))["total"] == 0
    retained = triage(atlas, decision="retain")
    assert sorted(d["section_anchor"] for d in retained) == [
        "chunk-001",
        "item-2-02",
        "part-i-item-1",
    ]
    assert len(triage(atlas, method="rule")) == 3
    assert len(triage(atlas, category="boilerplate")) == 3
    assert atlas.api.get("/api/v1/triage", params={"method": "guess"}).status_code == 422

    with atlas.engine.connect() as connection:
        audited = connection.execute(
            text("SELECT count(*) FROM audit_event WHERE entity_type = 'triage_decision'")
        ).scalar_one()
    assert audited == 19
    with pytest.raises(DBAPIError, match="immutable"), atlas.engine.begin() as connection:
        connection.execute(text("UPDATE triage_decision SET decision = 'retain'"))
    with pytest.raises(DBAPIError, match="immutable"), atlas.engine.begin() as connection:
        connection.execute(text("DELETE FROM triage_decision"))

    metrics = atlas.metrics()

    def sample(name: str, **labels: str) -> float:
        return metrics[(name, frozenset(labels.items()))]

    assert (
        sample("atlas_triage_sections_total", decision="retain", category="supplier_customer") == 1
    )
    assert (
        sample("atlas_triage_sections_total", decision="retain", category="segment_guidance") == 2
    )
    assert sample("atlas_triage_sections_total", decision="skip", category="boilerplate") == 3
    assert sample("atlas_triage_sections_total", decision="skip", category="other") == 13
    assert sample("atlas_triage_decisions_total", method="rule") == 3
    assert sample("atlas_triage_decisions_total", method="role") == 16
    saved = "atlas_triage_hindsight_operations_saved_estimate"
    assert sample(saved, unit="documents") == 16
    assert sample(saved, unit="batches") == 1  # the 10-Q: every section skipped


def test_with_triage_off_every_section_is_retained_without_a_call(
    database_url: str,
    tmp_path: Path,
    hindsight: tuple[RecordedHindsight, Served],
    litellm: Served,
    llm: FakeLiteLLM,
) -> None:
    fake = hindsight[0]
    atlas = Atlas(database_url, tmp_path, hindsight[1].url, litellm.url, retention_triage="off")
    atlas.apply_template()

    job = atlas.ingest("lumentum")

    assert job["status"] == "succeeded", job["failures"]
    ten_k = atlas.version(LITE_10K)
    assert retained_anchors(fake, ten_k["id"]) == [TEN_K_ANCHORS]
    assert llm.chat_requests() == []
    assert atlas.get("/api/v1/triage")["total"] == 0
    atlas.engine.dispose()


# --- when triage fails: hold and retry ----------------------------------------------------------


def test_a_quarantined_triage_retains_nothing_and_fails_visibly_after_its_attempts(
    atlas: Atlas, fake: RecordedHindsight, llm: FakeLiteLLM
) -> None:
    # Every answer is invalid: each attempt's call and its repair, 3 attempts, 4 versions.
    llm.chat_replies.clear()
    llm.script_chat(*[ChatReply.text("not a triage answer")] * 24)

    job = atlas.ingest("lumentum")

    assert job["status"] == "succeeded", job["failures"]
    jobs = triage_jobs(atlas)
    assert len(jobs) == 4
    for each in jobs.values():
        assert each["status"] == "failed"
        assert each["attempts"] == each["max_attempts"] == 3
        assert all("quarantined" in failure["error"] for failure in each["failures"])
    assert len(llm.chat_requests()) == 24
    # Nothing was decided by the role or by default, and nothing reached Hindsight.
    assert {decision["method"] for decision in triage(atlas)} == {"rule"}
    assert fake.retained() == []
    assert atlas.memory(atlas.version(LITE_10K)["id"])["documents"] == []
    assert failed_triage_jobs(atlas) == 4

    # The owner retries one version once the model answers again: only it is triaged.
    llm.script_chat(*[ChatReply.answer(triage_answer)] * 4)
    ten_k = atlas.version(LITE_10K)["id"]
    retried = retry(atlas, "--source-version", ten_k)
    assert [each["source_version_id"] for each in retried] == [ten_k]
    atlas.worker_pass()
    assert triage_jobs(atlas)[ten_k]["status"] == "succeeded"
    assert effective(atlas, ten_k)["part-i-item-1"]["method"] == "role"
    assert retained_anchors(fake, ten_k) == [["part-i-item-1"]]
    assert failed_triage_jobs(atlas) == 3
    # Its latest triage job succeeded, so it can't be retried again.
    refused = atlas.cli("triage", "retry", "--source-version", ten_k)
    assert refused.returncode == 2
    assert "succeeded, not failed" in refused.stderr

    # --failed retries the rest; afterwards there is nothing left to retry.
    assert len(retry(atlas, "--failed")) == 3
    atlas.worker_pass()
    assert all(each["status"] == "succeeded" for each in triage_jobs(atlas).values())
    assert failed_triage_jobs(atlas) == 0
    assert retry(atlas, "--failed") == []
    assert len(llm.chat_requests()) == 24 + 4


def test_a_section_the_answer_leaves_out_is_asked_again_on_retry_without_duplicating_decisions(
    atlas: Atlas, fake: RecordedHindsight, llm: FakeLiteLLM
) -> None:
    left_out: list[str] = []

    def forgetful(body: dict[str, Any]) -> JsonValue:
        """The stand-in model, leaving the 10-K's Item 1 out of its first answer about it."""
        answer = cast(dict[str, list[dict[str, Any]]], triage_answer(body))
        anchors = [decision["anchor"] for decision in answer["decisions"]]
        if not left_out and "part-i-item-1" in anchors:
            left_out.append("part-i-item-1")
            kept = [d for d in answer["decisions"] if d["anchor"] != "part-i-item-1"]
            return cast(JsonValue, {"decisions": kept})
        return cast(JsonValue, answer)

    llm.chat_replies.clear()
    llm.script_chat(*[ChatReply.answer(forgetful)] * 5)

    job = atlas.ingest("lumentum")

    assert job["status"] == "succeeded", job["failures"]
    ten_k = atlas.version(LITE_10K)
    ten_k_job = triage_jobs(atlas)[ten_k["id"]]
    assert ten_k_job["status"] == "succeeded"
    assert ten_k_job["attempts"] == 2
    (failure,) = ten_k_job["failures"]
    assert "no decision" in failure["error"]
    # The retry asked only about the section left out.
    calls = asked_anchors(llm)
    assert len(calls) == 5
    assert calls.count(TEN_K_ASKED) == 1
    assert calls.count(["part-i-item-1"]) == 1
    # One decision per section (insert-only; the retry duplicated none), none by default.
    rows = triage(atlas, source_version_id=ten_k["id"])
    assert sorted(row["section_anchor"] for row in rows) == sorted(TEN_K_ANCHORS)
    assert "default" not in {row["method"] for row in triage(atlas)}
    item_1 = effective(atlas, ten_k["id"])["part-i-item-1"]
    assert (item_1["method"], item_1["decision"]) == ("role", "retain")
    assert retained_anchors(fake, ten_k["id"]) == [["part-i-item-1"]]


def test_a_spent_budget_holds_triage_until_the_window_rolls_and_nothing_is_retained_meanwhile(
    database_url: str,
    tmp_path: Path,
    hindsight: tuple[RecordedHindsight, Served],
    litellm: Served,
    llm: FakeLiteLLM,
) -> None:
    fake = hindsight[0]
    reply = 120 + 40  # one call's tokens: a scripted reply's default usage
    atlas = Atlas(
        database_url,
        tmp_path,
        hindsight[1].url,
        litellm.url,
        retention_triage="on",
        triage_windows_per_section=1,  # one window per section, so the counts below hold
        triage_sections_per_call=4,  # the 10-K's 8 asked sections take two calls
        run_token_budget=reply,  # each attempt's run affords one call
        minimax_budget_tokens=reply,  # each 5 h window affords one call
    )
    atlas.apply_template()
    llm.chat_replies.clear()
    llm.script_chat(*[ChatReply.answer(triage_answer)] * 40)
    clock = Clock(datetime.now(UTC).replace(microsecond=0))
    api = TestClient(create_app(atlas.settings(), clock=clock))

    def paced_pass() -> int:
        """A worker pass on the controllable pacing clock; returns the calls it made."""
        before = len(llm.chat_requests())
        settings = atlas.settings()
        queue = JobQueue(atlas.engine, pacing=Pacing.from_settings(settings), clock=clock)
        Worker(queue, builtin_registry(settings)).run_once()
        return len(llm.chat_requests()) - before

    def check_held_versions_retain_nothing() -> bool:
        """No section is decided by default, and a version whose triage hasn't finished has
        nothing in Hindsight; True if the 10-K is part-decided right now."""
        assert "default" not in {row["method"] for row in triage(atlas)}
        for version_id, each in triage_jobs(atlas).items():
            if each["status"] != "succeeded":
                assert retained_anchors(fake, version_id) == []
        ten_k = atlas.version(LITE_10K)["id"]
        return 0 < len(effective(atlas, ten_k)) < len(TEN_K_ANCHORS)

    atlas.enqueue("ingest", "--company", "lumentum", "--key", "lumentum")
    assert paced_pass() == 1
    part_decided = check_held_versions_retain_nothing()
    # Nothing is paused, but the window is spent: triage is held, with no call.
    clock.advance(minutes=2)
    assert paced_pass() == 0
    queue = api.get("/api/v1/queue").json()
    assert queue["pause"]["pauses_total"] == 0
    (pending,) = [p for p in queue["pending"] if p["kind"] == "triage"]
    assert pending["budget_held"] == pending["queued"] > 0

    windows = 0
    while any(each["status"] != "succeeded" for each in triage_jobs(atlas).values()):
        windows += 1
        assert windows < 30, "triage never finished"
        clock.advance(hours=5, minutes=1)
        assert paced_pass() == 1  # one call per window, each asking only what's undecided
        part_decided = check_held_versions_retain_nothing() or part_decided

    # The 10-K's second call ran out of its run's budget: its job was requeued (no attempt
    # used, not retained by default, nothing paused) and resumed in a later window with a
    # fresh run, asking only what was left.
    assert part_decided
    ten_k = atlas.version(LITE_10K)
    ten_k_job = triage_jobs(atlas)[ten_k["id"]]
    requeued = [f for f in ten_k_job["failures"] if f["classification"] == "requeued"]
    assert requeued
    assert all("token budget" in failure["error"] for failure in requeued)
    assert ten_k_job["attempts"] == 1
    assert api.get("/api/v1/queue").json()["pause"]["pauses_total"] == 0
    calls = [
        (message["request"]["document"]["source_version_id"], section["anchor"])
        for message in asked(llm)
        for section in message["request"]["sections"]
    ]
    assert len(calls) == len(set(calls))  # no section of a version was asked about twice
    rows = triage(atlas, source_version_id=ten_k["id"])
    assert sorted(row["section_anchor"] for row in rows) == sorted(TEN_K_ANCHORS)
    assert retained_anchors(fake, ten_k["id"]) == [["part-i-item-1"]]
    atlas.engine.dispose()


# --- helpers ------------------------------------------------------------------------------------


def retry(atlas: Atlas, *args: str) -> list[dict[str, str]]:
    """`atlas triage retry ...`: the triage jobs it enqueued."""
    retried = atlas.cli("triage", "retry", *args)
    assert retried.returncode == 0, retried.stderr
    return cast(list[dict[str, str]], json.loads(retried.stdout)["enqueued"])


def failed_triage_jobs(atlas: Atlas) -> float:
    return atlas.metrics()[("atlas_triage_failed_jobs", frozenset())]


def triage_jobs(atlas: Atlas) -> dict[str, dict[str, Any]]:
    """Each Source Version's latest `triage` job (read through the API)."""
    with atlas.engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT id, payload->>'source_version_id' FROM job WHERE kind = 'triage'"
                " ORDER BY created_at, id"
            )
        ).all()
    return {version_id: atlas.get(f"/api/v1/jobs/{job_id}") for job_id, version_id in rows}


def start_investigation(atlas: Atlas) -> str:
    """An investigation row for a request to name (its tasks are not run here)."""
    response = atlas.api.post(
        "/api/v1/investigations",
        json={"theme": "photonics", "question": "Who supplies Lumentum's lasers?"},
    )
    assert response.status_code == 202, response.text
    return cast(str, response.json()["id"])


def editable_fixtures(tmp_path: Path) -> Path:
    root = tmp_path / "edgar"
    shutil.copytree(EDGAR_FIXTURES, root)
    return root


def change_recorded_document(
    root: Path, url: str, old: bytes, new: bytes, last_modified: str
) -> None:
    """Serve changed bytes for a recorded document, with a new Last-Modified, as SEC would."""
    path = root / "lumentum" / "manifest.json"
    manifest = json.loads(path.read_text())
    entry = next(entry for entry in manifest["responses"] if entry["url"] == url)
    entry["headers"]["last-modified"] = last_modified
    path.write_text(json.dumps(manifest, indent=2))
    body = root / "lumentum" / entry["file"]
    original = body.read_bytes()
    assert original.count(old) == 1
    body.write_bytes(original.replace(old, new))
