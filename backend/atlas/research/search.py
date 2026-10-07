"""Plain term search over archived parsed text: the tokenizer, the passages and the BM25
ranking that the archive-search baseline (`atlas.evaluation.baseline`) and the Investigator's
passage selection (`atlas.claims.selection`) share (memory-directed reading ticket 05).

Nothing here is learned or tuned to a question, and nothing calls a model or Memory:

- **Terms.** A text's words, lowercased (letters and digits; "1.6t" and "2.02" stay whole),
  each stemmed by dropping a plural's ending ("substrates" matches "substrate", "supplies"
  matches "supply"). `query_terms` also drops stopwords and question words and keeps each
  term once, in the query's order. No synonyms: "InP" doesn't find "indium phosphide".
- **Passages.** `passage_spans` cuts a text into passages of about `MIN_CHARS` to
  `MAX_CHARS`: lines are joined until a passage has at least `MIN_CHARS`, so a heading or a
  table row travels with its neighbour; a line longer than `MAX_CHARS` is cut at sentence
  ends. Offsets are code points into the text, like an Assertion's span.
- **Ranking.** `bm25` scores each of a set of texts against the terms with Okapi BM25 (`K1`,
  `B`); the inverse document frequencies and the average length are the set's own, so a
  score compares texts of one set only.
- **Overlap.** `overlap` counts how many of a query's terms a text contains: how a reading
  pointer's Memory text finds its window in the section it points to.
"""

import math
import re
from collections import Counter
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from functools import lru_cache

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
class Scored:
    """One text's BM25 score and the query's terms it contains (none: score 0.0)."""

    score: float
    terms: tuple[str, ...]


def query_terms(question: str) -> list[str]:
    """The question's content words, stemmed, each once, in the question's order."""
    words = [word for word in _TOKEN.findall(question.lower()) if word not in _STOPWORDS]
    return list(dict.fromkeys(stem(word) for word in words))


def tokens(text: str) -> list[str]:
    """Every word of the text, lowercased and stemmed (stopwords included)."""
    return [stem(token) for token in _TOKEN.findall(text.lower())]


def stem(token: str) -> str:
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
        return token[:-1]
    return token


def normalized(text: str) -> str:
    """The text lowercased, its runs of whitespace single spaces."""
    return " ".join(text.lower().split())


def passage_spans(text: str) -> list[tuple[int, int]]:
    """The text as passages of about `MIN_CHARS` to `MAX_CHARS`: their [start, end) spans."""
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
    return [(begin, end) for begin, end in spans if end > begin]


INDEX_CACHE_TEXTS = 256


@lru_cache(maxsize=INDEX_CACHE_TEXTS)
def indexed_passages(text: str) -> tuple[tuple[int, int, tuple[str, ...]], ...]:
    """The text's passages with their tokens: (start, end, tokens) per `passage_spans` span.
    An in-process LRU of the `INDEX_CACHE_TEXTS` (256) most recently used texts, so a second
    query over the same documents neither cuts nor tokenizes them again."""
    return tuple((begin, end, tuple(tokens(text[begin:end]))) for begin, end in passage_spans(text))


def bm25(terms: Sequence[str], texts: Sequence[Sequence[str]]) -> list[Scored]:
    """Each text's Okapi BM25 score against `terms`, in the texts' order. A text is its
    tokens (`tokens`); the document frequencies and the average length are those of `texts`."""
    counted = [(Counter(text), len(text)) for text in texts]
    if not counted or not terms:
        return [Scored(0.0, ()) for _ in counted]
    average_length = sum(length for _, length in counted) / len(counted)
    containing = {term: sum(1 for counts, _ in counted if term in counts) for term in terms}
    scored: list[Scored] = []
    for counts, length in counted:
        found = tuple(term for term in terms if term in counts)
        score = 0.0
        for term in found:
            idf = math.log(1 + (len(counted) - containing[term] + 0.5) / (containing[term] + 0.5))
            frequency = counts[term]
            norm = K1 * (1 - B + B * length / average_length)
            score += idf * frequency * (K1 + 1) / (frequency + norm)
        scored.append(Scored(score, found))
    return scored


def overlap(terms: Sequence[str], text: Collection[str]) -> int:
    """How many of `terms` (each once) the text's tokens contain."""
    present = text if isinstance(text, frozenset) else frozenset(text)
    return sum(1 for term in dict.fromkeys(terms) if term in present)


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
