"""Prometheus metrics read from the database at scrape time (spec Part B stories 34-35).

The worker runs in its own process without an HTTP server, so what it does is counted from
the rows it leaves: the API's `/metrics` reads the queue, the pause, the Hindsight operations
and the memory documents on each scrape. Counters are counts of rows in terminal states,
which never leave them, so they only grow. If the database can't be read, only
`atlas_state_metrics_up 0` is reported. Alert rules: `configs/prometheus/atlas-alerts.yaml`.
"""

from collections.abc import Iterator

from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily, Metric
from prometheus_client.registry import Collector
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import SQLAlchemyError

from atlas.jobs import JobQueue

# Final retain states of a section: they never change again.
_FINAL_SECTION_STATES = ("completed", "zero_fact", "failed", "linked")


class StateCollector(Collector):
    def __init__(self, engine: Engine, queue: JobQueue) -> None:
        self._engine = engine
        self._queue = queue

    def collect(self) -> Iterator[Metric]:
        up = GaugeMetricFamily(
            "atlas_state_metrics_up", "1 if the database-derived metrics could be read"
        )
        try:
            families = list(self._families())
        except SQLAlchemyError:
            up.add_metric([], 0)
            yield up
            return
        up.add_metric([], 1)
        yield up
        yield from families

    def _families(self) -> Iterator[Metric]:
        yield from self._pause()
        with self._engine.connect() as connection:
            yield from self._jobs(connection)
            yield from self._operations(connection)
            yield from self._sections(connection)

    def _pause(self) -> Iterator[Metric]:
        pause = self._queue.pause_state()
        now = self._queue.clock()
        pending = self._queue.pending()
        held = any(p.kind in pause.kinds and p.status == "queued" for p in pending)
        paused = GaugeMetricFamily(
            "atlas_queue_paused", "1 while the queue pause holds back its job kinds"
        )
        paused.add_metric([], 1 if pause.paused else 0)
        yield paused
        level = GaugeMetricFamily(
            "atlas_queue_pause_level", "Pauses entered since the last success of a pausable job"
        )
        level.add_metric([], pause.level)
        yield level
        backoff = GaugeMetricFamily(
            "atlas_queue_pause_backoff_seconds", "The current pause's backoff (0 when clear)"
        )
        backoff.add_metric([], (pause.backoff_seconds or 0) if pause.level else 0)
        yield backoff
        duration = GaugeMetricFamily(
            "atlas_queue_pause_duration_seconds",
            "How long the current run of pauses has held back queued jobs (0 when clear"
            " or when nothing of a paused kind is queued)",
        )
        since = pause.since
        duration.add_metric([], (now - since).total_seconds() if since and held else 0)
        yield duration
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT error_class, count(*) FROM queue_pause_event"
                    " GROUP BY error_class ORDER BY error_class"
                )
            ).all()
        pauses = CounterMetricFamily(
            "atlas_queue_pauses", "Queue pauses entered, by failure class", labels=["error_class"]
        )
        counts = {"quota": 0, "unavailable": 0} | {row[0]: row[1] for row in rows}
        for error_class, count in sorted(counts.items()):
            pauses.add_metric([error_class], count)
        yield pauses
        depth = GaugeMetricFamily(
            "atlas_queue_jobs",
            "Unfinished jobs (queue depth) by kind, class and status",
            labels=["kind", "job_class", "status"],
        )
        for group in pending:
            depth.add_metric([group.kind, group.job_class, group.status], group.count)
        yield depth

    def _jobs(self, connection: Connection) -> Iterator[Metric]:
        failed = CounterMetricFamily(
            "atlas_jobs_failed", "Jobs that failed with their retries exhausted", labels=["kind"]
        )
        # Every kind with jobs gets a sample, so the counter exists before its first failure.
        for kind, count in connection.execute(
            text(
                "SELECT kind, count(*) FILTER (WHERE status = 'failed') FROM job"
                " GROUP BY kind ORDER BY 1"
            )
        ).all():
            failed.add_metric([kind], count)
        yield failed

    def _operations(self, connection: Connection) -> Iterator[Metric]:
        operations = CounterMetricFamily(
            "atlas_hindsight_operations",
            "Hindsight operations that reached a terminal status, by kind, status and the"
            " failure's class (none for a completed operation)",
            labels=["kind", "status", "error_class"],
        )
        for kind, status, error_class, count in connection.execute(
            text(
                "SELECT kind, status, coalesce(error_class, 'none'), count(*)"
                " FROM hindsight_operation WHERE completed_at IS NOT NULL"
                " GROUP BY 1, 2, 3 ORDER BY 1, 2, 3"
            )
        ).all():
            operations.add_metric([kind, status, error_class], count)
        yield operations

    def _sections(self, connection: Connection) -> Iterator[Metric]:
        counts: dict[str, int] = {
            state: count
            for state, count in connection.execute(
                text("SELECT retain_state, count(*) FROM memory_document GROUP BY 1")
            ).all()
        }
        retained = CounterMetricFamily(
            "atlas_retained_sections",
            "Sections retained into memory, by final outcome",
            labels=["outcome"],
        )
        for state in _FINAL_SECTION_STATES:
            retained.add_metric([state], counts.get(state, 0))
        yield retained
        zero = CounterMetricFamily(
            "atlas_zero_fact_sections",
            "Sections flagged zero_fact: no facts extracted even after their one reprocess",
        )
        zero.add_metric([], counts.get("zero_fact", 0))
        yield zero
        pending = GaugeMetricFamily(
            "atlas_memory_sections_pending", "Sections awaiting their retain's outcome"
        )
        pending.add_metric([], counts.get("pending", 0))
        yield pending
