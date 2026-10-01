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
"""

import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

MIN_CHARS = 300
MAX_CHARS = 1500
K1 = 1.5
B = 0.75

_TOKEN = re.compile(r"[a-z0-9]+(?:\.[0-9]+[a-z]*)?")
_STOPWORDS = frozenset(
    """
    a about all also an and any are as at be been being but by can could do does
    for from had has have how if in into is it its may more most much no not of on or our
    should so such than that the their them then there these they this those to under up was
    we were what when where which who whom whose why will with would
    """.split()
)


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


def query_terms(question: str) -> list[str]:
    """The question's content words, stemmed, each once, in the question's order."""
    words = [word for word in _TOKEN.findall(question.lower()) if word not in _STOPWORDS]
    return list(dict.fromkeys(_stem(word) for word in words))


def passages(document: Document) -> list[Passage]:
    """The document's parsed text as passages of about `MIN_CHARS` to `MAX_CHARS`."""
    text = document.text
    spans: list[tuple[int, int]] = []
    start: int | None = None
    for unit_start, unit_end in _units(text):
        if start is None:
            start = unit_start
        if unit_end - start >= MIN_CHARS:
            spans.append((start, unit_end))
            start = None
    if start is not None:  # what is left is short: it joins the passage before it
        if spans:
            spans[-1] = (spans[-1][0], len(text.rstrip()))
        else:
            spans.append((start, len(text.rstrip())))
    return [
        Passage(document.source_version_id, begin, end, text[begin:end])
        for begin, end in spans
        if end > begin
    ]


def search(
    question: str, documents: Sequence[Document], *, top: int = 20, per_document: int = 3
) -> list[Hit]:
    """The `top` passages for the question, best first (module docstring: ranking)."""
    terms = query_terms(question)
    candidates: list[tuple[Passage, Counter[str], int]] = []
    seen: set[str] = set()
    for document in sorted(documents, key=lambda d: d.available_at, reverse=True):
        for passage in passages(document):
            key = _normalized(passage.text)
            if key in seen:
                continue
            seen.add(key)
            tokens = _tokens(passage.text)
            candidates.append((passage, Counter(tokens), len(tokens)))
    if not candidates or not terms:
        return []

    average_length = sum(length for _, _, length in candidates) / len(candidates)
    containing = {term: sum(1 for _, counts, _ in candidates if term in counts) for term in terms}
    scored: list[Hit] = []
    for passage, counts, length in candidates:
        found = tuple(term for term in terms if term in counts)
        if not found:
            continue
        score = 0.0
        for term in found:
            idf = math.log(
                1 + (len(candidates) - containing[term] + 0.5) / (containing[term] + 0.5)
            )
            frequency = counts[term]
            norm = K1 * (1 - B + B * length / average_length)
            score += idf * frequency * (K1 + 1) / (frequency + norm)
        scored.append(Hit(passage, round(score, 4), found))

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
    normalized = _normalized(passage_text)
    return [key for key, quote in quotes.items() if _normalized(quote) in normalized]


def _tokens(text: str) -> list[str]:
    return [_stem(token) for token in _TOKEN.findall(text.lower())]


def _stem(token: str) -> str:
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
        return token[:-1]
    return token


def _normalized(text: str) -> str:
    return " ".join(text.lower().split())


def _units(text: str) -> list[tuple[int, int]]:
    """Each non-empty line's span; a line longer than `MAX_CHARS` cut after sentence ends."""
    units: list[tuple[int, int]] = []
    position = 0
    for line in text.split("\n"):
        end = position + len(line)
        if line.strip():
            begin = position
            while end - begin > MAX_CHARS:
                cut = text.rfind(". ", begin, begin + MAX_CHARS)
                stop = cut + 2 if cut > begin else begin + MAX_CHARS
                units.append((begin, stop))
                begin = stop
            units.append((begin, end))
        position = end + 1
    return units
