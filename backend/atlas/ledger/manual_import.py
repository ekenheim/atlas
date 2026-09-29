"""Manual import: a document the owner fetched by hand, recorded in the source ledger.

`atlas sources import --company innolight --file report.pdf --origin-url <URL>
--published-at <timestamp>` is how material from a source Atlas may not fetch itself (HKEXnews,
whose terms forbid automated access) enters the ledger. The document:

- is a Source Document of provider `manual_import`, identified by its origin URL (the URL
  the owner downloaded it from), with the publisher (default: the site register's name for
  the origin's site, else its host) and a title (default: the file name);
- gets a Source Version whose `available_at` (and `published_at`) is the given publication
  time, basis `publisher_timestamp`; the timestamp must carry its UTC offset;
- is parsed (HTML, text or PDF, by the file's type), joins its Evidence Family, and when
  Hindsight is configured and it is English, gets a `retain` job;
- is audited under the importing actor (`ATLAS_ACTOR`), like every ledger write.

Re-importing the same bytes for the same origin URL creates no new version (a fetch
observation `unchanged`, as for a re-fetch); different bytes are a new version that
supersedes it, available from the time of the import (basis `observed_revision`), as for
any revised document. No request is made, so there is no fetch gate decision.
"""

import mimetypes
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from atlas.archive import open_archive
from atlas.audit import Actor
from atlas.companies import load_universe, seed
from atlas.db import create_engine
from atlas.ledger.service import SourceLedger
from atlas.retention.service import enqueue_retains
from atlas.settings import Settings
from atlas.sources import FetchedDocument, HttpValidators, ManualImport, SourceCandidate
from atlas.sources.gate import SiteRegisterError, load_site_register

PROVIDER_ID = "manual_import"
_MEDIA_TYPES = {".pdf": "application/pdf", ".htm": "text/html", ".html": "text/html"}


class ImportRefused(ValueError):
    """The import's arguments are unusable; nothing was recorded."""


@dataclass(frozen=True)
class Imported:
    outcome: str  # new_version or unchanged
    company_id: uuid.UUID
    source_document_id: uuid.UUID
    source_version_id: uuid.UUID
    retain_jobs: list[str] | None  # None when Hindsight isn't configured


def import_document(
    settings: Settings,
    *,
    company: str,
    file: Path,
    origin_url: str,
    published_at: datetime,
    title: str | None = None,
    publisher: str | None = None,
    media_type: str | None = None,
    published_local: str | None = None,
) -> Imported:
    universe = load_universe(settings.themes_config)
    if company not in universe.companies:
        raise ImportRefused(f"company {company!r} is not in {settings.themes_config}")
    if published_at.tzinfo is None:
        raise ImportRefused(
            "the publication time needs its UTC offset, e.g. 2026-08-21T22:30+08:00"
        )
    parts = urlsplit(origin_url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ImportRefused(f"the origin URL must be an http(s) URL, not {origin_url!r}")
    try:
        content = file.read_bytes()
    except OSError as error:
        raise ImportRefused(f"cannot read {file}: {error.strerror}") from None
    media_type = media_type or _MEDIA_TYPES.get(file.suffix.lower())
    media_type = media_type or mimetypes.guess_type(file.name)[0] or "application/octet-stream"
    actor = Actor.from_settings(settings)
    now = datetime.now(UTC)
    candidate = SourceCandidate(
        provider_id=PROVIDER_ID,
        kind="manual_import",
        url=origin_url,
        title=title or file.name,
        discovered_at=now,
        available_at=published_at,
        available_at_basis="publisher_timestamp",
        manual=ManualImport(
            publisher=publisher or _publisher(settings, origin_url),
            file_name=file.name,
            imported_by=actor.name,
            published_local=published_local or published_at.isoformat(),
        ),
    )
    fetched = FetchedDocument(
        candidate=candidate,
        url=origin_url,
        fetched_at=now,
        not_modified=False,
        content=content,
        media_type=media_type,
        validators=HttpValidators(),
        attempts=(),
    )
    engine = create_engine(settings)
    try:
        with engine.begin() as connection:
            (seeded,) = seed(connection, actor, universe, [company])
        ledger = SourceLedger(
            engine,
            open_archive(settings),
            actor,
            max_hamming_distance=settings.evidence_family_max_hamming_distance,
        )
        recorded = ledger.record(fetched, company_id=seeded.company_id)
        retain_jobs = (
            enqueue_retains(
                engine,
                [recorded.source_version_id] if recorded.outcome == "new_version" else [],
                actor=actor,
            )
            if settings.hindsight_url
            else None
        )
    finally:
        engine.dispose()
    return Imported(
        outcome=recorded.outcome,
        company_id=seeded.company_id,
        source_document_id=recorded.source_document_id,
        source_version_id=recorded.source_version_id,
        retain_jobs=retain_jobs,
    )


def _publisher(settings: Settings, url: str) -> str:
    try:
        found = load_site_register(settings.source_sites_config).site_for(url)
    except SiteRegisterError:
        found = None
    return found[1].publisher if found else (urlsplit(url).hostname or url)
