"""The archive-search baseline: what a plain term search of the archive finds for a question.

The pilot holds each investigation against it (`.scratch/atlas-pilot-review/`, "The
archive-search baseline"): the research card must cover at least half of the on-question
passages this search surfaces. It is deliberately the simplest thing a researcher could do
with the archive and no model: the question's content words, BM25 over passages of the
archived parsed text, nothing learned and nothing tuned to a question.

- **Passages.** A document's parsed text, line by line. Lines are joined until a passage has
  at least `MIN_CHARS`, so a heading or a table row travels with its neighbour; a line longer
  than `MAX_CHARS` is cut at sentence ends. Offsets are code points into the parsed text, like
  an Assertion's span.
- **Terms.** The question's words, lowercased, without stopwords and question words, each
  once; a plural's ending is dropped ("substrates" matches "substrate", "supplies" matches
  "supply"). No synonyms: "InP" doesn't find "indium phosphide" unless the question says both.
- **Ranking.** Okapi BM25 (`K1`, `B`) over every passage of every document. Documents are
  searched newest first, a passage whose text already occurred (a 10-Q repeating the 10-K) is
  dropped, and one document gives at most `per_document` hits, so a long filing can't fill
  the list.
- **Coverage.** `covering_quotes` says which accepted Claims' quotes a passage contains
  (whitespace-insensitive), whatever document or parse the Claim cites: the same sentence in
  another filing is the same finding. A quote that straddles two passages is found in neither;
  the reviewer judges those.

The tokenizer, the passages and BM25 are `atlas.research.search`, which the Investigator's
passage selection uses too (memory-directed reading ticket 05); this module keeps its names.
"""

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from atlas.research.search import (
    K1,
    MAX_CHARS,
    MIN_CHARS,
    B,
    bm25,
    normalized,
    passage_spans,
    query_terms,
    tokens,
)

__all__ = [
    "K1",
    "MAX_CHARS",
    "MIN_CHARS",
    "B",
    "Document",
    "Hit",
    "Passage",
    "covering_quotes",
    "passages",
    "query_terms",
    "search",
]


@dataclass(frozen=True)
class Document:
    """One archived Source Version's parsed text, as the search reads it."""

    source_version_id: str
    company: str
    title: str
    available_at: str  # ISO 8601; documents are searched newest first
    text: str


@dataclass(frozen=True)
class Passage:
    source_version_id: str
    char_start: int
    char_end: int
    text: str


@dataclass(frozen=True)
class Hit:
    passage: Passage
    score: float
    terms: tuple[str, ...]  # the question's terms the passage contains


def passages(document: Document) -> list[Passage]:
    """The document's parsed text as passages of about `MIN_CHARS` to `MAX_CHARS`."""
    text = document.text
    return [
        Passage(document.source_version_id, begin, end, text[begin:end])
        for begin, end in passage_spans(text)
    ]


def search(
    question: str, documents: Sequence[Document], *, top: int = 20, per_document: int = 3
) -> list[Hit]:
    """The `top` passages for the question, best first (module docstring: ranking)."""
    terms = query_terms(question)
    candidates: list[tuple[Passage, list[str]]] = []
    seen: set[str] = set()
    for document in sorted(documents, key=lambda d: d.available_at, reverse=True):
        for passage in passages(document):
            key = normalized(passage.text)
            if key in seen:
                continue
            seen.add(key)
            candidates.append((passage, tokens(passage.text)))
    if not candidates or not terms:
        return []
    scored = [
        Hit(passage, round(found.score, 4), found.terms)
        for (passage, _), found in zip(
            candidates, bm25(terms, [words for _, words in candidates]), strict=True
        )
        if found.terms
    ]

    hits: list[Hit] = []
    taken: Counter[str] = Counter()
    for hit in sorted(scored, key=lambda h: h.score, reverse=True):  # stable: newest first
        if taken[hit.passage.source_version_id] >= per_document:
            continue
        taken[hit.passage.source_version_id] += 1
        hits.append(hit)
        if len(hits) == top:
            break
    return hits


def covering_quotes(passage_text: str, quotes: Mapping[str, str]) -> list[str]:
    """The keys of the quotes the passage contains, whitespace aside."""
    within = normalized(passage_text)
    return [key for key, quote in quotes.items() if normalized(quote) in within]
