"""A discovery: the Scout writes queries, SearXNG searches them, and the results become leads.

One `discover` job is one discovery, in its own run (kind `discovery`):

1. **Gaps.** The Bottlenecks mental model's content is the open gaps, passed to the Scout as
   quoted low-trust data, but only once Hindsight has refreshed it (before its first refresh
   it holds a placeholder). Its source is recorded as `mental-model:bottlenecks@<refreshed>`.
2. **Scout.** One Scout role call (atlas.roles.scout) turns the theme's research question and
   the gaps into queries. Code, not the model, keeps the first `max_queries` (≤ 10) distinct
   ones (compared case- and whitespace-insensitively); how many were proposed is recorded.
3. **Search.** Each query is searched once with the named engines. A failed search is
   recorded on its query (with the error) and the others proceed; the engines SearXNG
   reports unresponsive are recorded on each query. Each query's results are stored in its
   own transaction as lead sightings, creating a lead per new canonical URL (atlas.discovery
   .leads). If every search failed, the attempt fails (an ordinary failure: SearXNG never
   pauses the queue) and the retry searches the failed queries again, reusing the Scout's
   queries rather than asking it again.
4. **Finish.** The run is finished with its token totals and the discovery marked completed.

Nothing here creates Evidence: no Source Version, Assertion, memory document or retain job.
"""

import json
import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, Engine, RowMapping, text

from atlas.companies import ThemeConfig
from atlas.discovery.leads import store_result
from atlas.discovery.searxng import SearchFailed, SearXNGClient, UnresponsiveEngine
from atlas.hindsight import HindsightGateway, HindsightNotFound
from atlas.jobs.queue import Artifacts, Job
from atlas.roles import QuotedText, RoleCaller, run_usage
from atlas.roles.scout import SCOUT, ScoutQuery, ScoutRequest
from atlas.runs import RunRecorder

DISCOVER_KIND = "discover"
RUN_KIND = "discovery"
# The mental model whose content names the open gaps (the bank template's Bottlenecks).
GAPS_MENTAL_MODEL = "bottlenecks"
_ERROR_TEXT_LIMIT = 500


class DiscoverPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    theme: str = Field(min_length=1)  # a theme in the universe config
    question: str = Field(min_length=1)  # the theme research question


class DiscoveryFailed(Exception):
    """A discovery attempt couldn't search anything; the job retries it."""


class DiscoveryQuery(BaseModel):
    id: uuid.UUID
    position: int
    query: str
    purpose: str | None
    status: Literal["pending", "searched", "failed"]
    result_count: int | None  # results SearXNG returned (web URLs or not)
    new_leads: int | None  # of them, canonical URLs never seen before
    unresponsive_engines: list[UnresponsiveEngine]
    error: str | None
    searched_at: datetime | None


class Discovery(BaseModel):
    id: uuid.UUID
    job_id: uuid.UUID | None
    run_id: uuid.UUID
    theme: str
    question: str
    engines: list[str]
    max_queries: int
    gaps_source: str | None  # where the open gaps came from; None: no gaps were sent
    queries_proposed: int | None  # how many queries the Scout wrote (None: not yet)
    status: Literal["scouting", "searching", "completed"]
    last_error: str | None  # the latest failed attempt's error, kept after a retry succeeds
    started_at: datetime
    finished_at: datetime | None
    queries: list[DiscoveryQuery]


class Scout:
    """Runs discoveries (see the module) with the given clients, all owned by the caller."""

    def __init__(
        self,
        engine: Engine,
        runs: RunRecorder,
        caller: RoleCaller,
        gateway: HindsightGateway,
        searxng: SearXNGClient,
        *,
        max_queries: int,
    ) -> None:
        if not 1 <= max_queries <= 10:
            raise ValueError("a discovery searches 1 to 10 queries")
        self._engine = engine
        self._runs = runs
        self._caller = caller
        self._gateway = gateway
        self._searxng = searxng
        self._max_queries = max_queries

    def discover(self, job: Job, theme_id: str, theme: ThemeConfig, question: str) -> Artifacts:
        """Run (or resume) the discovery of `job`; returns the job's artifacts."""
        discovery_id, run_id, status = self._open(job, theme_id, question)
        try:
            if status == "scouting":
                self._scout(discovery_id, run_id, theme_id, theme, question)
            searched, failed = self._search(discovery_id)
            if failed and not searched:
                raise DiscoveryFailed(
                    f"every SearXNG search failed ({failed} queries); the retry searches them again"
                )
        except Exception as error:
            self._set(discovery_id, "last_error = :error", error=_error_text(error))
            raise
        new_leads = self._finish(discovery_id, run_id)
        return {
            "discovery_id": str(discovery_id),
            "run_id": str(run_id),
            "queries": searched + failed,
            "searched": searched,
            "failed": failed,
            "new_leads": new_leads,
        }

    def _open(self, job: Job, theme_id: str, question: str) -> tuple[uuid.UUID, uuid.UUID, str]:
        with self._engine.connect() as connection:
            row = connection.execute(
                text("SELECT id, run_id, status FROM discovery WHERE job_id = :job"),
                {"job": job.id},
            ).one_or_none()
        if row is not None:
            return row.id, row.run_id, row.status
        run = self._runs.start(RUN_KIND)
        discovery_id = uuid.uuid4()
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO discovery (id, job_id, run_id, theme, question, engines,"
                    " max_queries) VALUES (:id, :job, :run, :theme, :question, :engines, :max)"
                ),
                {
                    "id": discovery_id,
                    "job": job.id,
                    "run": run.id,
                    "theme": theme_id,
                    "question": question,
                    "engines": self._searxng.engines,
                    "max": self._max_queries,
                },
            )
        return discovery_id, run.id, "scouting"

    def _gaps(self) -> tuple[list[QuotedText], str | None]:
        """The Bottlenecks model's content as quoted data, once Hindsight has refreshed it."""
        try:
            model = self._gateway.get_mental_model(GAPS_MENTAL_MODEL)
        except HindsightNotFound:
            return [], None
        if model.last_refreshed_at is None or not (model.content or "").strip():
            return [], None
        source = f"mental-model:{GAPS_MENTAL_MODEL}"
        quoted = QuotedText(id=GAPS_MENTAL_MODEL, source=source, text=model.content or "")
        return [quoted], f"{source}@{model.last_refreshed_at.isoformat()}"

    def _scout(
        self,
        discovery_id: uuid.UUID,
        run_id: uuid.UUID,
        theme_id: str,
        theme: ThemeConfig,
        question: str,
    ) -> None:
        gaps, gaps_source = self._gaps()
        request = ScoutRequest(
            theme_id=theme_id,
            theme_title=theme.title,
            theme_description=theme.description,
            research_question=question,
            max_queries=self._max_queries,
        )
        answer = self._caller.call(SCOUT, request, run_id=run_id, retrieved=gaps)
        kept = _distinct(answer.queries)[: self._max_queries]
        with self._engine.begin() as connection:
            role_call_id = connection.execute(
                text(
                    "SELECT id FROM role_call WHERE run_id = :run AND role = :role"
                    " AND status = 'accepted' ORDER BY started_at DESC, id LIMIT 1"
                ),
                {"run": run_id, "role": SCOUT.name},
            ).scalar_one()
            for position, query in enumerate(kept, start=1):
                connection.execute(
                    text(
                        "INSERT INTO discovery_query (id, discovery_id, position, query, purpose)"
                        " VALUES (:id, :discovery, :position, :query, :purpose)"
                    ),
                    {
                        "id": uuid.uuid4(),
                        "discovery": discovery_id,
                        "position": position,
                        "query": query.query,
                        "purpose": query.purpose,
                    },
                )
            _update(
                connection,
                discovery_id,
                "status = 'searching', gaps_source = :gaps, queries_proposed = :proposed,"
                " scout_role_call_id = :role_call",
                gaps=gaps_source,
                proposed=len(answer.queries),
                role_call=role_call_id,
            )

    def _search(self, discovery_id: uuid.UUID) -> tuple[int, int]:
        """Search every query not yet searched; returns (searched, failed) over all queries."""
        with self._engine.connect() as connection:
            pending = connection.execute(
                text(
                    "SELECT id, query FROM discovery_query WHERE discovery_id = :discovery"
                    " AND status <> 'searched' ORDER BY position"
                ),
                {"discovery": discovery_id},
            ).all()
        for query_id, query in pending:
            try:
                response = self._searxng.search(query)
            except SearchFailed as error:
                with self._engine.begin() as connection:
                    connection.execute(
                        text(
                            "UPDATE discovery_query SET status = 'failed', error = :error,"
                            " searched_at = now() WHERE id = :id"
                        ),
                        {"id": query_id, "error": _error_text(error)},
                    )
                continue
            with self._engine.begin() as connection:
                created = [store_result(connection, query_id, r) for r in response.results]
                connection.execute(
                    text(
                        "UPDATE discovery_query SET status = 'searched', error = NULL,"
                        " result_count = :results, new_leads = :new,"
                        " unresponsive_engines = CAST(:unresponsive AS jsonb),"
                        " searched_at = now() WHERE id = :id"
                    ),
                    {
                        "id": query_id,
                        "results": len(response.results),
                        "new": sum(1 for each in created if each),
                        "unresponsive": json.dumps(
                            [e.model_dump() for e in response.unresponsive_engines]
                        ),
                    },
                )
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT status, count(*) FROM discovery_query"
                    " WHERE discovery_id = :discovery GROUP BY status"
                ),
                {"discovery": discovery_id},
            ).all()
        counts: dict[str, int] = {status: count for status, count in rows}
        return counts.get("searched", 0), counts.get("failed", 0)

    def _finish(self, discovery_id: uuid.UUID, run_id: uuid.UUID) -> int:
        """Finish the run and the discovery; returns how many new leads it found."""
        with self._engine.connect() as connection:
            usage = run_usage(connection, run_id)
            new_leads = connection.execute(
                text(
                    "SELECT coalesce(sum(new_leads), 0) FROM discovery_query"
                    " WHERE discovery_id = :discovery"
                ),
                {"discovery": discovery_id},
            ).scalar_one()
        self._runs.finish(run_id, tokens_in=usage.tokens_in, tokens_out=usage.tokens_out)
        self._set(discovery_id, "status = 'completed', finished_at = now()")
        return int(new_leads)

    def _set(self, discovery_id: uuid.UUID, assignments: str, **values: object) -> None:
        with self._engine.begin() as connection:
            _update(connection, discovery_id, assignments, **values)


def _update(
    connection: Connection, discovery_id: uuid.UUID, assignments: str, **values: object
) -> None:
    connection.execute(
        text(f"UPDATE discovery SET {assignments} WHERE id = :id"),  # noqa: S608 (constant SQL)
        {"id": discovery_id, **values},
    )


_SPACE = re.compile(r"\s+")


def _distinct(queries: list[ScoutQuery]) -> list[ScoutQuery]:
    """The non-blank queries, stripped, each first occurrence only (ignoring case and spacing)."""
    seen: set[str] = set()
    kept: list[ScoutQuery] = []
    for each in queries:
        query = _SPACE.sub(" ", each.query).strip()
        key = query.casefold()
        if query and key not in seen:
            seen.add(key)
            kept.append(ScoutQuery(query=query, purpose=each.purpose))
    return kept


def _error_text(error: BaseException) -> str:
    return f"{type(error).__name__}: {error}"[:_ERROR_TEXT_LIMIT]


# --- the read side -------------------------------------------------------------------------------


def _discovery(row: RowMapping, queries: list[DiscoveryQuery]) -> Discovery:
    return Discovery.model_validate(dict(row) | {"queries": queries})


def _queries(
    connection: Connection, discovery_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[DiscoveryQuery]]:
    found: dict[uuid.UUID, list[DiscoveryQuery]] = {each: [] for each in discovery_ids}
    if not discovery_ids:
        return found
    rows = connection.execute(
        text(
            "SELECT * FROM discovery_query WHERE discovery_id = ANY(:ids)"
            " ORDER BY discovery_id, position"
        ),
        {"ids": discovery_ids},
    ).mappings()
    for row in rows:
        found[row["discovery_id"]].append(DiscoveryQuery.model_validate(dict(row)))
    return found


def get_discovery(connection: Connection, discovery_id: uuid.UUID) -> Discovery | None:
    row = (
        connection.execute(text("SELECT * FROM discovery WHERE id = :id"), {"id": discovery_id})
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    return _discovery(row, _queries(connection, [discovery_id])[discovery_id])


def list_discoveries(
    connection: Connection, *, limit: int, offset: int
) -> tuple[list[Discovery], int]:
    """Discoveries, newest first, with their queries; and how many there are in all."""
    total = connection.execute(text("SELECT count(*) FROM discovery")).scalar_one()
    rows = (
        connection.execute(
            text(
                "SELECT * FROM discovery ORDER BY started_at DESC, id LIMIT :limit OFFSET :offset"
            ),
            {"limit": limit, "offset": offset},
        )
        .mappings()
        .all()
    )
    queries = _queries(connection, [row["id"] for row in rows])
    return [_discovery(row, queries[row["id"]]) for row in rows], int(total)
