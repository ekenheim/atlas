"""The job queue, seen through the `atlas` CLI, the worker single pass and `/api/v1/jobs`."""

import json
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections import Counter
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import JsonValue
from sqlalchemy import create_engine

from atlas.api.app import create_app
from atlas.db.migrate import upgrade
from atlas.jobs import HandlerRegistry, Job, JobQueue, Worker, builtin_registry
from atlas.settings import Settings


@pytest.fixture
def database_url(empty_database_url: str) -> str:
    upgrade(empty_database_url)
    return empty_database_url


@pytest.fixture
def queue(database_url: str) -> Iterator[JobQueue]:
    engine = create_engine(database_url)
    yield JobQueue(engine)
    engine.dispose()


def app_env(database_url: str, tmp_path: Path, **extra: str) -> dict[str, str]:
    archive = tmp_path / "archive"
    archive.mkdir(exist_ok=True)
    return {
        "PATH": os.environ["PATH"],
        "HOME": str(tmp_path),
        "ATLAS_DATABASE_URL": database_url,
        "ATLAS_ACTOR": "local-researcher",
        "ATLAS_ARCHIVE_ROOT": str(archive),
        **extra,
    }


def run_atlas(args: list[str], env: dict[str, str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "atlas", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def api(database_url: str, tmp_path: Path) -> TestClient:
    archive = tmp_path / "archive"
    archive.mkdir(exist_ok=True)
    settings = Settings.model_validate(
        {"database_url": database_url, "actor": "local-researcher", "archive_root": archive}
    )
    return TestClient(create_app(settings))


def enqueue_cli(env: dict[str, str], cwd: Path, *args: str) -> dict[str, Any]:
    result = run_atlas(["jobs", "enqueue", *args], env, cwd)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_enqueued_noop_job_runs_in_one_worker_pass_and_its_status_is_visible(
    database_url: str, tmp_path: Path
) -> None:
    env = app_env(database_url, tmp_path)

    enqueued = enqueue_cli(env, tmp_path, "noop", "--key", "hello", "--payload", '{"n": 1}')
    queued = api(database_url, tmp_path).get(f"/api/v1/jobs/{enqueued['id']}").json()
    worker = run_atlas(["worker", "--once"], env, tmp_path)
    body = api(database_url, tmp_path).get(f"/api/v1/jobs/{enqueued['id']}").json()

    assert enqueued["created"] is True
    assert queued["status"] == "queued"
    assert queued["attempts"] == 0
    assert worker.returncode == 0, worker.stderr
    assert body["id"] == enqueued["id"]
    assert body["kind"] == "noop"
    assert body["idempotency_key"] == "hello"
    assert body["payload"] == {"n": 1}
    assert body["status"] == "succeeded"
    assert body["attempts"] == 1
    assert body["failures"] == []
    assert body["last_error"] is None
    assert body["artifacts"] == {}
    assert body["lease_owner"] is None
    assert body["finished_at"] is not None


def test_same_idempotency_key_gives_one_job_that_is_not_rerun(
    database_url: str, tmp_path: Path
) -> None:
    env = app_env(database_url, tmp_path)

    first = enqueue_cli(env, tmp_path, "noop", "--key", "lumentum-2026q3")
    assert run_atlas(["worker", "--once"], env, tmp_path).returncode == 0
    second = enqueue_cli(env, tmp_path, "noop", "--key", "lumentum-2026q3")
    assert run_atlas(["worker", "--once"], env, tmp_path).returncode == 0
    body = api(database_url, tmp_path).get(f"/api/v1/jobs/{first['id']}").json()

    assert first["created"] is True
    assert second["created"] is False
    assert second["id"] == first["id"]
    assert second["status"] == "succeeded"
    assert body["attempts"] == 1


def test_job_ids_are_deterministic_per_kind_and_idempotency_key(queue: JobQueue) -> None:
    a = queue.enqueue("noop", "k")
    again = queue.enqueue("noop", "k")
    other_kind = queue.enqueue("other", "k")
    other_key = queue.enqueue("noop", "k2")

    assert a.job.id == again.job.id
    assert len({a.job.id, other_kind.job.id, other_key.job.id}) == 3


def test_enqueue_cli_rejects_unknown_kinds_and_bad_payloads(
    database_url: str, tmp_path: Path
) -> None:
    env = app_env(database_url, tmp_path)

    unknown = run_atlas(["jobs", "enqueue", "bogus", "--key", "k"], env, tmp_path)
    bad_json = run_atlas(["jobs", "enqueue", "noop", "--key", "k", "--payload", "{"], env, tmp_path)
    not_object = run_atlas(
        ["jobs", "enqueue", "noop", "--key", "k", "--payload", "[1]"], env, tmp_path
    )

    assert unknown.returncode == 2
    assert "unknown job kind 'bogus'" in unknown.stderr
    assert "noop" in unknown.stderr
    for result in (bad_json, not_object):
        assert result.returncode == 2
        assert "--payload must be a JSON object" in result.stderr
        assert "Traceback" not in result.stderr


def test_concurrent_workers_never_claim_the_same_job(queue: JobQueue) -> None:
    ids = {queue.enqueue("record", f"job-{n}").job.id for n in range(40)}
    runs: list[tuple[uuid.UUID, str]] = []
    lock = threading.Lock()

    def record(job: Job) -> dict[str, JsonValue]:
        time.sleep(0.01)  # hold the claim long enough for the workers to overlap
        with lock:
            runs.append((job.id, job.lease_owner or ""))
        return {}

    registry = HandlerRegistry()
    registry.register("record", record)
    workers = [Worker(queue, registry, worker_id=f"w{n}") for n in range(4)]
    start = threading.Barrier(len(workers))

    def run(worker: Worker) -> None:
        start.wait()
        worker.run_once()

    threads = [threading.Thread(target=run, args=(w,)) for w in workers]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    per_job = Counter(job_id for job_id, _ in runs)
    assert set(per_job) == ids
    assert set(per_job.values()) == {1}
    assert len({owner for _, owner in runs}) > 1  # the workers really ran concurrently
    for job_id in ids:
        job = queue.get(job_id)
        assert job is not None
        assert (job.status, job.attempts) == ("succeeded", 1)


def test_an_expired_lease_is_reclaimed_and_the_lost_lease_recorded(
    queue: JobQueue, database_url: str, tmp_path: Path
) -> None:
    job_id = queue.enqueue("noop", "crashy").job.id
    crashed = queue.claim("crashed-worker", lease=timedelta(0))  # lease expires immediately
    assert crashed is not None

    processed = Worker(queue, builtin_registry(), worker_id="rescuer").run_once()
    late = queue.complete(crashed, "crashed-worker", {"too": "late"})
    body = api(database_url, tmp_path).get(f"/api/v1/jobs/{job_id}").json()

    assert processed == 1
    assert late is False  # the crashed worker lost its lease and cannot overwrite the result
    assert body["status"] == "succeeded"
    assert body["attempts"] == 2
    assert body["artifacts"] == {}
    assert len(body["failures"]) == 1
    assert body["failures"][0]["attempt"] == 1
    assert body["failures"][0]["worker"] == "crashed-worker"
    assert "lease expired" in body["failures"][0]["error"]


def test_a_live_lease_is_not_reclaimed(queue: JobQueue) -> None:
    queue.enqueue("noop", "busy")
    assert queue.claim("busy-worker", lease=timedelta(minutes=5)) is not None

    assert Worker(queue, builtin_registry(), worker_id="other").run_once() == 0


def test_retries_stop_at_the_bound_with_every_failure_recorded(
    queue: JobQueue, database_url: str, tmp_path: Path
) -> None:
    job_id = queue.enqueue("flaky", "always-fails", max_attempts=3).job.id
    calls: list[int] = []

    def always_fail(job: Job) -> dict[str, JsonValue]:
        calls.append(job.attempts)
        raise RuntimeError(f"EDGAR returned 503 on attempt {job.attempts}")

    registry = HandlerRegistry()
    registry.register("flaky", always_fail)
    Worker(queue, registry, worker_id="w").run_once()
    Worker(queue, registry, worker_id="w").run_once()  # nothing left to retry
    body = api(database_url, tmp_path).get(f"/api/v1/jobs/{job_id}").json()

    assert calls == [1, 2, 3]
    assert body["status"] == "failed"
    assert body["attempts"] == 3
    assert body["max_attempts"] == 3
    assert [f["attempt"] for f in body["failures"]] == [1, 2, 3]
    assert body["failures"][2]["error"] == "RuntimeError: EDGAR returned 503 on attempt 3"
    assert body["last_error"] == "RuntimeError: EDGAR returned 503 on attempt 3"
    assert body["lease_owner"] is None


def test_a_retried_job_can_succeed_and_its_artifacts_are_visible(
    queue: JobQueue, database_url: str, tmp_path: Path
) -> None:
    job_id = queue.enqueue("flaky", "fails-once").job.id

    def fail_first(job: Job) -> dict[str, JsonValue]:
        if job.attempts == 1:
            raise TimeoutError("read timed out")
        return {"source_version_ids": ["sv-1", "sv-2"]}

    registry = HandlerRegistry()
    registry.register("flaky", fail_first)
    Worker(queue, registry, worker_id="w").run_once()
    body = api(database_url, tmp_path).get(f"/api/v1/jobs/{job_id}").json()

    assert body["status"] == "succeeded"
    assert body["attempts"] == 2
    assert body["artifacts"] == {"source_version_ids": ["sv-1", "sv-2"]}
    assert [f["error"] for f in body["failures"]] == ["TimeoutError: read timed out"]
    assert body["last_error"] == "TimeoutError: read timed out"


def test_a_job_without_a_handler_fails_without_retrying(queue: JobQueue) -> None:
    job_id = queue.enqueue("unregistered", "k", max_attempts=5).job.id

    Worker(queue, builtin_registry(), worker_id="w").run_once()
    job = queue.get(job_id)

    assert job is not None
    assert (job.status, job.attempts) == ("failed", 1)
    assert job.last_error == "no handler registered for job kind 'unregistered'"


def test_an_expired_lease_on_the_last_attempt_fails_the_job(queue: JobQueue) -> None:
    job_id = queue.enqueue("noop", "k", max_attempts=1).job.id
    assert queue.claim("crashed-worker", lease=timedelta(0)) is not None

    processed = Worker(queue, builtin_registry(), worker_id="w").run_once()
    job = queue.get(job_id)

    assert processed == 0
    assert job is not None
    assert (job.status, job.attempts) == ("failed", 1)
    assert job.last_error is not None and "lease expired" in job.last_error


def test_unknown_job_is_404_with_an_error_envelope(database_url: str, tmp_path: Path) -> None:
    client = api(database_url, tmp_path)

    missing = client.get(f"/api/v1/jobs/{uuid.uuid4()}")
    malformed = client.get("/api/v1/jobs/not-a-uuid")

    assert missing.status_code == 404
    assert missing.json() == {"error": {"code": "not_found", "message": "job not found"}}
    assert malformed.status_code == 422


def test_continuous_worker_picks_up_new_jobs_and_stops_on_sigterm(
    database_url: str, tmp_path: Path
) -> None:
    env = app_env(database_url, tmp_path, ATLAS_WORKER_POLL_SECONDS="0.2")
    worker = subprocess.Popen(
        [sys.executable, "-m", "atlas", "worker"],
        cwd=tmp_path,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        time.sleep(1)  # the worker is idle, polling
        job_id = enqueue_cli(env, tmp_path, "noop", "--key", "later")["id"]
        client = api(database_url, tmp_path)
        deadline = time.monotonic() + 30
        status = None
        while time.monotonic() < deadline:
            status = client.get(f"/api/v1/jobs/{job_id}").json()["status"]
            if status == "succeeded":
                break
            time.sleep(0.2)
        assert status == "succeeded"
        assert worker.poll() is None  # still running
    finally:
        worker.send_signal(signal.SIGTERM)
        _, stderr = worker.communicate(timeout=30)

    assert worker.returncode == 0, stderr


def test_worker_once_on_an_empty_queue_exits_cleanly(database_url: str, tmp_path: Path) -> None:
    result = run_atlas(["worker", "--once"], app_env(database_url, tmp_path), tmp_path)

    assert result.returncode == 0, result.stderr


def audit_events(database_url: str) -> list[tuple[str, str, str, str]]:
    engine = create_engine(database_url)
    with engine.connect() as connection:
        rows = connection.exec_driver_sql(
            "SELECT actor, action, entity_type, entity_id FROM audit_event ORDER BY id"
        ).all()
    engine.dispose()
    return [(row[0], row[1], row[2], row[3]) for row in rows]


def test_an_enqueue_is_audited_once_and_claims_and_leases_are_not(
    database_url: str, tmp_path: Path
) -> None:
    env = app_env(database_url, tmp_path)

    first = enqueue_cli(env, tmp_path, "noop", "--key", "audited")
    enqueue_cli(env, tmp_path, "noop", "--key", "audited")  # idempotent: nothing new
    assert run_atlas(["worker", "--once"], env, tmp_path).returncode == 0

    # The enqueue wrote its event with the job; the claim, lease and completion are the
    # job's own history (docs/decisions.md), not audit events.
    assert audit_events(database_url) == [("local-researcher", "job.enqueued", "job", first["id"])]
    verified = run_atlas(["audit", "verify"], env, tmp_path)
    assert verified.returncode == 0, verified.stdout + verified.stderr
