"""Queue pause and pacing: quota or outage failures pause the queue with backoff, and
backfill-class jobs wait for the nightly window (spec Part B stories 12-14, 34-35).

Seams: the `atlas` CLI enqueues, single worker passes run the jobs with a controllable
pacing clock, and everything is observed through `/api/v1/queue`, `/api/v1/jobs`,
`/api/v1/source-versions/{id}/memory`, `/metrics` and the requests Hindsight received.
Hindsight is the recorded fake on localhost with `derive_retains` on (see
`tests/integration/test_retention.py`). A failed operation's error message was never
recorded, so `hold_retains(..., error_message=...)` derives it; its text is the OpenAI-style
error LiteLLM returns for a 429. An outage is real: Hindsight's URL points at a closed port.
"""

import json
import re
import socket
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

import pytest
import yaml
from fastapi.testclient import TestClient

from atlas.api.app import create_app
from atlas.jobs import JobQueue, Pacing, Worker, builtin_registry, job_id_for
from tests.fakes.hindsight import RecordedHindsight
from tests.fakes.serve import Served
from tests.harness import (
    LITE_10K,
    QUOTA_ERROR,
    REPO,
    TEN_K_ANCHORS,
    Atlas,
    Clock,
    Metrics,
    at,
    make_settings,
    scrape_metrics,
)

ALERT_RULES = REPO / "configs" / "prometheus" / "atlas-alerts.yaml"
PAUSABLE_KINDS = [
    "discover",
    "extract_claims",
    "poll_operation",
    "refresh_mental_model",
    "reprocess",
    "retain",
]
UNRELATED_ERROR = "ValueError: document exceeds the extraction schema's maximum length"
STOCKHOLM = ZoneInfo("Europe/Stockholm")


class Paced:
    """The Atlas harness, with worker passes and the API on a controllable pacing clock."""

    def __init__(self, atlas: Atlas, clock: Clock) -> None:
        self.atlas = atlas
        self.clock = clock
        self.api = TestClient(create_app(atlas.settings(), clock=clock))

    def worker_pass(self, **overrides: Any) -> int:
        settings = self.atlas.settings().model_copy(update=overrides)
        queue = JobQueue(self.atlas.engine, pacing=Pacing.from_settings(settings), clock=self.clock)
        return Worker(queue, builtin_registry(settings)).run_once()

    def get(self, path: str) -> Any:
        response = self.api.get(path)
        assert response.status_code == 200, response.text
        return response.json()

    def queue(self) -> dict[str, Any]:
        return self.get("/api/v1/queue")

    def pause(self) -> dict[str, Any]:
        return self.queue()["pause"]

    def pending(self) -> dict[str, dict[str, Any]]:
        return {entry["kind"]: entry for entry in self.queue()["pending"]}

    def job(self, job_id: uuid.UUID | str) -> dict[str, Any]:
        return self.get(f"/api/v1/jobs/{job_id}")

    def ingest_10k(self, key: str = "ingest-10k", *extra: str) -> str:
        return self.atlas.enqueue(
            "ingest", "--company", "lumentum", "--key", key, "--forms", "10-K", *extra
        )

    def ten_k_memory(self) -> dict[str, Any]:
        return self.atlas.memory(self.atlas.version(LITE_10K)["id"])

    def pause_audit(self) -> list[tuple[str, str]]:
        """The audit events of the queue pause (entered and cleared), oldest first."""
        with self.atlas.engine.connect() as connection:
            rows = connection.exec_driver_sql(
                "SELECT actor, action FROM audit_event WHERE entity_type = 'queue_pause'"
                " ORDER BY id"
            ).all()
        return [(row[0], row[1]) for row in rows]

    def metrics(self) -> Metrics:
        return scrape_metrics(self.api)


def is_10k_batch(document_ids: list[str] | Any) -> bool:
    return any(str(i).endswith(":part-i-item-1a") for i in document_ids)


def ten_k_batches(fake: RecordedHindsight) -> list[list[dict[str, Any]]]:
    return [batch for batch in fake.retained() if is_10k_batch([i["document_id"] for i in batch])]


@pytest.fixture
def clock() -> Clock:
    # Real time, so the database's lease clock and the pacing clock start together.
    return Clock(datetime.now(UTC).replace(microsecond=0))


@pytest.fixture
def paced(
    database_url: str, tmp_path: Path, hindsight: tuple[RecordedHindsight, Served], clock: Clock
) -> Paced:
    # No backfill window unless a test sets one, so only the pause gates these passes.
    atlas = Atlas(database_url, tmp_path, hindsight[1].url, backfill_window="")
    atlas.apply_template()
    return Paced(atlas, clock)


@pytest.fixture
def unreachable_url() -> str:
    """A localhost URL nothing listens on: connecting is refused, as when Hindsight is down."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    return f"http://127.0.0.1:{port}"


# --- pause on quota -------------------------------------------------------------------------


def test_a_429_failed_operation_pauses_the_queue_then_resumes_and_resubmits(
    paced: Paced, fake: RecordedHindsight, clock: Clock
) -> None:
    fake.hold_retains("failed", where=is_10k_batch, error_message=QUOTA_ERROR, times=1)
    paced.ingest_10k()

    paced.worker_pass()

    # The 10-K's operation failed with a 429 behind Hindsight: the queue pauses for 60 s.
    pause = paced.pause()
    assert pause["paused"] is True
    assert (pause["level"], pause["error_class"], pause["backoff_seconds"]) == (1, "quota", 60)
    assert QUOTA_ERROR in pause["reason"]
    assert pause["kinds"] == PAUSABLE_KINDS
    assert at(pause["paused_at"]) == clock.now == at(pause["since"])
    assert at(pause["resume_after"]) == clock.now + timedelta(seconds=60)
    assert pause["pauses_total"] == 1
    # Its sections wait, rather than fail; the operation keeps Hindsight's error and class.
    memory = paced.ten_k_memory()
    assert memory["counts"]["pending"] == len(TEN_K_ANCHORS)
    (operation,) = memory["operations"]
    assert (operation["status"], operation["error_class"]) == ("failed", "quota")
    assert operation["error_message"] == QUOTA_ERROR
    # The poll job is requeued without using up an attempt, the failure recorded as quota.
    poll = paced.job(job_id_for("poll_operation", f"poll:{operation['id']}"))
    assert (poll["status"], poll["attempts"]) == ("queued", 0)
    assert poll["failures"][-1]["classification"] == "quota"
    assert QUOTA_ERROR in poll["failures"][-1]["error"]
    assert paced.pending()["poll_operation"] | {"queued": 1} == {
        "kind": "poll_operation",
        "queued": 1,
        "running": 0,
        "backfill_queued": 0,
        "paused": True,
    }

    # While paused, nothing of a paused kind is claimed and Hindsight hears nothing.
    calls = len(fake.calls)
    clock.advance(seconds=59)
    assert paced.worker_pass() == 0
    assert len(fake.calls) == calls

    # After the backoff, the same sections are resubmitted, unchanged, and complete.
    clock.advance(seconds=1)
    assert paced.worker_pass() > 0
    first, again = ten_k_batches(fake)
    assert again == first
    memory = paced.ten_k_memory()
    assert memory["counts"]["completed"] == len(TEN_K_ANCHORS)
    assert [o["status"] for o in memory["operations"]] == ["failed", "completed"]
    assert memory["operations"][1]["id"] != operation["id"]
    assert paced.job(poll["id"])["artifacts"]["outcome"] == "resubmitted"
    # The success cleared the pause.
    pause = paced.pause()
    assert (pause["paused"], pause["level"], pause["since"]) == (False, 0, None)
    assert at(pause["cleared_at"]) == clock.now
    assert paced.queue()["pending"] == []
    # Entering and clearing the pause are audited, by the system actor; the claims, leases
    # and requeues around them are not (they stay in each job's history).
    assert paced.pause_audit() == [
        ("atlas-system", "queue.paused"),
        ("atlas-system", "queue.pause_cleared"),
    ]
    verified = paced.atlas.cli("audit", "verify")
    assert verified.returncode == 0, verified.stdout + verified.stderr


def test_outage_pauses_double_their_backoff_up_to_one_hour_and_never_fail_the_job(
    paced: Paced, fake: RecordedHindsight, clock: Clock, unreachable_url: str
) -> None:
    paced.ingest_10k()

    backoffs: list[float] = []
    for _ in range(8):
        paced.worker_pass(hindsight_url=unreachable_url)
        pause = paced.pause()
        assert (pause["paused"], pause["error_class"]) == (True, "unavailable")
        assert at(pause["resume_after"]) - at(pause["paused_at"]) == timedelta(
            seconds=pause["backoff_seconds"]
        )
        backoffs.append(pause["backoff_seconds"])
        clock.now = at(pause["resume_after"])

    assert backoffs == [60, 120, 240, 480, 960, 1920, 3600, 3600]
    pause = paced.pause()
    assert pause["level"] == 8
    assert at(pause["since"]) < at(pause["paused_at"])  # one run of pauses since it began
    # The retain job was never failed: every attempt was handed back.
    (retain_id,) = paced.job(job_id_for("ingest", "ingest-10k"))["artifacts"]["retain_jobs"]
    retain = paced.job(retain_id)
    assert (retain["status"], retain["attempts"]) == ("queued", 0)
    assert [f["classification"] for f in retain["failures"]] == ["unavailable"] * 8
    assert "HindsightUnavailable" in retain["failures"][0]["error"]
    assert fake.retained() == []

    # Hindsight is back: the retain succeeds and the next success clears the pause.
    paced.worker_pass()
    assert paced.job(retain_id)["status"] == "succeeded"
    assert paced.pause()["level"] == 0
    # A later outage starts again at the base backoff.
    paced.atlas.enqueue("ingest", "--company", "coherent", "--key", "coherent", "--forms", "10-K")
    paced.worker_pass(hindsight_url=unreachable_url)
    pause = paced.pause()
    assert (pause["level"], pause["backoff_seconds"], pause["pauses_total"]) == (1, 60, 9)


def test_a_failed_operation_with_an_unrelated_error_fails_its_sections_without_pausing(
    paced: Paced, fake: RecordedHindsight
) -> None:
    fake.hold_retains("failed", where=is_10k_batch, error_message=UNRELATED_ERROR)
    paced.ingest_10k()

    paced.worker_pass()

    pause = paced.pause()
    assert (pause["paused"], pause["level"], pause["pauses_total"]) == (False, 0, 0)
    memory = paced.ten_k_memory()
    assert memory["counts"]["failed"] == len(TEN_K_ANCHORS)
    assert {d["error"] for d in memory["documents"]} == {UNRELATED_ERROR}
    (operation,) = memory["operations"]
    assert operation["error_class"] == "permanent"
    assert len(ten_k_batches(fake)) == 1  # not resubmitted
    assert paced.queue()["pending"] == []


def test_a_pausable_job_failing_for_its_own_reason_is_retried_without_pausing(
    database_url: str, tmp_path: Path, hindsight: tuple[RecordedHindsight, Served], clock: Clock
) -> None:
    # No bank template applied: retains fail on their own account, not Hindsight's.
    paced = Paced(Atlas(database_url, tmp_path, hindsight[1].url, backfill_window=""), clock)
    paced.ingest_10k()

    paced.worker_pass()

    (retain_id,) = paced.job(job_id_for("ingest", "ingest-10k"))["artifacts"]["retain_jobs"]
    retain = paced.job(retain_id)
    assert (retain["status"], retain["attempts"]) == ("failed", 3)
    assert [f["classification"] for f in retain["failures"]] == ["error"] * 3
    assert "NoTemplateApplied" in retain["last_error"]
    pause = paced.pause()
    assert (pause["paused"], pause["level"], pause["pauses_total"]) == (False, 0, 0)


# --- the backfill window --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("window", "timezone", "outside", "next_open", "inside"),
    [
        # 07:00 is the end of 01:00-07:00 and already outside; the window opens at 01:00 CEST.
        (
            "01:00-07:00",
            "Europe/Stockholm",
            datetime(2026, 9, 29, 7, 0, tzinfo=STOCKHOLM),
            "2026-09-29T23:00:00Z",
            datetime(2026, 9, 30, 2, 59, tzinfo=STOCKHOLM),
        ),
        # A window across midnight.
        (
            "22:00-06:00",
            "UTC",
            datetime(2026, 9, 29, 6, 0, tzinfo=UTC),
            "2026-09-29T22:00:00Z",
            datetime(2026, 9, 30, 3, 0, tzinfo=UTC),
        ),
    ],
)
def test_backfill_jobs_wait_for_the_nightly_window(
    database_url: str,
    tmp_path: Path,
    hindsight: tuple[RecordedHindsight, Served],
    window: str,
    timezone: str,
    outside: datetime,
    next_open: str,
    inside: datetime,
) -> None:
    clock = Clock(outside)
    atlas = Atlas(
        database_url, tmp_path, hindsight[1].url, backfill_window=window, backfill_timezone=timezone
    )
    paced = Paced(atlas, clock)
    backfill = json.loads(
        atlas.cli("jobs", "enqueue", "noop", "--key", "nightly", "--backfill").stdout
    )
    interactive = atlas.enqueue("jobs", "enqueue", "noop", "--key", "now")
    assert backfill["job_class"] == "backfill"

    assert paced.worker_pass() == 1

    assert paced.job(interactive)["status"] == "succeeded"
    assert paced.job(backfill["id"])["status"] == "queued"
    status = paced.queue()
    assert status["backfill_window"] == {
        "window": window,
        "timezone": timezone,
        "open": False,
        "next_open_at": next_open,
    }
    assert status["pending"] == [
        {"kind": "noop", "queued": 1, "running": 0, "backfill_queued": 1, "paused": False}
    ]

    clock.now = inside
    assert paced.worker_pass() == 1

    assert paced.job(backfill["id"])["status"] == "succeeded"
    assert paced.queue()["backfill_window"]["open"] is True
    assert paced.queue()["backfill_window"]["next_open_at"] is None


def test_a_backfill_ingest_and_its_retains_run_only_in_the_window(
    database_url: str, tmp_path: Path, hindsight: tuple[RecordedHindsight, Served]
) -> None:
    fake = hindsight[0]
    fake.report_zero_facts(lambda document_id: document_id.endswith(":part-i-item-1b"))
    clock = Clock(datetime(2026, 9, 29, 12, 0, tzinfo=UTC))
    atlas = Atlas(database_url, tmp_path, hindsight[1].url, backfill_window="01:00-07:00")
    atlas.apply_template()
    paced = Paced(atlas, clock)
    ingest = json.loads(
        atlas.cli(
            "ingest", "--company", "lumentum", "--key", "backfill", "--forms", "10-K", "--backfill"
        ).stdout
    )
    assert ingest["job_class"] == "backfill"

    assert paced.worker_pass() == 0  # noon UTC: outside the window
    assert paced.job(ingest["id"])["status"] == "queued"

    clock.now = datetime(2026, 9, 30, 1, 0, tzinfo=UTC)
    paced.worker_pass()

    retain_ids = paced.job(ingest["id"])["artifacts"]["retain_jobs"]
    assert retain_ids
    assert {paced.job(i)["job_class"] for i in retain_ids} == {"backfill"}
    memory = paced.ten_k_memory()
    assert memory["counts"]["zero_fact"] == 1
    first, reprocess = [o["id"] for o in memory["operations"]]
    # Polling spends no quota, so it is never held for the window; the reprocess does.
    assert paced.job(job_id_for("poll_operation", f"poll:{first}"))["job_class"] == "interactive"
    reprocess_job = paced.job(job_id_for("reprocess", f"reprocess:{first}"))
    assert (reprocess_job["job_class"], reprocess_job["status"]) == ("backfill", "succeeded")
    assert reprocess


# --- metrics and alert rules ----------------------------------------------------------------


def labels(**pairs: str) -> frozenset[tuple[str, str]]:
    return frozenset(pairs.items())


def test_metrics_report_pauses_operations_retains_zero_facts_and_queue_depth(
    paced: Paced, fake: RecordedHindsight, clock: Clock
) -> None:
    fake.hold_retains("failed", where=is_10k_batch, error_message=QUOTA_ERROR, times=1)
    fake.report_zero_facts(lambda document_id: document_id.endswith(":part-i-item-1b"))
    paced.ingest_10k()
    paced.worker_pass()
    clock.advance(seconds=30)

    paused = paced.metrics()
    assert paused[("atlas_state_metrics_up", labels())] == 1
    assert paused[("atlas_queue_paused", labels())] == 1
    assert paused[("atlas_queue_pause_level", labels())] == 1
    assert paused[("atlas_queue_pause_backoff_seconds", labels())] == 60
    assert paused[("atlas_queue_pause_duration_seconds", labels())] == 30
    assert paused[("atlas_queue_pauses_total", labels(error_class="quota"))] == 1
    assert paused[("atlas_queue_pauses_total", labels(error_class="unavailable"))] == 0
    operation = labels(kind="retain", status="failed", error_class="quota")
    assert paused[("atlas_hindsight_operations_total", operation)] == 1
    depth = labels(kind="poll_operation", job_class="interactive", status="queued")
    assert paused[("atlas_queue_jobs", depth)] == 1
    assert paused[("atlas_memory_sections_pending", labels())] >= len(TEN_K_ANCHORS)

    clock.advance(seconds=30)
    paced.worker_pass()

    done = paced.metrics()
    assert done[("atlas_queue_paused", labels())] == 0
    assert done[("atlas_queue_pause_duration_seconds", labels())] == 0
    assert done[("atlas_queue_pauses_total", labels(error_class="quota"))] == 1
    memory = paced.ten_k_memory()
    completed = labels(outcome="completed")
    assert done[("atlas_retained_sections_total", completed)] >= memory["counts"]["completed"]
    assert memory["counts"]["completed"] == len(TEN_K_ANCHORS) - 1
    assert done[("atlas_zero_fact_sections_total", labels())] == 1
    reprocessed = labels(kind="reprocess", status="completed", error_class="none")
    assert done[("atlas_hindsight_operations_total", reprocessed)] == 1
    assert ("atlas_queue_jobs", depth) not in done
    assert done[("atlas_memory_sections_pending", labels())] == 0

    # Every metric the alert rules use is one /metrics exposes.
    rules = cast(dict[str, Any], yaml.safe_load(ALERT_RULES.read_text(encoding="utf-8")))
    exprs = [r["expr"] for g in rules["spec"]["groups"] for r in g["rules"]]
    used = {name for expr in exprs for name in re.findall(r"\batlas_[a-z_]+", expr)}
    exposed = {name for name, _ in done}
    assert used and used <= exposed, used - exposed


def test_metrics_report_the_database_as_unreadable_instead_of_failing(tmp_path: Path) -> None:
    client = TestClient(create_app(make_settings(tmp_path)))

    response = client.get("/metrics")

    assert response.status_code == 200
    assert "atlas_state_metrics_up 0.0" in response.text
    assert "atlas_queue_paused" not in response.text
