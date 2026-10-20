"""The edition store (atlas-record ticket 01): import a page, list and read what is kept.

`Editions.import_page` is the one way in (the CLI, `POST /api/v1/editions` and, in ticket 03, the
drop-box pull call it). It parses the page, puts the bytes in the archive (content-addressed),
and inserts one `ledger_edition` row with the audit event `edition.imported`, in one
transaction. The rewrite check (`atlas.record.rewrite_store`) runs in that transaction for a
parsed edition and records its findings insert-only (audited `edition.rewrites_found` when there
are any). The same bytes again change nothing (`outcome: unchanged`, no audit event); another
edition of the same theme and `as_of` with different bytes is kept and marked
`same_as_of_differs`. A page that does not parse is recorded with its error.

The theme is the ledger's own (`council` for the council's). A page whose ledger names another
theme than the one given is refused (`theme_mismatch`), so a file imported under the wrong theme
cannot be filed there.
"""

import hashlib
import json
import re
import uuid
from datetime import date, datetime
from typing import Any, Literal, cast

from pydantic import BaseModel, Field
from sqlalchemy import Connection, Engine, text

from atlas.archive import Archive, Namespace
from atlas.audit import Actor, record
from atlas.jobs.pacing import Clock, utc_now
from atlas.record.ledger import COUNCIL, CouncilLedger, Ledger, ThemeLedger
from atlas.record.parse import Parsed, parse_page
from atlas.record.rewrite_store import check_rewrites

type EditionSource = Literal["drop_box", "manual"]
type ImportOutcome = Literal["imported", "unchanged"]

MAX_PAGE_BYTES = 8 * 1024 * 1024
THEME_SLUG = r"^[a-z][a-z0-9-]{1,40}$"
COMMIT_SHA = r"^[0-9a-f]{7,64}$"

_COLUMNS = (
    "id, theme, as_of, edition, page_sha256, page_uri, page_size, ledger, parse_error, source,"
    " commit_sha, same_as_of_differs, read_at"
)
_INSERT = (
    "INSERT INTO ledger_edition (id, theme, as_of, edition, page_sha256, page_uri,"  # noqa: S608
    " page_size, ledger, parse_error, source, commit_sha, same_as_of_differs, read_at)"
    " VALUES (:id, :theme, :as_of, :edition, :digest, :uri, :size,"
    " CAST(:ledger AS jsonb), :error, :source, :commit, :rewrote, :read_at)"
    " RETURNING " + _COLUMNS
)
_SELECT = "SELECT " + _COLUMNS + " FROM ledger_edition"  # noqa: S608 (constant fragments)


class EditionError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


class EditionSummary(BaseModel):
    id: uuid.UUID
    theme: str = Field(description="the theme's slug; `council` for the council's")
    as_of: date | None = Field(description="the ledger's as-of day; null when it did not parse")
    edition: int | None = Field(
        description="the ledger's edition number; null when it did not parse"
    )
    source: EditionSource
    commit_sha: str | None = Field(description="the drop box commit the page came from")
    page_sha256: str
    page_size: int
    parse_error: str | None = Field(description="why the page has no ledger, when it has none")
    same_as_of_differs: bool = Field(
        description="an edition of this theme and as-of day with other bytes was kept before: the"
        " task rewrote its edition the same day"
    )
    read_at: datetime = Field(description="when Atlas read the page")


class Edition(EditionSummary):
    ledger: ThemeLedger | CouncilLedger | None = Field(
        description="the parsed ledger, with every field the page wrote"
    )
    page_uri: str = Field(description="the page in the archive (content-addressed)")
    page_href: str = Field(description="the page as a download, `GET /api/v1/editions/{id}/page`")


class EditionImported(BaseModel):
    outcome: ImportOutcome
    edition: Edition
    rewrites_found: int = Field(
        default=0,
        description="the differences the rewrite check found against the theme's previous"
        " parsed edition (`GET /api/v1/editions/{id}/rewrites`); 0 when nothing changed",
    )


def _ledger(raw: object) -> Ledger | None:
    if not isinstance(raw, dict):
        return None
    body = cast("dict[str, Any]", raw)
    if "chokepoints" in body:
        return ThemeLedger.model_validate(body)
    return CouncilLedger.model_validate(body)


def _fields(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "theme": row.theme,
        "as_of": row.as_of,
        "edition": row.edition,
        "source": row.source,
        "commit_sha": row.commit_sha,
        "page_sha256": row.page_sha256,
        "page_size": row.page_size,
        "parse_error": row.parse_error,
        "same_as_of_differs": row.same_as_of_differs,
        "read_at": row.read_at,
    }


def _edition(row: Any) -> Edition:
    return Edition(
        **_fields(row),
        ledger=_ledger(row.ledger),
        page_uri=row.page_uri,
        page_href=f"/api/v1/editions/{row.id}/page",
    )


def _summary(row: Any) -> EditionSummary:
    return EditionSummary(**_fields(row))


def _ledger_theme(ledger: Ledger) -> str:
    return ledger.theme if isinstance(ledger, ThemeLedger) else COUNCIL


class Editions:
    def __init__(
        self, engine: Engine, archive: Archive, actor: Actor, clock: Clock = utc_now
    ) -> None:
        self._engine = engine
        self._archive = archive
        self._actor = actor
        self._clock = clock

    def import_page(
        self,
        theme: str,
        page: bytes,
        *,
        source: EditionSource = "manual",
        commit_sha: str | None = None,
    ) -> EditionImported:
        if not re.fullmatch(THEME_SLUG, theme):
            raise EditionError(422, "invalid_theme", "the theme must be a slug such as `photonics`")
        if not page:
            raise EditionError(422, "empty_page", "the page is empty")
        if len(page) > MAX_PAGE_BYTES:
            raise EditionError(413, "page_too_large", f"a page is at most {MAX_PAGE_BYTES} bytes")
        if (source == "drop_box") != (commit_sha is not None):
            raise EditionError(
                422, "invalid_source", "a drop_box page carries its commit SHA; a manual one none"
            )
        if commit_sha is not None and not re.fullmatch(COMMIT_SHA, commit_sha):
            raise EditionError(422, "invalid_commit_sha", "the commit SHA is 7 to 64 hex digits")
        parsed = parse_page(page)
        if parsed.ledger is not None and _ledger_theme(parsed.ledger) != theme:
            raise EditionError(
                422,
                "theme_mismatch",
                f"the page's ledger is `{_ledger_theme(parsed.ledger)}`, not `{theme}`",
            )
        digest = hashlib.sha256(page).hexdigest()
        uri = self._archive.put(Namespace.RAW, page)
        with self._engine.begin() as connection:
            # One import per theme at a time, so the same-day comparison below cannot race.
            connection.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"ledger_edition:{theme}"},
            )
            existing = _by_hash(connection, digest)
            if existing is not None:
                return EditionImported(outcome="unchanged", edition=_edition(existing))
            edition_id = uuid.uuid4()
            row = _insert(
                connection,
                edition_id,
                theme,
                parsed,
                digest,
                uri,
                len(page),
                source,
                commit_sha,
                self._clock(),
            )
            record(
                connection,
                self._actor,
                "edition.imported",
                entity_type="ledger_edition",
                entity_id=str(edition_id),
                new_hash=digest,
            )
            # The rewrite check, in the same transaction: an edition never exists without it.
            found = (
                []
                if parsed.ledger is None
                else check_rewrites(connection, edition_id, theme, parsed.ledger, row.read_at)
            )
            if found:
                record(
                    connection,
                    self._actor,
                    "edition.rewrites_found",
                    entity_type="ledger_edition",
                    entity_id=str(edition_id),
                    new_hash=digest,
                )
        return EditionImported(outcome="imported", edition=_edition(row), rewrites_found=len(found))


def _by_hash(connection: Connection, digest: str) -> Any | None:
    return connection.execute(
        text(_SELECT + " WHERE page_sha256 = :digest"),
        {"digest": digest},
    ).one_or_none()


def _insert(
    connection: Connection,
    edition_id: uuid.UUID,
    theme: str,
    parsed: Parsed,
    digest: str,
    uri: str,
    size: int,
    source: EditionSource,
    commit_sha: str | None,
    read_at: datetime,
) -> Any:
    as_of: date | None = None
    number: int | None = None
    if parsed.ledger is not None:
        as_of, number = parsed.ledger.as_of, parsed.ledger.edition
    rewrote = (
        as_of is not None
        and connection.execute(
            text(
                "SELECT EXISTS (SELECT FROM ledger_edition WHERE theme = :theme AND as_of = :day)"
            ),
            {"theme": theme, "day": as_of},
        ).scalar_one()
    )
    return connection.execute(
        text(_INSERT),
        {
            "id": edition_id,
            "theme": theme,
            "as_of": as_of,
            "edition": number,
            "digest": digest,
            "uri": uri,
            "size": size,
            "ledger": None if parsed.raw is None else json.dumps(parsed.raw),
            "error": parsed.error,
            "source": source,
            "commit": commit_sha,
            "rewrote": bool(rewrote),
            "read_at": read_at,
        },
    ).one()


def list_editions(
    engine: Engine, theme: str | None, limit: int, offset: int
) -> tuple[list[EditionSummary], int]:
    """Editions newest first (by the ledger's as-of day, then by when they were read)."""
    where = "(CAST(:theme AS text) IS NULL OR theme = :theme)"
    params: dict[str, Any] = {"theme": theme, "limit": limit, "offset": offset}
    with engine.connect() as connection:
        total = connection.execute(
            text("SELECT count(*) FROM ledger_edition WHERE " + where),  # noqa: S608 (constants)
            params,
        ).scalar_one()
        rows = connection.execute(
            text(
                _SELECT
                + " WHERE "
                + where
                + " ORDER BY as_of DESC NULLS LAST, seq DESC LIMIT :limit OFFSET :offset"
            ),
            params,
        ).all()
    return [_summary(row) for row in rows], total


def get_edition(engine: Engine, edition_id: uuid.UUID) -> Edition | None:
    with engine.connect() as connection:
        row = connection.execute(
            text(_SELECT + " WHERE id = :id"),
            {"id": edition_id},
        ).one_or_none()
    return None if row is None else _edition(row)


def read_page(engine: Engine, archive: Archive, edition_id: uuid.UUID) -> bytes | None:
    """The page's bytes from the archive (verified against their hash on read)."""
    with engine.connect() as connection:
        uri = connection.execute(
            text("SELECT page_uri FROM ledger_edition WHERE id = :id"), {"id": edition_id}
        ).scalar_one_or_none()
    return None if uri is None else archive.get(uri)
