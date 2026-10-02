"""Where a fact's chunk lies in its section (memory-quality ticket 08; docs/decisions.md,
"Chunk-exact pointers").

Hindsight cuts a retained section into chunks and extracts each fact from one of them; the
fact names it (`chunk_id`, `<bank>_<document>_<index>`). On 0.10.2 a chunk's text is a
verbatim slice of the retained content, which is the section's parsed text, but the API
gives no offsets (`docs/hindsight-feature-matrix.md`, question (b); recordings `chunks/`). So
a chunk is **located**: its text is found in the archived section, the chunks searched in
`chunk_index` order, each search starting where the previous chunk ended (the breaks between
chunks belong to none).

The chunk a recall answer carries (`include.chunks`) is used when it settles the place alone:
its text whole (not `truncated`) and occurring exactly once in the section, where the ordered
search could only find it too. Otherwise the document's chunks are listed
(`HindsightGateway.document_chunks`, once per document) and located in order. A chunk found
neither way, a fact with no chunk, or a document Hindsight no longer has, leaves the fact
unplaced, and the pointer falls back to the window its memory's words match best.

Memory stays an index: the chunk's text is used to find a span of the archived section and
goes no further. It is never stored, quoted, or sent to a role; only its ID and span are kept.
"""

import uuid
from collections.abc import Iterable, Mapping, Sequence

from sqlalchemy import Engine, text

from atlas.archive import Archive
from atlas.hindsight import HindsightGateway, HindsightHTTPError, RecallChunk
from atlas.research.provenance import CitationSource


def locate(section: str, chunks: Iterable[tuple[str, str]]) -> dict[str, tuple[int, int]]:
    """The spans (offsets into `section`) of the chunks, given as (chunk ID, text) in
    `chunk_index` order, that occur verbatim: each searched from where the previous chunk
    found ended. A chunk not found is left out and moves nothing."""
    spans: dict[str, tuple[int, int]] = {}
    cursor = 0
    for chunk_id, chunk_text in chunks:
        if not chunk_text:
            continue
        at = section.find(chunk_text, cursor)
        if at < 0:
            continue
        spans[chunk_id] = (at, at + len(chunk_text))
        cursor = at + len(chunk_text)
    return spans


class ChunkPlacer:
    """Places the facts of one recall answer in their sections; caches parsed texts and
    document listings for its life."""

    def __init__(
        self,
        engine: Engine,
        archive: Archive,
        gateway: HindsightGateway,
        answered: Mapping[str, RecallChunk],
    ) -> None:
        self._engine = engine
        self._archive = archive
        self._gateway = gateway
        self._answered = answered
        self._parsed: dict[uuid.UUID, str | None] = {}
        self._listed: dict[str, dict[str, tuple[int, int]]] = {}

    def place_all(self, sources: Sequence[CitationSource]) -> None:
        """Set each source's chunk span (parsed-text offsets) where its chunk is located."""
        for source in sources:
            span = self.place(source)
            if span is not None:
                source.chunk_char_start, source.chunk_char_end = span

    def place(self, source: CitationSource) -> tuple[int, int] | None:
        """The span of the source fact's chunk in the parsed text, within its section; None
        when it can't be located."""
        if source.chunk_id is None:
            return None
        section = self._section(source)
        if section is None:
            return None
        found: tuple[int, int] | None = None
        answered = self._answered.get(source.chunk_id)
        if answered is not None and not answered.truncated and answered.text:
            if section.count(answered.text) == 1:
                at = section.index(answered.text)
                found = (at, at + len(answered.text))
        if found is None:
            found = self._listing(source, section).get(source.chunk_id)
        if found is None:
            return None
        return source.section_char_start + found[0], source.section_char_start + found[1]

    def _listing(self, source: CitationSource, section: str) -> dict[str, tuple[int, int]]:
        if source.document_id not in self._listed:
            try:
                chunks = self._gateway.document_chunks(source.document_id)
            except HindsightHTTPError as error:
                if error.status_code == 429 or error.status_code >= 500:
                    raise  # a quota or an outage: the caller's to handle
                chunks = []  # the document is gone, or the listing refused: unplaced
            self._listed[source.document_id] = locate(
                section, ((chunk.chunk_id, chunk.chunk_text) for chunk in chunks)
            )
        return self._listed[source.document_id]

    def _section(self, source: CitationSource) -> str | None:
        version = source.source_version_id
        if version not in self._parsed:
            with self._engine.connect() as connection:
                uri = connection.execute(
                    text("SELECT parsed_object_uri FROM source_version WHERE id = :id"),
                    {"id": version},
                ).scalar_one_or_none()
            self._parsed[version] = None if uri is None else self._archive.get(uri).decode("utf-8")
        parsed = self._parsed[version]
        if parsed is None:
            return None
        return parsed[source.section_char_start : source.section_char_end]
