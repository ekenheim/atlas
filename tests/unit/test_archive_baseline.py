"""The archive-search baseline (pilot review ticket 03): a plain term search of archived
parsed text, the comparison every pilot investigation is held against."""

import pytest

from atlas.evaluation.baseline import Document, covering_quotes, passages, query_terms, search

QUESTION = (
    "Is indium phosphide substrate supply a chokepoint for optical laser chips: who makes it, "
    "how concentrated is it, and do export controls (gallium, germanium, indium) bind?"
)

SUBSTRATES = (
    "We manufacture indium phosphide substrates at our facilities in China. Export controls on "
    "gallium and germanium require us to obtain permits for each shipment, and permits for "
    "indium phosphide have been delayed, which limited the substrates we could ship to customers "
    "making optical laser chips in the quarter."
)
BOILERPLATE = (
    "Our business is subject to general economic conditions, and our operating results may "
    "fluctuate from quarter to quarter for many reasons, including changes in demand, the timing "
    "of orders, and our ability to control costs and to hire and retain the people we need to "
    "operate and to grow the business over time."
)
OFFERING = (
    "The Company announced today the pricing of an underwritten public offering of common stock. "
    "The gross proceeds from the offering are expected to be approximately $87 million, before "
    "deducting underwriting discounts and commissions and other offering expenses payable by the "
    "Company in connection with the offering."
)


def document(version: str, text: str, *, available_at: str = "2026-03-17T20:00:00Z") -> Document:
    return Document(
        source_version_id=version,
        company="axt",
        title=f"AXT INC {version}",
        available_at=available_at,
        text=text,
    )


def test_passages_keep_their_offsets_and_short_lines_join_a_neighbour() -> None:
    text = "\n".join(["Item 1. Business", SUBSTRATES, BOILERPLATE, "Signatures"])
    found = passages(document("10-K", text))

    assert [text[p.char_start : p.char_end] for p in found] == [p.text for p in found]
    # the heading joins the paragraph after it; the trailing short line the one before it
    assert found[0].text.startswith("Item 1. Business\nWe manufacture indium phosphide")
    assert found[-1].text.endswith("Signatures")
    assert len(found) == 2


def test_a_long_line_is_cut_at_sentence_ends() -> None:
    text = " ".join([SUBSTRATES] * 8)
    found = passages(document("10-K", text))

    assert len(found) > 1
    assert all(len(p.text) <= 1500 for p in found)
    assert all(p.text.rstrip().endswith(".") for p in found)
    assert "".join(p.text for p in found) == text


def test_the_question_s_content_words_are_the_terms() -> None:
    terms = query_terms(QUESTION)

    assert {"indium", "phosphide", "substrate", "chokepoint", "gallium", "control"} <= set(terms)
    assert not {"is", "who", "how", "it", "and", "do", "for", "a"} & set(terms)
    assert len(terms) == len(set(terms))
    assert query_terms("Who supplies the laser chips?") == ["supply", "laser", "chip"]


def test_the_passage_naming_the_question_s_rare_terms_ranks_first() -> None:
    text = "\n".join([BOILERPLATE, OFFERING, SUBSTRATES])
    hits = search(QUESTION, [document("10-K", text)])

    assert hits[0].passage.text == SUBSTRATES
    # singular and plural match: "substrate" in the question, "substrates" in the filing
    assert {"substrate", "indium", "export", "germanium"} <= set(hits[0].terms)
    # a passage with none of the terms is no hit
    assert all(hit.terms for hit in hits)
    assert OFFERING not in [hit.passage.text for hit in hits]


def test_a_passage_repeated_in_an_older_filing_is_one_hit_from_the_newest() -> None:
    older = document("10-Q-2025", SUBSTRATES, available_at="2025-11-05T21:00:00Z")
    respaced = SUBSTRATES.replace("substrates at", "substrates  at")
    newer = document("10-K-2026", respaced, available_at="2026-03-17T20:00:00Z")

    hits = search(QUESTION, [older, newer])

    assert [hit.passage.source_version_id for hit in hits] == ["10-K-2026"]


def test_one_document_gives_at_most_its_share_of_the_hits() -> None:
    variants = [SUBSTRATES.replace("in the quarter", f"in quarter {n}") for n in range(6)]
    long_filing = document("10-K", "\n".join(variants))
    other = document("8-K", SUBSTRATES.replace("in the quarter", "this year"))

    hits = search(QUESTION, [long_filing, other], top=10, per_document=3)

    by_document = [hit.passage.source_version_id for hit in hits]
    assert by_document.count("10-K") == 3
    assert by_document.count("8-K") == 1


def test_a_claim_s_quote_covers_the_passage_that_contains_it() -> None:
    quotes = {
        # the whitespace of another parse
        "claim-1": "permits for indium phosphide\nhave been  delayed",
        "claim-2": "demand is outpacing our current supply",
    }

    assert covering_quotes(SUBSTRATES, quotes) == ["claim-1"]
    assert covering_quotes(BOILERPLATE, quotes) == []


# Near-duplicates (memory-directed reading ticket 10). The paragraphs are hand-shaped on the
# pilot's case (the breadth run of investigation 2: one export-permit paragraph in five AXT
# filings, worded a little differently each time); they are not the filings' text.
PERMITS = (
    "Since August 1, 2023, our subsidiary in China has needed permits from the Chinese "
    "authorities to export gallium arsenide and germanium substrates. Our main product imported "
    "into the United States is the indium phosphide substrate. In 2024, approximately 8% of our "
    "revenue came from sales to customers in the United States. On February 4, 2025, China added "
    "indium phosphide substrates to its export control list. As a result, all three of our "
    "substrate product families need a permit from China's Ministry of Commerce before they can "
    "leave China. The portal for indium phosphide export applications opened in March and we "
    "began to submit our applications at once. On June 11, our subsidiary was told that it had "
    "met the requirements, and it received its first permits to resume shipping indium phosphide "
    "substrates to certain customers in Europe and Japan."
)
# the next filing: two dates changed
PERMITS_REDATED = PERMITS.replace("opened in March and", "opened in March 2025 and").replace(
    "On June 11, our", "On June 11, 2025, our"
)
# the one after: a figure changed too, and one sentence added
PERMITS_UPDATED = (
    PERMITS_REDATED.replace("In 2024, approximately 8%", "In 2025, approximately 11%")
    + " While we have received some permits as of the date of this report, we cannot predict "
    "when a permit application will be reviewed and approved."
)
# Another paragraph on the subject: an earlier filing's, written before any permit was granted.
# It has the paragraph's first six sentences but says something else (no permit yet, and no
# date for one), so it is its own hit.
WAITING = (
    "Since August 1, 2023, our subsidiary in China has needed permits from the Chinese "
    "authorities to export gallium arsenide and germanium substrates. Our main product imported "
    "into the United States is the indium phosphide substrate. In 2024, approximately 8% of our "
    "revenue came from sales to customers in the United States. On February 4, 2025, China added "
    "indium phosphide substrates to its export control list. As a result, all three of our "
    "substrate product families need a permit from China's Ministry of Commerce before they can "
    "leave China. The portal for indium phosphide export applications opened in March and we "
    "began to submit our applications at once. To our knowledge, indium phosphide is rarely used "
    "in military applications, and we expect that the permits will be granted. However, the "
    "requirement is new, the timing remains uncertain, and we are unable to estimate when we "
    "will receive the permits we need to resume shipping. We are actively following up on the "
    "status of every application."
)
# And a third, with the subject's vocabulary and none of its sentences.
BACKLOG = (
    "Export permits for indium phosphide substrates are the most significant challenge we "
    "currently face. While we continue to receive permits, we have a backlog of orders for which "
    "no permit has been issued, and the export control list may be extended to further gallium "
    "and germanium products. The uncertainty weighs on us and on our customers, who make optical "
    "laser chips and may look for a second source of supply for their substrates outside China."
)
NOVEMBER, MARCH, AUGUST = "2025-11-13T21:00:00Z", "2026-03-17T20:00:00Z", "2026-08-13T20:00:00Z"


@pytest.mark.parametrize(
    "oldest_to_newest",
    [
        # the shortest wording scores best: here it is the oldest filing's, there the newest's
        (PERMITS, PERMITS_REDATED, PERMITS_UPDATED),
        (PERMITS_UPDATED, PERMITS_REDATED, PERMITS),
    ],
)
def test_a_paragraph_reworded_from_filing_to_filing_is_one_hit_from_the_newest(
    oldest_to_newest: tuple[str, str, str],
) -> None:
    oldest, middle, newest = oldest_to_newest
    filings = [
        document("10-K-2026-03", middle, available_at=MARCH),
        document("10-Q-2025-11", oldest, available_at=NOVEMBER),
        document("10-Q-2026-08", newest, available_at=AUGUST),
    ]

    hits = search(QUESTION, filings)

    assert [hit.passage.source_version_id for hit in hits] == ["10-Q-2026-08"]
    assert hits[0].passage.text == newest
    # the hit names the documents its dropped wordings came from, newest first
    assert hits[0].also_in == ("10-K-2026-03", "10-Q-2025-11")


def test_different_paragraphs_on_one_subject_stay_separate_hits() -> None:
    filings = [
        document("10-Q-2026-08", PERMITS_UPDATED, available_at=AUGUST),
        document("10-K-2026-03", BACKLOG, available_at=MARCH),
        document("10-Q-2025-11", PERMITS, available_at=NOVEMBER),
        document("10-Q-2025-05", WAITING, available_at="2025-05-14T20:00:00Z"),
    ]

    hits = search(QUESTION, filings)

    # the earlier version is dropped for neither wording of the paragraph it grew into
    assert {hit.passage.text: hit.also_in for hit in hits} == {
        PERMITS_UPDATED: ("10-Q-2025-11",),
        BACKLOG: (),
        WAITING: (),
    }
    assert len(hits) == 3


def test_a_hit_names_the_documents_that_repeat_it_word_for_word() -> None:
    older = document("10-Q-2025-11", SUBSTRATES, available_at=NOVEMBER)
    newer = document("10-K-2026-03", SUBSTRATES, available_at=MARCH)
    # a reworded copy in between, and its own word-for-word copy in an exhibit filed with it
    reworded = SUBSTRATES.replace("in the quarter", "in the year")
    between = document("10-Q-2026-01", reworded, available_at="2026-01-20T21:00:00Z")
    exhibit = document("EX-99.1-2026-01", reworded, available_at="2026-01-20T21:00:00Z")

    hits = search(QUESTION, [older, between, exhibit, newer])

    assert [hit.passage.source_version_id for hit in hits] == ["10-K-2026-03"]
    assert hits[0].also_in == ("10-Q-2026-01", "EX-99.1-2026-01", "10-Q-2025-11")


def test_a_dropped_wording_does_not_use_its_document_s_share() -> None:
    newer = document("10-Q-2026-08", PERMITS_UPDATED, available_at=AUGUST)
    older = document("10-Q-2025-11", "\n".join([PERMITS, BACKLOG]), available_at=NOVEMBER)

    hits = search(QUESTION, [older, newer], per_document=1)

    assert sorted((hit.passage.source_version_id, hit.passage.text) for hit in hits) == [
        ("10-Q-2025-11", BACKLOG),
        ("10-Q-2026-08", PERMITS_UPDATED),
    ]
    assert {hit.passage.text: hit.also_in for hit in hits} == {
        PERMITS_UPDATED: ("10-Q-2025-11",),
        BACKLOG: (),
    }
    assert [hit.score for hit in hits] == sorted((hit.score for hit in hits), reverse=True)


def test_the_newest_filing_with_a_share_left_shows_the_paragraph() -> None:
    # the newest filing's one hit is its best passage; the paragraph it also restates is shown
    # from the filing before it, which names both others
    newest = document("10-Q-2026-08", "\n".join([SUBSTRATES, PERMITS_UPDATED]), available_at=AUGUST)
    middle = document("10-K-2026-03", PERMITS_REDATED, available_at=MARCH)
    oldest = document("10-Q-2025-11", PERMITS, available_at=NOVEMBER)

    hits = search(QUESTION, [oldest, middle, newest], per_document=1)

    assert [(hit.passage.source_version_id, hit.passage.text) for hit in hits] == [
        ("10-Q-2026-08", SUBSTRATES),
        ("10-K-2026-03", PERMITS_REDATED),
    ]
    assert hits[1].also_in == ("10-Q-2026-08", "10-Q-2025-11")


def test_passages_of_one_filing_and_of_its_exhibits_are_not_compared() -> None:
    # what "one document gives at most its share" above relies on: a near-duplicate is another
    # filing's wording, so one filing's own repeats (and its exhibits') are each a hit
    filing = document("10-K", "\n".join([PERMITS, PERMITS_REDATED]))
    exhibit = document("EX-13", PERMITS_UPDATED)

    hits = search(QUESTION, [filing, exhibit])

    assert sorted(hit.passage.text for hit in hits) == sorted(
        [PERMITS, PERMITS_REDATED, PERMITS_UPDATED]
    )
    assert [hit.also_in for hit in hits] == [(), (), ()]
