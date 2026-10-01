"""The archive-search baseline (pilot review ticket 03): a plain term search of archived
parsed text, the comparison every pilot investigation is held against."""

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
