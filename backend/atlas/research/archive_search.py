"""Archive term search as a service (bottleneck-argument ticket 01): the archive's BM25 term
search (`atlas.evaluation.baseline.search`, which the pilot baseline runs) over the parsed,
English Source Versions of some companies available at an as-of time, for the reading agent
(ticket 03), the workbench and debugging (`GET /api/v1/archive-search`).

- **Which documents.** Each Source Document of the companies (an XBRL companyfacts document
  is no text) contributes its latest Source Version whose effective availability
  (`source_version_availability`) is at or before `as_of`: a later version never leaks in.
  Filings and call transcripts alike. Only a version with a parse that has text (`parsed`,
  `incomplete`) and in English (`en`, or no language recorded) is searched.
- **Which parse.** The current one (`atlas.ledger.current_parse`: a re-parse under the current
  parser when it has text, else the recorded parse), named in each hit as `parser_version`. A
  hit's offsets are code points into that parse's text, so a quote cut from a hit passes the
  span check (`atlas.assertions.check_quote`) when the Assertion names that parser version.
- **Ranking and repeats.** As the baseline: BM25 over the passages of all the documents
  together, at most `per_document` hits from one document, near-duplicate statements across
  filings one hit with the other documents in `also_in`.
- **Section.** Each hit names the section (`atlas.retention.sections`, the anchor retention and
  Assertions use) its passage starts in.
- **Cache.** The archive reads are kept in an in-process LRU of the last `TEXT_CACHE` (256)
  parsed texts, by the parse's archived object URI (a parse never changes); the passages, their
  tokens and the sections are cached per text too (`indexed_passages`, bound 256 texts;
  `_sections`, bound 256). A second query over the same companies reads neither the archive nor
  re-tokenizes. Memory use is bounded by those counts, a few hundred MB at most for filings.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from functools import lru_cache

from pydantic import BaseModel
from sqlalchemy import Engine, text

from atlas.archive import Archive
from atlas.evaluation.baseline import Document, search
from atlas.ledger.reads import current_parse
from atlas.research.search import query_terms
from atlas.retention.sections import Section, split_sections

TEXT_CACHE = 256
_WITH_TEXT = ("parsed", "incomplete")


class UnknownCompany(ValueError):
    """A company id that is not in the universe."""


class AlsoIn(BaseModel):
    """Another document that repeats the hit's statement, word for word or nearly."""

    source_version_id: uuid.UUID
    company_id: uuid.UUID
    title: str
    available_at: datetime


class ArchiveHit(BaseModel):
    """One passage of an archived document that matches the query."""

    source_version_id: uuid.UUID
    company_id: uuid.UUID
    company: str  # the slug
    title: str
    provider: str
    form_type: str | None
    document_type: str | None  # the kind: `10-K`, `8-K`, `EX-99.1`, a call-transcript type
    available_at: datetime
    parser_version: str
    section_anchor: str | None
    char_start: int  # code points into the named parse's text, like an Assertion's span
    char_end: int
    text: str
    score: float
    terms: list[str]  # the query's terms the passage contains
    also_in: list[AlsoIn]


class ArchiveSearch(BaseModel):
    query: str
    terms: list[str]
    as_of: datetime
    documents_searched: int
    hits: list[ArchiveHit]


class _Meta(BaseModel):
    company_id: uuid.UUID
    provider: str
    form_type: str | None
    document_type: str | None
    parser_version: str
    available_at: datetime


_VERSIONS = """
    SELECT DISTINCT ON (d.id)
           v.id, d.company_id, c.slug, d.provider, d.title, d.canonical_url, d.form_type,
           d.document_type, a.available_at
    FROM source_document d
    JOIN company c ON c.id = d.company_id
    JOIN source_version v ON v.source_document_id = d.id
    JOIN source_version_availability a ON a.source_version_id = v.id
    WHERE d.company_id = ANY(:companies) AND d.source_type <> 'xbrl_companyfacts'
      AND a.available_at <= :as_of
    ORDER BY d.id, a.available_at DESC, v.version_number DESC
"""


def archive_search(
    engine: Engine,
    archive: Archive,
    query: str,
    company_ids: Sequence[uuid.UUID],
    as_of: datetime,
    top: int = 20,
    per_document: int = 3,
) -> ArchiveSearch:
    """The `top` best passages for the query among the companies' documents at `as_of`
    (module docstring). Raises `UnknownCompany` for an id not in the universe."""
    as_of = as_of if as_of.tzinfo else as_of.replace(tzinfo=UTC)
    documents: list[Document] = []
    meta: dict[str, _Meta] = {}
    with engine.connect() as connection:
        known = {
            row.id
            for row in connection.execute(
                text("SELECT id FROM company WHERE id = ANY(:ids)"), {"ids": list(company_ids)}
            )
        }
        unknown = [str(each) for each in company_ids if each not in known]
        if unknown:
            raise UnknownCompany(f"unknown company: {', '.join(unknown)}")
        rows = (
            connection.execute(text(_VERSIONS), {"companies": list(company_ids), "as_of": as_of})
            .mappings()
            .all()
        )
        for row in rows:
            parse = current_parse(connection, row["id"])
            if (
                parse is None
                or parse.parse_status not in _WITH_TEXT
                or parse.parsed_object_uri is None
                or parse.language not in (None, "en")
            ):
                continue
            available_at = row["available_at"].astimezone(UTC)
            version_id = str(row["id"])
            documents.append(
                Document(
                    source_version_id=version_id,
                    company=row["slug"],
                    title=row["title"] or row["canonical_url"],
                    available_at=available_at.isoformat(),
                    text=_text(archive, parse.parsed_object_uri),
                )
            )
            meta[version_id] = _Meta(
                company_id=row["company_id"],
                provider=row["provider"],
                form_type=row["form_type"],
                document_type=row["document_type"],
                parser_version=parse.parser_version,
                available_at=available_at,
            )
    by_version = {document.source_version_id: document for document in documents}
    found = search(query, documents, top=top, per_document=per_document)
    hits: list[ArchiveHit] = []
    for hit in found:
        passage = hit.passage
        document = by_version[passage.source_version_id]
        about = meta[passage.source_version_id]
        hits.append(
            ArchiveHit(
                source_version_id=uuid.UUID(passage.source_version_id),
                company_id=about.company_id,
                company=document.company,
                title=document.title,
                provider=about.provider,
                form_type=about.form_type,
                document_type=about.document_type,
                available_at=about.available_at,
                parser_version=about.parser_version,
                section_anchor=_anchor(document.text, about, passage.char_start),
                char_start=passage.char_start,
                char_end=passage.char_end,
                text=passage.text,
                score=hit.score,
                terms=list(hit.terms),
                also_in=[
                    AlsoIn(
                        source_version_id=uuid.UUID(other),
                        company_id=meta[other].company_id,
                        title=by_version[other].title,
                        available_at=meta[other].available_at,
                    )
                    for other in hit.also_in
                ],
            )
        )
    return ArchiveSearch(
        query=query,
        terms=query_terms(query),
        as_of=as_of,
        documents_searched=len(documents),
        hits=hits,
    )


@lru_cache(maxsize=TEXT_CACHE)
def _text(archive: Archive, uri: str) -> str:
    return archive.get(uri).decode("utf-8")


@lru_cache(maxsize=TEXT_CACHE)
def _sections(parsed: str, form: str | None, primary: bool) -> tuple[Section, ...]:
    return tuple(split_sections(parsed, form=form, primary=primary))


def _anchor(parsed: str, about: _Meta, position: int) -> str | None:
    primary = about.document_type is not None and about.document_type == about.form_type
    sections = _sections(parsed, about.form_type, primary)
    return next((s.anchor for s in sections if s.start <= position < s.end), None)
