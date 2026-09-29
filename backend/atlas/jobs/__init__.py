"""Jobs: the Postgres-backed work queue, its handlers and the worker (spec Part A, Jobs).

`pacing` adds the queue-level pause on quota or outage failures and the backfill window
(spec Part B, Job queue extensions); `budget` the rolling-window provider budgets (ticket 27).
"""

from atlas.jobs.budget import (
    PROVIDER_KINDS,
    PROVIDERS,
    Budgets,
    Provider,
    ProviderBudget,
    provider_of,
)
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
    Requeue,
    TransientFailure,
    classify_error_text,
    classify_failure,
    utc_now,
)
from atlas.jobs.queue import (
    Artifacts,
    Enqueued,
    HeldJobs,
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
    "PROVIDERS",
    "PROVIDER_KINDS",
    "Artifacts",
    "BackfillWindow",
    "Budgets",
    "Clock",
    "Enqueued",
    "FailureClass",
    "HandlerRegistry",
    "HeldJobs",
    "Job",
    "JobClass",
    "JobFailure",
    "JobHandler",
    "JobQueue",
    "JobStatus",
    "Pacing",
    "PendingJobs",
    "Provider",
    "ProviderBudget",
    "QueuePause",
    "Requeue",
    "Schedule",
    "TransientFailure",
    "Worker",
    "builtin_registry",
    "builtin_schedules",
    "classify_error_text",
    "classify_failure",
    "job_id_for",
    "provider_of",
    "utc_now",
]
