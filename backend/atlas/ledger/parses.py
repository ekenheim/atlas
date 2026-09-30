"""Re-parsing recorded Source Versions with the current parser (pilot-fixes ticket 11;
docs/decisions.md, "Re-parsing recorded Source Versions").

A recorded parse is never overwritten (the `source_version` trigger), so re-parsing a version
with a later parser is a separate, insert-only `source_parse` row keyed by (version, parser
version); `atlas.ledger.reads` reads a version's parses (`get_parse`, `current_parse`,
`list_parses`).

The `reparse` job (`REPARSE_KIND`; not pausable: no LLM, no Hindsight) reads each selected
version's **archived raw bytes** (never refetches), parses them with the current parser,
archives the text (content-addressed) and inserts the row, audited `source_parse.created`,
one version per transaction. A version already re-parsed under that parser is skipped, so
running it again inserts nothing. It selects the versions whose recorded parse is `parsed` or
`incomplete` under an earlier version of the same parser (`PARSER_LINEAGE`), optionally of
one company or a list of versions. A re-parse that raises is recorded `failed`, one with no
usable text `unsupported`, as the ledger records a first parse.
"""

import json
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, JsonValue
from sqlalchemy import Engine, text

from atlas.archive import Archive, Namespace, open_archive
from atlas.audit import Actor, content_hash, record
from atlas.db import create_engine
from atlas.jobs.handlers import JobHandler
from atlas.jobs.queue import Artifacts, Job
from atlas.parsing import PARSER_LINEAGE, PARSER_VERSION, ParsedText, parse
from atlas.settings import Settings

REPARSE_KIND = "reparse"
_WITH_TEXT = ("parsed", "incomplete")


class ReparsePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parser_version: str = Field(
        default=PARSER_VERSION, description="the parser to re-parse with: the current one"
    )
    company_id: uuid.UUID | None = None  # only this company's Source Versions
    source_version_ids: list[uuid.UUID] | None = None  # only these


def reparse_payload(
    *, company_id: uuid.UUID | None = None, parser_version: str = PARSER_VERSION
) -> dict[str, Any]:
    return ReparsePayload(parser_version=parser_version, company_id=company_id).model_dump(
        mode="json", exclude_none=True
    )


def older_parser_versions(parser_version: str) -> list[str]:
    """The versions of the parser before `parser_version` (none if it isn't one of them)."""
    if parser_version not in PARSER_LINEAGE:
        return []
    return list(PARSER_LINEAGE[: PARSER_LINEAGE.index(parser_version)])


class Reparser:
    def __init__(self, engine: Engine, archive: Archive, actor: Actor) -> None:
        self._engine = engine
        self._archive = archive
        self._actor = actor

    def run(self, job: Job) -> Artifacts:
        payload = ReparsePayload.model_validate(job.payload)
        if payload.parser_version != PARSER_VERSION:
            raise ValueError(
                f"only the current parser ({PARSER_VERSION}) can re-parse; the job names"
                f" {payload.parser_version!r}"
            )
        selected = self._select(payload)
        parses: list[JsonValue] = []
        for version in selected:
            made = self._reparse(job.id, version)
            if made is not None:
                parses.append(made)
        return {
            "parser_version": PARSER_VERSION,
            "selected": len(selected),
            "inserted": len(parses),
            "parses": parses,
        }

    def _select(self, payload: ReparsePayload) -> list[dict[str, Any]]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT v.id, v.object_uri, v.media_type, v.language, v.content_sha256,"
                    " v.parser_version FROM source_version v"
                    " JOIN source_document d ON d.id = v.source_document_id"
                    " WHERE v.parser_version = ANY(:older)"
                    " AND v.parse_status = ANY(:with_text)"
                    " AND (CAST(:company AS uuid) IS NULL OR d.company_id = :company)"
                    " AND (CAST(:ids AS uuid[]) IS NULL OR v.id = ANY(:ids))"
                    " AND NOT EXISTS (SELECT FROM source_parse p WHERE p.source_version_id = v.id"
                    "  AND p.parser_version = :parser)"
                    " ORDER BY v.ingested_at, v.id"
                ),
                {
                    "older": older_parser_versions(payload.parser_version),
                    "with_text": list(_WITH_TEXT),
                    "company": payload.company_id,
                    "ids": payload.source_version_ids,
                    "parser": payload.parser_version,
                },
            ).mappings()
            return [dict(row) for row in rows]

    def _reparse(self, job_id: uuid.UUID, version: dict[str, Any]) -> dict[str, JsonValue] | None:
        """Parse one version's archived raw bytes and insert the row; None if another attempt
        inserted it first."""
        raw = self._archive.get(version["object_uri"])  # verifies the raw hash
        row: dict[str, Any] = {
            "id": uuid.uuid4(),
            "source_version_id": version["id"],
            "parser_version": PARSER_VERSION,
            "parse_status": "failed",
            "parse_error": None,
            "content_sha256": None,
            "parsed_object_uri": None,
            "language": version["language"],
            "page_anchors": None,
            "job_id": job_id,
        }
        try:
            parsed = parse(raw, version["media_type"])
        except Exception as error:  # recorded, as the ledger records a failed first parse
            row["parse_error"] = f"{type(error).__name__}: {error}"
        else:
            if isinstance(parsed, ParsedText):
                row |= {
                    "parse_status": "parsed" if parsed.complete else "incomplete",
                    "content_sha256": parsed.sha256,
                    "parsed_object_uri": self._archive.put(Namespace.PARSED, parsed.encoded()),
                    # The recorded language is the adapter's declaration or the parse's; the
                    # language rules did not change, so it stands (else the new parse's).
                    "language": version["language"] or parsed.language,
                    "page_anchors": [a.__dict__ for a in parsed.pages] if parsed.pages else None,
                }
            elif parsed is None:
                row["parse_error"] = f"media type {version['media_type']} is not parsed"
            else:
                row |= {"parse_status": "unsupported", "parse_error": parsed.reason}
        with self._engine.begin() as connection:
            inserted = connection.execute(
                text(
                    "INSERT INTO source_parse (id, source_version_id, parser_version,"
                    " parse_status, parse_error, content_sha256, parsed_object_uri, language,"
                    " page_anchors, job_id) VALUES (:id, :source_version_id, :parser_version,"
                    " :parse_status, :parse_error, :content_sha256, :parsed_object_uri,"
                    " :language, CAST(:page_anchors AS jsonb), :job_id)"
                    " ON CONFLICT (source_version_id, parser_version) DO NOTHING"
                    " RETURNING created_at"
                ),
                {
                    **row,
                    "page_anchors": None
                    if row["page_anchors"] is None
                    else json.dumps(row["page_anchors"], sort_keys=True),
                },
            ).scalar_one_or_none()
            if inserted is None:
                return None
            record(
                connection,
                self._actor,
                "source_parse.created",
                entity_type="source_parse",
                entity_id=str(row["id"]),
                new_hash=content_hash({**row, "created_at": inserted}),
            )
        return {
            "source_parse_id": str(row["id"]),
            "source_version_id": str(version["id"]),
            "recorded_parser_version": version["parser_version"],
            "parse_status": row["parse_status"],
            "content_sha256": row["content_sha256"],
            "same_text_as_recorded": row["content_sha256"] == version["content_sha256"],
        }


def make_reparse_handler(settings: Settings) -> JobHandler:
    def handle(job: Job) -> Artifacts:
        engine = create_engine(settings)
        try:
            return Reparser(engine, open_archive(settings), Actor.from_settings(settings)).run(job)
        finally:
            engine.dispose()

    return handle
