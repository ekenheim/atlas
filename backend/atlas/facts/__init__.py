"""Facts: a verbatim quote about one company, with the argument step it bears on and, when the
quote states them, a quantity, a period and a status (bottleneck-argument ticket 02).

A Fact is an Assertion with predicate `fact` and a validated `value_json` (`FactValue`); it
needs no predicate from the Relationship whitelist, and the Relationship review never makes an
edge from it. The quote is held to the Assertion's span check, unchanged
(`atlas.assertions.check_quote`). A quantity's number must occur in the quote (the number rule
of `atlas.investigations.grounding`). The status keeps the tense of the source ("planned",
"hedged", ...) from the start, so a plan or a risk is never recorded as a present fact.
Recorded with the document's date and the company's fiscal year end, a Fact's relative periods
("this calendar year", "the current quarter") are resolved by code and a period the date
contradicts is refused (`periods`; R2-02).

A Fact the investigation holds already is not recorded again (`duplicates`, ticket 10): the
same span or folded quote, or an overlapping span with the same status and an alike statement,
of the same company and Source Version.

Recording is insert-only and audited (`fact.created`, with the Assertion's own
`assertion.created`, in one transaction). Review of a Fact is its Assertion's review.
"""

from atlas.facts.service import (
    FACT_PREDICATE,
    Fact,
    FactCreate,
    FactNotFound,
    FactRecorded,
    Facts,
    FactStatus,
    FactStep,
    FactValue,
    PeriodBasis,
    Quantity,
    facts_of_version,
    get_fact,
    list_facts,
)

__all__ = [
    "FACT_PREDICATE",
    "Fact",
    "FactCreate",
    "FactNotFound",
    "FactRecorded",
    "FactStatus",
    "FactStep",
    "FactValue",
    "Facts",
    "PeriodBasis",
    "Quantity",
    "facts_of_version",
    "get_fact",
    "list_facts",
]
