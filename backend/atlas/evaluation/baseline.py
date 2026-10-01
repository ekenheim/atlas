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
- **Near-duplicates.** A filing restates the filing before it with small edits, which the
  exact comparison above doesn't catch, so a hit is a statement, not a passage. Passages are
  taken best first. The first wording of a statement takes with it every passage of a document
  available at another time that says nearly the same (`NEAR_DUPLICATE`, below); a passage met
  later that says nearly the same as a hit shown is dropped for that hit. The hit shows the
  wording of the newest of those documents that hasn't shown its `per_document` hits yet (a
  dropped wording uses none of its document's share) and names the other documents in
  `also_in`, those of the word-for-word copies too: how often the statement is repeated. The
  hits stay in the order of their own scores. Each hit is compared once with every passage
  that has a term of the question (20 hits, a few thousand passages each), never passage with
  passage.
- **Coverage.** `covering_quotes` says which accepted Claims' quotes a passage contains
  (whitespace-insensitive), whatever document or parse the Claim cites: the same sentence in
  another filing is the same finding. A quote that straddles two passages is found in neither;
  the reviewer judges those.

The tokenizer, the passages and BM25 are `atlas.research.search`, which the Investigator's
passage selection uses too (memory-directed reading ticket 05); this module keeps its names.
Near-duplicate dropping is this module's alone: the selection doesn't use it.

**What "nearly the same" is** (memory-directed reading ticket 10). The Jaccard overlap of two
passages' sets of terms (every word, stemmed as for the ranking, stopwords included) is at
least `NEAR_DUPLICATE`, 0.75. Measure and threshold were chosen on the pilot's case: the
breadth run of investigation 2, whose top five hits were one export-permit paragraph from five
AXT filings (`.scratch/pilot/results.md`, "Breadth runs on 0.2.5"). Among the 80 saved hits of
the four breadth baselines:

- Four of those five overlap 0.86 to 1.00: the same paragraph with a year added to two dates,
  a tense changed and a closing sentence added or dropped. These must be one hit.
- The lowest pairs that are still one paragraph repeated: 0.79, a paragraph and the same
  paragraph with the short one before it joined to its passage; 0.80, a paragraph and the next
  filing's version, which keeps all of it and adds two sentences.
- The highest pairs that say different things: 0.67 and 0.68, the paragraph as written before
  the first export permits were granted, and a later version that reports them and no longer
  has the earlier one's opening. The fifth of the five hits, the oldest, is such an earlier
  version too: 0.57 to 0.59 from the other four. These must stay separate hits.
- Every other pair is at 0.64 or below.

No pair lies between 0.68 and 0.79, and 0.75 is in that gap, nearer the pairs to drop: a
repeat left in costs the reviewer a minute, a different statement dropped is hidden from the
review. The line is a judgement, not a property of the text: a paragraph drifts from filing to
filing, and among the 300 best passages for a question in the whole cached archive there are
pairs at every value. The hand-shaped paragraphs of `tests/unit/test_archive_baseline.py` are
modelled on these pairs: the reworded versions overlap 0.85 to 1.00, the earlier version 0.63
to 0.68, the other paragraph on the subject 0.18 to 0.19.

Stopwords stay in the sets because they widen the gap (without them it is 0.65 to 0.72).
Three-word shingles separate no better (their gap is 0.56 to 0.67) and a copy-edit moves them
more: a company's "About" paragraph with a few words changed is 0.94 by terms and 0.68 by
shingles.

Limits. Only documents available at different times are compared: what is dropped is one
filing restating another, so a filing that repeats itself, or its exhibit, still gives each
repeat as a hit (at most `per_document`). A passage is compared with the hits, not with every
other passage, so of three versions drifting apart the third may be a hit of its own. And when
the newest document has shown its `per_document` hits, a statement is shown in an older
wording and names the newer document in `also_in`.
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

NEAR_DUPLICATE = 0.75

__all__ = [
    "K1",
    "MAX_CHARS",
    "MIN_CHARS",
    "NEAR_DUPLICATE",
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
    # the other documents (source version ids, newest first) with a passage dropped as this
    # one's copy or near-duplicate
    also_in: tuple[str, ...] = ()


@dataclass(frozen=True)
class _Wording:
    """A passage with a term of the question: one wording of a statement."""

    passage: Passage
    score: float
    terms: tuple[str, ...]
    available_at: str
    words: frozenset[str]  # its terms, all of them: what near-duplicates are compared by
    copies: tuple[str, ...]  # the documents whose word-for-word copy of it was dropped


@dataclass
class _Statement:
    """A hit while the search runs: the wording shown and the wordings dropped for it."""

    shown: _Wording
    dropped: list[_Wording]


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
    """The `top` passages for the question, best first (module docstring: ranking and
    near-duplicates)."""
    terms = query_terms(question)
    newest_first = sorted(documents, key=lambda d: d.available_at, reverse=True)
    candidates: list[tuple[Document, Passage, list[str]]] = []
    first: dict[str, int] = {}  # a passage's normalized text -> its candidate
    copies: dict[int, list[str]] = {}
    for document in newest_first:
        for passage in passages(document):
            key = normalized(passage.text)
            if key in first:
                copies.setdefault(first[key], []).append(document.source_version_id)
                continue
            first[key] = len(candidates)
            candidates.append((document, passage, tokens(passage.text)))
    if not candidates or not terms:
        return []
    scored = [
        _Wording(
            passage,
            round(found.score, 4),
            found.terms,
            document.available_at,
            frozenset(words),
            tuple(copies.get(index, ())),
        )
        for index, ((document, passage, words), found) in enumerate(
            zip(candidates, bm25(terms, [words for _, _, words in candidates]), strict=True)
        )
        if found.terms
    ]
    ranked = sorted(scored, key=lambda w: w.score, reverse=True)  # stable: newest first

    statements: list[_Statement] = []
    taken: Counter[str] = Counter()  # the hits each document shows
    placed = [False] * len(ranked)
    for index, wording in enumerate(ranked):
        if placed[index]:
            continue
        known = next((s for s in statements if _near_duplicates(wording, s.shown)), None)
        if known is not None:
            placed[index] = True
            known.dropped.append(wording)
            continue
        if taken[wording.passage.source_version_id] >= per_document:
            continue  # no hit of its own; a later statement may still take it as a wording
        # A new statement: this wording and every one not yet placed that says nearly the same,
        # shown from the newest of their documents with a share left (this wording's has one).
        placed[index] = True
        wordings = [wording]
        for other, candidate in enumerate(ranked):
            if not placed[other] and _near_duplicates(candidate, wording):
                placed[other] = True
                wordings.append(candidate)
        shown = max(  # of one document's wordings the best-ranked: `max` keeps the first
            (w for w in wordings if taken[w.passage.source_version_id] < per_document),
            key=lambda w: w.available_at,
        )
        taken[shown.passage.source_version_id] += 1
        statements.append(_Statement(shown, [w for w in wordings if w is not shown]))
        if len(statements) == top:
            break

    order = {document.source_version_id: at for at, document in enumerate(newest_first)}
    hits = [
        Hit(s.shown.passage, s.shown.score, s.shown.terms, _other_documents(s, order))
        for s in statements
    ]
    return sorted(hits, key=lambda h: h.score, reverse=True)  # stable: as the statements came


def _near_duplicates(one: _Wording, other: _Wording) -> bool:
    """Whether the two passages, of documents available at different times, say nearly the
    same (module docstring)."""
    if one.available_at == other.available_at:
        return False
    fewer, more = sorted((len(one.words), len(other.words)))
    if fewer < NEAR_DUPLICATE * more:  # so different in length that the overlap can't reach it
        return False
    shared = len(one.words & other.words)
    return shared >= NEAR_DUPLICATE * (len(one.words) + len(other.words) - shared)


def _other_documents(statement: _Statement, order: Mapping[str, int]) -> tuple[str, ...]:
    """The documents, newest first, of the copies and wordings dropped for the hit shown."""
    shown = statement.shown
    found = {*shown.copies}
    for wording in statement.dropped:
        found |= {wording.passage.source_version_id, *wording.copies}
    found.discard(shown.passage.source_version_id)
    return tuple(sorted(found, key=lambda document: order[document]))


def covering_quotes(passage_text: str, quotes: Mapping[str, str]) -> list[str]:
    """The keys of the quotes the passage contains, whitespace aside."""
    within = normalized(passage_text)
    return [key for key, quote in quotes.items() if normalized(quote) in within]
