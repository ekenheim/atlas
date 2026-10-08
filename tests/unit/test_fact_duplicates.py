"""One Fact per span (bottleneck-argument ticket 10): the duplicate rule a Reader's Fact is
checked by before it is recorded.

Seam: `atlas.facts.duplicates.duplicate_of`, pure: a Fact about to be recorded against the
investigation's Facts of the same Source Version. Measured on the 11 reviewed argument runs
(1,840 Facts): 31% overlapped an earlier Fact; the rule keeps (a) the same span or folded quote
in any step and (b) an overlapping span with the same status and an alike statement.
"""

import uuid

import pytest

from atlas.facts.duplicates import FactSpan, alike, duplicate_of, normalized_quote

VERSION = uuid.UUID("00000000-0000-0000-0000-0000000000f1")
OTHER_VERSION = uuid.UUID("00000000-0000-0000-0000-0000000000f2")
COMPANY = uuid.UUID("00000000-0000-0000-0000-00000000c0c0")
OTHER_COMPANY = uuid.UUID("00000000-0000-0000-0000-00000000c0c1")
# Shaped like 0.5.5 Q2's triple (one Reader, spans 29766-30193 / 29865-30193 / 29814-30193, all
# constraint): a document's text, each Fact's quote its text at the Fact's offsets.
DOCUMENT = (
    "Although we are expanding our indium phosphide capacity in Ottawa and Sagamihara over the"
    " coming quarters, that capacity might not be enough to meet the demand we expect from cloud"
    " customers for our lasers, and we may need to allocate supply among them for some time."
)
STATEMENT = "Lumentum's expanded indium phosphide capacity might not be enough to meet demand."


def span(
    start: int,
    end: int,
    *,
    quote: str | None = None,
    status: str = "hedged",
    statement: str = STATEMENT,
    step: str = "constraint",
    company: uuid.UUID = COMPANY,
    version: uuid.UUID = VERSION,
    session: str | None = None,
) -> FactSpan:
    return FactSpan(
        fact_id=uuid.uuid4(),
        source_version_id=version,
        company_id=company,
        span_start=start,
        span_end=end,
        quote=DOCUMENT[start:end] if quote is None else quote,
        status=status,
        statement=statement,
        step=step,
        session_key=session,
    )


def test_the_same_span_or_the_same_folded_quote_is_a_duplicate_in_any_step() -> None:
    recorded = span(10, 60, step="constraint")

    # The same offsets, another step, another status and statement: (a).
    same_span = span(
        10, 60, step="relief", status="planned", statement="Lumentum plans more capacity."
    )
    assert duplicate_of(same_span, [recorded]) == recorded
    # The same words elsewhere (another occurrence: other offsets that don't overlap), with
    # curly quotes and a trailing period where the recorded one has straight ones and none.
    straight = span(
        300, 340, quote='We call it "the bottleneck"', step="control", statement="Unlike."
    )
    curly = span(
        900,
        941,
        quote="We call it \N{LEFT DOUBLE QUOTATION MARK}the bottleneck"
        "\N{RIGHT DOUBLE QUOTATION MARK}.",
        step="capture",
        status="in_effect",
        statement="Something else entirely.",
    )
    assert normalized_quote(curly.quote) == normalized_quote(straight.quote)
    assert duplicate_of(curly, [straight]) == straight
    # Another Source Version is never a duplicate, whatever the span.
    assert duplicate_of(span(10, 60, version=OTHER_VERSION), [recorded]) is None


def test_an_overlapping_span_with_the_same_status_and_an_alike_statement_is_a_duplicate() -> None:
    first = span(0, 170)
    # One span containing the other, then a partial overlap; the statements alike.
    contained = span(
        40,
        170,
        statement="Lumentum says its indium phosphide capacity might not be enough to meet demand.",
    )
    assert alike(contained.statement, first.statement)
    assert duplicate_of(contained, [first]) == first
    partial = span(100, 230, statement=STATEMENT)
    assert duplicate_of(partial, [first]) == first


@pytest.mark.parametrize(
    "candidate",
    [
        span(40, 170, status="in_effect"),
        span(40, 170, statement="Lumentum expects demand for datacom lasers to grow."),
        span(40, 170, company=OTHER_COMPANY),
    ],
    ids=["another status", "an unlike statement", "another company"],
)
def test_an_overlapping_span_with_another_status_or_an_unlike_statement_or_another_company_is_not(
    candidate: FactSpan,
) -> None:
    assert duplicate_of(candidate, [span(0, 170)]) is None


def test_the_earliest_match_wins() -> None:
    # This session's own Fact first, then the ledger's (oldest first): the first match is it.
    own = span(20, 170, session="reader:constraint")
    ledger_first = span(0, 170)
    ledger_second = span(40, 170)
    candidate = span(30, 170)

    assert duplicate_of(candidate, [own, ledger_first, ledger_second]) == own
    assert duplicate_of(candidate, [ledger_second, ledger_first]) == ledger_second
    # A non-match before the match is passed over.
    unlike = span(0, 30, status="planned", statement="Lumentum expands in Ottawa.")
    assert duplicate_of(candidate, [unlike, ledger_first]) == ledger_first
