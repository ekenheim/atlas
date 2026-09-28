"""The sectioner (`sec-items-v1`): Item headings for SEC filings, bounded chunks otherwise."""

from itertools import pairwise

from atlas.retention import MAX_CHUNK_CHARS, SECTIONER_VERSION, Section, split_sections

TEN_Q = (
    "LUMENTUM HOLDINGS INC.\n"
    "FORM 10-Q\n"
    "TABLE OF CONTENTS\n"
    "PART I - FINANCIAL INFORMATION\n"
    "Item 1.\n"
    "Financial Statements\n"
    "2\n"
    "Item 2.\n"
    "Management's Discussion and Analysis\n"
    "48\n"
    "PART II - OTHER INFORMATION\n"
    "Item 1.\n"
    "Legal Proceedings\n"
    "68\n"
    "Item 1A.\n"
    "Risk Factors\n"
    "69\n"
    "PART I - FINANCIAL INFORMATION\n"
    "ITEM 1. FINANCIAL STATEMENTS (UNAUDITED)\n"
    "Revenue rose.\n"
    "ITEM 2. MANAGEMENT'S DISCUSSION AND ANALYSIS\n"
    "Demand for 800G modules exceeded supply.\n"
    "Part II \N{EN DASH} Other Information\n"
    "Item 1. LEGAL PROCEEDINGS\n"
    "None.\n"
    "Item 1A. RISK FACTORS\n"
    "See Item 1A of our annual report.\n"
    "Item 1A. RISK FACTORS\n"
    "A repeated heading folds into the section before it.\n"
)


def texts(text: str, sections: list[Section]) -> dict[str, str]:
    return {section.anchor: text[section.start : section.end] for section in sections}


def test_the_sectioner_is_versioned() -> None:
    assert SECTIONER_VERSION == "sec-items-v1"


def test_a_10q_splits_on_its_body_items_qualified_by_part_skipping_the_contents() -> None:
    sections = split_sections(TEN_Q, form="10-Q", primary=True)

    assert texts(TEN_Q, sections) == {
        "cover": TEN_Q[: TEN_Q.index("PART I - FINANCIAL INFORMATION\nITEM 1.")],
        "part-i-item-1": (
            "PART I - FINANCIAL INFORMATION\nITEM 1. FINANCIAL STATEMENTS (UNAUDITED)\n"
            "Revenue rose.\n"
        ),
        "part-i-item-2": (
            "ITEM 2. MANAGEMENT'S DISCUSSION AND ANALYSIS\n"
            "Demand for 800G modules exceeded supply.\n"
        ),
        "part-ii-item-1": (
            "Part II \N{EN DASH} Other Information\nItem 1. LEGAL PROCEEDINGS\nNone.\n"
        ),
        "part-ii-item-1a": (
            "Item 1A. RISK FACTORS\nSee Item 1A of our annual report.\n"
            "Item 1A. RISK FACTORS\nA repeated heading folds into the section before it.\n"
        ),
    }
    assert [s.heading for s in sections] == [
        None,
        "ITEM 1. FINANCIAL STATEMENTS (UNAUDITED)",
        "ITEM 2. MANAGEMENT'S DISCUSSION AND ANALYSIS",
        "Item 1. LEGAL PROCEEDINGS",
        "Item 1A. RISK FACTORS",
    ]


def test_sections_tile_the_text() -> None:
    sections = split_sections(TEN_Q, form="10-Q/A", primary=True)

    assert sections[0].start == 0
    assert sections[-1].end == len(TEN_Q)
    assert all(a.end == b.start for a, b in pairwise(sections))


def test_an_8k_uses_its_numbered_items_without_parts() -> None:
    text = (
        "FORM 8-K\nCurrent report\n"
        "Item 2.02. Results of Operations and Financial Condition.\nResults were reported.\n"
        "Item 9.01 - Financial Statements and Exhibits.\n99.1 Press release\n"
    )

    sections = split_sections(text, form="8-K", primary=True)

    assert [(s.anchor, s.heading) for s in sections] == [
        ("cover", None),
        ("item-2-02", "Item 2.02. Results of Operations and Financial Condition."),
        ("item-9-01", "Item 9.01 - Financial Statements and Exhibits."),
    ]


def test_a_sentence_or_an_overlong_line_starting_with_item_is_not_a_heading() -> None:
    text = (
        "ITEM 7. MD&A\nOverview\n"
        "Item 7 of this report describes results.\n"  # no punctuation after the number
        f"Item 8. {'x' * 250}\n"  # longer than a heading
    )

    sections = split_sections(text, form="10-K", primary=True)

    assert [s.anchor for s in sections] == ["item-7"]


def test_exhibits_and_other_documents_are_cut_into_bounded_chunks_at_line_breaks() -> None:
    line = "Revenue grew on strong datacom demand. " * 20 + "\n"  # 781 characters
    text = line * 40
    text += "Item 1. BUSINESS\n"  # headings count only in a filing's primary document

    for form, primary in [("8-K", False), ("10-K", False), (None, True)]:
        sections = split_sections(text, form=form, primary=primary)

        assert [s.anchor for s in sections] == ["chunk-001", "chunk-002", "chunk-003"]
        assert all(s.end - s.start <= MAX_CHUNK_CHARS for s in sections)
        assert all(text[s.end - 1] == "\n" for s in sections)
        assert (sections[0].start, sections[-1].end) == (0, len(text))
        assert all(s.heading is None for s in sections)


def test_a_primary_document_without_item_headings_is_chunked() -> None:
    assert [s.anchor for s in split_sections("No items here.\n", form="10-K", primary=True)] == [
        "chunk-001"
    ]


def test_a_line_longer_than_a_chunk_is_split_hard() -> None:
    text = "x" * (MAX_CHUNK_CHARS + 5)

    sections = split_sections(text, form=None, primary=False)

    assert [(s.start, s.end) for s in sections] == [
        (0, MAX_CHUNK_CHARS),
        (MAX_CHUNK_CHARS, MAX_CHUNK_CHARS + 5),
    ]


def test_an_empty_text_has_no_sections() -> None:
    assert split_sections("", form="10-K", primary=True) == []
