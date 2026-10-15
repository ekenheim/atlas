"""The `scan_signals` job: archive bottleneck signals stored as leads (atlas-beliefs ticket 18;
`docs/decisions.md`, "Archive signals are leads").

The job reads the parsed text of Source Versions with the scorer of `atlas.discovery.signals`
and stores each sentence that scores as a Tier C lead of origin `archive_signal` (where to look,
never Evidence) with its quote, span, company, cue families and score. It calls no LLM and no
Hindsight, so it is not pausable and no budget holds it; the worker enqueues it daily
(`ATLAS_SIGNAL_SCAN_AT`, backfill class).

- **Which versions.** By default the Source Versions **ingested since the last scan** (the
  latest `signal_scan` run of this kind: `until`), up to `ATLAS_SIGNAL_SCAN_LAG_SECONDS` (ten
  minutes) before now so a version whose transaction is still open is not passed over; the
  first scan reads the whole archive.
  `source_version_ids` scans those versions; `since` the versions public (effective
  availability) from that time on; `company` (a slug) narrows either. Only the first kind moves
  the pointer. A version is read through its current parse (`atlas.ledger.current_parse`), in
  English, of a researched company, and an XBRL companyfacts document has no text.
- **Once per span.** A hit is identified by its Source Version, parser version and span
  (code points into that parse), so a rerun stores nothing twice. A sentence a company's earlier
  document already holds as a hit (the same words, whitespace and case aside) is a **repeat**:
  not stored again, counted. The earlier document keeps the lead; the later one's quarterly
  restatement of a statement is not news.
- **The lead.** Its `url` is the document's, its title the document's title, its snippet the
  sentence; the lead's own `canonical_url` is the document's plus a fragment naming the version
  and span. `GET /api/v1/leads?origin=archive_signal` reads them ranked by score.
- **As-of.** A lead is a pure function of an archived document, so for this origin the bound
  `known_by` is when the document became public (its effective availability), not when the scan
  ran: a scan today over a 2025 call gives a lead a session at 2025-08-31 may see.
- **Audit.** One `signal_scan.recorded` event per run, with the run's counts.
"""

import hashlib
import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, JsonValue
from sqlalchemy import Connection, Engine, text

from atlas.archive import Archive, open_archive
from atlas.audit import Actor, content_hash, record
from atlas.claims.predicates import company_names
from atlas.companies import extend_universe, load_universe
from atlas.db import create_engine
from atlas.discovery.signals import (
    SCORER_VERSION,
    SignalHit,
    SignalScorer,
    load_signals_config,
)
from atlas.jobs.handlers import HandlerRegistry, Schedule
from atlas.jobs.pacing import Clock, FailedWithArtifacts, utc_now
from atlas.jobs.queue import Artifacts, Enqueued, Job, JobQueue
from atlas.ledger.reads import current_parse
from atlas.settings import Settings

SCAN_KIND = "scan_signals"
_WITH_TEXT = ("parsed", "incomplete")
_SPACES = re.compile(r"\s+")


class ScanPayload(BaseModel):
    """What to scan: nothing (the versions ingested since the last scan), or a selection."""

    model_config = ConfigDict(extra="forbid")

    since: AwareDatetime | None = None  # versions public from this time on
    source_version_ids: list[uuid.UUID] | None = None  # only these versions
    company: str | None = None  # only this company's (a slug)


def scan_key(day: str) -> str:
    return f"{SCAN_KIND}:{day}"


def enqueue_scan(
    queue: JobQueue,
    key: str,
    payload: ScanPayload | None = None,
    *,
    job_class: Literal["interactive", "backfill"] = "backfill",
) -> Enqueued:
    """Ask for a scan (idempotent per key). Backfill class by default: the nightly one runs
    when the interactive jobs have gone."""
    body = (payload or ScanPayload()).model_dump(mode="json", exclude_none=True)
    return queue.enqueue(SCAN_KIND, key, body, job_class=job_class)


def sentence_sha256(quote: str) -> str:
    """The identity of a sentence's words: lowercased, whitespace collapsed."""
    return hashlib.sha256(_SPACES.sub(" ", quote.strip().lower()).encode()).hexdigest()


def signal_url(
    document_url: str, version_id: uuid.UUID, parser_version: str, hit: SignalHit
) -> str:
    """The lead's own canonical URL: the document's, and a fragment naming the span."""
    return f"{document_url}#atlas-signal-{version_id}-{parser_version}-{hit.start}-{hit.end}"


_VERSIONS = """
    SELECT v.id, v.ingested_at, d.company_id, d.title, d.canonical_url, d.form_type,
           d.document_type, d.source_type, a.available_at, c.slug, c.display_name, c.legal_name
    FROM source_version v
    JOIN source_document d ON d.id = v.source_document_id
    JOIN source_version_availability a ON a.source_version_id = v.id
    JOIN company c ON c.id = d.company_id
    WHERE c.role = 'researched' AND d.source_type <> 'xbrl_companyfacts'
      AND (CAST(:ids AS uuid[]) IS NULL OR v.id = ANY(CAST(:ids AS uuid[])))
      AND (CAST(:company AS text) IS NULL OR c.slug = :company)
      AND (CAST(:since AS timestamptz) IS NULL OR a.available_at >= :since)
      AND (CAST(:after AS timestamptz) IS NULL OR v.ingested_at > :after)
      AND (CAST(:through AS timestamptz) IS NULL OR v.ingested_at <= :through)
    ORDER BY a.available_at, v.id
"""


class Scanner:
    def __init__(
        self,
        engine: Engine,
        archive: Archive,
        settings: Settings,
        clock: Clock = utc_now,
    ) -> None:
        self._engine = engine
        self._archive = archive
        self._settings = settings
        self._clock = clock
        config = load_signals_config(settings.signals_config)
        self._config_version = config.version
        self._scorer = SignalScorer(config)

    def run(self, job: Job) -> Artifacts:
        payload = ScanPayload.model_validate(job.payload)
        started = self._clock()
        explicit = bool(payload.source_version_ids or payload.since or payload.company)
        mode = "versions" if payload.source_version_ids else "since" if explicit else "since_last"
        after = through = None
        if not explicit:
            with self._engine.connect() as connection:
                # The database's clock, which stamps `ingested_at`.
                through = connection.execute(
                    text("SELECT now() - make_interval(secs => :lag)"),
                    {"lag": self._settings.signal_scan_lag_seconds},
                ).scalar_one()
                after = connection.execute(
                    text("SELECT max(until) FROM signal_scan WHERE mode = 'since_last'")
                ).scalar_one()
        with self._engine.connect() as connection:
            universe = extend_universe(connection, load_universe(self._settings.themes_config))
            versions = (
                connection.execute(
                    text(_VERSIONS),
                    {
                        "ids": [str(each) for each in payload.source_version_ids]
                        if payload.source_version_ids
                        else None,
                        "company": payload.company,
                        "since": payload.since,
                        "after": after,
                        "through": through,
                    },
                )
                .mappings()
                .all()
            )
        themes = {
            slug: sorted(name for name, theme in universe.themes.items() if slug in theme.companies)
            for slug in {row["slug"] for row in versions}
        }
        counts = {"versions_scanned": 0, "hits": 0, "stored": 0, "repeats": 0, "already": 0}
        skipped: dict[str, int] = {}
        failed: list[JsonValue] = []
        for row in versions:
            try:
                found = self._scan_version(job, dict(row), themes[row["slug"]], started)
            except Exception as error:  # one unreadable document does not stop the night's scan
                failed.append({"source_version_id": str(row["id"]), "error": str(error)[:300]})
                continue
            if isinstance(found, str):
                skipped[found] = skipped.get(found, 0) + 1
                continue
            counts["versions_scanned"] += 1
            for name, number in found.items():
                counts[name] += number
        scan_id = uuid.uuid4()
        artifacts: Artifacts = {
            "scan_id": str(scan_id),
            "mode": mode,
            "versions_selected": len(versions),
            **counts,
            "versions_skipped": dict[str, JsonValue](skipped),
            "versions_failed": failed,
            "scorer_version": SCORER_VERSION,
            "config_version": self._config_version,
        }
        if failed:
            # The run is not recorded, so the pointer stays where it was and the next run reads
            # these versions again (a span is stored once). A failure that persists fails the
            # night's job every night, which is how it is noticed.
            artifacts["scan_id"] = None
            raise FailedWithArtifacts(
                f"{len(failed)} Source Versions could not be read; the others were scanned",
                artifacts,
            )
        run = {
            "id": str(scan_id),
            "job_id": str(job.id),
            "mode": mode,
            "since": payload.since.isoformat() if payload.since else None,
            "until": (through or started).isoformat(),
            "scorer_version": SCORER_VERSION,
            "config_version": self._config_version,
            **counts,
        }
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO signal_scan (id, job_id, mode, since, until, versions_scanned,"
                    " hits, stored, repeats, scorer_version, config_version, scanned_at)"
                    " VALUES (:id, :job, :mode, :since, :until, :versions_scanned, :hits,"
                    " :stored, :repeats, :scorer, :config, :now)"
                ),
                {
                    "id": scan_id,
                    "job": job.id,
                    "mode": mode,
                    "since": payload.since,
                    "until": through or started,
                    "versions_scanned": counts["versions_scanned"],
                    "hits": counts["hits"],
                    "stored": counts["stored"],
                    "repeats": counts["repeats"],
                    "scorer": SCORER_VERSION,
                    "config": self._config_version,
                    "now": started,
                },
            )
            record(
                connection,
                Actor.from_settings(self._settings),
                "signal_scan.recorded",
                entity_type="signal_scan",
                entity_id=str(scan_id),
                new_hash=content_hash(run),
            )
        return artifacts

    def _scan_version(
        self, job: Job, row: dict[str, Any], themes: list[str], now: datetime
    ) -> dict[str, int] | str:
        """Scan one version and store its hits; the counts, or why it was skipped."""
        with self._engine.connect() as connection:
            parse = current_parse(connection, row["id"])
        if parse is None or parse.parse_status not in _WITH_TEXT or parse.parsed_object_uri is None:
            return "no_text"
        if parse.language not in (None, "en"):
            return "not_english"
        text_ = self._archive.get(parse.parsed_object_uri).decode("utf-8")
        primary = row["document_type"] is not None and row["document_type"] == row["form_type"]
        hits = self._scorer.scan(
            text_,
            form_type=row["form_type"],
            primary=primary,
            source_type=row["source_type"],
            company_names=company_names(row["display_name"], row["legal_name"]),
        )
        counts = {"hits": len(hits), "stored": 0, "repeats": 0, "already": 0}
        if not hits:
            return counts
        with self._engine.begin() as connection:
            for hit in hits:
                stored = self._store(connection, job, row, parse.parser_version, themes, hit, now)
                counts[stored] += 1
        return counts

    def _store(
        self,
        connection: Connection,
        job: Job,
        row: dict[str, Any],
        parser_version: str,
        themes: list[str],
        hit: SignalHit,
        now: datetime,
    ) -> Literal["stored", "repeats", "already"]:
        sha = sentence_sha256(hit.quote)
        earlier = connection.execute(
            text(
                "SELECT 1 FROM archive_signal s"
                " JOIN source_version_availability a ON a.source_version_id = s.source_version_id"
                " WHERE s.company_id = :company AND s.sentence_sha256 = :sha"
                " AND s.source_version_id <> :version AND a.available_at <= :available LIMIT 1"
            ),
            {
                "company": row["company_id"],
                "sha": sha,
                "version": row["id"],
                "available": row["available_at"],
            },
        ).first()
        if earlier is not None:
            return "repeats"
        url = signal_url(row["canonical_url"], row["id"], parser_version, hit)
        lead_id = connection.execute(
            text(
                "INSERT INTO lead (id, canonical_url, url, title, snippet, published_date,"
                " engines, first_query_id, origin, first_seen_at, last_seen_at)"
                " VALUES (:id, :canonical, :url, :title, :snippet, :published, ARRAY['archive'],"
                " NULL, 'archive_signal', :now, :now) ON CONFLICT (canonical_url) DO NOTHING"
                " RETURNING id"
            ),
            {
                "id": uuid.uuid4(),
                "canonical": url,
                "url": row["canonical_url"],
                "title": row["title"] or row["canonical_url"],
                "snippet": hit.quote,
                "published": row["available_at"].astimezone(UTC).date(),
                "now": now,
            },
        ).scalar_one_or_none()
        if lead_id is None:
            return "already"
        connection.execute(
            text(
                "INSERT INTO archive_signal (lead_id, source_version_id, company_id, themes,"
                " parser_version, section_anchor, char_start, char_end, quote, sentence_sha256,"
                " families, matches, factors, score, speaker, speaker_kind, scorer_version,"
                " config_version, job_id, scanned_at) VALUES (:lead, :version, :company, :themes,"
                " :parser, :anchor, :start, :end, :quote, :sha, :families,"
                " CAST(:matches AS jsonb), CAST(:factors AS jsonb), :score, :speaker, :kind,"
                " :scorer, :config, :job, :now)"
            ),
            {
                "lead": lead_id,
                "version": row["id"],
                "company": row["company_id"],
                "themes": themes,
                "parser": parser_version,
                "anchor": hit.section_anchor,
                "start": hit.start,
                "end": hit.end,
                "quote": hit.quote,
                "sha": sha,
                "families": list(hit.families),
                "matches": json.dumps(
                    [
                        {"family": each.family, "pattern": each.pattern, "text": each.text}
                        for each in hit.matches
                    ]
                ),
                "factors": json.dumps(dict(hit.factors)),
                "score": hit.score,
                "speaker": hit.speaker,
                "kind": hit.speaker_kind,
                "scorer": SCORER_VERSION,
                "config": self._config_version,
                "job": job.id,
                "now": now,
            },
        )
        return "stored"


def register_signal_handlers(
    registry: HandlerRegistry, settings: Settings, clock: Clock = utc_now
) -> None:
    def scan(job: Job) -> Artifacts:
        engine = create_engine(settings)
        try:
            return Scanner(engine, open_archive(settings), settings, clock).run(job)
        finally:
            engine.dispose()

    # Not pausable: it calls no LLM and no Hindsight, so no quota or outage pause holds it.
    registry.register(SCAN_KIND, scan)


class SignalScanSchedule:
    """Enqueues the day's scan from `at` (UTC), once a day, backfill class."""

    def __init__(self, engine: Engine, at: tuple[int, int]) -> None:
        self._engine = engine
        self._at = at
        self._done: str | None = None

    def __call__(self, now: datetime) -> list[Enqueued]:
        moment = now.astimezone(UTC)
        day = moment.date().isoformat()
        if self._done == day or (moment.hour, moment.minute) < self._at:
            return []
        enqueued = enqueue_scan(JobQueue(self._engine), scan_key(day))
        self._done = day
        return [enqueued]


def signal_schedules(settings: Settings, engine: Engine) -> list[Schedule]:
    """The daily scan (none with an empty `ATLAS_SIGNAL_SCAN_AT`)."""
    if not settings.signal_scan_at:
        return []
    hour, minute = (int(part) for part in settings.signal_scan_at.split(":"))
    return [SignalScanSchedule(engine, (hour, minute))]
