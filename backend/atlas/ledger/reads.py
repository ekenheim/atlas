"""The source ledger's read side: Source Documents, their version history, and content."""

import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, JsonValue
from sqlalchemy import Connection, text

from atlas.archive import Archive
from atlas.ledger.families import Match, simhash_hex
from atlas.parsing import PARSER_VERSION

ContentKind = Literal["raw", "parsed"]


class SourceDocument(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID | None
    provider: str
    canonical_url: str
    origin_url: str
    accession: str | None
    form_type: str | None
    document_type: str | None
    source_type: str
    title: str
    publisher: str
    source_tier: str
    license_class: str
    first_seen_at: datetime
    version_count: int
    latest_version_id: uuid.UUID | None


class PageAnchor(BaseModel):
    """One PDF page's place in the parsed text: `text[start:end]`, in code points."""

    page: int  # 1-based, in document order
    label: str  # the page's label as the PDF gives it (e.g. "iv"), else its number
    start: int
    end: int


class SourceParse(BaseModel):
    """One parse of a Source Version: the one it was recorded with (`recorded`, the version's
    own parse columns), or a re-parse under a later parser version (a `source_parse` row)."""

    parser_version: str
    recorded: bool
    parse_status: str
    parse_error: str | None
    content_sha256: str | None
    parsed_object_uri: str | None
    language: str | None
    page_anchors: list[PageAnchor] | None
    source_parse_id: uuid.UUID | None  # None for the recorded parse
    job_id: uuid.UUID | None  # the `reparse` job that made it; None for the recorded parse
    parsed_at: datetime  # for the recorded parse, when the version was ingested
    content: str | None  # the parsed text's URL, when the parse has text


class SourceVersionSummary(BaseModel):
    id: uuid.UUID
    source_document_id: uuid.UUID
    version_number: int
    raw_sha256: str
    content_sha256: str | None
    parser_version: str | None
    parse_status: str
    language: str | None  # ISO 639 primary subtag, or "und" (undetermined)
    available_at: datetime  # effective: a recorded correction's, else the version's own
    available_at_basis: str
    recorded_available_at: datetime  # as the immutable version recorded it
    recorded_available_at_basis: str
    fetched_at: datetime
    ingested_at: datetime
    supersedes_version_id: uuid.UUID | None
    superseded_by_version_id: uuid.UUID | None
    evidence_family_id: uuid.UUID | None  # None: not parsed, so in no family


class EvidenceFamilyMembership(BaseModel):
    """How a Source Version joined its Evidence Family (atlas.ledger.families)."""

    evidence_family_id: uuid.UUID
    match: Match
    matched_source_version_id: uuid.UUID | None  # the member it duplicates; None: founder
    hamming_distance: int | None  # SimHash distance to that member
    simhash: str  # 16 hex digits
    simhash_rule: str
    max_hamming_distance: int  # the family's recorded threshold
    member_count: int  # the family counts as one witness, however many members
    assigned_at: datetime


class EvidenceFamilyMember(BaseModel):
    source_version_id: uuid.UUID
    source_document_id: uuid.UUID
    canonical_url: str
    publisher: str
    match: Match
    matched_source_version_id: uuid.UUID | None
    hamming_distance: int | None
    simhash: str
    assigned_at: datetime


class EvidenceFamily(BaseModel):
    """Source Versions that are copies of one announcement: one witness."""

    id: uuid.UUID
    simhash_rule: str
    max_hamming_distance: int
    created_at: datetime
    member_count: int
    members: list[EvidenceFamilyMember]  # in assignment order, the founder first


class FetchObservation(BaseModel):
    """One fetch of the document that produced or matched this version."""

    id: uuid.UUID
    outcome: str
    url: str
    fetched_at: datetime
    observed_at: datetime
    raw_sha256: str | None
    comparison_sha256: str | None
    etag: str | None
    last_modified: str | None
    attempts: int
    job_id: uuid.UUID | None
    # The allowed fetch gate decision this fetch was made under (exchange sources; None for
    # SEC EDGAR): `GET /api/v1/fetch-gate-decisions/{id}`.
    gate_decision_id: uuid.UUID | None
    # The owner's recorded override this fetch was made under (TradingView, ticket 31).
    owner_override: str | None = None


class ContentLinks(BaseModel):
    raw: str
    parsed: str | None


class SourceVersionDetail(SourceVersionSummary):
    """A Source Version's full provenance."""

    source_document: SourceDocument
    comparison_sha256: str
    comparison_rule: str
    object_uri: str
    parsed_object_uri: str | None
    byte_size: int
    media_type: str
    parse_error: str | None
    page_anchors: list[PageAnchor] | None  # a PDF parse's pages; None without pages
    event_at: datetime | None
    published_at: datetime | None
    fetch_status: str
    metadata: dict[str, JsonValue]
    content: ContentLinks
    fetches: list[FetchObservation]
    evidence_family: EvidenceFamilyMembership | None
    # Every parse: the recorded one (the parse columns above) first, then re-parses.
    parses: list[SourceParse]
    # The parse the Investigator's extraction reads: a re-parse under the current parser
    # when there is one with text, else the recorded parse's version (None: never parsed).
    current_parser_version: str | None


@dataclass(frozen=True)
class Content:
    data: bytes
    media_type: str
    sha256: str
    filename: str


_DOCUMENT = """
    SELECT d.id, d.company_id, d.provider, d.canonical_url, d.origin_url, d.accession,
           d.form_type, d.document_type, d.source_type, d.title, d.publisher, d.source_tier,
           d.license_class, d.first_seen_at,
           (SELECT count(*) FROM source_version v WHERE v.source_document_id = d.id)
               AS version_count,
           (SELECT v.id FROM source_version v WHERE v.source_document_id = d.id
            ORDER BY v.version_number DESC LIMIT 1) AS latest_version_id
    FROM source_document d
"""

_VERSION = """
    SELECT v.*, a.available_at AS effective_available_at,
           a.available_at_basis AS effective_available_at_basis,
           (SELECT n.id FROM source_version n WHERE n.supersedes_version_id = v.id)
               AS superseded_by_version_id,
           (SELECT m.evidence_family_id FROM evidence_family_member m
            WHERE m.source_version_id = v.id) AS evidence_family_id
    FROM source_version v
    JOIN source_version_availability a ON a.source_version_id = v.id
"""


def _version_fields(row: Any) -> dict[str, Any]:
    """A version row with its effective availability (docs/decisions.md)."""
    return {
        **row,
        "available_at": row["effective_available_at"],
        "available_at_basis": row["effective_available_at_basis"],
        "recorded_available_at": row["available_at"],
        "recorded_available_at_basis": row["available_at_basis"],
    }


def list_source_documents(
    connection: Connection, company_id: uuid.UUID, *, limit: int, offset: int
) -> tuple[list[SourceDocument], int]:
    total = connection.execute(
        text("SELECT count(*) FROM source_document WHERE company_id = :company"),
        {"company": company_id},
    ).scalar_one()
    rows = connection.execute(
        text(
            f"{_DOCUMENT} WHERE d.company_id = :company"
            " ORDER BY d.first_seen_at, d.canonical_url LIMIT :limit OFFSET :offset"
        ),
        {"company": company_id, "limit": limit, "offset": offset},
    ).mappings()
    return [SourceDocument.model_validate(dict(row)) for row in rows], total


def get_source_document(connection: Connection, document_id: uuid.UUID) -> SourceDocument | None:
    row = (
        connection.execute(text(f"{_DOCUMENT} WHERE d.id = :id"), {"id": document_id})
        .mappings()
        .one_or_none()
    )
    return None if row is None else SourceDocument.model_validate(dict(row))


def list_versions(
    connection: Connection, document_id: uuid.UUID, *, limit: int, offset: int
) -> tuple[list[SourceVersionSummary], int]:
    """A document's version history, oldest first."""
    total = connection.execute(
        text("SELECT count(*) FROM source_version WHERE source_document_id = :document"),
        {"document": document_id},
    ).scalar_one()
    rows = connection.execute(
        text(
            f"{_VERSION} WHERE v.source_document_id = :document"
            " ORDER BY v.version_number LIMIT :limit OFFSET :offset"
        ),
        {"document": document_id, "limit": limit, "offset": offset},
    ).mappings()
    return [SourceVersionSummary.model_validate(_version_fields(row)) for row in rows], total


def get_version(connection: Connection, version_id: uuid.UUID) -> SourceVersionDetail | None:
    row = (
        connection.execute(text(f"{_VERSION} WHERE v.id = :id"), {"id": version_id})
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    source_document = get_source_document(connection, row["source_document_id"])
    fetches = connection.execute(
        text(
            "SELECT id, outcome, url, fetched_at, observed_at, raw_sha256, comparison_sha256,"
            " etag, last_modified, attempts, job_id, gate_decision_id, owner_override"
            " FROM fetch_observation"
            " WHERE source_version_id = :id ORDER BY observed_at, fetched_at, id"
        ),
        {"id": version_id},
    ).mappings()
    base = f"/api/v1/source-versions/{version_id}/content"
    current = current_parse(connection, version_id)
    return SourceVersionDetail.model_validate(
        {
            **_version_fields(row),
            "source_document": source_document,
            "content": ContentLinks(
                raw=f"{base}?kind=raw",
                parsed=f"{base}?kind=parsed" if row["parsed_object_uri"] else None,
            ),
            "fetches": [FetchObservation.model_validate(dict(fetch)) for fetch in fetches],
            "evidence_family": _membership(connection, version_id),
            "parses": list_parses(connection, version_id),
            "current_parser_version": current.parser_version if current else None,
        }
    )


def _membership(connection: Connection, version_id: uuid.UUID) -> EvidenceFamilyMembership | None:
    row = (
        connection.execute(
            text(
                "SELECT m.evidence_family_id, m.match, m.matched_source_version_id,"
                " m.hamming_distance, m.simhash, m.assigned_at, f.simhash_rule,"
                " f.max_hamming_distance, (SELECT count(*) FROM evidence_family_member o"
                " WHERE o.evidence_family_id = m.evidence_family_id) AS member_count"
                " FROM evidence_family_member m"
                " JOIN evidence_family f ON f.id = m.evidence_family_id"
                " WHERE m.source_version_id = :id"
            ),
            {"id": version_id},
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    return EvidenceFamilyMembership.model_validate({**row, "simhash": simhash_hex(row["simhash"])})


def get_evidence_family(connection: Connection, family_id: uuid.UUID) -> EvidenceFamily | None:
    family = (
        connection.execute(
            text(
                "SELECT id, simhash_rule, max_hamming_distance, created_at"
                " FROM evidence_family WHERE id = :id"
            ),
            {"id": family_id},
        )
        .mappings()
        .one_or_none()
    )
    if family is None:
        return None
    rows = connection.execute(
        text(
            "SELECT m.source_version_id, v.source_document_id, d.canonical_url, d.publisher,"
            " m.match, m.matched_source_version_id, m.hamming_distance, m.simhash,"
            " m.assigned_at FROM evidence_family_member m"
            " JOIN source_version v ON v.id = m.source_version_id"
            " JOIN source_document d ON d.id = v.source_document_id"
            " WHERE m.evidence_family_id = :id ORDER BY m.seq"
        ),
        {"id": family_id},
    ).mappings()
    members = [
        EvidenceFamilyMember.model_validate({**row, "simhash": simhash_hex(row["simhash"])})
        for row in rows
    ]
    return EvidenceFamily.model_validate(
        {**family, "member_count": len(members), "members": members}
    )


def get_content(
    connection: Connection,
    archive: Archive,
    version_id: uuid.UUID,
    kind: ContentKind,
    parser_version: str | None = None,
) -> Content | None:
    """The archived raw bytes or parse of a version; None if the version or parse is absent.
    The parse is the recorded one unless `parser_version` names one of the version's parses
    (a re-parse's file name carries its parser version)."""
    row: Any = connection.execute(
        text(
            "SELECT v.object_uri, v.raw_sha256, v.media_type, v.parsed_object_uri,"
            " v.content_sha256, v.parser_version, d.canonical_url FROM source_version v"
            " JOIN source_document d ON d.id = v.source_document_id WHERE v.id = :id"
        ),
        {"id": version_id},
    ).one_or_none()
    if row is None:
        return None
    name = re.sub(r"[^A-Za-z0-9._-]", "_", row.canonical_url.rstrip("/").rsplit("/", 1)[-1])
    name = name.strip(".") or "document"
    if kind == "raw":
        return Content(archive.get(row.object_uri), row.media_type, row.raw_sha256, name)
    uri, sha, filename = row.parsed_object_uri, row.content_sha256, f"{name}.txt"
    if parser_version is not None and parser_version != row.parser_version:
        chosen = get_parse(connection, version_id, parser_version)
        if chosen is None:
            return None
        uri, sha = chosen.parsed_object_uri, chosen.content_sha256
        filename = f"{name}.{re.sub(r'[^A-Za-z0-9._-]', '_', parser_version)}.txt"
    if uri is None or sha is None:
        return None
    return Content(archive.get(uri), "text/plain; charset=utf-8", sha, filename)


# --- parses -------------------------------------------------------------------------------------

_WITH_TEXT = ("parsed", "incomplete")
_PARSE = (
    "SELECT source_version_id, parser_version, recorded, parse_status, parse_error,"
    " content_sha256, parsed_object_uri, language, page_anchors, source_parse_id, job_id,"
    " parsed_at FROM source_version_parse"
)


def _source_parse(row: Any) -> SourceParse:
    values = dict(row)
    link: str | None = None
    if values["parse_status"] in _WITH_TEXT:
        link = f"/api/v1/source-versions/{values['source_version_id']}/content?kind=parsed"
        if not values["recorded"]:
            link += f"&parser_version={values['parser_version']}"
    return SourceParse.model_validate({**values, "content": link})


def list_parses(connection: Connection, version_id: uuid.UUID) -> list[SourceParse]:
    """A version's parses: the recorded one first, then its re-parses, oldest first."""
    rows = connection.execute(
        text(
            f"{_PARSE} WHERE source_version_id = :id"
            " ORDER BY recorded DESC, parsed_at, parser_version"
        ),
        {"id": version_id},
    ).mappings()
    return [_source_parse(row) for row in rows]


def get_parse(
    connection: Connection, version_id: uuid.UUID, parser_version: str | None = None
) -> SourceParse | None:
    """A version's parse under `parser_version` (the recorded one, or a re-parse); None names
    the recorded parse."""
    if parser_version is None:
        condition, params = "recorded", {"id": version_id}
    else:
        condition = "parser_version = :parser"
        params = {"id": version_id, "parser": parser_version}
    row = (
        connection.execute(text(f"{_PARSE} WHERE source_version_id = :id AND {condition}"), params)
        .mappings()
        .one_or_none()
    )
    return None if row is None else _source_parse(row)


def current_parse(connection: Connection, version_id: uuid.UUID) -> SourceParse | None:
    """The parse the Investigator reads: the version's parse under the current parser
    (`PARSER_VERSION`) when it has text, else the recorded parse (whatever its status). None
    for an unknown version or one never parsed (a format Atlas doesn't parse)."""
    current = get_parse(connection, version_id, PARSER_VERSION)
    if current is not None and current.parse_status in _WITH_TEXT:
        return current
    return get_parse(connection, version_id)
