"""The Phase 2 gate, end to end against real Hindsight 0.10.1 and MiniMax via LiteLLM.

**Opt-in and never in CI** (spec Part B, Testing Decisions: live tests). It needs the `live`
marker *and* `ATLAS_LIVE_TESTS` (see `tests/live/stack.py`); without the second, every scenario
is skipped. `scripts/live-tests.sh` brings up the stack, runs it and records the results
(`docs/runbooks.md`, "Live test suite"). A live run spends MiniMax quota: the default forms
(`10-Q`, about 18k characters) cost roughly what the extraction bake-off did.

The seam is the gate tests': the `atlas` CLI applies the template and enqueues the ingests,
single worker passes run the ingest, retain, poll, reprocess and reflect jobs, and everything is
observed through `/api/v1`. Unlike the gate tests, nothing here chooses what the model says:
the scenarios assert what must hold for any correct answer (every cited memory resolves, no
citation is broken, sections end in a final state) and *report* the rest, such as which
citations and quotes were unverified and why, and which sections gave zero facts.

The scenarios share one run (module-scoped fixtures), in order: preflight, template, ingest
and retain (waiting for the operations), consolidation, recall, reflect.
"""

import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from atlas.api.app import create_app
from atlas.db.migrate import upgrade
from atlas.jobs import JobQueue, Pacing, Worker, builtin_registry
from atlas.settings import Settings
from tests.live.stack import (
    HINDSIGHT_VERSION,
    REFUSED,
    REPO,
    LiveReport,
    LiveStack,
    Refused,
    Rehearsal,
    live_mode,
    live_stack,
)

THEMES = REPO / "configs" / "themes" / "ai-infrastructure.yaml"
TEMPLATE = REPO / "configs" / "hindsight" / "bank-template.json"
EDGAR_FIXTURES = REPO / "tests" / "fixtures" / "edgar"
COMPANIES = ("lumentum", "coherent")
FINAL_STATES = {"completed", "zero_fact", "linked"}

RECALL_QUERY = "Lumentum and Coherent: reporting periods, revenue, products and headquarters"
REFLECT_QUESTION = (
    "Using only the Lumentum and Coherent filings in memory: for each company, state its most "
    "recent reporting period and one fact it reported about its business or results. Support "
    "each point with a short passage quoted verbatim from the filing, in double quotes."
)


class Atlas:
    """The app under test: a fresh database, a local archive, the CLI, the worker and the API."""

    def __init__(self, stack: LiveStack, database_url: str, tmp_path: Path) -> None:
        self.stack = stack
        self.database_url = database_url
        self.tmp_path = tmp_path
        self.archive = tmp_path / "archive"
        self.archive.mkdir(exist_ok=True)
        self.engine = create_engine(database_url)
        # Retention is off when the run stops before LLM-backed calls: ingest enqueues no retain.
        self.retain = not stack.stop_before_llm
        self.api = TestClient(create_app(self.settings()))
        self.pauses_seen: list[dict[str, Any]] = []

    def settings(self) -> Settings:
        stack = self.stack
        return Settings.model_validate(
            {
                "database_url": self.database_url,
                "actor": "live-test",
                "archive_root": self.archive,
                "themes_config": THEMES,
                "sec_fixtures_dir": EDGAR_FIXTURES,
                "hindsight_url": stack.hindsight_url if self.retain else None,
                "hindsight_api_key": stack.hindsight_api_key,
                "hindsight_version": os.environ.get("ATLAS_LIVE_HINDSIGHT_VERSION") or None,
                "hindsight_bank_id": stack.bank_id,
                "hindsight_template_path": TEMPLATE,
                "litellm_url": stack.litellm_url,
                "litellm_api_key": stack.litellm_api_key,
                "llm_extract_alias": stack.extract_alias,
                "llm_reflect_alias": stack.reflect_alias,
                "retain_poll_timeout_seconds": stack.poll_timeout_seconds,
                "retain_poll_interval_seconds": stack.poll_interval_seconds,
                "retain_poll_attempts": stack.poll_attempts,
                "backfill_window": "",
            }
        )

    def cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = {
            "PATH": os.environ["PATH"],
            "HOME": str(self.tmp_path),
            "ATLAS_DATABASE_URL": self.database_url,
            "ATLAS_ACTOR": "live-test",
            "ATLAS_ARCHIVE_ROOT": str(self.archive),
            "ATLAS_THEMES_CONFIG": str(THEMES),
            "ATLAS_SEC_FIXTURES_DIR": str(EDGAR_FIXTURES),
            "ATLAS_HINDSIGHT_URL": self.stack.hindsight_url,
            "ATLAS_HINDSIGHT_BANK_ID": self.stack.bank_id,
            **(
                {"ATLAS_HINDSIGHT_API_KEY": self.stack.hindsight_api_key}
                if self.stack.hindsight_api_key
                else {}
            ),
            "ATLAS_HINDSIGHT_TEMPLATE_PATH": str(TEMPLATE),
        }
        return subprocess.run(
            [sys.executable, "-m", "atlas", *args],
            cwd=self.tmp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
        )

    def worker_pass(self) -> int:
        settings = self.settings()
        queue = JobQueue(self.engine, pacing=Pacing.from_settings(settings))
        return Worker(queue, builtin_registry(settings)).run_once()

    def drain(self) -> float:
        """Run worker passes until no job is queued or running (waiting out queue pauses), or
        the retain deadline passes. Returns the seconds it took."""
        started = time.monotonic()
        while True:
            ran = self.worker_pass()
            queue = self.get("/api/v1/queue")
            if queue["pause"]["paused"]:
                self.pauses_seen.append(queue["pause"])
            if not any(k["queued"] or k["running"] for k in queue["pending"]):
                return time.monotonic() - started
            if time.monotonic() - started > self.stack.retain_deadline_seconds:
                pending = [k for k in queue["pending"] if k["queued"] or k["running"]]
                pytest.fail(f"jobs still pending at the deadline: {pending}")
            if ran == 0:
                time.sleep(self.stack.idle_sleep_seconds)

    def get(self, path: str, **params: Any) -> Any:
        response = self.api.get(path, params=params)
        assert response.status_code == 200, response.text
        return response.json()

    def company(self, slug: str) -> dict[str, Any]:
        companies = self.get("/api/v1/companies")["items"]
        return next(company for company in companies if company["slug"] == slug)

    def versions(self, slug: str) -> list[dict[str, Any]]:
        """Every Source Version of the company, with its details."""
        company = self.company(slug)
        documents = self.get(f"/api/v1/companies/{company['id']}/sources", limit=100)["items"]
        versions: list[dict[str, Any]] = []
        for document in documents:
            for summary in self.get(f"/api/v1/sources/{document['id']}/versions")["items"]:
                versions.append(self.get(f"/api/v1/source-versions/{summary['id']}"))
        return versions

    def memory(self, version_id: str) -> dict[str, Any]:
        return self.get(f"/api/v1/source-versions/{version_id}/memory")

    def close(self) -> None:
        self.api.close()
        self.engine.dispose()


@dataclass
class Retained:
    """What the ingest and retention left: per company, its Source Versions and their memory."""

    versions: dict[str, list[dict[str, Any]]]  # company slug -> Source Versions
    memory: dict[str, dict[str, Any]]  # Source Version ID -> its memory documents

    def documents(self) -> list[dict[str, Any]]:
        return [d for memory in self.memory.values() for d in memory["documents"]]

    def first_completed(self) -> list[str]:
        """One completed section's Hindsight document ID per company, in COMPANIES order."""
        found: list[str] = []
        for slug in COMPANIES:
            for version in self.versions[slug]:
                completed = [
                    d["document_id"]
                    for d in self.memory[version["id"]]["documents"]
                    if d["retain_state"] == "completed"
                ]
                if completed:
                    found.append(completed[-1])
                    break
        return found


# --- the run, shared by the scenarios ------------------------------------------------------


@pytest.fixture(scope="module")
def stack() -> Iterator[LiveStack]:
    mode = live_mode()
    assert mode is not None  # tests/live/conftest.py skips every scenario otherwise
    with live_stack(mode) as configured:
        yield configured


@pytest.fixture(scope="module")
def report(stack: LiveStack) -> Iterator[LiveReport]:
    run = LiveReport(stack.mode, stack.stop_before_llm)
    yield run
    if results := os.environ.get("ATLAS_LIVE_RESULTS_DIR"):
        run.write(Path(results))


@pytest.fixture(scope="module")
def preflight(stack: LiveStack, report: LiveReport) -> dict[str, Any]:
    try:
        checked = stack.preflight()
    except Refused as error:
        report.add("refused", str(error))
        if results := os.environ.get("ATLAS_LIVE_RESULTS_DIR"):
            report.write(Path(results))
        pytest.exit(f"live suite refused: {error}", returncode=REFUSED)
    report.add("stack", checked | {"forms": stack.forms})
    return checked


@pytest.fixture(scope="module")
def atlas(
    stack: LiveStack,
    preflight: dict[str, Any],
    report: LiveReport,
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[Atlas]:
    with stack.fresh_database() as database_url:
        upgrade(database_url)
        if stack.keep_database:
            report.sections["stack"]["database"] = database_url.rsplit("/", 1)[-1]
        harness = Atlas(stack, database_url, tmp_path_factory.mktemp("live"))
        yield harness
        harness.close()


@pytest.fixture(scope="module")
def template(atlas: Atlas, stack: LiveStack, report: LiveReport) -> dict[str, Any] | None:
    """The template applied through the CLI; None if a stopped run must not import it."""
    manifest = json.loads(TEMPLATE.read_text(encoding="utf-8"))["manifest"]
    if stack.stop_before_llm and manifest.get("mental_models"):
        report.add("template", "not applied: its mental models would queue LLM refreshes")
        return None
    applied = atlas.cli("hindsight", "apply-template")
    assert applied.returncode == 0, applied.stderr
    summary: dict[str, Any] = json.loads(applied.stdout)
    report.add("template", summary)
    return summary


@pytest.fixture(scope="module")
def ingested(
    atlas: Atlas, template: dict[str, Any] | None, stack: LiveStack, report: LiveReport
) -> dict[str, list[dict[str, Any]]]:
    """Both companies' fixtures ingested, and (unless stopped) every retain waited for."""
    jobs: dict[str, str] = {}
    for slug in COMPANIES:
        enqueued = atlas.cli("ingest", "--company", slug, "--forms", stack.forms, "--key", slug)
        assert enqueued.returncode == 0, enqueued.stderr
        jobs[slug] = json.loads(enqueued.stdout)["id"]
    seconds = atlas.drain()
    versions = {slug: atlas.versions(slug) for slug in COMPANIES}
    report.add(
        "ingest",
        {
            "forms": stack.forms,
            "drain_seconds": round(seconds),
            "queue_pauses": atlas.pauses_seen,
            "jobs": {
                slug: atlas.get(f"/api/v1/jobs/{job}")["status"] for slug, job in jobs.items()
            },
            "versions": {
                slug: [
                    {
                        "id": v["id"],
                        "form": v["source_document"]["form_type"],
                        "document_type": v["source_document"]["document_type"],
                        "url": v["source_document"]["canonical_url"],
                        "parse_status": v["parse_status"],
                        "available_at": v["available_at"],
                    }
                    for v in company_versions
                ]
                for slug, company_versions in versions.items()
            },
        },
    )
    for slug, job in jobs.items():
        status = atlas.get(f"/api/v1/jobs/{job}")
        assert status["status"] == "succeeded", (slug, status.get("failures"))
    return versions


@pytest.fixture(scope="module")
def retained(
    atlas: Atlas, stack: LiveStack, ingested: dict[str, list[dict[str, Any]]], report: LiveReport
) -> Retained:
    if stack.stop_before_llm:
        pytest.skip("stopped before LLM-backed calls (ATLAS_LIVE_STOP_BEFORE_LLM)")
    memory = {v["id"]: atlas.memory(v["id"]) for vs in ingested.values() for v in vs}
    report.add("retention", _retention_report(ingested, memory))
    return Retained(ingested, memory)


@pytest.fixture(scope="module")
def consolidated(stack: LiveStack, retained: Retained, report: LiveReport) -> str | None:
    """Wait for Hindsight's consolidation; returns an observation ID in a rehearsal."""
    outcome = stack.wait_for_consolidation(retained.first_completed())
    report.add("consolidation", outcome)
    ids: list[str] = outcome.get("observation_ids", [])
    return ids[0] if ids else None


# --- scenarios ------------------------------------------------------------------------------


def test_preflight_finds_hindsight_0_10_1_and_routed_aliases(
    stack: LiveStack, preflight: dict[str, Any]
) -> None:
    assert preflight["hindsight_version"] == HINDSIGHT_VERSION
    assert set(preflight["routed_models"]) == set(stack.aliases)
    assert all(preflight["routed_models"][alias] for alias in stack.aliases)


def test_bank_template_is_applied_to_the_research_bank(
    stack: LiveStack, template: dict[str, Any] | None
) -> None:
    if template is None:
        pytest.skip("the template has mental models; a stopped run doesn't import it")
    wrapper = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    assert template["bank_id"] == stack.bank_id
    assert template["template_version"] == wrapper["template_version"]
    with stack.gateway() as gateway:
        config = gateway.bank_config().config
    for key, value in wrapper["manifest"]["bank"].items():
        assert config[key] == value, key


def test_both_companies_fixtures_are_ingested_as_parsed_source_versions(
    ingested: dict[str, list[dict[str, Any]]],
) -> None:
    for slug in COMPANIES:
        parsed = [v for v in ingested[slug] if v["parse_status"] == "parsed"]
        assert parsed, f"{slug}: no parsed Source Version"
        assert all(
            v["available_at_basis"] in {"sec_acceptance", "sec_dissemination"} for v in parsed
        )


def test_every_retained_section_reaches_a_final_state_through_completed_operations(
    retained: Retained,
) -> None:
    documents = retained.documents()
    assert documents, "nothing was retained"
    stuck = [(d["document_id"], d["retain_state"], d["error"]) for d in documents]
    stuck = [each for each in stuck if each[1] not in FINAL_STATES]
    assert not stuck, f"sections not final: {stuck}"
    for memory in retained.memory.values():
        for operation in memory["operations"]:
            assert operation["status"] == "completed", operation
    for d in documents:
        if d["retain_state"] == "completed":
            assert d["fact_count"] and d["fact_count"] > 0, d
    for slug in COMPANIES:
        ids = {v["id"] for v in retained.versions[slug]}
        facts = sum(m["fact_count"] for vid, m in retained.memory.items() if vid in ids)
        assert facts > 0, f"{slug}: no facts extracted"


def test_cross_company_recall_returns_both_companies_with_resolved_provenance(
    atlas: Atlas, retained: Retained, consolidated: str | None, report: LiveReport
) -> None:
    lumentum, coherent = atlas.company("lumentum"), atlas.company("coherent")
    response = atlas.api.post(
        "/api/v1/memory/recall",
        json={"query": RECALL_QUERY, "scope": {"company_ids": [lumentum["id"], coherent["id"]]}},
    )
    assert response.status_code == 200, response.text
    recalled = response.json()
    memories: list[dict[str, Any]] = recalled["memories"]
    report.add(
        "recall", _recall_report(recalled, {lumentum["id"]: "lumentum", coherent["id"]: "coherent"})
    )

    assert recalled["scope"]["tags_match"] == "any_strict"
    assert memories, "recall returned nothing"
    unresolved = [(m["type"], m["provenance"]["reason"], m["text"][:120]) for m in memories]
    unresolved = [
        each
        for each, m in zip(unresolved, memories, strict=True)
        if m["provenance"]["state"] != "resolved"
    ]
    assert not unresolved, f"recalled memories not resolved: {unresolved}"
    companies = {s["company_id"] for m in memories for s in m["provenance"]["sources"]}
    assert companies == {lumentum["id"], coherent["id"]}

    sections = {
        d["document_id"]: (vid, d) for vid, m in retained.memory.items() for d in m["documents"]
    }
    available = {v["id"]: v["available_at"] for vs in retained.versions.values() for v in vs}
    for memory in memories:
        for source in memory["provenance"]["sources"]:
            version_id, section = sections[source["document_id"]]
            assert source["source_version_id"] == version_id
            assert source["section_anchor"] == section["section_anchor"]
            assert source["section_char_start"] == section["char_start"]
            assert source["section_char_end"] == section["char_end"]
            assert source["available_at"] == available[version_id]


def test_reflect_citations_resolve_and_unverified_ones_are_reported(
    atlas: Atlas, stack: LiveStack, retained: Retained, consolidated: str | None, report: LiveReport
) -> None:
    stack.before_reflect(retained.first_completed(), consolidated)
    response = atlas.api.post(
        "/api/v1/memory/reflect",
        json={"question": REFLECT_QUESTION, "scope": {"theme_ids": ["photonics"]}},
    )
    assert response.status_code == 202, response.text
    answer_id = response.json()["research_answer"]["id"]
    seconds = atlas.drain()
    answer = atlas.get(f"/api/v1/memory/reflect/{answer_id}")
    report.add("reflect", _reflect_report(answer, seconds))

    assert answer["status"] == "completed", answer["error"]
    assert answer["run_id"] is not None, "no run recorded (LiteLLM not configured?)"
    citations: list[dict[str, Any]] = answer["citations"]
    assert answer["counts"]["broken"] == 0, [c for c in citations if c["state"] == "broken"]
    memory_citations = [c for c in citations if c["kind"] == "memory"]
    unresolved = [
        (c["memory_type"], c["reason"], c["text"][:120])
        for c in memory_citations
        if c["state"] != "resolved"
    ]
    assert not unresolved, f"cited memories not resolved: {unresolved}"
    assert answer["evidence"], "no Evidence: nothing the answer cites resolved"
    assert answer["evidence_missing"] is False
    if stack.rehearsal is not None:
        # The scripted answer: a raw chunk and a paraphrased "quote" are unverified.
        reasons = {c["reason"] for c in citations if c["state"] == "unverified"}
        assert reasons == {"no_memory_id", "quote_mismatch"}
        quotes = {c["text"]: c["state"] for c in citations if c["kind"] == "quote"}
        assert quotes == {
            Rehearsal.LITE_QUOTE: "resolved",
            Rehearsal.COHR_QUOTE: "resolved",
            Rehearsal.PARAPHRASE: "unverified",
        }


def test_zero_fact_sections_are_visible_after_their_one_reprocess(
    atlas: Atlas, retained: Retained, report: LiveReport
) -> None:
    zero = [d for d in retained.documents() if d["retain_state"] == "zero_fact"]
    metric = _metric(atlas.api.get("/metrics").text, "atlas_zero_fact_sections")
    report.add(
        "zero_fact",
        {
            "sections": [
                {"document_id": d["document_id"], "chars": d["char_end"] - d["char_start"]}
                for d in zero
            ],
            "metric": metric,
        },
    )
    if not zero:
        pytest.skip("no section gave zero facts in this run: the zero-fact path wasn't exercised")
    for d in zero:
        assert d["fact_count"] == 0 and d["reprocess_count"] == 1, d
    assert sum(m["counts"].get("zero_fact", 0) for m in retained.memory.values()) == len(zero)
    assert metric == len(zero)


def test_llm_usage_is_recorded(stack: LiveStack, retained: Retained, report: LiveReport) -> None:
    """Not a gate scenario: the bank's LLM calls and tokens, for the log (live only)."""
    usage = stack.llm_usage()
    if usage is None:
        pytest.skip("a rehearsal makes no LLM calls")
    report.add("llm_usage", usage)


# --- reporting helpers ----------------------------------------------------------------------


def _retention_report(
    versions: dict[str, list[dict[str, Any]]], memory: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for slug, company_versions in versions.items():
        out[slug] = []
        for version in company_versions:
            mem = memory[version["id"]]
            out[slug].append(
                {
                    "source_version_id": version["id"],
                    "form": version["source_document"]["form_type"],
                    "counts": mem["counts"],
                    "fact_count": mem["fact_count"],
                    "sections": [
                        {
                            "anchor": d["section_anchor"],
                            "chars": d["char_end"] - d["char_start"],
                            "state": d["retain_state"],
                            "facts": d["fact_count"],
                            "reprocessed": d["reprocess_count"],
                            "error": d["error"],
                        }
                        for d in mem["documents"]
                    ],
                    "operations": [
                        {
                            "id": o["id"],
                            "kind": o["kind"],
                            "status": o["status"],
                            "error_class": o["error_class"],
                            "error": o["error_message"],
                            "submitted_at": o["submitted_at"],
                            "completed_at": o["completed_at"],
                        }
                        for o in mem["operations"]
                    ],
                }
            )
    return out


def _recall_report(recalled: dict[str, Any], companies: dict[str, str]) -> dict[str, Any]:
    per_company: dict[str, int] = {}
    types: dict[str, int] = {}
    for memory in recalled["memories"]:
        types[memory["type"]] = types.get(memory["type"], 0) + 1
        for slug in {companies.get(s["company_id"], "?") for s in memory["provenance"]["sources"]}:
            per_company[slug] = per_company.get(slug, 0) + 1
    return {
        "query": recalled["query"],
        "tags": recalled["scope"]["tags"],
        "tags_match": recalled["scope"]["tags_match"],
        "memories": len(recalled["memories"]),
        "counts": recalled["counts"],
        "by_type": types,
        "by_company": per_company,
        "unresolved": [
            {"type": m["type"], "reason": m["provenance"]["reason"], "text": m["text"][:200]}
            for m in recalled["memories"]
            if m["provenance"]["state"] != "resolved"
        ],
    }


def _reflect_report(answer: dict[str, Any], seconds: float) -> dict[str, Any]:
    citations: list[dict[str, Any]] = answer.get("citations") or []
    kinds: dict[str, dict[str, int]] = {}
    for c in citations:
        by_state = kinds.setdefault(c["kind"], {})
        by_state[c["state"]] = by_state.get(c["state"], 0) + 1
    return {
        "research_answer_id": answer["id"],
        "status": answer["status"],
        "error": answer["error"],
        "seconds": round(seconds),
        "run_id": answer["run_id"],
        "counts": answer["counts"],
        "by_kind": kinds,
        "evidence_sections": len(answer.get("evidence") or []),
        "unverified": [
            {"kind": c["kind"], "reason": c["reason"], "text": c["text"][:200]}
            for c in citations
            if c["state"] == "unverified"
        ],
        "broken": [
            {"kind": c["kind"], "reason": c["reason"], "memory_id": c["memory_id"]}
            for c in citations
            if c["state"] == "broken"
        ],
        "answer": answer["answer"],
    }


def _metric(exposition: str, name: str) -> float | None:
    match = re.search(rf"^{name}(?:_total)?(?:\{{\}})? (\S+)$", exposition, re.MULTILINE)
    return float(match.group(1)) if match else None
