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
            " etag, last_modified, attempts, job_id FROM fetch_observation"
            " WHERE source_version_id = :id ORDER BY observed_at, fetched_at, id"
        ),
        {"id": version_id},
    ).mappings()
    base = f"/api/v1/source-versions/{version_id}/content"
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
    connection: Connection, archive: Archive, version_id: uuid.UUID, kind: ContentKind
) -> Content | None:
    """The archived raw bytes or parse of a version; None if the version or parse is absent."""
    row: Any = connection.execute(
        text(
            "SELECT v.object_uri, v.raw_sha256, v.media_type, v.parsed_object_uri,"
            " v.content_sha256, d.canonical_url FROM source_version v"
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
    if row.parsed_object_uri is None:
        return None
    data = archive.get(row.parsed_object_uri)
    return Content(data, "text/plain; charset=utf-8", row.content_sha256, f"{name}.txt")
