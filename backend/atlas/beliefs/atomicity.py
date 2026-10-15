"""A Belief is one proposition: one claim, one period, one actor (atlas-beliefs ticket 23).

The MCP session of 2026-10-15 proposed eleven Beliefs and six were compound (several clauses of
one document joined), which `joins_dated_documents` cannot see: it compares the cited
documents' dates, not the statement's own words. This is the check on the words, run before the
judge is asked (it costs no call) and conservative on purpose: a statement is compound only
when it shows one of these marks, each a join a reader can point to.

- more than one sentence;
- a semicolon;
- "respectively", which pairs several subjects with several figures;
- several periods: two different quarters or halves, two different fiscal years, or three
  different calendar years ("revenue grew from $1 billion in 2024 to $2 billion in 2025" names
  two years and one claim).

What it cannot see (two actors, or two claims in one sentence joined by "and") is the judge's
to find and the author's to split. `compound_reasons` returns why the statement is compound, in
words an author can act on; empty: nothing found.
"""

import re

# Abbreviations whose full stop does not end a sentence, and an initial's ("Lisa T. Su").
_ABBREVIATIONS = re.compile(
    r"\b(?:U\.S|U\.K|E\.U|Inc|Corp|Co|Cos|Ltd|vs|approx|No|Nos|Mr|Ms|Mrs|Dr|St|Jr|Sr|Mt|etc)\."
    r"|\be\.g\.|\bi\.e\.|\b[A-Z]\.(?=\s)"
)
_SENTENCE_END = re.compile(r"[.!?][\"')\]]*\s+(?=[A-Z0-9\"“(\[])")
# One alternation, so a longer label wins over the shorter one inside it: "Q3 FY2026" is one
# quarter, not a quarter and a fiscal year.
_PERIOD = re.compile(
    r"\b(?P<quarter>(?:Q[1-4]|H[12])(?:\s*(?:FY|CY)?\s*'?\d{2,4})?)\b"
    r"|\b(?P<fiscal>(?:FY|CY)\s*'?\d{2,4})\b"
    r"|\b(?P<year>(?:19|20)\d{2})\b"
)
MAX_YEARS = 2  # distinct calendar years one proposition may name


def _normal(label: str) -> str:
    return re.sub(r"[\s']", "", label).upper()


def _sentences(statement: str) -> int:
    masked = _ABBREVIATIONS.sub(lambda found: found.group(0).replace(".", "·"), statement)
    return 1 + len(_SENTENCE_END.findall(masked.strip()))


def compound_reasons(statement: str) -> list[str]:
    """Why `statement` is more than one proposition, or an empty list."""
    reasons: list[str] = []
    if _sentences(statement) > 1:
        reasons.append("it is more than one sentence")
    if ";" in statement:
        reasons.append("a semicolon joins its clauses")
    if re.search(r"\brespectively\b", statement, re.IGNORECASE):
        reasons.append('"respectively" pairs several subjects with several figures')
    quarters: dict[str, str] = {}
    fiscal: dict[str, str] = {}
    years: dict[str, str] = {}
    for found in _PERIOD.finditer(statement):
        kind = found.lastgroup
        label = found.group(0)
        if kind == "quarter":
            quarters.setdefault(_normal(label), label)
        elif kind == "fiscal":
            fiscal.setdefault(_normal(label), label)
        else:
            years.setdefault(label, label)
    if len(quarters) > 1:
        reasons.append("it names several quarters or halves: " + ", ".join(quarters.values()))
    if len(fiscal) > 1:
        reasons.append("it names several fiscal years: " + ", ".join(fiscal.values()))
    if len(years) > MAX_YEARS:
        reasons.append("it names several years: " + ", ".join(years.values()))
    return reasons
