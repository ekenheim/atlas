"""Atlas decides when Memory consolidates (memory-quality ticket 19), follows a run to its
end and counts it by rounds (ticket 20).

The research bank's template turns Hindsight's automatic consolidation off; a `consolidate`
job asks for it instead: by hand (`atlas memory consolidate`), or once a day from
`ATLAS_CONSOLIDATE_AT`, skipped when nothing was retained since the last completed run and
tried again an hour later while a retain of the bank is queued or running. Hindsight
consolidates in rounds, each its own operation, and chains the next round by itself while
memories are pending: Atlas follows the chain across jobs, counts each round against the
`hindsight_consolidation` budget and cancels its run's round when the window's rounds are
spent.

Seams: the `atlas` CLI (template, ingest, `memory consolidate`), single worker passes (with
the worker's schedules, on a controllable clock) and `/api/v1` (`memory/health`, `queue`,
`jobs`, `/metrics`), and the requests the recorded Hindsight fake received. Consolidation is
the fake's documented derivation (`observations/01-consolidate`, `02-consolidate-final`;
`hold_consolidations`), and so are its rounds, the operations listing, the cancel and the
bank's stats (`script_pending_consolidation`, `end_consolidation_round`; built to the shapes
the lead read live, not recorded) and the template import with `enable_auto_consolidation`
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
OUTCOMES = (
    "completed",
    "failed",
    "stopped_at_budget",
    "skipped_nothing_retained",
    "skipped_retains_pending",
    "skipped_consolidation_off",
    "skipped_other_consolidation_running",
)
NO_OUTCOMES = dict.fromkeys(OUTCOMES, 0)
ROUNDS = ("atlas_consolidation_rounds_total", frozenset[tuple[str, str]]())


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
            reconcile_at="",  # the nightly reconciliation (ticket 22) too
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
        return self.budget("codex")

    def rounds_budget(self) -> dict[str, Any]:
        return self.budget("hindsight_consolidation")

    def budget(self, provider: str) -> dict[str, Any]:
        budgets = self.get("/api/v1/queue")["budgets"]
        return next(b for b in budgets if b["provider"] == provider)

    def with_rounds_budget(self, rounds: int) -> None:
        self.overrides["consolidate_budget_rounds"] = rounds
        self.api = TestClient(create_app(self.settings(), clock=self.clock))

    def by_hand(self, key: str) -> dict[str, Any]:
        """Ask for a consolidation by hand, run one worker pass, and read the job."""
        enqueued = self.consolidate("--key", key)
        self.scheduled_pass()
        return self.get(f"/api/v1/jobs/{enqueued['id']}")

    @property
    def bank(self) -> str:
        return self.settings().hindsight_bank_id

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

    assert TEMPLATE_FILE["template_version"] == "1.6.0"  # 1.4.0 added it; 1.5.0 and 1.6.0 kept it
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
    rounds_before = atlas.rounds_budget()["used"]

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
    assert (requested["rounds"], requested["last_operation_id"]) == (1, requested["operation_id"])
    assert requested["pending_consolidation"] == 0
    assert record["sections_retained_since"] == 0
    # One round of the consolidation budget (ticket 20), none of the Codex budget.
    assert atlas.rounds_budget()["used"] == rounds_before + 1
    assert atlas.codex()["used"] == before
    assert outcomes(atlas.metrics()) == NO_OUTCOMES | {"completed": 1}

    # Asked again with nothing retained since: skipped, no request.
    again = atlas.consolidate("--key", "again")
    atlas.scheduled_pass()
    job = atlas.get(f"/api/v1/jobs/{again['id']}")
    assert (job["artifacts"]["outcome"], job["artifacts"]["reason"]) == (
        "skipped",
        "nothing_retained",
    )
    assert consolidations(fake) == 1
    assert atlas.rounds_budget()["used"] == rounds_before + 1
    assert outcomes(atlas.metrics())["skipped_nothing_retained"] == 1


def test_a_spent_codex_window_no_longer_holds_the_job(
    atlas: Consolidating, hindsight: tuple[RecordedHindsight, Served], clock: Clock
) -> None:
    # Ticket 20: `consolidate` left the Codex budget for its own, counted by rounds.
    fake, _ = hindsight
    atlas.ingest_company("lumentum")
    used = atlas.codex()["used"]
    atlas.overrides["codex_budget_operations"] = used  # the retains spent the window
    atlas.api = TestClient(create_app(atlas.settings(), clock=clock))
    codex = atlas.codex()
    assert (codex["interactive_held"], "consolidate" in codex["kinds"]) == (True, False)
    rounds = atlas.rounds_budget()
    assert (rounds["unit"], rounds["kinds"], rounds["budget"]) == ("rounds", ["consolidate"], 40)

    job = atlas.by_hand("beside-a-spent-codex-window")

    assert job["artifacts"]["outcome"] == "completed"
    assert consolidations(fake) == 1
    assert atlas.codex()["used"] == used


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
    assert outcomes(atlas.metrics()) == NO_OUTCOMES | {
        "completed": 1,
        "skipped_nothing_retained": 1,
        "skipped_retains_pending": 1,
    }


def test_a_retain_waiting_its_turn_does_not_hold_a_consolidation_one_in_flight_does(
    atlas: Consolidating, hindsight: tuple[RecordedHindsight, Served], clock: Clock
) -> None:
    # A backfill keeps hundreds of retains queued behind its budget or window for days; they
    # have sent nothing to Hindsight, so they don't hold the bank's consolidation. A retain's
    # operation still being polled does: it is half in the bank.
    fake, _ = hindsight
    atlas.ingest_company("lumentum")
    opens = (clock.now + timedelta(hours=6)).replace(minute=0)
    atlas.overrides["backfill_window"] = f"{opens:%H:%M}-{opens + timedelta(hours=1):%H:%M}"
    version = atlas.version("https://data.sec.gov/api/xbrl/companyfacts/CIK0001633978.json")
    queue = JobQueue(atlas.engine)
    queue.enqueue(
        "retain", "waiting-retain", {"source_version_id": version["id"]}, job_class="backfill"
    )

    first = atlas.consolidate("--key", "beside-a-waiting-retain")
    atlas.scheduled_pass()

    job = atlas.get(f"/api/v1/jobs/{first['id']}")
    assert job["artifacts"]["outcome"] == "completed"
    assert consolidations(fake) == 1
    with atlas.engine.connect() as connection:
        waiting = connection.exec_driver_sql(
            "SELECT status FROM job WHERE kind = 'retain' AND job_class = 'backfill'"
        ).scalar_one()
    assert waiting == "queued"

    queue.enqueue("poll_operation", "in-flight", {"source_version_id": version["id"]})
    in_flight = queue.claim("another-worker", timedelta(hours=1))
    assert in_flight is not None and in_flight.kind == "poll_operation"
    second = atlas.consolidate("--key", "beside-an-operation-in-flight")
    atlas.scheduled_pass()

    job = atlas.get(f"/api/v1/jobs/{second['id']}")
    assert (job["artifacts"]["outcome"], job["artifacts"]["reason"]) == (
        "skipped",
        "retains_pending",
    )
    assert consolidations(fake) == 1


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


def test_with_consolidation_off_no_request_is_made_by_any_path(
    atlas: Consolidating, hindsight: tuple[RecordedHindsight, Served]
) -> None:
    # ATLAS_CONSOLIDATION_ENABLED=false (the owner's choice while the cost of consolidation on
    # the shared server's model is open): a job asked for by hand, by the backfill or by the
    # schedule is recorded as skipped, no request reaches Hindsight and nothing is counted.
    fake, _ = hindsight
    atlas.overrides["consolidation_enabled"] = False
    atlas.schedule_daily()
    atlas.ingest_company("lumentum")
    before = atlas.rounds_budget()["used"]

    enqueued = atlas.consolidate("--key", "by-hand-while-off")
    atlas.scheduled_pass()

    job = atlas.get(f"/api/v1/jobs/{enqueued['id']}")
    assert job["status"] == "succeeded", job["failures"]
    assert (job["artifacts"]["outcome"], job["artifacts"]["reason"]) == (
        "skipped",
        "consolidation_off",
    )
    assert consolidations(fake) == 0
    assert atlas.rounds_budget()["used"] == before
    assert outcomes(atlas.metrics())["skipped_consolidation_off"] == 1
    # The daily schedule enqueues nothing while consolidation is off.
    assert [j["id"] for j in atlas.consolidate_jobs()] == [enqueued["id"]]


# --- rounds (ticket 20) ------------------------------------------------------------------------


def test_a_run_of_three_rounds_is_followed_across_jobs_and_counted_by_rounds(
    atlas: Consolidating, hindsight: tuple[RecordedHindsight, Served]
) -> None:
    fake, _ = hindsight
    atlas.ingest_company("lumentum")
    fake.script_pending_consolidation(atlas.bank, 300)  # three rounds of 100
    codex_before = atlas.codex()["used"]

    first = atlas.by_hand("round-1")

    (round_1,) = fake.consolidation_operations(atlas.bank)
    assert first["status"] == "succeeded", first["failures"]
    assert first["artifacts"]["outcome"] == "running"
    assert (first["artifacts"]["operation_id"], first["artifacts"]["rounds"]) == (round_1, 1)
    running = atlas.consolidation()["last_requested"]
    assert (running["status"], running["operation_status"]) == ("submitted", "processing")
    assert (running["rounds"], running["last_operation_id"]) == (1, round_1)
    assert running["pending_consolidation"] is None
    assert atlas.rounds_budget()["used"] == 1

    # Hindsight ends the round with memories still pending and submits the next by itself.
    round_2 = fake.end_consolidation_round(atlas.bank)
    second = atlas.by_hand("round-2")

    assert (second["artifacts"]["outcome"], second["artifacts"]["joined"]) == ("running", True)
    assert second["artifacts"]["rounds"] == 2
    assert atlas.consolidation()["last_requested"]["last_operation_id"] == round_2
    assert atlas.rounds_budget()["used"] == 2

    round_3 = fake.end_consolidation_round(atlas.bank)
    third = atlas.by_hand("round-3")

    assert (third["artifacts"]["outcome"], third["artifacts"]["rounds"]) == ("running", 3)
    assert atlas.consolidation()["last_completed"] is None

    assert fake.end_consolidation_round(atlas.bank) is None  # nothing pending: the chain ends
    fake.script_pending_consolidation(atlas.bank, 7)  # retained since, the next run's
    fourth = atlas.by_hand("after-the-last-round")

    assert (fourth["artifacts"]["outcome"], fourth["artifacts"]["joined"]) == ("completed", True)
    assert fourth["artifacts"]["pending_consolidation"] == 7
    assert consolidations(fake) == 1  # one request, three rounds
    assert fake.consolidation_operations(atlas.bank) == [round_1, round_2, round_3]
    record = atlas.consolidation()
    completed = record["last_completed"]
    assert completed == record["last_requested"]
    assert (completed["operation_id"], completed["job_id"]) == (round_1, first["id"])
    assert (completed["status"], completed["operation_status"]) == ("completed", "completed")
    assert (completed["rounds"], completed["last_operation_id"]) == (3, round_3)
    assert completed["pending_consolidation"] == 7
    # Three units of the rounds budget, none of the Codex budget.
    rounds = atlas.rounds_budget()
    assert (rounds["used"], rounds["unit"], rounds["kinds"]) == (3, "rounds", ["consolidate"])
    codex = atlas.codex()
    assert codex["used"] == codex_before
    assert "consolidate" not in codex["kinds"]
    metrics = atlas.metrics()
    assert metrics[ROUNDS] == 3
    assert outcomes(metrics) == NO_OUTCOMES | {"completed": 1}
    assert fake.cancelled_operations() == []


def test_a_run_that_reaches_the_rounds_budget_is_cancelled_and_the_next_try_completes_it(
    atlas: Consolidating, hindsight: tuple[RecordedHindsight, Served], clock: Clock
) -> None:
    fake, _ = hindsight
    atlas.with_rounds_budget(3)
    atlas.ingest_company("lumentum")
    fake.script_pending_consolidation(atlas.bank, 400)  # four rounds of 100

    assert atlas.by_hand("round-1")["artifacts"]["outcome"] == "running"
    fake.end_consolidation_round(atlas.bank)
    assert atlas.by_hand("round-2")["artifacts"]["outcome"] == "running"
    round_3 = fake.end_consolidation_round(atlas.bank)
    stopped = atlas.by_hand("round-3")

    # The third round reaches the budget: Atlas cancels it on Hindsight, and it is counted.
    assert stopped["status"] == "succeeded", stopped["failures"]
    assert stopped["artifacts"]["outcome"] == "stopped_at_budget"
    assert stopped["artifacts"]["rounds"] == 3
    assert stopped["artifacts"]["pending_consolidation"] == 200
    assert fake.cancelled_operations() == [round_3]
    record = atlas.consolidation()
    run = record["last_requested"]
    assert (run["status"], run["operation_status"]) == ("stopped_at_budget", "cancelled")
    assert (run["rounds"], run["last_operation_id"], run["pending_consolidation"]) == (
        3,
        round_3,
        200,
    )
    assert run["completed_at"] is not None
    assert record["last_completed"] is None
    rounds = atlas.rounds_budget()
    assert (rounds["used"], rounds["interactive_held"]) == (3, True)
    assert outcomes(atlas.metrics()) == NO_OUTCOMES | {"stopped_at_budget": 1}

    # The next try waits for the window, then asks again and completes the rest.
    retry = atlas.consolidate("--key", "after-the-window")
    assert atlas.scheduled_pass() == 0
    assert atlas.get(f"/api/v1/jobs/{retry['id']}")["status"] == "queued"
    assert consolidations(fake) == 1
    pending = atlas.get("/api/v1/queue")["pending"]
    (consolidate,) = [p for p in pending if p["kind"] == "consolidate"]
    assert (consolidate["queued"], consolidate["budget_held"]) == (1, 1)

    clock.advance(hours=5, seconds=1)  # the first run's rounds leave the window
    atlas.scheduled_pass()

    asked = atlas.get(f"/api/v1/jobs/{retry['id']}")
    assert (asked["artifacts"]["outcome"], asked["artifacts"]["joined"]) == ("running", False)
    assert consolidations(fake) == 2
    assert fake.end_consolidation_round(atlas.bank) is not None
    assert atlas.by_hand("the-rest-round-2")["artifacts"]["outcome"] == "running"
    assert fake.end_consolidation_round(atlas.bank) is None
    done = atlas.by_hand("the-rest-done")

    assert done["artifacts"]["outcome"] == "completed"
    completed = atlas.consolidation()["last_completed"]
    assert completed["job_id"] == retry["id"]
    assert (completed["rounds"], completed["pending_consolidation"]) == (2, 0)
    assert fake.cancelled_operations() == [round_3]
    assert atlas.rounds_budget()["used"] == 2  # this window's: the second run's rounds
    metrics = atlas.metrics()
    assert metrics[ROUNDS] == 5
    assert outcomes(metrics) == NO_OUTCOMES | {"stopped_at_budget": 1, "completed": 1}


def test_a_consolidation_atlas_did_not_request_is_neither_counted_nor_cancelled(
    atlas: Consolidating, hindsight: tuple[RecordedHindsight, Served]
) -> None:
    fake, _ = hindsight
    # Two rounds would spend the budget, so had Atlas counted the other chain's two rounds it
    # would cancel its own first round.
    atlas.with_rounds_budget(2)
    atlas.ingest_company("lumentum")
    fake.script_pending_consolidation(atlas.bank, 200)
    elsewhere_1 = fake.request_consolidation_elsewhere(atlas.bank)  # the owner's, say

    skipped = atlas.by_hand("beside-another-chain")

    assert (skipped["artifacts"]["outcome"], skipped["artifacts"]["reason"]) == (
        "skipped",
        "other_consolidation_running",
    )
    assert consolidations(fake) == 0
    assert fake.cancelled_operations() == []
    assert atlas.rounds_budget()["used"] == 0

    elsewhere_2 = fake.end_consolidation_round(atlas.bank)  # its chain goes on by itself
    assert fake.end_consolidation_round(atlas.bank) is None
    fake.script_pending_consolidation(atlas.bank, 100)  # retained since
    asked = atlas.by_hand("after-the-other-chain")

    assert asked["artifacts"]["outcome"] == "running"
    own = asked["artifacts"]["operation_id"]
    assert fake.consolidation_operations(atlas.bank) == [elsewhere_1, elsewhere_2, own]
    assert fake.end_consolidation_round(atlas.bank) is None
    done = atlas.by_hand("its-own-round-done")

    assert done["artifacts"]["outcome"] == "completed"
    completed = atlas.consolidation()["last_completed"]
    assert (completed["rounds"], completed["last_operation_id"]) == (1, own)
    assert atlas.rounds_budget()["used"] == 1
    assert fake.cancelled_operations() == []
    metrics = atlas.metrics()
    assert metrics[ROUNDS] == 1
    assert outcomes(metrics) == NO_OUTCOMES | {
        "completed": 1,
        "skipped_other_consolidation_running": 1,
    }


# --- follow-ups (ticket 20, the lead's audit) ----------------------------------------------------


def test_a_run_still_going_is_followed_every_interval_past_the_daily_tries_until_it_ends(
    atlas: Consolidating, hindsight: tuple[RecordedHindsight, Served], clock: Clock
) -> None:
    fake, _ = hindsight
    atlas.schedule_daily()
    atlas.overrides["consolidate_max_tries"] = 1  # the day's one try is the run's request
    atlas.ingest_company("lumentum")
    fake.script_pending_consolidation(atlas.bank, 400)  # four rounds
    clock.now = clock.now.replace(hour=4, minute=30, second=0)
    start = clock.now

    assert atlas.scheduled_pass() == 1
    (requested,) = atlas.consolidate_jobs()
    assert requested["artifacts"]["outcome"] == "running"
    run_id = requested["artifacts"]["consolidation_id"]

    clock.advance(seconds=299)  # not yet an interval (ATLAS_CONSOLIDATE_FOLLOW_SECONDS, 300)
    assert atlas.scheduled_pass() == 0

    for round_number in (2, 3, 4):
        fake.end_consolidation_round(atlas.bank)  # Hindsight chains the next round itself
        clock.advance(seconds=2 if round_number == 2 else 301)
        assert atlas.scheduled_pass() == 1
        follow = atlas.consolidate_jobs()[-1]
        assert follow["job_class"] == "backfill"  # the run's class
        assert follow["payload"]["follow"] == run_id
        assert follow["artifacts"]["follow"] is True
        assert (follow["artifacts"]["outcome"], follow["artifacts"]["rounds"]) == (
            "running",
            round_number,
        )

    assert fake.end_consolidation_round(atlas.bank) is None
    clock.advance(seconds=301)
    assert atlas.scheduled_pass() == 1
    done = atlas.consolidate_jobs()[-1]
    assert (done["artifacts"]["outcome"], done["artifacts"]["rounds"]) == ("completed", 4)
    assert clock.now - start < timedelta(hours=1)  # every few minutes, not hourly

    # The run has ended: no more follow-ups, and no daily try is left for the day.
    clock.advance(hours=2)
    assert atlas.scheduled_pass() == 0
    jobs = atlas.consolidate_jobs()
    assert [j["payload"].get("follow") for j in jobs] == [None] + [run_id] * 4
    assert [j["idempotency_key"] for j in jobs[1:]] == [
        f"consolidate:{atlas.bank}:follow:{run_id}:{n}" for n in range(4)
    ]
    assert consolidations(fake) == 1  # a follow-up never asks again
    assert atlas.rounds_budget()["used"] == 4
    assert atlas.consolidation()["last_completed"]["id"] == run_id


def test_a_chain_longer_than_the_budget_is_cancelled_within_one_follow_interval(
    atlas: Consolidating, hindsight: tuple[RecordedHindsight, Served], clock: Clock
) -> None:
    fake, _ = hindsight
    atlas.with_rounds_budget(3)
    atlas.ingest_company("lumentum")
    fake.script_pending_consolidation(atlas.bank, 1000)  # ten rounds

    first = atlas.by_hand("a-long-chain")
    assert (first["artifacts"]["outcome"], first["artifacts"]["rounds"]) == ("running", 1)

    # Two rounds end unwatched within one interval; the third is running at the next look.
    fake.end_consolidation_round(atlas.bank)
    round_3 = fake.end_consolidation_round(atlas.bank)
    clock.advance(seconds=301)
    assert atlas.scheduled_pass() == 1

    follow = atlas.consolidate_jobs()[-1]
    assert follow["job_class"] == "interactive"  # the run's class
    assert follow["artifacts"]["outcome"] == "stopped_at_budget"
    assert follow["artifacts"]["rounds"] == 3
    assert fake.cancelled_operations() == [round_3]
    assert fake.consolidation_operations(atlas.bank)[-1] == round_3  # no round after it
    assert atlas.consolidation()["last_requested"]["status"] == "stopped_at_budget"
    assert atlas.rounds_budget()["used"] == 3

    clock.advance(seconds=301)  # the run has ended: nothing more follows it
    assert atlas.scheduled_pass() == 0
    assert consolidations(fake) == 1
