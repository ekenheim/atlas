"""The worker: claims jobs from the queue and runs their handlers."""

import json
import logging
import os
import socket
import threading
import uuid
from collections.abc import Sequence
from datetime import timedelta

from sqlalchemy.exc import OperationalError

from atlas.jobs.handlers import HandlerRegistry, Schedule
from atlas.jobs.pacing import Requeue, classify_failure
from atlas.jobs.queue import Job, JobQueue

log = logging.getLogger("atlas.worker")


def default_worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


class Worker:
    def __init__(
        self,
        queue: JobQueue,
        registry: HandlerRegistry,
        worker_id: str | None = None,
        lease: timedelta = timedelta(minutes=5),
        schedules: Sequence[Schedule] = (),
    ) -> None:
        self.queue = queue
        self.registry = registry
        self.worker_id = worker_id or default_worker_id()
        self.lease = lease
        self.schedules = list(schedules)

    def run_once(self) -> int:
        """Enqueue what the schedules say is due, then process jobs until none is runnable;
        return how many attempts were run."""
        for schedule in self.schedules:
            try:
                schedule(self.queue.clock())
            except OperationalError:
                raise
            except Exception:
                log.exception("schedule failed; its jobs were not enqueued this pass")
        attempts = 0
        while (job := self.queue.claim(self.worker_id, self.lease)) is not None:
            self._attempt(job)
            attempts += 1
        return attempts

    def run_forever(self, stop: threading.Event, poll_seconds: float) -> None:
        """Process jobs until `stop` is set, polling every `poll_seconds` while idle.

        A database outage is logged and waited out; a job interrupted by it is reclaimed
        once its lease expires.
        """
        log.info("worker started", extra={"worker": self.worker_id})
        while not stop.is_set():
            try:
                busy = self.run_once() > 0
            except OperationalError as error:
                log.error(f"database unavailable: {_first_line(error)}")
                busy = False
            if not busy:
                stop.wait(poll_seconds)
        log.info("worker stopped", extra={"worker": self.worker_id})

    def _attempt(self, job: Job) -> None:
        context = {"job_id": str(job.id), "kind": job.kind, "attempt": job.attempts}
        handler = self.registry.get(job.kind)
        if handler is None:
            error = f"no handler registered for job kind {job.kind!r}"
            log.error(error, extra=context)
            self.queue.fail(job, self.worker_id, error, retry=False)
            return
        try:
            artifacts = handler(job) or {}
            json.dumps(artifacts)  # unserializable artifacts fail the attempt, not the worker
        except Requeue as error:
            # Not a failure: the job goes back to the queue with its attempt, nothing paused.
            log.info(f"job requeued: {error}", extra=context)
            self.queue.requeue(job, self.worker_id, f"{type(error).__name__}: {error}")
            return
        except Exception as error:
            message = f"{type(error).__name__}: {error}"
            failure_class = classify_failure(error)
            if failure_class is not None and self.registry.pausable(job.kind):
                # Quota or outage: not the job's fault. Pause, and requeue it untouched.
                pause, _ = self.queue.pause(
                    job, self.worker_id, message, failure_class, self.registry.pausable_kinds()
                )
                log.warning(
                    f"queue paused ({failure_class}) until {pause.resume_after}: {message}",
                    extra=context | {"pause_level": pause.level},
                )
                return
            log.exception("job attempt failed", extra=context)
            self.queue.fail(job, self.worker_id, message)
            return
        if self.queue.complete(job, self.worker_id, artifacts):
            log.info("job succeeded", extra=context)
            if self.registry.pausable(job.kind) and self.queue.clear_pause():
                log.info("queue pause cleared by a successful job", extra=context)
        else:
            log.warning("job lease lost before completion; result discarded", extra=context)


def _first_line(error: Exception) -> str:
    cause = getattr(error, "orig", None) or error
    return str(cause).strip().splitlines()[0] if str(cause).strip() else type(cause).__name__
