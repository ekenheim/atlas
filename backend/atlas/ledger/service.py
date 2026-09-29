"""The source ledger's write side: every fetch becomes a Source Version or an observation.

`SourceLedger.record(fetched)` owns the Source Document / Source Version lifecycle:

1. Resolve the candidate to a Source Document by (provider, canonical URL); for SEC this
   is the accession's folder plus the file name, so each document of a filing (primary
   document, exhibits) has its own identity. Titles are never used.
2. Hash the raw bytes (`raw_sha256`, exactly as fetched) and archive them.
3. Decide whether the content changed, by the change-detection hash (`comparison_sha256`):
   the raw bytes after the comparison rule removed bytes that are not content. For SEC
   Archives HTML that is every `<script>` element: SEC's edge appends one that may vary
   between fetches, and EDGAR does not accept scripts in filed documents, so a script is
   never filed content (rule `sec-edge-script-v1`; docs/decisions.md). Other material uses
   the raw hash itself (rule `identity`).
4. Unchanged (same raw hash, same comparison hash, or HTTP 304): record a fetch
   observation only. Changed: create a new Source Version superseding the latest one, then
   parse it and archive the parse separately. A document's first version takes
   `available_at` from the candidate (SEC filings: `acceptanceDateTime`, basis
   `sec_acceptance`). A version that supersedes an earlier one takes the time Atlas fetched
   it (basis `observed_revision`): its bytes weren't public at the original acceptance, and
   availability is never overstated (spec Part A story 31; docs/decisions.md).
5. Write an audit event for each row created, in the same transaction.

Only this service writes Source Documents, Source Versions and fetch observations.
"""

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import Connection, Engine, text

from atlas.archive import Archive, Namespace
from atlas.audit import Actor, content_hash, record
from atlas.parsing import PARSER_VERSION, is_parseable, parse
from atlas.sources import FetchedDocument, HttpValidators, SourceCandidate
from atlas.sources.edgar import PROVIDER_ID as SEC_EDGAR

FetchOutcome = Literal["new_version", "unchanged", "not_modified"]
# The basis of a superseding version's `available_at`: when Atlas observed the change.
OBSERVED_REVISION = "observed_revision"

IDENTITY_RULE = "identity"
SEC_EDGE_SCRIPT_RULE = "sec-edge-script-v1"
_SCRIPT_ELEMENT = re.compile(rb"<script\b[^>]*>.*?</script\s*>", re.IGNORECASE | re.DOTALL)
_HTML = frozenset({"text/html", "application/xhtml+xml"})
_FALLBACK_MEDIA_TYPE = "application/octet-stream"


class LedgerError(Exception):
    """A fetch the ledger cannot record (e.g. a 304 for a document it has never stored)."""


@dataclass(frozen=True)
class DocumentIdentity:
    provider: str
    canonical_url: str
    accession: str | None
    form_type: str | None
    document_type: str | None
    source_type: str
    title: str
    publisher: str
    source_tier: str
    license_class: str


@dataclass(frozen=True)
class RecordedFetch:
    outcome: FetchOutcome
    url: str
    source_document_id: uuid.UUID
    source_version_id: uuid.UUID
    observation_id: uuid.UUID


def canonical_url(url: str) -> str:
    """Scheme and host lowercased; query, fragment and default ports dropped."""
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    if parts.port and not (
        (parts.scheme == "https" and parts.port == 443)
        or (parts.scheme == "http" and parts.port == 80)
    ):
        host = f"{host}:{parts.port}"
    return urlunsplit((parts.scheme.lower(), host, parts.path or "/", "", ""))


def describe(candidate: SourceCandidate) -> DocumentIdentity:
    """The Source Document a candidate belongs to. Phase 1 knows SEC EDGAR only."""
    if candidate.provider_id != SEC_EDGAR:
        raise LedgerError(f"no ledger rules for provider {candidate.provider_id!r}")
    filing = candidate.filing
    return DocumentIdentity(
        provider=candidate.provider_id,
        canonical_url=canonical_url(candidate.url),
        accession=filing.accession_number if filing else None,
        form_type=filing.form if filing else None,
        document_type=candidate.document_type,
        source_type="filing" if candidate.kind == "sec_filing_document" else "xbrl_companyfacts",
        title=candidate.title,
        publisher="SEC EDGAR",
        source_tier="A",
        license_class="public_regulatory",
    )


def comparison_bytes(provider: str, media_type: str, raw: bytes) -> tuple[str, bytes]:
    """(rule, bytes) for change detection; the raw bytes themselves are never altered."""
    if provider == SEC_EDGAR and media_type.lower() in _HTML:
        return SEC_EDGE_SCRIPT_RULE, _SCRIPT_ELEMENT.sub(b"", raw)
    return IDENTITY_RULE, raw


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


class SourceLedger:
    def __init__(self, engine: Engine, archive: Archive, actor: Actor) -> None:
        self._engine = engine
        self._archive = archive
        self._actor = actor

    def validators_for(self, candidate: SourceCandidate) -> HttpValidators | None:
        """Validators from the document's latest fetch, to make the next one conditional."""
        with self._engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT o.etag, o.last_modified FROM fetch_observation o"
                    " JOIN source_document d ON d.id = o.source_document_id"
                    " WHERE d.provider = :provider AND d.canonical_url = :url"
                    " ORDER BY o.observed_at DESC, o.id LIMIT 1"
                ),
                {"provider": candidate.provider_id, "url": canonical_url(candidate.url)},
            ).one_or_none()
        if row is None or (row.etag is None and row.last_modified is None):
            return None
        return HttpValidators(etag=row.etag, last_modified=row.last_modified)

    def record(
        self,
        fetched: FetchedDocument,
        *,
        company_id: uuid.UUID | None,
        job_id: uuid.UUID | None = None,
    ) -> RecordedFetch:
        identity = describe(fetched.candidate)
        media_type = fetched.media_type or _FALLBACK_MEDIA_TYPE
        raw: bytes | None = None if fetched.not_modified else fetched.content
        raw_sha = comparison_sha = raw_uri = None
        rule = IDENTITY_RULE
        if raw is not None:
            raw_sha = _sha256(raw)
            rule, comparable = comparison_bytes(identity.provider, media_type, raw)
            comparison_sha = _sha256(comparable)
            # Archived before the transaction: a put is idempotent and content-addressed,
            # so an object left behind by a rollback is harmless.
            raw_uri = self._archive.put(Namespace.RAW, raw)

        with self._engine.begin() as connection:
            document_id, document_created = self._resolve(
                connection, identity, company_id, fetched.candidate.discovered_at
            )
            latest = (
                connection.execute(
                    text(
                        "SELECT id, version_number, comparison_rule, comparison_sha256"
                        " FROM source_version WHERE source_document_id = :document"
                        " ORDER BY version_number DESC LIMIT 1"
                    ),
                    {"document": document_id},
                )
                .mappings()
                .one_or_none()
            )
            observation_uri: str | None = None
            created_version: dict[str, Any] | None = None
            if raw is None:
                if latest is None:
                    raise LedgerError(f"304 for {identity.canonical_url}, which has no version")
                outcome: FetchOutcome = "not_modified"
                version_id: uuid.UUID = latest["id"]
            else:
                assert raw_sha is not None and comparison_sha is not None and raw_uri is not None
                same_bytes = connection.execute(
                    text(
                        "SELECT id FROM source_version"
                        " WHERE source_document_id = :document AND raw_sha256 = :sha"
                    ),
                    {"document": document_id, "sha": raw_sha},
                ).scalar_one_or_none()
                if same_bytes is not None:
                    outcome, version_id = "unchanged", same_bytes
                elif (
                    latest is not None
                    and latest["comparison_rule"] == rule
                    and latest["comparison_sha256"] == comparison_sha
                ):
                    # Only non-content bytes differ: keep this fetch's exact bytes archived
                    # and hashed on the observation, but make no new version.
                    outcome, version_id, observation_uri = "unchanged", latest["id"], raw_uri
                else:
                    outcome = "new_version"
                    created_version = self._create_version(
                        connection,
                        fetched,
                        document_id=document_id,
                        latest=latest,
                        raw=raw,
                        raw_uri=raw_uri,
                        raw_sha=raw_sha,
                        rule=rule,
                        comparison_sha=comparison_sha,
                        media_type=media_type,
                    )
                    version_id = created_version["id"]

            observation: dict[str, Any] = {
                "id": uuid.uuid4(),
                "source_document_id": document_id,
                "source_version_id": version_id,
                "job_id": job_id,
                "outcome": outcome,
                "url": fetched.url,
                "fetched_at": fetched.fetched_at,
                "raw_sha256": raw_sha,
                "comparison_sha256": comparison_sha,
                "object_uri": observation_uri,
                "etag": fetched.validators.etag,
                "last_modified": fetched.validators.last_modified,
                "attempts": max(1, len(fetched.attempts)),
            }
            connection.execute(
                text(
                    "INSERT INTO fetch_observation (id, source_document_id, source_version_id,"
                    " job_id, outcome, url, fetched_at, raw_sha256, comparison_sha256,"
                    " object_uri, etag, last_modified, attempts) VALUES (:id,"
                    " :source_document_id, :source_version_id, :job_id, :outcome, :url,"
                    " :fetched_at, :raw_sha256, :comparison_sha256, :object_uri, :etag,"
                    " :last_modified, :attempts)"
                ),
                observation,
            )

            # Audit last: appending takes the chain's lock until commit.
            if document_created:
                self._audit(
                    connection,
                    "source_document.created",
                    "source_document",
                    document_id,
                    {"id": document_id, "company_id": company_id, **identity.__dict__},
                )
            if created_version is not None:
                self._audit(
                    connection,
                    "source_version.created",
                    "source_version",
                    version_id,
                    created_version,
                )
            self._audit(
                connection,
                f"fetch.{outcome}",
                "fetch_observation",
                observation["id"],
                observation,
            )
        return RecordedFetch(outcome, fetched.url, document_id, version_id, observation["id"])

    def _resolve(
        self,
        connection: Connection,
        identity: DocumentIdentity,
        company_id: uuid.UUID | None,
        first_seen_at: datetime,
    ) -> tuple[uuid.UUID, bool]:
        """The Source Document's ID, created if new, and locked for this transaction."""
        created = connection.execute(
            text(
                "INSERT INTO source_document (id, company_id, provider, canonical_url,"
                " origin_url, accession, form_type, document_type, source_type, title,"
                " publisher, source_tier, license_class, first_seen_at) VALUES (:id,"
                " :company_id, :provider, :canonical_url, :origin_url, :accession, :form_type,"
                " :document_type, :source_type, :title, :publisher, :source_tier,"
                " :license_class, :first_seen_at)"
                " ON CONFLICT (provider, canonical_url) DO NOTHING RETURNING id"
            ),
            {
                "id": uuid.uuid4(),
                "company_id": company_id,
                "origin_url": identity.canonical_url,
                "first_seen_at": first_seen_at,
                **identity.__dict__,
            },
        ).scalar_one_or_none()
        if created is not None:
            return created, True
        existing = connection.execute(
            text(
                "SELECT id FROM source_document"
                " WHERE provider = :provider AND canonical_url = :url FOR UPDATE"
            ),
            {"provider": identity.provider, "url": identity.canonical_url},
        ).scalar_one()
        return existing, False

    def _create_version(
        self,
        connection: Connection,
        fetched: FetchedDocument,
        *,
        document_id: uuid.UUID,
        latest: Any,
        raw: bytes,
        raw_uri: str,
        raw_sha: str,
        rule: str,
        comparison_sha: str,
        media_type: str,
    ) -> dict[str, Any]:
        candidate = fetched.candidate
        parse_fields = self._parse(raw, media_type)
        if latest is None:
            available_at, basis = candidate.available_at, candidate.available_at_basis
        else:
            available_at, basis = fetched.fetched_at, OBSERVED_REVISION
        version: dict[str, Any] = {
            "id": uuid.uuid4(),
            "source_document_id": document_id,
            "version_number": 1 if latest is None else latest["version_number"] + 1,
            "supersedes_version_id": None if latest is None else latest["id"],
            "raw_sha256": raw_sha,
            "comparison_sha256": comparison_sha,
            "comparison_rule": rule,
            "object_uri": raw_uri,
            "byte_size": len(raw),
            "media_type": media_type,
            **parse_fields,
            "event_at": None,
            "published_at": None,
            "available_at": available_at,
            "available_at_basis": basis,
            "fetched_at": fetched.fetched_at,
            "fetch_status": "ok",
            "metadata": _metadata(fetched),
        }
        ingested_at = connection.execute(
            text(
                "INSERT INTO source_version (id, source_document_id, version_number,"
                " supersedes_version_id, raw_sha256, comparison_sha256, comparison_rule,"
                " object_uri, byte_size, media_type, content_sha256, parsed_object_uri,"
                " parser_version, parse_status, parse_error, event_at, published_at,"
                " available_at, available_at_basis, fetched_at, fetch_status, metadata)"
                " VALUES (:id, :source_document_id, :version_number, :supersedes_version_id,"
                " :raw_sha256, :comparison_sha256, :comparison_rule, :object_uri, :byte_size,"
                " :media_type, :content_sha256, :parsed_object_uri, :parser_version,"
                " :parse_status, :parse_error, :event_at, :published_at, :available_at,"
                " :available_at_basis, :fetched_at, :fetch_status, CAST(:metadata AS jsonb))"
                " RETURNING ingested_at"
            ),
            {**version, "metadata": _json(version["metadata"])},
        ).scalar_one()
        return {**version, "ingested_at": ingested_at}

    def _parse(self, raw: bytes, media_type: str) -> dict[str, Any]:
        fields: dict[str, Any] = {
            "content_sha256": None,
            "parsed_object_uri": None,
            "parser_version": None,
            "parse_status": "not_applicable",
            "parse_error": None,
        }
        if not is_parseable(media_type):
            return fields
        try:
            parsed = parse(raw, media_type)
        except Exception as error:  # a parser bug must not lose the raw version
            return fields | {
                "parser_version": PARSER_VERSION,
                "parse_status": "failed",
                "parse_error": f"{type(error).__name__}: {error}",
            }
        assert parsed is not None
        return fields | {
            "content_sha256": parsed.sha256,
            "parsed_object_uri": self._archive.put(Namespace.PARSED, parsed.encoded()),
            "parser_version": parsed.parser_version,
            "parse_status": "parsed" if parsed.complete else "incomplete",
        }

    def _audit(
        self,
        connection: Connection,
        action: str,
        entity_type: str,
        entity_id: uuid.UUID,
        content: dict[str, Any],
    ) -> None:
        record(
            connection,
            self._actor,
            action,
            entity_type=entity_type,
            entity_id=str(entity_id),
            new_hash=content_hash(content),
        )


def _metadata(fetched: FetchedDocument) -> dict[str, Any]:
    """Adapter metadata kept with the version: what EDGAR said, and how it was fetched."""
    candidate = fetched.candidate
    metadata: dict[str, Any] = {
        "url": fetched.url,
        "http": {
            "etag": fetched.validators.etag,
            "last_modified": fetched.validators.last_modified,
        },
        "attempts": len(fetched.attempts),
        "discovered_at": _iso(candidate.discovered_at),
    }
    filing = candidate.filing
    if filing is not None:
        metadata |= {
            "cik": filing.cik,
            "company_name": filing.company_name,
            "accession_number": filing.accession_number,
            "form": filing.form,
            "filing_date": filing.filing_date.isoformat(),
            "report_date": filing.report_date.isoformat() if filing.report_date else None,
            "acceptance_datetime": _iso(filing.acceptance_datetime),
            "primary_document": filing.primary_document,
            "items": list(filing.items),
        }
    return metadata


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True)
