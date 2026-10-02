"""A discovery: the Scout writes queries, SearXNG (and EDGAR full-text search) search them, and
the results become leads.

One `discover` job is one discovery, in its own run (kind `discovery`), or within a run the
caller names (an investigation's: that run's owner finishes it):

1. **Gaps.** The Bottlenecks mental model's content is the open gaps, passed to the Scout as
   quoted low-trust data, but only once Hindsight has refreshed it (before its first refresh
   it holds a placeholder). Its source is recorded as `mental-model:bottlenecks@<refreshed>`.
2. **Scout.** One Scout role call (atlas.roles.scout) turns the theme's research question and
   the gaps into queries. Code, not the model, keeps the first `max_queries` (≤ 10) distinct
   ones (compared case- and whitespace-insensitively); how many were proposed is recorded.
   With EDGAR full-text search on (atlas.discovery.edgar_fts; pilot fix 12), a query with a
   `filing_phrase` also gets an EDGAR search of that exact phrase in the filings of the
   window: the 18 months before the discovery's as-of time (an investigation's `as_of`, else
   now). Only a specific phrase is searched: at least two words, or a product or layer term
   of the lead-ranking config; any other is recorded as a `skipped` search with the reason
   and never sent (memory-directed reading, ticket 04).
3. **Search.** Each query is searched once with the named engines. A failed search is
   recorded on its query (with the error) and the others proceed; the engines SearXNG
   reports unresponsive are recorded on each query. Each query's results are stored in its
   own transaction as lead sightings, creating a lead per new canonical URL (atlas.discovery
   .leads). Then each EDGAR search runs the same way, its filing documents becoming
   `edgar_fts` leads of its query. If every search of both channels failed, the attempt
   fails (an ordinary failure: neither channel pauses the queue) and the retry searches the
   failed ones again, reusing the Scout's queries rather than asking it again. A search that
   returns nothing is not a failure.
4. **Finish.** The run, if the discovery started it, is finished with its token totals, and
   the discovery marked completed.

Nothing here creates Evidence: no Source Version, Assertion, memory document or retain job.
"""

import json
import re
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, Engine, RowMapping, text

from atlas.companies import ThemeConfig
from atlas.discovery.edgar_fts import (
    EdgarFullTextSearch,
    FilingSearchFailed,
    filing_phrases,
    filing_query,
)
from atlas.discovery.leads import store_filing, store_result
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
# EDGAR full-text search looks this many months back from the as-of time.
FILING_WINDOW_MONTHS = 18
_ERROR_TEXT_LIMIT = 500


class DiscoverPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    theme: str = Field(min_length=1)  # a theme in the universe config
    question: str = Field(min_length=1)  # the theme research question
    # An unfinished run to call the Scout within (its owner finishes it); else the job
    # starts and finishes its own.
    run_id: uuid.UUID | None = None


class DiscoveryFailed(Exception):
    """A discovery attempt couldn't search anything; the job retries it."""


class EdgarSearch(BaseModel):
    """A query's EDGAR full-text search (atlas.discovery.edgar_fts)."""

    query: str  # the `q` sent (or, skipped, not sent): each phrase in double quotes
    forms: list[str]
    start_date: date
    end_date: date
    # `skipped`: the filing phrase isn't specific enough to search (no request was made).
    status: Literal["pending", "searched", "failed", "skipped"]
    skip_reason: str | None  # why a skipped search was not made
    total_hits: int | None  # the documents EDGAR matched
    result_count: int | None  # of them, the ones kept (at most ATLAS_DISCOVERY_EDGAR_MAX_HITS)
    new_leads: int | None  # of those, canonical URLs never seen before
    error: str | None
    searched_at: datetime | None


class DiscoveryQuery(BaseModel):
    id: uuid.UUID
    position: int
    query: str
    purpose: str | None
    filing_phrase: str | None  # the exact phrase asked for in filings, as written
    # The supply-chain layer the Scout said the query concerns (memory-quality ticket 13); the
    # pointer recall asks the facts labelled with it too. None: no layer.
    layer: str | None = None
    status: Literal["pending", "searched", "failed"]
    result_count: int | None  # results SearXNG returned (web URLs or not)
    new_leads: int | None  # of them, canonical URLs never seen before
    unresponsive_engines: list[UnresponsiveEngine]
    error: str | None
    searched_at: datetime | None
    edgar: EdgarSearch | None  # its EDGAR full-text search, when it had one


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
        edgar: EdgarFullTextSearch | None = None,
    ) -> None:
        if not 1 <= max_queries <= 10:
            raise ValueError("a discovery searches 1 to 10 queries")
        self._engine = engine
        self._runs = runs
        self._caller = caller
        self._gateway = gateway
        self._searxng = searxng
        self._edgar = edgar
        self._max_queries = max_queries

    def discover(
        self,
        job: Job,
        theme_id: str,
        theme: ThemeConfig,
        question: str,
        *,
        run_id: uuid.UUID | None = None,
        as_of: datetime | None = None,
    ) -> Artifacts:
        """Run (or resume) the discovery of `job`; returns the job's artifacts.

        With `run_id`, the Scout calls within that unfinished run, which is left open for
        its owner to finish; else the discovery starts its own run and finishes it. `as_of`
        ends the EDGAR search window (default: now).
        """
        owned = run_id is None
        discovery_id, run_id, status = self._open(job, theme_id, question, run_id)
        try:
            if status == "scouting":
                self._scout(discovery_id, run_id, theme_id, theme, question, as_of)
            counts = run_searches(self._engine, discovery_id, self._searxng, self._edgar)
            if counts.failed_all:
                raise DiscoveryFailed(
                    f"every SearXNG search failed ({counts.failed} queries); the retry"
                    " searches them again"
                    if not counts.filing_failed
                    else f"every search failed ({counts.failed} SearXNG queries,"
                    f" {counts.filing_failed} EDGAR searches); the retry searches them again"
                )
        except Exception as error:
            self._set(discovery_id, "last_error = :error", error=_error_text(error))
            raise
        new_leads = self._finish(discovery_id, run_id, owned=owned)
        return {
            "discovery_id": str(discovery_id),
            "run_id": str(run_id),
            "queries": counts.searched + counts.failed,
            "searched": counts.searched,
            "failed": counts.failed,
            "filing_searches": counts.filing_searched + counts.filing_failed,
            "filing_searches_failed": counts.filing_failed,
            "filing_searches_skipped": counts.filing_skipped,
            "new_leads": new_leads,
        }

    def _open(
        self, job: Job, theme_id: str, question: str, run_id: uuid.UUID | None
    ) -> tuple[uuid.UUID, uuid.UUID, str]:
        with self._engine.connect() as connection:
            row = connection.execute(
                text("SELECT id, run_id, status FROM discovery WHERE job_id = :job"),
                {"job": job.id},
            ).one_or_none()
            if row is None and run_id is not None:
                open_run = connection.execute(
                    text("SELECT 1 FROM run WHERE id = :id AND finished_at IS NULL"),
                    {"id": run_id},
                ).one_or_none()
                if open_run is None:
                    raise DiscoveryFailed(f"no unfinished run {run_id} to discover in")
        if row is not None:
            return row.id, row.run_id, row.status
        run_id = run_id if run_id is not None else self._runs.start(RUN_KIND).id
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
                    "run": run_id,
                    "theme": theme_id,
                    "question": question,
                    "engines": self._searxng.engines,
                    "max": self._max_queries,
                },
            )
        return discovery_id, run_id, "scouting"

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
        as_of: datetime | None,
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
        window = filing_window(as_of)
        with self._engine.begin() as connection:
            role_call_id = connection.execute(
                text(
                    "SELECT id FROM role_call WHERE run_id = :run AND role = :role"
                    " AND status = 'accepted' ORDER BY started_at DESC, id LIMIT 1"
                ),
                {"run": run_id, "role": SCOUT.name},
            ).scalar_one()
            for position, query in enumerate(kept, start=1):
                add_query(
                    connection,
                    discovery_id,
                    position,
                    query.query,
                    query.purpose,
                    query.filing_phrase,
                    layer=query.layer,
                    edgar=self._edgar,
                    window=window,
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

    def _finish(self, discovery_id: uuid.UUID, run_id: uuid.UUID, *, owned: bool) -> int:
        """Finish the discovery (and its run, if it owns it); returns its new leads."""
        with self._engine.connect() as connection:
            usage = run_usage(connection, run_id)
            new_leads = connection.execute(
                text(
                    "SELECT coalesce(sum(new_leads), 0) FROM discovery_query"
                    " WHERE discovery_id = :discovery"
                ),
                {"discovery": discovery_id},
            ).scalar_one()
        if owned:
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


# --- queries and searches (shared with the Skeptic's discovery) ------------------------------


def _layer_names() -> frozenset[str]:
    """The Claim layer taxonomy's names (imported here: atlas.claims imports the research
    package, which loads beside this one)."""
    from atlas.claims import LAYER_NAMES

    return LAYER_NAMES


def months_before(day: date, months: int) -> date:
    """The same day `months` calendar months earlier (the month's last day if it is shorter)."""
    index = day.year * 12 + day.month - 1 - months
    year, month = divmod(index, 12)
    month += 1
    for last in (31, 30, 29, 28):
        try:
            return date(year, month, min(day.day, last))
        except ValueError:
            continue
    raise AssertionError("unreachable: every month has 28 days")  # pragma: no cover


def filing_window(as_of: datetime | None) -> tuple[date, date]:
    """The filing dates an EDGAR search covers: the `FILING_WINDOW_MONTHS` before `as_of`
    (default: now), in UTC."""
    end = (as_of or datetime.now(UTC)).astimezone(UTC).date()
    return months_before(end, FILING_WINDOW_MONTHS), end


def add_query(
    connection: Connection,
    discovery_id: uuid.UUID,
    position: int,
    query: str,
    purpose: str | None,
    filing_phrase: str | None,
    *,
    edgar: EdgarFullTextSearch | None,
    window: tuple[date, date],
    layer: str | None = None,
) -> None:
    """Add a query to a discovery, with its EDGAR search when the channel is on and the query
    has a filing phrase. A phrase that isn't specific enough (`edgar.skip_reason`: one word
    that is no product or layer term) is recorded as a `skipped` search with the reason, and
    never sent."""
    query_id = uuid.uuid4()
    connection.execute(
        text(
            "INSERT INTO discovery_query (id, discovery_id, position, query, purpose,"
            " filing_phrase, layer) VALUES (:id, :discovery, :position, :query, :purpose,"
            " :phrase, :layer)"
        ),
        {
            "id": query_id,
            "discovery": discovery_id,
            "position": position,
            "query": query,
            "purpose": purpose,
            "phrase": filing_phrase,
            # Only a name of the layer taxonomy is kept; anything else the model wrote is none.
            "layer": layer if layer is not None and layer in _layer_names() else None,
        },
    )
    phrases = filing_phrases(filing_phrase)
    if edgar is None or not phrases:
        return
    skip_reason = edgar.skip_reason(filing_phrase)
    connection.execute(
        text(
            "INSERT INTO edgar_search (discovery_query_id, query, forms, start_date, end_date,"
            " status, skip_reason) VALUES (:id, :query, :forms, :start, :end, :status, :reason)"
        ),
        {
            "id": query_id,
            "query": filing_query(phrases),
            "forms": list(edgar.forms),
            "start": window[0],
            "end": window[1],
            "status": "pending" if skip_reason is None else "skipped",
            "reason": skip_reason,
        },
    )


class SearchCounts(BaseModel):
    """A discovery's searches over all its queries, by channel and outcome."""

    searched: int  # SearXNG
    failed: int
    filing_searched: int  # EDGAR full-text search
    filing_failed: int
    filing_skipped: int = 0  # filing phrases not specific enough to search (never sent)

    @property
    def failed_all(self) -> bool:
        """Some search failed and none of either channel succeeded."""
        failed = self.failed + self.filing_failed
        return bool(failed) and not (self.searched + self.filing_searched)


def run_searches(
    engine: Engine,
    discovery_id: uuid.UUID,
    searxng: SearXNGClient,
    edgar: EdgarFullTextSearch | None,
) -> SearchCounts:
    """Search every query (SearXNG) and EDGAR search not yet searched, each stored in its own
    transaction (a failure recorded on it, the others proceeding); the counts over all."""
    with engine.connect() as connection:
        pending = connection.execute(
            text(
                "SELECT id, query FROM discovery_query WHERE discovery_id = :discovery"
                " AND status <> 'searched' ORDER BY position"
            ),
            {"discovery": discovery_id},
        ).all()
    for query_id, query in pending:
        try:
            response = searxng.search(query)
        except SearchFailed as error:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE discovery_query SET status = 'failed', error = :error,"
                        " searched_at = now() WHERE id = :id"
                    ),
                    {"id": query_id, "error": _error_text(error)},
                )
            continue
        with engine.begin() as connection:
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
    if edgar is not None:
        _search_filings(engine, discovery_id, edgar)
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT 'searxng', status, count(*) FROM discovery_query"
                " WHERE discovery_id = :discovery GROUP BY status"
                " UNION ALL SELECT 'edgar', e.status, count(*) FROM edgar_search e"
                " JOIN discovery_query q ON q.id = e.discovery_query_id"
                " WHERE q.discovery_id = :discovery GROUP BY e.status"
            ),
            {"discovery": discovery_id},
        ).all()
    counts: dict[tuple[str, str], int] = {(channel, status): n for channel, status, n in rows}
    return SearchCounts(
        searched=counts.get(("searxng", "searched"), 0),
        failed=counts.get(("searxng", "failed"), 0),
        filing_searched=counts.get(("edgar", "searched"), 0),
        filing_failed=counts.get(("edgar", "failed"), 0),
        filing_skipped=counts.get(("edgar", "skipped"), 0),
    )


def _search_filings(engine: Engine, discovery_id: uuid.UUID, edgar: EdgarFullTextSearch) -> None:
    with engine.connect() as connection:
        pending = connection.execute(
            text(
                "SELECT e.discovery_query_id, e.query, e.start_date, e.end_date"
                " FROM edgar_search e JOIN discovery_query q ON q.id = e.discovery_query_id"
                " WHERE q.discovery_id = :discovery AND e.status IN ('pending', 'failed')"
                " ORDER BY q.position"
            ),
            {"discovery": discovery_id},
        ).all()
    for query_id, query, start, end in pending:
        try:
            found = edgar.search(filing_phrases(query), start=start, end=end)
        except FilingSearchFailed as error:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE edgar_search SET status = 'failed', error = :error,"
                        " searched_at = now() WHERE discovery_query_id = :id"
                    ),
                    {"id": query_id, "error": _error_text(error)},
                )
            continue
        with engine.begin() as connection:
            created = [store_filing(connection, query_id, found.query, hit) for hit in found.hits]
            connection.execute(
                text(
                    "UPDATE edgar_search SET status = 'searched', error = NULL,"
                    " total_hits = :total, result_count = :results, new_leads = :new,"
                    " searched_at = now() WHERE discovery_query_id = :id"
                ),
                {
                    "id": query_id,
                    "total": found.total,
                    "results": len(found.hits),
                    "new": sum(1 for each in created if each),
                },
            )


_SPACE = re.compile(r"\s+")


def _distinct(queries: Sequence[ScoutQuery]) -> list[ScoutQuery]:
    """The non-blank queries, stripped, each first occurrence only (ignoring case and spacing)."""
    seen: set[str] = set()
    kept: list[ScoutQuery] = []
    for each in queries:
        query = _SPACE.sub(" ", each.query).strip()
        key = query.casefold()
        if query and key not in seen:
            seen.add(key)
            kept.append(
                ScoutQuery(
                    query=query,
                    purpose=each.purpose,
                    filing_phrase=each.filing_phrase,
                    layer=each.layer,
                )
            )
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
            "SELECT q.*, e.query AS edgar_query, e.forms AS edgar_forms,"
            " e.start_date AS edgar_start_date, e.end_date AS edgar_end_date,"
            " e.status AS edgar_status, e.skip_reason AS edgar_skip_reason,"
            " e.total_hits AS edgar_total_hits,"
            " e.result_count AS edgar_result_count, e.new_leads AS edgar_new_leads,"
            " e.error AS edgar_error, e.searched_at AS edgar_searched_at"
            " FROM discovery_query q LEFT JOIN edgar_search e ON e.discovery_query_id = q.id"
            " WHERE q.discovery_id = ANY(:ids) ORDER BY q.discovery_id, q.position"
        ),
        {"ids": discovery_ids},
    ).mappings()
    for row in rows:
        fields = {k: v for k, v in row.items() if not k.startswith("edgar_")}
        edgar = None
        if row["edgar_query"] is not None:
            edgar = EdgarSearch.model_validate(
                {k.removeprefix("edgar_"): v for k, v in row.items() if k.startswith("edgar_")}
            )
        found[row["discovery_id"]].append(DiscoveryQuery.model_validate(fields | {"edgar": edgar}))
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
