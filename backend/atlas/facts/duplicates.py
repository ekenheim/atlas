"""One Fact per span (bottleneck-argument ticket 10; docs/decisions.md, "One Fact per span").

The Readers of an argument investigation recorded the same sentence several times: one Reader
with slightly different offsets, and several Readers each for its own step. Measured over the 11
reviewed argument runs (0.5.3 Q1-5, 0.5.4 Q1, Q2 and Q5, 0.5.5 Q1-3; 1,840 Facts, every one
labelled; `.scratch/tools/fact_duplicates.py`): 574 Facts (31%) overlapped an earlier Fact of the
same Source Version, always of the same company; 75 had the same span or the same folded quote
(73 of them across steps), 452 a span containing or contained in the other's, 47 a partial
overlap; 242 were across steps. On 0.5.5's question 2, 9 of the 14 wrong Facts were copies: two
mistakes (the CHIPS funding as `regulatory`, "might not be enough" as `in_effect`), each counted
three times by the Skeptic, the judges and the Editor.

The verdict pairs, original -> duplicate, over the 11 runs: right -> right 412, wrong -> wrong
33, right -> wrong 33, wrong -> right 42. Keeping the first is precision-neutral (per run within
-2.5 to +2.8 points of today). The rule keeps what the measurement supports:

(a) the same span, or the same quote folded (`normalized_quote`), of the same company in the
    same Source Version, whatever the step or status: 126 Facts over the 11 runs (14 wrong, 107
    right among them);
(b) an overlapping span of the same company and Source Version with the same status and an
    alike statement (`alike`: word-set Jaccard >= `JACCARD_ALIKE`): 324 (32 wrong, 267 right).

Overlap alone, whatever the statement, would have removed 489 (53 wrong, 397 right); rejected,
because it refuses distinct clauses of one sentence (another status, or another fact stated).

`duplicate_of` is pure: the Reader (`atlas.investigations.reader`) gives it the Fact it is
about to record and the investigation's Facts of that Source Version, its own session's first.
"""

import re
import uuid
from collections.abc import Iterable
from dataclasses import dataclass

from atlas.claims.predicates import fold

JACCARD_ALIKE = 0.5
# Words that say nothing of what a statement states.
STOP_WORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "of",
        "to",
        "and",
        "in",
        "its",
        "it",
        "is",
        "that",
        "for",
        "s",
        "says",
        "said",
        "states",
    }
)
_WORD = re.compile(r"[a-z0-9]+")
_SPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class FactSpan:
    """A Fact, recorded or about to be, as the duplicate rule reads it. `session_key` names
    the Reader session that holds it (None: read from the ledger, another session's)."""

    fact_id: uuid.UUID | None  # None: not recorded yet
    source_version_id: uuid.UUID
    company_id: uuid.UUID
    span_start: int
    span_end: int
    quote: str
    status: str
    statement: str
    step: str
    session_key: str | None


def normalized_quote(quote: str) -> str:
    """The quote through the typographic fold (`atlas.claims.predicates.fold`), its runs of
    whitespace one space, lower case, without a trailing `.`, `,`, `;` or `:`."""
    return _SPACE.sub(" ", fold(quote)).strip().lower().rstrip(".,;:").rstrip()


def _words(text: str) -> set[str]:
    return {word for word in _WORD.findall(text.lower()) if word not in STOP_WORDS}


def alike(a: str, b: str) -> bool:
    """Whether two statements say the same: the Jaccard index of their word sets (`[a-z0-9]+`
    tokens, lower case, `STOP_WORDS` left out) is at least `JACCARD_ALIKE`."""
    first, second = _words(a), _words(b)
    union = first | second
    if not union:
        return True
    return len(first & second) / len(union) >= JACCARD_ALIKE


def duplicate_of(candidate: FactSpan, existing: Iterable[FactSpan]) -> FactSpan | None:
    """The first of `existing` (in its order) that `candidate` duplicates, or None. Each is of
    the same Source Version and company and (a) has the same span or the same normalized
    quote, or (b) overlaps the candidate's span with the same status and an alike statement."""
    quote = normalized_quote(candidate.quote)
    for other in existing:
        if (
            other.source_version_id != candidate.source_version_id
            or other.company_id != candidate.company_id
        ):
            continue
        if (other.span_start, other.span_end) == (candidate.span_start, candidate.span_end):
            return other
        if normalized_quote(other.quote) == quote:
            return other
        overlaps = candidate.span_start < other.span_end and other.span_start < candidate.span_end
        if (
            overlaps
            and other.status == candidate.status
            and alike(other.statement, candidate.statement)
        ):
            return other
    return None
