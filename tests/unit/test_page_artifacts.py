"""Page artifacts in paginated HTML filings (`text-v3`): page numbers, "Table of Contents"
back-links and paragraphs split by a page break.

The fragments are shaped like the recorded Coherent and Lumentum filings (the markup their
filing agent's software writes around every page break, styles shortened), and the recorded
filings themselves are parsed too. Expected texts are written by hand from the rules.
"""

from pathlib import Path

from atlas.parsing import ParsedText, parse

EDGAR = Path(__file__).parents[1] / "fixtures" / "edgar"
COHERENT_10K = (
    EDGAR / "coherent/www.sec.gov/Archives/edgar/data/820318/000082031826000020/iivi-20260630.htm"
)
LUMENTUM_10K = (
    EDGAR / "lumentum/www.sec.gov/Archives/edgar/data/1633978/000162828026057358/lite-20260627.htm"
)
LUMENTUM_10Q = (
    EDGAR / "lumentum/www.sec.gov/Archives/edgar/data/1633978/000162828026030777/lite-20260328.htm"
)

PAGE_BREAK = '<hr style="page-break-after:always"/>'
BACK_LINK = (
    '<div style="min-height:42.75pt;width:100%"><div><span style="color:#0000ff">'
    '<a style="color:#0000ff" href="#i994ba7cf1bc444699c20cbef454a6f29_7">Table of Contents</a>'
    "</span></div></div>"
)


def footer(page_number: int | None) -> str:
    """The page's bottom block, with its page number if it shows one."""
    shown = "<br/>" if page_number is None else str(page_number)
    return (
        '<div style="height:42.75pt;position:relative;width:100%">'
        '<div style="bottom:0;position:absolute;width:100%">'
        f'<div style="text-align:center"><span>{shown}</span></div></div></div>'
    )


def paragraph(text: str) -> str:
    return f'<div style="margin-top:6pt;text-align:justify"><span>{text}</span></div>'


def text_of(*body: str) -> str:
    parsed = parse(f"<html><body>{''.join(body)}</body></html>".encode(), "text/html")
    assert isinstance(parsed, ParsedText)
    assert parsed.parser_version == "text-v3"
    return parsed.text


def recorded(path: Path) -> str:
    parsed = parse(path.read_bytes(), "text/html")
    assert isinstance(parsed, ParsedText)
    return parsed.text


# --- a sentence broken by a page break comes out whole ---


def test_a_sentence_broken_by_a_page_number_and_a_back_link_comes_out_whole() -> None:
    # Coherent's FY2026 10-K, pages 8 to 10.
    text = text_of(
        paragraph("nor is it incorporated herein by reference."),
        footer(8),
        PAGE_BREAK,
        BACK_LINK,
        paragraph("Sources of Supply"),
        paragraph(
            "Our vertically integrated technology platform includes the in-house design"
            " and manufacture "
        ),
        footer(9),
        PAGE_BREAK,
        BACK_LINK,
        paragraph("of transceivers and many of their critical components, including lasers."),
        paragraph("InP is a foundational technology for next-generation AI optical interconnects."),
    )

    assert text == (
        "nor is it incorporated herein by reference.\n"
        "Sources of Supply\n"
        "Our vertically integrated technology platform includes the in-house design and"
        " manufacture of transceivers and many of their critical components, including lasers.\n"
        "InP is a foundational technology for next-generation AI optical interconnects.\n"
    )


def test_the_recorded_coherent_10k_has_whole_sentences_and_no_back_links() -> None:
    text = recorded(COHERENT_10K)

    # Broken across pages 9|10, 3|4 and 7|8 in the filing.
    assert (
        "Our vertically integrated technology platform includes the in-house design and"
        " manufacture of transceivers and many of their critical components, including lasers,"
    ) in text
    assert (
        "terms and conditions that could have an adverse effect on our business or ability to"
        " recognize revenues."
    ) in text
    assert "We also offer a compelling suite of benefits, including comprehensive health" in text
    assert "Table of Contents" not in text
    # The page numbers between those fragments are gone; the text around them is not.
    assert "\n9\n" not in text
    assert "\nSources of Supply\n" in text
    assert "\nPART I\nItem 1. BUSINESS\n" in text


def test_artifacts_between_whole_paragraphs_are_removed_and_nothing_is_joined() -> None:
    # Lumentum's Q3 FY2026 10-Q, the financial statements' pages 3 to 5.
    statement_note = (
        '<div style="text-align:center"><span>See accompanying Notes to Condensed'
        " Consolidated Financial Statements.</span></div>"
    )
    company = '<div style="text-align:center"><span>LUMENTUM HOLDINGS INC.</span></div>'
    text = text_of(
        statement_note,
        footer(3),
        PAGE_BREAK,
        BACK_LINK,
        company,
        '<div style="text-align:center"><span>CONDENSED CONSOLIDATED BALANCE SHEETS</span></div>',
        statement_note,
        footer(4),
        PAGE_BREAK,
        BACK_LINK,
        company,
        '<div style="text-align:center"><span>CONDENSED CONSOLIDATED STATEMENTS OF CASH FLOWS'
        "</span></div>",
    )

    assert text == (
        "See accompanying Notes to Condensed Consolidated Financial Statements.\n"
        "LUMENTUM HOLDINGS INC.\n"
        "CONDENSED CONSOLIDATED BALANCE SHEETS\n"
        "See accompanying Notes to Condensed Consolidated Financial Statements.\n"
        "LUMENTUM HOLDINGS INC.\n"
        "CONDENSED CONSOLIDATED STATEMENTS OF CASH FLOWS\n"
    )


def test_a_heading_that_ends_a_page_is_not_joined_to_the_next_page() -> None:
    # Lumentum's FY2026 10-K, pages 41 and 42: a heading ends the page, a heading starts the
    # next. Neither is a sentence fragment, so they stay two lines.
    text = text_of(
        paragraph("None."),
        footer(40),
        PAGE_BREAK,
        paragraph("Issuer Purchases of Equity Securities"),
        paragraph("ITEM 6. [RESERVED] "),
        footer(41),
        PAGE_BREAK,
        paragraph("ITEM 7. MANAGEMENT\u2019S DISCUSSION AND ANALYSIS"),
    )

    assert text == (
        "None.\n"
        "Issuer Purchases of Equity Securities\n"
        "ITEM 6. [RESERVED]\n"
        "ITEM 7. MANAGEMENT\u2019S DISCUSSION AND ANALYSIS\n"
    )


def test_a_continuation_that_starts_with_a_capital_is_left_on_its_own_line() -> None:
    # Coherent's 10-K, pages 13|14: "... of Applied" | "Materials, Inc., where ...". A capital
    # can also start a new paragraph or heading, so the two lines are not joined; the page
    # number and back-link between them still go.
    text = text_of(
        paragraph("available free of charge."),
        footer(12),
        PAGE_BREAK,
        BACK_LINK,
        paragraph("Mr. Anderson currently serves on the Board of Directors of Applied "),
        footer(13),
        PAGE_BREAK,
        BACK_LINK,
        paragraph("Materials, Inc., where he was appointed in July 2025."),
    )

    assert text == (
        "available free of charge.\n"
        "Mr. Anderson currently serves on the Board of Directors of Applied\n"
        "Materials, Inc., where he was appointed in July 2025.\n"
    )


def test_a_paragraph_split_by_a_page_break_without_artifacts_is_joined_too() -> None:
    text = text_of(
        paragraph("We rely on a limited number of suppliers for "),
        footer(None),
        PAGE_BREAK,
        paragraph("indium phosphide substrates."),
    )

    assert text == "We rely on a limited number of suppliers for indium phosphide substrates.\n"


def test_table_rows_and_list_markers_across_a_page_break_are_not_joined() -> None:
    row = "<table><tr><td>{}</td><td>{}</td></tr></table>"
    rows = text_of(row.format("Total", "12"), PAGE_BREAK, row.format("net of tax", "3"))
    markers = text_of(paragraph("any of the following"), PAGE_BREAK, paragraph("a. a merger"))
    after_a_sentence = text_of(paragraph("It ended."), PAGE_BREAK, paragraph("iPhone sales rose."))

    assert rows == "Total\t12\nnet of tax\t3\n"
    assert markers == "any of the following\na. a merger\n"
    assert after_a_sentence == "It ended.\niPhone sales rose.\n"


# --- what is not clearly an artifact stays ---


CONTENTS_PAGE = (
    '<div style="text-align:center"><span>TABLE OF CONTENTS</span></div>'
    "<table><tr>"
    '<td><div><span><a href="#i907d06b081224f5692d1860258ba168d_292">SIGNATURES</a></span></div>'
    '</td><td><div style="text-align:right"><span>'
    '<a href="#i907d06b081224f5692d1860258ba168d_292">135</a></span></div></td>'
    "</tr></table>"
)


def test_the_contents_page_keeps_its_heading_and_its_page_references() -> None:
    # Lumentum's FY2026 10-K: the cover, the contents page (page 1), then page 2.
    text = text_of(
        paragraph("DOCUMENTS INCORPORATED BY REFERENCE"),
        footer(None),
        PAGE_BREAK,
        BACK_LINK,
        CONTENTS_PAGE,
        footer(1),
        PAGE_BREAK,
        BACK_LINK,
        paragraph("FORWARD-LOOKING STATEMENTS"),
        footer(2),
        PAGE_BREAK,
        BACK_LINK,
        paragraph("We have a global footprint."),
    )

    assert text == (
        "DOCUMENTS INCORPORATED BY REFERENCE\n"
        "TABLE OF CONTENTS\n"
        "SIGNATURES\n"
        "135\n"
        "FORWARD-LOOKING STATEMENTS\n"
        "We have a global footprint.\n"
    )


def test_the_recorded_lumentum_filings_keep_their_contents_pages() -> None:
    ten_k, ten_q = recorded(LUMENTUM_10K), recorded(LUMENTUM_10Q)

    assert "\nTABLE OF CONTENTS\nPage\nPART I\n" in ten_k
    assert "\nSIGNATURES\n135\nFORWARD-LOOKING STATEMENTS\n" in ten_k
    assert "Table of Contents" not in ten_k
    assert (
        "manufacturing precision, flexibility, and sustainability.\n"
        "We have a global footprint that enables us"
    ) in ten_k
    assert "\nTABLE OF CONTENTS\nPage\nPART I - FINANCIAL INFORMATION\n" in ten_q
    assert "\nSIGNATURES\n106\nPART I - FINANCIAL INFORMATION\n" in ten_q
    assert (
        "See accompanying Notes to Condensed Consolidated Financial Statements.\n"
        "LUMENTUM HOLDINGS INC.\n"
        "CONDENSED CONSOLIDATED BALANCE SHEETS\n"
    ) in ten_q
    assert "Table of Contents" not in ten_q


def test_a_number_that_ends_a_page_but_is_not_in_the_page_sequence_stays() -> None:
    # A contents page without a page number of its own ends with a page reference ("106"),
    # and the page numbers 2 and 3 count up with the pages after it.
    text = text_of(
        CONTENTS_PAGE.replace("135", "106"),
        footer(None),
        PAGE_BREAK,
        paragraph("PART I"),
        footer(2),
        PAGE_BREAK,
        paragraph("Item 2. Properties"),
        footer(3),
        PAGE_BREAK,
        paragraph("Item 3. Legal Proceedings"),
    )

    assert text == (
        "TABLE OF CONTENTS\nSIGNATURES\n106\nPART I\nItem 2. Properties\n"
        "Item 3. Legal Proceedings\n"
    )


def test_a_single_number_at_a_page_end_with_no_neighbour_to_confirm_it_stays() -> None:
    text = text_of(
        paragraph("Shares outstanding (in millions):"),
        paragraph("77"),
        PAGE_BREAK,
        paragraph("Signature"),
    )

    assert text == "Shares outstanding (in millions):\n77\nSignature\n"


def test_a_back_link_that_is_not_alone_on_a_pages_first_line_stays() -> None:
    text = text_of(
        paragraph("Item 1. Business"),
        BACK_LINK,
        paragraph("We make lasers."),
        PAGE_BREAK,
        '<div><a href="#contents">Table of Contents</a> (continued)</div>',
        paragraph("Item 2. Properties"),
        PAGE_BREAK,
        '<div><a href="https://example.com/contents">Table of Contents</a></div>',
        paragraph("Item 3. Legal Proceedings"),
    )

    assert text == (
        "Item 1. Business\nTable of Contents\nWe make lasers.\n"
        "Table of Contents (continued)\nItem 2. Properties\n"
        "Table of Contents\nItem 3. Legal Proceedings\n"
    )


def test_a_document_without_page_breaks_is_left_as_it_is() -> None:
    text = text_of(
        '<div><a href="#contents">Table of Contents</a></div>',
        paragraph("Our supply of wafers comes from"),
        paragraph("12"),
        paragraph("suppliers in three countries."),
        paragraph("13"),
    )

    assert text == (
        "Table of Contents\nOur supply of wafers comes from\n12\n"
        "suppliers in three countries.\n13\n"
    )


def test_a_hidden_page_break_is_not_a_page_break() -> None:
    text = text_of(
        paragraph("we depend on a single "),
        f'<div style="display:none">{PAGE_BREAK}</div>',
        paragraph("supplier"),
    )

    assert text == "we depend on a single\nsupplier\n"


# --- other ways of marking a page break ---


def test_a_block_that_breaks_the_page_before_or_after_itself_is_a_page_break() -> None:
    before = text_of(
        paragraph("qualification of a second source "),
        '<p style="text-indent: 0; PAGE-BREAK-BEFORE: always">takes twelve months.</p>',
    )
    after = text_of(
        '<div style="break-after:page"><p>qualification of a second source </p></div>',
        paragraph("takes twelve months."),
    )

    assert before == after == "qualification of a second source takes twelve months.\n"


def test_avoiding_a_page_break_is_not_a_page_break() -> None:
    text = text_of(
        '<p style="page-break-after:avoid">qualification of a second source </p>',
        paragraph("takes twelve months."),
    )

    assert text == "qualification of a second source\ntakes twelve months.\n"
