"""Atlas's records are reconciled with Memory every night (memory-quality ticket 22).

A read-only `reconcile_memory` job compares what Atlas records about the research bank with
what Hindsight holds, records every difference by kind (one insert-only row per run) and
shows it: the health read's `reconciliation`, `GET /api/v1/memory/reconciliations[/{id}]`,
the gauge `atlas_memory_drift{kind}` and the alert rules.

Seams: the `atlas` CLI (`memory reconcile`, `ingest`, `memory consolidate`), single worker
passes with the worker's schedules on a controllable clock, `/api/v1` and `/metrics`, and the
requests the recorded Hindsight fake received. The fake derives the document listing, the bank
config after a template import, the LLM request stats (`GET .../llm-requests/stats`) and a live
config change, built to the shapes the lead read from Hindsight 0.10.2 on 2026-10-03 (not
recorded; tests/fakes/hindsight.py, "The reconciliation's listings"); the rest are its earlier
derivations. Nothing live is called; an old profile and a stuck section are arranged in the
database, as in the backfill's tests.
"""

import json
import os
import subprocess
import sys
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from atlas.api.app import create_app
from atlas.hindsight import HindsightGateway, RetainItem
from atlas.jobs import JobQueue, Pacing, Worker, builtin_registry, builtin_schedules
from tests.fakes.hindsight import RecordedHindsight
from tests.fakes.serve import Served
from tests.harness import (
    BANK,
    EDGAR_FIXTURES,
    LITE_10K,
    TEMPLATE,
    THEMES,
    Atlas,
    Clock,
    Metrics,
    scrape_metrics,
)

LITE = "https://www.sec.gov/Archives/edgar/data/1633978"
LITE_10Q = f"{LITE}/000162828026030777/lite-20260328.htm"
LITE_8K = f"{LITE}/000162828026055726/lite-20260811.htm"
KINDS = (
    "section_missing",
    "document_unrecorded",
    "profile_mismatch",
    "observation_scope_outside",
    "config_drift",
    "consolidation_untracked",
)
NO_DRIFT = dict.fromkeys(KINDS, 0)
ORPHAN = "srcv:00000000-0000-4000-8000-000000000000:cover"
UNKNOWN_ID = "00000000-0000-4000-8000-000000000022"


@pytest.fixture
def hindsight_fake() -> RecordedHindsight:
    fake = RecordedHindsight()
    fake.derive_memories()
    return fake


class Reconciling(Atlas):
    """The Atlas harness with the worker's schedules and the API on a controllable clock."""

    def __init__(self, database_url: str, tmp_path: Path, hindsight: str, clock: Clock) -> None:
        super().__init__(
            database_url,
            tmp_path,
            hindsight,
            hindsight_template_path=TEMPLATE,
            consolidate_poll_timeout_seconds=0.2,
            consolidate_poll_interval_seconds=0.01,
            # The other schedules stay out of these passes; the reconciliation's stays in
            # only where a test schedules it.
            mental_model_refresh_at="",
            consolidate_at="",
            reconcile_at="",
        )
        self.clock = clock
        self.api = TestClient(create_app(self.settings(), clock=clock))

    def scheduled_pass(self) -> int:
        """One `atlas worker` pass: the schedules, then the jobs, on the clock."""
        settings = self.settings()
        queue = JobQueue(self.engine, pacing=Pacing.from_settings(settings), clock=self.clock)
        worker = Worker(
            queue,
            builtin_registry(settings, clock=self.clock),
            schedules=builtin_schedules(settings, self.engine),
        )
        return worker.run_once()

    def reconcile(self, *args: str) -> dict[str, Any]:
        result = self.cli("memory", "reconcile", *args)
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    def reconciled(self) -> dict[str, Any]:
        """Ask for a reconciliation by hand, run one worker pass now, and read the run."""
        self.clock.now = datetime.now(UTC).replace(microsecond=0)
        enqueued = self.reconcile()
        assert (enqueued["kind"], enqueued["job_class"]) == ("reconcile_memory", "interactive")
        self.scheduled_pass()
        job = self.get(f"/api/v1/jobs/{enqueued['id']}")
        assert job["status"] == "succeeded", job["failures"]
        return self.get(f"/api/v1/memory/reconciliations/{job['artifacts']['reconciliation_id']}")

    def sql(self, statement: str, **params: Any) -> None:
        with self.engine.begin() as connection:
            connection.execute(text(statement), params)

    def stick(self, url: str, *, hours_ago: float) -> list[str]:
        """The version's sections were submitted under `retain-v1` and their outcome never
        recorded (ticket 21's stuck case): pending, their documents in Hindsight."""
        version = self.version(url)["id"]
        self.sql(
            "UPDATE memory_document SET retain_state = 'pending', fact_count = NULL,"
            " memory_ids = NULL, retain_profile = 'retain-v1', retain_context = NULL,"
            " retain_entities = NULL, updated_at = now() - make_interval(secs => :seconds)"
            " WHERE source_version_id = :version",
            version=version,
            seconds=hours_ago * 3600,
        )
        return [d["document_id"] for d in self.memory(version)["documents"]]

    def document_ids(self, url: str) -> list[str]:
        return [d["document_id"] for d in self.memory(self.version(url)["id"])["documents"]]

    def metrics(self) -> Metrics:
        return scrape_metrics(self.api)


def drift(metrics: Metrics) -> dict[str, float]:
    return {kind: metrics[("atlas_memory_drift", frozenset({("kind", kind)}))] for kind in KINDS}


def status(metrics: Metrics) -> dict[str, float]:
    """The last run's status gauge: 1 for its status, 0 for the others."""
    return {
        s: metrics[("atlas_memory_reconciliation_status", frozenset({("status", s)}))]
        for s in ("clean", "drift", "failed")
    }


@pytest.fixture
def clock() -> Clock:
    # Real time, so the database's lease clock and the pacing clock start together.
    return Clock(datetime.now(UTC).replace(microsecond=0))


@pytest.fixture
def atlas(
    database_url: str, tmp_path: Path, hindsight: tuple[RecordedHindsight, Served], clock: Clock
) -> Iterator[Reconciling]:
    harness = Reconciling(database_url, tmp_path, hindsight[1].url, clock)
    harness.apply_template()
    harness.ingest_company("lumentum")
    yield harness
    harness.engine.dispose()


# --- clean, and each kind of drift -------------------------------------------------------------


def test_a_bank_that_matches_atlas_s_records_reconciles_clean(
    atlas: Reconciling, fake: RecordedHindsight
) -> None:
    retained = atlas.get("/api/v1/memory/health")["sections"]["completed"]
    assert retained > 0
    writes = [r for r in fake.calls if r.method != "GET"]

    run = atlas.reconciled()

    assert run["status"] == "clean"
    assert run["error"] is None
    assert run["counts"] == NO_DRIFT
    assert run["samples"] == {}
    assert run["bank_id"] == BANK
    # Read-only: Hindsight received no request but reads.
    assert [r for r in fake.calls if r.method != "GET"] == writes
    paths = {r.url.path.split(f"/{BANK}/", 1)[-1] for r in fake.calls if r.method == "GET"}
    expected = {"documents", "config", "observations/scopes", "operations", "llm-requests/stats"}
    assert expected <= paths
    # The per-call listing (each row carries a prompt and an answer) is never read.
    assert "llm-requests" not in paths
    # Visible: the health read, the list, the gauge and the last success.
    health = atlas.get("/api/v1/memory/health")["reconciliation"]
    assert (health["id"], health["status"], health["counts"]) == (run["id"], "clean", NO_DRIFT)
    listed = atlas.get("/api/v1/memory/reconciliations")
    assert listed["total"] == 1 and [r["id"] for r in listed["items"]] == [run["id"]]
    metrics = atlas.metrics()
    assert drift(metrics) == NO_DRIFT
    assert status(metrics) == {"clean": 1, "drift": 0, "failed": 0}
    # Template 1.5.0 (ticket 23) pins 23 bank settings; each was compared, generically.
    template = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    assert (template["template_version"], len(template["manifest"]["bank"])) == ("1.5.0", 23)
    ended = datetime.fromisoformat(run["ended_at"]).timestamp()
    last = (
        "atlas_memory_reconciliation_last_success_timestamp_seconds",
        frozenset[tuple[str, str]](),
    )
    assert metrics[last] == pytest.approx(ended)
    clean = ("atlas_memory_reconciliations_total", frozenset({("status", "clean")}))
    assert metrics[clean] == 1


def test_each_kind_of_drift_is_found_with_its_samples(
    atlas: Reconciling, fake: RecordedHindsight, hindsight: tuple[RecordedHindsight, Served]
) -> None:
    _, served = hindsight
    ten_k = atlas.document_ids(LITE_10K)
    ten_q = atlas.document_ids(LITE_10Q)
    # 1. A completed section whose document Hindsight no longer has.
    missing = ten_k[0]
    # 3. A section Atlas records at the current profile, retained without its scopes.
    mismatched = ten_k[1]
    fake.script_retain_params(mismatched, without=["observation_scopes"])
    with HindsightGateway(served.url, BANK) as outside:
        outside.delete_document(missing)
        # 2. A document of the bank Atlas never recorded (an orphan) ...
        at = datetime(2026, 8, 1, tzinfo=UTC)
        outside.retain_batch([RetainItem(content="Unknown.", document_id=ORPHAN, timestamp=at)])
    # ... and sections stuck pending under the old profile, their documents stored.
    stuck = atlas.stick(LITE_8K, hours_ago=72)
    # 4. An observation formed across companies' tags (no explicit scope), beside one formed
    # in the theme's scope, which is not drift.
    fake.derive_observation(ten_q)
    fake.derive_observation(ten_q, scope=["theme:photonics"])
    scopes = atlas.get("/api/v1/memory/health")["observation_scopes"]["scopes"]
    (scope_tags,) = [s["tags"] for s in scopes if s["tags"] != ["theme:photonics"]]
    # 5. A setting the template sets, changed live.
    fake.change_bank_config(BANK, enable_auto_consolidation=True)
    # 6. A consolidation of the bank that no run of Atlas's follows.
    fake.script_pending_consolidation(BANK, 250)
    unfollowed = fake.request_consolidation_elsewhere(BANK)

    run = atlas.reconciled()

    assert run["status"] == "drift"
    assert run["counts"] == {
        "section_missing": 1,
        "document_unrecorded": len(stuck) + 1,
        "profile_mismatch": 1,
        "observation_scope_outside": 1,
        "config_drift": 1,
        "consolidation_untracked": 1,
    }
    samples = run["samples"]
    assert samples["section_missing"] == [missing]
    assert samples["document_unrecorded"] == sorted([*stuck, ORPHAN])
    assert samples["profile_mismatch"] == [mismatched]
    assert samples["observation_scope_outside"] == [",".join(scope_tags)]
    assert samples["config_drift"] == ["enable_auto_consolidation"]
    assert samples["consolidation_untracked"] == [unfollowed]
    assert run["details"]["document_unrecorded"] == {"pending": len(stuck), "unknown": 1}
    assert run["details"]["profile_mismatch"] == {"observation_scopes": 1}
    assert run["details"]["consolidation_untracked"] == {"not_followed": 1}
    # Read-only: nothing was cancelled, deleted or retained by the reconciliation.
    assert fake.cancelled_operations() == []
    # Visible.
    assert atlas.get("/api/v1/memory/health")["reconciliation"]["status"] == "drift"
    assert drift(atlas.metrics()) == {kind: float(n) for kind, n in run["counts"].items()}


def test_a_setting_stored_with_empty_fields_or_reordered_keys_is_not_drift(
    atlas: Reconciling, fake: RecordedHindsight
) -> None:
    # The live bank stores the template's entity_labels groups with `"fields": {}` (the lead,
    # 2026-10-03) and answers objects in its own key order: neither is drift.
    bank = json.loads(TEMPLATE.read_text(encoding="utf-8"))["manifest"]["bank"]
    empty: dict[str, Any] = {"fields": {}, "aliases": None}
    stored: list[dict[str, Any]] = [
        dict(reversed([*group.items(), *empty.items()])) for group in bank["entity_labels"]
    ]
    fake.change_bank_config(BANK, entity_labels=stored)

    run = atlas.reconciled()

    assert run["status"] == "clean", run["samples"]
    # A value that really differs inside the same setting still is drift.
    changed = [{**stored[0], "tag": not stored[0]["tag"]}, *stored[1:]]
    fake.change_bank_config(BANK, entity_labels=changed)
    assert atlas.reconciled()["samples"]["config_drift"] == ["entity_labels"]


def test_a_run_whose_consolidation_ended_unseen_is_untracked_drift(
    atlas: Reconciling, fake: RecordedHindsight
) -> None:
    fake.hold_consolidations("processing")
    consolidate = atlas.cli("memory", "consolidate", "--key", "by-hand")
    assert consolidate.returncode == 0, consolidate.stderr
    atlas.scheduled_pass()  # still processing at the bound: the run stays `submitted`
    run = atlas.get("/api/v1/memory/health")["consolidation"]["last_requested"]
    assert run["status"] == "submitted"
    assert atlas.reconciled()["counts"]["consolidation_untracked"] == 0  # followed

    fake.hold_operation(run["operation_id"], "processing", polls=0)  # Hindsight finished it

    found = atlas.reconciled()
    assert found["counts"]["consolidation_untracked"] == 1
    assert found["samples"]["consolidation_untracked"] == [f"run:{run['id']}"]
    assert found["details"]["consolidation_untracked"] == {"run_ended": 1}


@pytest.mark.parametrize("listing", ["documents", "scopes"])
def test_a_failed_listing_makes_the_run_failed_never_clean(
    atlas: Reconciling, fake: RecordedHindsight, listing: str
) -> None:
    first = atlas.reconciled()
    assert first["status"] == "clean"
    if listing == "documents":
        fake.fail_document_listing(503)
    else:
        fake.fail_listings(500)

    failed = atlas.reconciled()

    assert failed["status"] == "failed"
    assert failed["error"] is not None and "HindsightHTTPError" in failed["error"]
    assert (failed["counts"], failed["samples"], failed["usage"]) == ({}, {}, None)
    assert atlas.get("/api/v1/memory/health")["reconciliation"]["status"] == "failed"
    # The gauge and the last success stay those of the last run that read everything.
    metrics = atlas.metrics()
    assert drift(metrics) == NO_DRIFT
    last = (
        "atlas_memory_reconciliation_last_success_timestamp_seconds",
        frozenset[tuple[str, str]](),
    )
    assert metrics[last] == pytest.approx(datetime.fromisoformat(first["ended_at"]).timestamp())
    assert metrics[("atlas_memory_reconciliations_total", frozenset({("status", "failed")}))] == 1
    # The last run's status is its own gauge, so a failed night is visible (and alerted).
    assert status(metrics) == {"clean": 0, "drift": 0, "failed": 1}


# --- usage --------------------------------------------------------------------------------------


def test_usage_reads_the_day_s_llm_stats_beside_atlas_s_budgets_and_is_never_drift(
    atlas: Reconciling, fake: RecordedHindsight
) -> None:
    sections = atlas.get("/api/v1/memory/health")["sections"]
    retained = sections["completed"] + sections["zero_fact"]
    now = datetime.now(UTC)
    # The owner's reflects today, one of them an error, and one two days ago (outside the day).
    fake.script_llm_request(
        BANK, "reflect", input_tokens=1500, output_tokens=400, started_at=now - timedelta(hours=2)
    )
    fake.script_llm_request(
        BANK,
        "reflect",
        input_tokens=700,
        output_tokens=0,
        started_at=now - timedelta(hours=1),
        status="error",
    )
    fake.script_llm_request(
        BANK, "reflect", input_tokens=9000, output_tokens=900, started_at=now - timedelta(days=2)
    )
    consolidate = atlas.cli("memory", "consolidate", "--key", "today")
    assert consolidate.returncode == 0, consolidate.stderr
    atlas.scheduled_pass()  # nothing pending: one round, completed

    run = atlas.reconciled()

    assert run["status"] == "clean"  # usage, errors included, is a report, never drift
    usage = run["usage"]
    rows = {row["operation"]: row for row in usage["hindsight"]}
    assert [row["operation"] for row in usage["hindsight"]] == [
        "retain",
        "consolidation",
        "reflect",
        "total",
    ]
    assert rows["retain"]["calls"] == retained  # one extraction call per section
    assert rows["retain"]["input_tokens"] > 0 and rows["retain"]["errors"] == 0
    reflect = rows["reflect"]
    assert (
        reflect["calls"],
        reflect["errors"],
        reflect["input_tokens"],
        reflect["output_tokens"],
        reflect["cached_tokens"],
    ) == (2, 1, 2200, 400, 0)
    assert rows["consolidation"]["calls"] == 1
    total = rows["total"]
    for field in ("calls", "errors", "input_tokens", "output_tokens"):
        assert total[field] == sum(rows[op][field] for op in ("retain", "consolidation", "reflect"))
    # Beside it, what Atlas's budgets counted in the same window.
    queue = {b["provider"]: b["used"] for b in atlas.get("/api/v1/queue")["budgets"]}
    assert usage["atlas_counted"]["codex"] == queue["codex"] > 0
    assert usage["atlas_counted"]["hindsight_consolidation"] == 1
    window = datetime.fromisoformat(usage["until"]) - datetime.fromisoformat(usage["since"])
    assert timedelta(hours=23, minutes=59) < window <= timedelta(hours=24)
    # One stats read per operation and one for the total; never the per-call listing.
    stats = [
        r.url.params.get("operation")
        for r in fake.calls
        if r.url.path.endswith("/llm-requests/stats")
    ]
    assert stats == ["retain", "consolidation", "reflect", None]
    assert not [r for r in fake.calls if r.url.path.endswith("/llm-requests")]


# --- the routes, the CLI and the schedule -------------------------------------------------------


def test_an_unknown_reconciliation_is_404_and_the_list_pages_newest_first(
    atlas: Reconciling,
) -> None:
    first, second = atlas.reconciled(), atlas.reconciled()
    response = atlas.api.get(f"/api/v1/memory/reconciliations/{UNKNOWN_ID}")
    assert response.status_code == 404
    page = atlas.get("/api/v1/memory/reconciliations", limit=1)
    assert (page["total"], [r["id"] for r in page["items"]]) == (2, [second["id"]])
    page = atlas.get("/api/v1/memory/reconciliations", limit=1, offset=1)
    assert [r["id"] for r in page["items"]] == [first["id"]]


def test_reconcile_wait_prints_the_run_once_the_worker_has_reconciled(
    atlas: Reconciling, fake: RecordedHindsight
) -> None:
    fake.change_bank_config(BANK, enable_auto_consolidation=True)
    command = [sys.executable, "-m", "atlas", "memory", "reconcile", "--wait"]
    command += ["--poll-seconds", "0.2"]
    env = atlas_cli_env(atlas)
    with subprocess.Popen(
        command, cwd=atlas.tmp_path, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    ) as process:
        deadline = time.monotonic() + 90
        while process.poll() is None:
            assert time.monotonic() < deadline, "atlas memory reconcile --wait never returned"
            atlas.clock.now = datetime.now(UTC)
            atlas.scheduled_pass()
            time.sleep(0.2)
        stdout, stderr = process.communicate()
    assert process.returncode == 1, stderr.decode()  # drift
    printed = json.loads(stdout)
    assert printed["status"] == "drift"
    assert printed["counts"]["config_drift"] == 1
    assert printed == atlas.get(f"/api/v1/memory/reconciliations/{printed['id']}")
    assert "drift: config_drift 1" in stderr.decode()


def test_the_worker_reconciles_once_a_day_from_reconcile_at_while_consolidation_is_off(
    atlas: Reconciling, clock: Clock
) -> None:
    del atlas.overrides["reconcile_at"]  # the default, 03:30 UTC
    atlas.overrides["consolidation_enabled"] = False
    clock.now = clock.now.replace(hour=3, minute=0, second=0)

    assert atlas.scheduled_pass() == 0  # before ATLAS_RECONCILE_AT
    clock.advance(minutes=30)
    assert atlas.scheduled_pass() == 1
    clock.advance(hours=3)
    assert atlas.scheduled_pass() == 0  # one a day
    clock.advance(days=1)
    assert atlas.scheduled_pass() == 1

    with atlas.engine.connect() as connection:
        jobs = connection.execute(
            text(
                "SELECT idempotency_key, job_class, status, artifacts->>'status' FROM job"
                " WHERE kind = 'reconcile_memory' ORDER BY created_at"
            )
        ).all()
    day = clock.now.date()
    assert [row[0] for row in jobs] == [
        f"reconcile_memory:{BANK}:{day - timedelta(days=1)}",
        f"reconcile_memory:{BANK}:{day}",
    ]
    assert {(row[1], row[2], row[3]) for row in jobs} == {("interactive", "succeeded", "clean")}

    atlas.overrides["reconcile_at"] = ""  # empty: never
    clock.advance(days=1)
    assert atlas.scheduled_pass() == 0


def atlas_cli_env(atlas: Atlas) -> dict[str, str]:
    """The environment `Atlas.cli` runs the CLI with."""
    return {
        "PATH": os.environ["PATH"],
        "HOME": str(atlas.tmp_path),
        "ATLAS_DATABASE_URL": atlas.database_url,
        "ATLAS_ACTOR": "local-researcher",
        "ATLAS_ARCHIVE_ROOT": str(atlas.archive),
        "ATLAS_THEMES_CONFIG": str(THEMES),
        "ATLAS_SEC_FIXTURES_DIR": str(EDGAR_FIXTURES),
        "ATLAS_HINDSIGHT_URL": atlas.hindsight_url,
        "ATLAS_HINDSIGHT_BANK_ID": BANK,
        "ATLAS_HINDSIGHT_TEMPLATE_PATH": str(TEMPLATE),
    }
