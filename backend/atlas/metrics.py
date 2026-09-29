"""Prometheus metrics read from the database at scrape time (spec Part A story 8, Part B
stories 34-35).

The worker runs in its own process without an HTTP server, so what it does is counted from
the rows it leaves: the API's `/metrics` reads the ledger (fetches, parses, archive writes),
the queue (job retries), the pause, the Hindsight operations, the memory documents, the
research answers and the runs on each scrape. Counters are counts (or sums) over rows in
terminal states, which never leave them, and over append-only rows, so they only grow. If
the database can't be read, only `atlas_state_metrics_up 0` is reported. Recall runs in the
API, so its latency is an in-process histogram (`recall_latency`). Alert rules:
`configs/prometheus/atlas-alerts.yaml`.
"""

from collections.abc import Iterator

from prometheus_client import CollectorRegistry, Histogram
from prometheus_client.core import (
    CounterMetricFamily,
    GaugeMetricFamily,
    HistogramMetricFamily,
    Metric,
)
from prometheus_client.registry import Collector
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import SQLAlchemyError

from atlas.jobs import JobQueue

# Final retain states of a section: they never change again.
_FINAL_SECTION_STATES = ("completed", "zero_fact", "failed", "linked")
_FETCH_OUTCOMES = ("new_version", "unchanged", "not_modified")
_PARSE_STATUSES = ("parsed", "incomplete", "failed", "unsupported", "not_applicable")
# Seconds; a reflect is a job, so its latency includes the wait in the queue.
_REFLECT_BUCKETS = (5.0, 15.0, 30.0, 60.0, 120.0, 300.0, 600.0, 1800.0, 3600.0)
_RECALL_BUCKETS = (0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0)
RECALL_OUTCOMES = ("ok", "refused", "error")


def recall_latency(registry: CollectorRegistry) -> Histogram:
    """The API's recall latency histogram, by outcome (ok, refused before Hindsight, error)."""
    histogram = Histogram(
        "atlas_recall_latency_seconds",
        "Seconds to answer a recall request, by outcome",
        ["outcome"],
        registry=registry,
        buckets=_RECALL_BUCKETS,
    )
    for outcome in RECALL_OUTCOMES:
        histogram.labels(outcome)  # every outcome is exposed before its first observation
    return histogram


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
            yield from self._ledger(connection)
            yield from self._jobs(connection)
            yield from self._operations(connection)
            yield from self._sections(connection)
            yield from self._research(connection)

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

    def _ledger(self, connection: Connection) -> Iterator[Metric]:
        fetches = CounterMetricFamily(
            "atlas_fetches",
            "Source fetches recorded in the ledger, by outcome (a failed fetch records nothing"
            " and fails its ingest job: atlas_jobs_failed_total, atlas_job_retries_total)",
            labels=["outcome"],
        )
        by_outcome: dict[str, int] = {
            outcome: count
            for outcome, count in connection.execute(
                text("SELECT outcome, count(*) FROM fetch_observation GROUP BY 1")
            ).all()
        }
        for outcome in _FETCH_OUTCOMES:
            fetches.add_metric([outcome], by_outcome.get(outcome, 0))
        yield fetches
        retries = CounterMetricFamily(
            "atlas_fetch_retries",
            "HTTP retries (429, 5xx, timeouts) behind the fetches recorded in the ledger",
        )
        retries.add_metric(
            [],
            connection.execute(
                text("SELECT coalesce(sum(attempts - 1), 0) FROM fetch_observation")
            ).scalar_one(),
        )
        yield retries
        parses = CounterMetricFamily(
            "atlas_parses",
            "Source Versions by parse outcome (not_applicable: a format Atlas doesn't parse)",
            labels=["status"],
        )
        by_status: dict[str, int] = {
            status: count
            for status, count in connection.execute(
                text("SELECT parse_status, count(*) FROM source_version GROUP BY 1")
            ).all()
        }
        for status in _PARSE_STATUSES:
            parses.add_metric([status], by_status.get(status, 0))
        yield parses
        writes = CounterMetricFamily(
            "atlas_archive_writes",
            "Objects written to the content-addressed archive, by namespace (each distinct"
            " object the ledger references; an identical put writes nothing new)",
            labels=["namespace"],
        )
        raw, parsed = connection.execute(
            text(
                "SELECT (SELECT count(*) FROM (SELECT object_uri FROM source_version"
                "   UNION SELECT object_uri FROM fetch_observation"
                "   WHERE object_uri IS NOT NULL) raw),"
                " (SELECT count(DISTINCT parsed_object_uri) FROM source_version)"
            )
        ).one()
        writes.add_metric(["raw"], raw)
        writes.add_metric(["parsed"], parsed)
        yield writes

    def _jobs(self, connection: Connection) -> Iterator[Metric]:
        failed = CounterMetricFamily(
            "atlas_jobs_failed", "Jobs that failed with their retries exhausted", labels=["kind"]
        )
        retries = CounterMetricFamily(
            "atlas_job_retries",
            "Failed job attempts that were retried (requeued), including those a queue pause"
            " requeued, by kind",
            labels=["kind"],
        )
        # Every kind with jobs gets a sample, so the counters exist before their first event.
        # A job's failures list gains one entry per failed attempt; all but a failed job's
        # last were followed by another attempt.
        for kind, failed_count, retried in connection.execute(
            text(
                "SELECT kind, count(*) FILTER (WHERE status = 'failed'),"
                " coalesce(sum(jsonb_array_length(failures)), 0)"
                "   - count(*) FILTER (WHERE status = 'failed')"
                " FROM job GROUP BY kind ORDER BY 1"
            )
        ).all():
            failed.add_metric([kind], failed_count)
            retries.add_metric([kind], retried)
        yield failed
        yield retries

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

    def _research(self, connection: Connection) -> Iterator[Metric]:
        buckets = ", ".join(
            f"count(*) FILTER (WHERE latency <= {bound})" for bound in _REFLECT_BUCKETS
        )
        row = connection.execute(
            text(
                f"SELECT {buckets}, count(*), coalesce(sum(latency), 0) FROM ("  # noqa: S608 (constant bounds)
                "   SELECT extract(epoch FROM answered_at - created_at) AS latency"
                "   FROM research_answer WHERE answered_at IS NOT NULL) answered"
            )
        ).one()
        counts = list(row)
        reflect = HistogramMetricFamily(
            "atlas_reflect_latency_seconds",
            "Seconds from a reflect request to its stored answer (queue wait included)",
            buckets=[
                *((str(bound), counts[i]) for i, bound in enumerate(_REFLECT_BUCKETS)),
                ("+Inf", counts[len(_REFLECT_BUCKETS)]),
            ],
            sum_value=float(counts[-1]),
        )
        yield reflect
        tokens = CounterMetricFamily(
            "atlas_llm_tokens",
            "LLM tokens used, by the work that used them and direction: runs (reflect,"
            " refresh_mental_model) record input and output; Hindsight reports a retain or"
            " reprocess operation's total only",
            labels=["kind", "direction"],
        )
        for kind, direction, total in connection.execute(
            text(
                "SELECT kind, 'input', sum(tokens_in) FROM run WHERE finished_at IS NOT NULL"
                " GROUP BY kind"
                " UNION ALL SELECT kind, 'output', sum(tokens_out) FROM run"
                " WHERE finished_at IS NOT NULL GROUP BY kind"
                " UNION ALL SELECT kind, 'total',"
                " sum(coalesce((result_metadata ->> 'total_tokens')::bigint, 0))"
                " FROM hindsight_operation WHERE completed_at IS NOT NULL GROUP BY kind"
                " ORDER BY 1, 2"
            )
        ).all():
            tokens.add_metric([kind, direction], total)
        yield tokens
