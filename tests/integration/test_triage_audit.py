"""The triage audit (ticket 33): how often triage skips a section a full reading would retain.

Seam: `atlas ingest` and single worker passes triage Lumentum's recorded EDGAR filings, then
`atlas triage audit` (the CLI) draws a sample of the skipped sections and enqueues the
`triage_audit` job, worker passes run it, and the results are read through
`GET /api/v1/triage/audits[/{id}]` and the chat completions LiteLLM was asked for.
LiteLLM is the scripted chat fake; **both roles' answers are written here**:

- the Triage role (`triage_answer`) reads only each section's opening window
  (`triage_windows_per_section=1`) and retains nothing but the 10-K's Business section, the
  8-K's results item and the press release's first chunk;
- the full-section judge (`judge_answer`) retains a text if it contains `KEY`, a sentence from
  deep inside the 10-K's Item 1A (about 79,000 characters in, of 143,495; the recorded
  fixture's parsed text): a capacity detail the opening-only reader never saw.
"""

import json
import os
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from pydantic import JsonValue

from tests.fakes.hindsight import RecordedHindsight
from tests.fakes.litellm import ChatReply, FakeLiteLLM
from tests.fakes.serve import Served, serve
from tests.harness import LITE_10K, SITES, THEMES, Atlas

KEY = "lower cost of non-U.S. manufacturing"
RISK_FACTORS = "part-i-item-1a"
RISK_FACTORS_LENGTH = 143_495  # the recorded 10-K's Item 1A, in characters
JUDGE_MAX_CHARS = 60_000
RETAINED_HEADINGS = {
    "ITEM 1. BUSINESS",
    "Item 2.02. Results of Operations and Financial Condition.",
}


def triage_answer(body: dict[str, Any]) -> JsonValue:
    """The stand-in Triage role: retains only the headings above (and the press release)."""
    user = json.loads(body["messages"][1]["content"])
    decisions: list[JsonValue] = []
    for section in user["request"]["sections"]:
        keep = section["heading"] in RETAINED_HEADINGS or section["anchor"] == "chunk-001"
        decisions.append(
            {
                "anchor": section["anchor"],
                "decision": "retain" if keep else "skip",
                "category": "supplier_customer" if keep else "other",
                "reason": f"{'names' if keep else 'no'} bottleneck content",
            }
        )
    return {"decisions": decisions}


def judge_answer(body: dict[str, Any]) -> JsonValue:
    """The stand-in judge: retains a text that states the capacity detail `KEY`."""
    user = json.loads(body["messages"][1]["content"])
    (quoted,) = user["retrieved_data"]
    if KEY in quoted["text"]:
        return {
            "decision": "retain",
            "category": "capacity",
            "reason": "manufacturing footprint moving to non-U.S. sites",
        }
    return {"decision": "skip", "category": "other", "reason": "generic text"}


def judge_requests(llm: FakeLiteLLM) -> list[dict[str, Any]]:
    """The user message of each judge call so far."""
    return [
        json.loads(body["messages"][1]["content"])
        for body in llm.chat_requests()
        if body["response_format"]["json_schema"]["name"] == "triage_judge"
    ]


@pytest.fixture
def llm() -> FakeLiteLLM:
    return (
        FakeLiteLLM()
        .script_chat(*[ChatReply.answer(triage_answer)] * 12)
        .script_role("triage_judge", *[ChatReply.answer(judge_answer)] * 200)
    )


@pytest.fixture
def atlas(
    database_url: str,
    tmp_path: Path,
    hindsight: tuple[RecordedHindsight, Served],
    llm: FakeLiteLLM,
) -> Iterator[Atlas]:
    with serve(llm.handle) as litellm:
        harness = Atlas(
            database_url,
            tmp_path,
            hindsight[1].url,
            litellm.url,
            retention_triage="on",
            triage_windows_per_section=1,  # the opening-only reader
            triage_audit_samples_per_attempt=2,  # several attempts, each requeued
        )
        harness.apply_template()
        job = harness.ingest("lumentum")
        assert job["status"] == "succeeded", job["failures"]
        yield harness
        harness.engine.dispose()
        litellm.raise_errors()


def audit_cli(atlas: Atlas, *args: str) -> subprocess.CompletedProcess[str]:
    return atlas.cli("triage", "audit", *args)


def create(atlas: Atlas, *args: str) -> dict[str, Any]:
    created = audit_cli(atlas, *args)
    assert created.returncode == 0, created.stderr
    return json.loads(created.stdout)


def skipped(atlas: Atlas) -> dict[str, dict[str, Any]]:
    """Lumentum's effective skip decisions, by ID."""
    company = atlas.company("lumentum")["id"]
    decisions = atlas.get(
        "/api/v1/triage", company_id=company, decision="skip", effective="true", limit=500
    )["items"]
    return {decision["id"]: decision for decision in decisions}


# --- a miss past the windows read ---------------------------------------------------------------


def test_a_skipped_section_whose_detail_lies_past_the_windows_read_is_found_and_is_a_miss(
    atlas: Atlas, llm: FakeLiteLLM
) -> None:
    ten_k = atlas.version(LITE_10K)
    risk = next(
        d
        for d in skipped(atlas).values()
        if (d["source_version_id"], d["section_anchor"])
        == (
            ten_k["id"],
            RISK_FACTORS,
        )
    )
    assert risk["method"] == "role"  # triage read its opening and skipped it
    population = len(skipped(atlas))

    created = create(atlas, "--company", "lumentum", "--sample", "100", "--seed", "7")
    assert created["status"] == "running"
    assert created["population"] == created["sample_size"] == population  # all of them
    assert atlas.worker_pass() >= 2  # requeued after each 2 samples, till done

    audit = atlas.get(f"/api/v1/triage/audits/{created['triage_audit_id']}")
    assert audit["status"] == "completed"
    assert audit["job_status"] == "succeeded"
    assert audit["judge_rubric_version"] == "triage_judge.v1"
    assert audit["triage_rubric_version"] == "triage.v2"
    assert audit["judge_max_chars"] == JUDGE_MAX_CHARS  # the default
    samples = {(s["source_version_id"], s["section_anchor"]): s for s in audit["samples"]}
    assert len(samples) == population == audit["samples_judged"]

    miss = samples[(ten_k["id"], RISK_FACTORS)]
    assert miss["triage_decision_id"] == risk["id"]
    assert (miss["triage_decision"], miss["triage_method"]) == ("skip", "role")
    assert miss["char_end"] - miss["char_start"] == RISK_FACTORS_LENGTH
    assert (miss["form"], miss["length_band"]) == ("10-K", "50k-plus")
    assert miss["windows_read"] == 1 < miss["windows_total"]
    assert miss["judge_decision"] == "retain"
    assert miss["judge_category"] == "capacity"
    # Three chunks of at most 60,000 characters; the detail is in the second, where the
    # judge stopped reading.
    assert miss["judge_reason"] == ("chunk 2/3: manufacturing footprint moving to non-U.S. sites")
    assert miss["judge_chunks"] == 2
    assert len(miss["role_call_ids"]) == 2
    assert miss["agreement"] is False
    assert miss["error"] is None
    # Every other skipped section is judged in full and agrees.
    for key, sample in samples.items():
        if key != (ten_k["id"], RISK_FACTORS):
            assert (sample["judge_decision"], sample["agreement"]) == ("skip", True)

    # The judge read the archived parse, whole, in overlapping chunks, as low-trust data.
    parsed = atlas.parsed(ten_k["id"])
    start = miss["char_start"]
    chunks = [
        m
        for m in judge_requests(llm)
        if m["request"]["document"]["source_version_id"] == ten_k["id"]
        and m["request"]["section"]["anchor"] == RISK_FACTORS
    ]
    assert [
        (m["request"]["section"]["chunk"], m["request"]["section"]["chunks"]) for m in chunks
    ] == [
        (1, 3),
        (2, 3),
    ]
    assert chunks[0]["retrieved_data"][0]["text"] == parsed[start : start + 60_000]
    assert chunks[1]["retrieved_data"][0]["text"] == parsed[start + 59_800 : start + 119_800]
    assert chunks[1]["retrieved_data"][0]["trust"] == "low"
    assert chunks[0]["request"]["section"]["length"] == RISK_FACTORS_LENGTH
    assert KEY not in parsed[start : start + 1500]  # not in the window triage read
    # A short section is one call with its whole text.
    short = next(s for s in samples.values() if s["length_band"] == "under-2k")
    (whole,) = [
        m
        for m in judge_requests(llm)
        if m["request"]["document"]["source_version_id"] == short["source_version_id"]
        and m["request"]["section"]["anchor"] == short["section_anchor"]
    ]
    assert (
        whole["retrieved_data"][0]["text"]
        == atlas.parsed(short["source_version_id"])[short["char_start"] : short["char_end"]]
    )

    summary = audit["summary"]
    assert (summary["sampled"], summary["judged"], summary["pending"]) == (
        population,
        population,
        0,
    )
    assert (summary["misses"], summary["unjudged"]) == (1, 0)
    assert summary["miss_rate"] == pytest.approx(1 / population)
    assert summary["wilson_low"] < summary["miss_rate"] < summary["wilson_high"]
    bands = {rate["key"]: rate for rate in summary["by_length_band"]}
    assert (bands["50k-plus"]["misses"], bands["50k-plus"]["judged"]) == (1, 1)
    assert bands["50k-plus"]["miss_rate"] == 1.0
    assert all(rate["misses"] == 0 for key, rate in bands.items() if key != "50k-plus")
    assert {rate["key"]: rate["misses"] for rate in summary["by_category"]}["other"] == 1
    assert summary["misses_by_judge_category"] == {"capacity": 1}
    (example,) = summary["examples"]
    assert (example["source_version_id"], example["section_anchor"]) == (
        ten_k["id"],
        RISK_FACTORS,
    )
    assert example["judge_reason"] == miss["judge_reason"]
    assert example["section_heading"] == "ITEM 1A. RISK FACTORS"

    listed = atlas.get("/api/v1/triage/audits")
    assert [item["id"] for item in listed["items"]] == [created["triage_audit_id"]]
    assert listed["items"][0]["samples_judged"] == population
    assert atlas.api.get(f"/api/v1/triage/audits/{ten_k['id']}").status_code == 404
    # A completed audit's job, run again, judges nothing more.
    assert atlas.worker_pass() == 0


def test_audit_wait_prints_the_summary_once_the_worker_has_judged_the_sample(
    atlas: Atlas,
) -> None:
    command = [sys.executable, "-m", "atlas", "triage", "audit", "--company", "lumentum"]
    command += ["--sample", "3", "--seed", "2", "--wait", "--poll-seconds", "0.2"]
    env = atlas_cli_env(atlas)
    with subprocess.Popen(
        command, cwd=atlas.tmp_path, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    ) as process:
        deadline = time.monotonic() + 90
        while process.poll() is None:
            assert time.monotonic() < deadline, "atlas triage audit --wait never returned"
            atlas.worker_pass()
            time.sleep(0.2)
        stdout, stderr = process.communicate()
    assert process.returncode == 0, stderr.decode()
    printed = json.loads(stdout)
    assert printed["status"] == "completed"
    assert printed["summary"]["judged"] == printed["sample_size"] == 3
    audit = atlas.get(f"/api/v1/triage/audits/{printed['triage_audit_id']}")
    assert printed["summary"] == audit["summary"]
    assert "miss rate" in stderr.decode()


# --- sampling -----------------------------------------------------------------------------------


def test_the_sample_is_seeded_and_stratified_by_form_and_length_band(atlas: Atlas) -> None:
    population = skipped(atlas)

    first = create(atlas, "--company", "lumentum", "--sample", "6", "--seed", "7")
    again = create(atlas, "--company", "lumentum", "--sample", "6", "--seed", "7")
    other = create(atlas, "--company", "lumentum", "--sample", "6", "--seed", "8")

    def read(created: dict[str, Any]) -> dict[str, Any]:
        return atlas.get(f"/api/v1/triage/audits/{created['triage_audit_id']}")

    a, b, c = read(first), read(again), read(other)
    assert len(a["plan"]) == 6
    assert a["plan"] == b["plan"]  # same seed, same decisions: the same sample, in order
    assert c["plan"] != a["plan"]
    assert set(a["plan"]) <= set(population)  # effective skips of Lumentum only
    assert a["strata"] == b["strata"]
    # Every stratum of the population is listed with its size; the sample is spread across
    # them, no stratum taking two more than another that still had sections left.
    strata = a["strata"]
    assert sum(s["population"] for s in strata) == len(population) == a["population"]
    assert sum(s["sampled"] for s in strata) == 6
    for mine in strata:
        for theirs in strata:
            assert (
                mine["sampled"] <= theirs["sampled"] + 1
                or theirs["sampled"] == theirs["population"]
            )
    by_id = {decision_id: population[decision_id] for decision_id in a["plan"]}
    bands = {s["length_band"] for s in strata if s["sampled"]}
    assert len(bands) > 1  # short and long sections both drawn
    assert len(by_id) == 6


def test_an_audit_is_refused_for_an_unknown_company_or_nothing_skipped(atlas: Atlas) -> None:
    unknown = audit_cli(atlas, "--company", "no-such-company")
    assert unknown.returncode == 2
    assert "unknown company" in unknown.stderr
    assert atlas.cli("companies", "seed").returncode == 0
    nothing = audit_cli(atlas, "--company", "coherent")  # seeded, never ingested
    assert nothing.returncode == 2
    assert "no section of coherent" in nothing.stderr
    assert atlas.get("/api/v1/triage/audits")["total"] == 0


def atlas_cli_env(atlas: Atlas) -> dict[str, str]:
    """The environment `Atlas.cli` runs the CLI with (for a CLI run in the background)."""
    return {
        "PATH": os.environ["PATH"],
        "HOME": str(atlas.tmp_path),
        "ATLAS_DATABASE_URL": atlas.database_url,
        "ATLAS_ACTOR": "local-researcher",
        "ATLAS_ARCHIVE_ROOT": str(atlas.archive),
        "ATLAS_THEMES_CONFIG": str(THEMES),
        "ATLAS_SOURCE_SITES_CONFIG": str(SITES),
        "ATLAS_HINDSIGHT_URL": atlas.hindsight_url,
    }
