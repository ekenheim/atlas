"""Jobs: the Postgres-backed work queue, its handlers and the worker (spec Part A, Jobs).

`pacing` adds the queue-level pause on quota or outage failures and the nightly backfill
window (spec Part B, Job queue extensions).
"""

from atlas.jobs.handlers import (
    HandlerRegistry,
    JobHandler,
    Schedule,
    builtin_registry,
    builtin_schedules,
)
from atlas.jobs.pacing import (
    JOB_CLASSES,
    BackfillWindow,
    Clock,
    FailureClass,
    JobClass,
    Pacing,
    TransientFailure,
    classify_error_text,
    classify_failure,
    utc_now,
)
from atlas.jobs.queue import (
    Artifacts,
    Enqueued,
    Job,
    JobFailure,
    JobQueue,
    JobStatus,
    PendingJobs,
    QueuePause,
    job_id_for,
)
from atlas.jobs.worker import Worker

__all__ = [
    "JOB_CLASSES",
    "Artifacts",
    "BackfillWindow",
    "Clock",
    "Enqueued",
    "FailureClass",
    "HandlerRegistry",
    "Job",
    "JobClass",
    "JobFailure",
    "JobHandler",
    "JobQueue",
    "JobStatus",
    "Pacing",
    "PendingJobs",
    "QueuePause",
    "Schedule",
    "TransientFailure",
    "Worker",
    "builtin_registry",
    "builtin_schedules",
    "classify_error_text",
    "classify_failure",
    "job_id_for",
    "utc_now",
]
