"""The speaker of a cited transcript quote, for the judge and the grounding check
(atlas-beliefs ticket 25; `docs/decisions.md`, "The judge knows a transcript quote's speaker").

A call or conference transcript's quote is one paragraph's words, and the paragraph opens with
its speaker's label ("Name (Title, Firm)"; `atlas.claims.speakers`). A Claim stores that label
when it is accepted (`claim.speaker`); a Fact stores nothing, and the Facts already recorded
are the ones the production re-run cites. So a Fact's label is read where it is judged, from
the archived parse its span is in (the assertion's `parser_version`, else the recorded parse):
`with_speakers` gives each Fact row of a transcript a `speaker` key holding the label, which
`atlas.investigations.meaning.judged_claim` sends beside the quote, `finding_metadata` lets a
clause name and `atlas.investigations.grounding.claim_grounds` counts as grounds. A row of any
other document gets none, so a filing's judge request is what it was.

The label is returned whoever speaks (`atlas.claims.speakers.label_at`): an analyst's
question is still an analyst's, and a statement attributing it to the company is exactly what
the judge must be able to see. A span over two speakers' paragraphs, an unlabelled paragraph,
a parse that has no text or an archive that cannot be read gives no speaker: the judge is then
sent what it was sent before, never a guess.
"""

import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import Connection, text

from atlas.archive import Archive, ArchiveError
from atlas.claims.speakers import TRANSCRIPT_SOURCE_TYPE, label_at
from atlas.ledger.reads import get_parse

_TRANSCRIPTS = (
    "SELECT v.id FROM source_version v JOIN source_document d ON d.id = v.source_document_id"
    " WHERE v.id = ANY(:ids) AND d.source_type = :transcript"
)


def with_speakers(
    connection: Connection, archive: Archive, rows: Sequence[Mapping[Any, Any]]
) -> list[Mapping[Any, Any]]:
    """`rows` (Fact rows: `source_version_id`, `span_start`, `span_end`, and the assertion's
    `parser_version` when known) with a `speaker` label added to each row that quotes a call
    or conference transcript and has none yet. Other rows are returned as they are."""
    wanted = {
        row["source_version_id"]
        for row in rows
        if not row.get("speaker") and row.get("source_version_id") is not None
    }
    if not wanted:
        return list(rows)
    transcripts = set(
        connection.execute(
            text(_TRANSCRIPTS), {"ids": list(wanted), "transcript": TRANSCRIPT_SOURCE_TYPE}
        ).scalars()
    )
    if not transcripts:
        return list(rows)
    texts: dict[tuple[uuid.UUID, str | None], str | None] = {}

    def parsed(version_id: uuid.UUID, parser_version: str | None) -> str | None:
        key = (version_id, parser_version)
        if key not in texts:
            texts[key] = _parsed_text(connection, archive, version_id, parser_version)
        return texts[key]

    out: list[Mapping[Any, Any]] = []
    for row in rows:
        version_id: uuid.UUID | None = row.get("source_version_id")
        if row.get("speaker") or version_id is None or version_id not in transcripts:
            out.append(row)
            continue
        document = parsed(version_id, row.get("parser_version"))
        label = (
            label_at(document, (int(row["span_start"]), int(row["span_end"])))
            if document is not None
            else None
        )
        out.append(row if label is None else {**row, "speaker": label})
    return out


def _parsed_text(
    connection: Connection, archive: Archive, version_id: uuid.UUID, parser_version: str | None
) -> str | None:
    parse = get_parse(connection, version_id, parser_version)
    if parse is None or parse.parsed_object_uri is None:
        return None
    try:
        return archive.get(parse.parsed_object_uri).decode("utf-8")
    except (ArchiveError, UnicodeDecodeError):
        return None
