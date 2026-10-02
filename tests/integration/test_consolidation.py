"""Atlas decides when Memory consolidates (memory-quality ticket 19).

The research bank's template turns Hindsight's automatic consolidation off; a `consolidate`
job asks for it instead: by hand (`atlas memory consolidate`), or once a day from
`ATLAS_CONSOLIDATE_AT`, skipped when nothing was retained since the last completed run and
tried again an hour later while a retain of the bank is queued or running.

Seams: the `atlas` CLI (template, ingest, `memory consolidate`), single worker passes (with
the worker's schedules, on a controllable clock) and `/api/v1` (`memory/health`, `queue`,
`jobs`, `/metrics`), and the requests the recorded Hindsight fake received. Consolidation is
the fake's documented derivation (`observations/01-consolidate`, `02-consolidate-final`;
`hold_consolidations`), and so is the template import with `enable_auto_consolidation`
(tests/fakes/hindsight.py). Nothing live is called.
"""

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from jsonschema.validators import validator_for

from atlas.api.app import create_app
from atlas.jobs import JobQueue, Pacing, Worker, builtin_registry, builtin_schedules
from tests.fakes.hindsight import RecordedHindsight
from tests.fakes.serve import Served
from tests.harness import TEMPLATE, Atlas, Clock, Metrics, scrape_metrics

TEMPLATE_FILE: dict[str, Any] = json.loads(TEMPLATE.read_text(encoding="utf-8"))
SCHEMA = cast(
    dict[str, Any], RecordedHindsight().recording("bank_templates/01-schema").response_object()
)
OUTCOMES = ("completed", "failed", "skipped_nothing_retained", "skipped_retains_pending")


class Consolidating(Atlas):
    """The Atlas harness with the worker's schedules and the API on a controllable clock."""

    def __init__(self, database_url: str, tmp_path: Path, hindsight: str, clock: Clock) -> None:
        super().__init__(
            database_url,
            tmp_path,
            hindsight,
            consolidate_poll_timeout_seconds=0.2,
            consolidate_poll_interval_seconds=0.01,
            # The mental models' schedule stays out of these passes, and so does the daily
            # consolidation unless a test schedules it (`schedule_daily`).
            mental_model_refresh_at="",
            consolidate_at="",
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

    def schedule_daily(self) -> None:
        """The daily consolidation at its default time (ATLAS_CONSOLIDATE_AT unset)."""
        del self.overrides["consolidate_at"]

    def consolidate(self, *args: str) -> dict[str, Any]:
        result = self.cli("memory", "consolidate", *args)
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    def consolidation(self) -> dict[str, Any]:
        return self.get("/api/v1/memory/health")["consolidation"]

    def codex(self) -> dict[str, Any]:
        budgets = self.get("/api/v1/queue")["budgets"]
        return next(b for b in budgets if b["provider"] == "codex")

    def consolidate_jobs(self) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            rows = connection.exec_driver_sql(
                "SELECT id FROM job WHERE kind = 'consolidate' ORDER BY created_at, id"
            ).all()
        return [self.get(f"/api/v1/jobs/{row[0]}") for row in rows]

    def metrics(self) -> Metrics:
        return scrape_metrics(self.api)


def consolidations(fake: RecordedHindsight) -> int:
    """How many consolidation requests Hindsight received."""
    return len(fake.requests("POST", "consolidate"))


def outcomes(metrics: Metrics) -> dict[str, float]:
    return {
        outcome: metrics[("atlas_consolidations_total", frozenset({("outcome", outcome)}))]
        for outcome in OUTCOMES
    }


@pytest.fixture
def clock() -> Clock:
    # Real time, so the database's lease clock and the pacing clock start together.
    return Clock(datetime.now(UTC).replace(microsecond=0))


@pytest.fixture
def atlas(
    database_url: str, tmp_path: Path, hindsight: tuple[RecordedHindsight, Served], clock: Clock
) -> Iterator[Consolidating]:
    fake, served = hindsight
    # The health read lists the bank's scopes and entities too (hand-written, empty here).
    fake.script_observation_scopes([])
    fake.script_entities([])
    harness = Consolidating(database_url, tmp_path, served.url, clock)
    harness.apply_template()
    yield harness
    harness.engine.dispose()


# --- the template ------------------------------------------------------------------------------


def test_the_template_turns_auto_consolidation_off_within_the_recorded_schema(
    atlas: Consolidating, hindsight: tuple[RecordedHindsight, Served]
) -> None:
    fake, _ = hindsight
    manifest = TEMPLATE_FILE["manifest"]

    assert TEMPLATE_FILE["template_version"] == "1.4.0"
    assert manifest["bank"]["enable_auto_consolidation"] is False
    validator = validator_for(SCHEMA)(SCHEMA)
    assert list(validator.iter_errors(manifest)) == []
    # The schema's own field: a per-bank, nullable boolean.
    config = SCHEMA["$defs"]["BankTemplateConfig"]["properties"]
    assert "enable_auto_consolidation" in config
    # Hindsight was sent the setting, dry run then import.
    imports = fake.requests("POST", "import")
    assert [body["bank"]["enable_auto_consolidation"] for body in imports] == [False, False]


@pytest.mark.parametrize("value", [None, True])
def test_a_template_that_leaves_auto_consolidation_on_is_refused_before_any_call(
    atlas: Consolidating,
    hindsight: tuple[RecordedHindsight, Served],
    tmp_path: Path,
    value: bool | None,
) -> None:
    fake, _ = hindsight
    bank = dict(TEMPLATE_FILE["manifest"]["bank"])
    if value is None:
        del bank["enable_auto_consolidation"]
    else:
        bank["enable_auto_consolidation"] = value
    edited = {**TEMPLATE_FILE, "manifest": {**TEMPLATE_FILE["manifest"], "bank": bank}}
    path = tmp_path / "auto-consolidating-template.json"
    path.write_text(json.dumps(edited), encoding="utf-8")
    calls = len(fake.calls)

    result = atlas.cli("hindsight", "apply-template", "--template", str(path))

    assert result.returncode == 2
    assert "invalid bank template" in result.stderr
    assert "enable_auto_consolidation" in result.stderr
    assert len(fake.calls) == calls


# --- the job -----------------------------------------------------------------------------------


def test_retains_request_no_consolidation_until_the_job_asks_once_and_counts_it(
    atlas: Consolidating, hindsight: tuple[RecordedHindsight, Served]
) -> None:
    fake, _ = hindsight
    atlas.ingest_company("lumentum")
    retained = atlas.get("/api/v1/memory/health")["sections"]["completed"]
    assert retained > 0
    assert consolidations(fake) == 0
    assert atlas.consolidation() == {
        "last_requested": None,
        "last_completed": None,
        "sections_retained_since": retained,
    }
    before = atlas.codex()["used"]

    enqueued = atlas.consolidate("--key", "by-hand")
    assert (enqueued["kind"], enqueued["job_class"], enqueued["created"]) == (
        "consolidate",
        "interactive",
        True,
    )
    atlas.scheduled_pass()

    job = atlas.get(f"/api/v1/jobs/{enqueued['id']}")
    assert job["status"] == "succeeded", job["failures"]
    assert job["artifacts"]["outcome"] == "completed"
    assert consolidations(fake) == 1
    assert fake.requests("POST", "consolidate") == [{}]
    record = atlas.consolidation()
    requested, completed = record["last_requested"], record["last_completed"]
    assert requested == completed
    assert requested["operation_id"] == job["artifacts"]["operation_id"]
    assert (requested["status"], requested["operation_status"]) == ("completed", "completed")
    assert requested["sections_retained"] == retained
    assert requested["job_id"] == enqueued["id"]
    assert record["sections_retained_since"] == 0
    # One unit of the Codex budget: the request Atlas submitted.
    codex = atlas.codex()
    assert codex["used"] == before + 1
    assert "consolidate" in codex["kinds"]
    assert outcomes(atlas.metrics()) == {
        "completed": 1,
        "failed": 0,
        "skipped_nothing_retained": 0,
        "skipped_retains_pending": 0,
    }

    # Asked again with nothing retained since: skipped, no request.
    again = atlas.consolidate("--key", "again")
    atlas.scheduled_pass()
    job = atlas.get(f"/api/v1/jobs/{again['id']}")
    assert (job["artifacts"]["outcome"], job["artifacts"]["reason"]) == (
        "skipped",
        "nothing_retained",
    )
    assert consolidations(fake) == 1
    assert atlas.codex()["used"] == before + 1
    assert outcomes(atlas.metrics())["skipped_nothing_retained"] == 1


def test_a_spent_codex_window_holds_the_job_like_the_other_codex_kinds(
    atlas: Consolidating, hindsight: tuple[RecordedHindsight, Served], clock: Clock
) -> None:
    fake, _ = hindsight
    atlas.ingest_company("lumentum")
    used = atlas.codex()["used"]
    atlas.overrides["codex_budget_operations"] = used  # the retains spent the window
    atlas.api = TestClient(create_app(atlas.settings(), clock=clock))

    enqueued = atlas.consolidate("--key", "held")
    atlas.scheduled_pass()

    assert atlas.get(f"/api/v1/jobs/{enqueued['id']}")["status"] == "queued"
    assert consolidations(fake) == 0
    codex = atlas.codex()
    assert (codex["used"], codex["interactive_held"]) == (used, True)
    pending = atlas.get("/api/v1/queue")["pending"]
    (consolidate,) = [p for p in pending if p["kind"] == "consolidate"]
    assert (consolidate["queued"], consolidate["budget_held"]) == (1, 1)

    clock.advance(hours=5, seconds=1)  # the retains leave the window
    atlas.scheduled_pass()

    assert atlas.get(f"/api/v1/jobs/{enqueued['id']}")["artifacts"]["outcome"] == "completed"
    assert consolidations(fake) == 1


def test_a_second_request_while_one_is_running_submits_nothing_and_follows_it(
    atlas: Consolidating, hindsight: tuple[RecordedHindsight, Served]
) -> None:
    fake, _ = hindsight
    atlas.ingest_company("lumentum")
    fake.hold_consolidations("processing")

    first = atlas.consolidate("--key", "first")
    atlas.scheduled_pass()

    # Still running at the bound: the job ends, the operation stays recorded as running.
    job = atlas.get(f"/api/v1/jobs/{first['id']}")
    assert job["status"] == "succeeded", job["failures"]
    assert job["artifacts"]["outcome"] == "running"
    operation_id = job["artifacts"]["operation_id"]
    record = atlas.consolidation()
    assert record["last_requested"]["status"] == "submitted"
    assert record["last_requested"]["operation_status"] == "processing"
    assert record["last_completed"] is None
    used = atlas.codex()["used"]

    second = atlas.consolidate("--key", "second")
    atlas.scheduled_pass()

    job = atlas.get(f"/api/v1/jobs/{second['id']}")
    assert (job["artifacts"]["outcome"], job["artifacts"]["joined"]) == ("running", True)
    assert job["artifacts"]["operation_id"] == operation_id
    assert consolidations(fake) == 1
    assert atlas.codex()["used"] == used

    fake.hold_operation(operation_id, "processing", polls=0)  # Hindsight finishes it
    third = atlas.consolidate("--key", "third")
    atlas.scheduled_pass()

    job = atlas.get(f"/api/v1/jobs/{third['id']}")
    assert (job["artifacts"]["outcome"], job["artifacts"]["joined"]) == ("completed", True)
    assert consolidations(fake) == 1
    record = atlas.consolidation()
    assert record["last_completed"]["operation_id"] == operation_id
    assert record["last_completed"]["job_id"] == first["id"]
    assert record["sections_retained_since"] == 0
    assert outcomes(atlas.metrics())["completed"] == 1


# --- the daily schedule ------------------------------------------------------------------------


def test_the_daily_run_waits_for_retains_then_skips_a_day_with_nothing_new(
    atlas: Consolidating, hindsight: tuple[RecordedHindsight, Served], clock: Clock
) -> None:
    fake, _ = hindsight
    atlas.schedule_daily()
    atlas.ingest_company("lumentum")
    clock.now = clock.now.replace(hour=4, minute=0, second=0)
    # A retain of the bank is running (another worker holds it).
    version = atlas.version("https://data.sec.gov/api/xbrl/companyfacts/CIK0001633978.json")
    queue = JobQueue(atlas.engine)
    queue.enqueue("retain", "running-retain", {"source_version_id": version["id"]})
    running = queue.claim("another-worker", timedelta(hours=1))
    assert running is not None and running.kind == "retain"

    assert atlas.scheduled_pass() == 0  # before ATLAS_CONSOLIDATE_AT (04:30 UTC)
    assert atlas.consolidate_jobs() == []

    clock.advance(minutes=30)
    assert atlas.scheduled_pass() == 1
    (waited,) = atlas.consolidate_jobs()
    assert waited["job_class"] == "backfill"
    assert waited["artifacts"]["outcome"] == "skipped"
    assert waited["artifacts"]["reason"] == "retains_pending"
    assert consolidations(fake) == 0

    clock.advance(minutes=30)  # not an hour yet
    assert atlas.scheduled_pass() == 0
    assert queue.complete(running, "another-worker", {})

    clock.advance(minutes=31)  # an hour after it waited: tried again
    assert atlas.scheduled_pass() == 1
    waited, tried = atlas.consolidate_jobs()
    assert tried["artifacts"]["outcome"] == "completed"
    assert consolidations(fake) == 1

    clock.advance(hours=2)  # the day's run is done
    assert atlas.scheduled_pass() == 0

    clock.advance(days=1)  # the next day: nothing retained since
    clock.now = clock.now.replace(hour=4, minute=30)
    assert atlas.scheduled_pass() == 1
    *_, skipped = atlas.consolidate_jobs()
    assert (skipped["artifacts"]["outcome"], skipped["artifacts"]["reason"]) == (
        "skipped",
        "nothing_retained",
    )
    assert consolidations(fake) == 1
    assert outcomes(atlas.metrics()) == {
        "completed": 1,
        "failed": 0,
        "skipped_nothing_retained": 1,
        "skipped_retains_pending": 1,
    }


def test_the_daily_run_tries_a_bounded_number_of_times(
    atlas: Consolidating, hindsight: tuple[RecordedHindsight, Served], clock: Clock
) -> None:
    fake, _ = hindsight
    atlas.schedule_daily()
    atlas.overrides["consolidate_max_tries"] = 2
    atlas.ingest_company("lumentum")
    clock.now = clock.now.replace(hour=4, minute=30, second=0)
    version = atlas.version("https://data.sec.gov/api/xbrl/companyfacts/CIK0001633978.json")
    queue = JobQueue(atlas.engine)
    queue.enqueue("retain", "queued-retain", {"source_version_id": version["id"]})
    assert queue.claim("another-worker", timedelta(hours=6)) is not None

    for _ in range(4):
        atlas.scheduled_pass()
        clock.advance(hours=1, minutes=1)

    assert [job["artifacts"]["reason"] for job in atlas.consolidate_jobs()] == [
        "retains_pending",
        "retains_pending",
    ]
    assert consolidations(fake) == 0
