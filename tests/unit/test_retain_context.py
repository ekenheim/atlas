"""What a retained section says (memory-quality ticket 04): the context an extraction model
reads before the section, the entities sent with it and the display metadata.

The expected texts are written out in full: they are what the model reads.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from atlas.hindsight import RetainEntity
from atlas.retention.context import (
    KnownCompany,
    SectionSource,
    display_metadata,
    section_context,
    section_entities,
)

LUMENTUM = uuid.UUID("00000000-0000-0000-0000-000000000001")
COHERENT = uuid.UUID("00000000-0000-0000-0000-000000000002")
INNOLIGHT = uuid.UUID("00000000-0000-0000-0000-000000000003")
BROADCOM = uuid.UUID("00000000-0000-0000-0000-000000000004")


def source(**changes: Any) -> SectionSource:
    """A Lumentum 10-K's primary document, with `changes`."""
    fields: dict[str, Any] = {
        "source_type": "filing",
        "form_type": "10-K",
        "document_type": "10-K",
        "title": "lite-20260627.htm",
        "publisher": "SEC EDGAR",
        "available_at": datetime(2026, 8, 14, 20, 15, tzinfo=UTC),
        "company_id": LUMENTUM,
        "company_name": "Lumentum",
        "company_legal_name": "Lumentum Holdings Inc.",
        "metadata": {"form": "10-K", "report_date": "2026-06-27", "cik": "0001633978"},
    }
    return SectionSource(**(fields | changes))


TRANSCRIPT = source(
    source_type="transcript",
    form_type=None,
    document_type="Call transcript",
    title="SYNTHETIC Q4 FY2026 earnings call",
    publisher="Quartr via TradingView",
    available_at=datetime(2026, 8, 12, 21, 0, tzinfo=UTC),
    metadata={
        "tradingview": {
            "category": "Earnings call",
            "event": "Synthetic Q4 FY2026 earnings call",
            "fiscal_period": "Q4",
            "fiscal_year": "2026",
        }
    },
)
MANUAL_IMPORT = source(
    source_type="manual_import",
    form_type=None,
    document_type="manual_import",
    title="Interim Report 2026",
    publisher="HKEXnews",
    available_at=datetime(2026, 8, 26, 9, 30, tzinfo=UTC),
    company_id=INNOLIGHT,
    company_name="InnoLight",
    company_legal_name="Zhongji Innolight Co., Ltd.",
    metadata={"manual_import": {"publisher": "HKEXnews", "file_name": "interim.pdf"}},
)


# --- the context -------------------------------------------------------------------------------


def test_a_10k_item_says_whose_annual_report_for_which_period_and_that_the_filer_speaks() -> None:
    assert section_context(source(), heading="ITEM 1. BUSINESS", anchor="part-i-item-1") == (
        "This is Lumentum's annual report on Form 10-K for the period ended 2026-06-27."
        " It was made public on 2026-08-14."
        ' This section is headed "ITEM 1. BUSINESS".'
        " Lumentum is speaking: this is its own document."
    )


def test_a_10k_cover_is_the_cover_page() -> None:
    assert section_context(source(), heading=None, anchor="cover") == (
        "This is Lumentum's annual report on Form 10-K for the period ended 2026-06-27."
        " It was made public on 2026-08-14."
        " This section is the cover page."
        " Lumentum is speaking: this is its own document."
    )


def test_an_8k_exhibit_names_its_exhibit_the_report_s_date_and_its_part() -> None:
    exhibit = source(
        form_type="8-K",
        document_type="EX-99.1",
        title="lite_ex991xq4fy26.htm",
        available_at=datetime(2026, 8, 11, 20, 5, tzinfo=UTC),
        metadata={"form": "8-K", "report_date": "2026-08-11", "items": ["2.02", "9.01"]},
    )

    assert section_context(exhibit, heading=None, anchor="chunk-002") == (
        "This is exhibit 99.1 to Lumentum's current report on Form 8-K dated 2026-08-11."
        " It was made public on 2026-08-11."
        " This is part 2 of the document."
        " Lumentum is speaking: this is its own document."
    )


def test_a_call_transcript_says_an_analyst_s_question_is_not_the_company_s_statement() -> None:
    assert section_context(TRANSCRIPT, heading=None, anchor="chunk-001") == (
        "This is the transcript of Lumentum's earnings call"
        ' "Synthetic Q4 FY2026 earnings call" for fiscal Q4 2026.'
        " It was made public on 2026-08-12."
        " This is part 1 of the document."
        " Lumentum's management and analysts speak on the call;"
        " an analyst's question is not a statement by Lumentum."
    )


def test_a_manual_import_names_its_publisher_as_the_speaker() -> None:
    assert section_context(MANUAL_IMPORT, heading=None, anchor="chunk-001") == (
        'This is InnoLight\'s document "Interim Report 2026", imported by hand from HKEXnews.'
        " It was made public on 2026-08-26."
        " This is part 1 of the document."
        " HKEXnews published it and is taken as the speaker."
    )


def test_an_amended_10q_without_a_report_date_says_so_without_a_period() -> None:
    amended = source(form_type="10-Q/A", document_type="10-Q/A", metadata={})

    assert section_context(amended, heading="Item 2. MD&A", anchor="part-i-item-2") == (
        "This is Lumentum's amended quarterly report on Form 10-Q/A."
        " It was made public on 2026-08-14."
        ' This section is headed "Item 2. MD&A".'
        " Lumentum is speaking: this is its own document."
    )


def test_the_context_carries_no_identifier_a_reader_could_not_use() -> None:
    context = section_context(source(), heading="ITEM 1. BUSINESS", anchor="part-i-item-1")

    for identifier in (str(LUMENTUM), "0001633978", "part-i-item-1", "lite-20260627.htm"):
        assert identifier not in context


# --- the entities ------------------------------------------------------------------------------

COMPANIES = [
    KnownCompany(BROADCOM, "Broadcom Inc.", ("Broadcom Inc.", "Broadcom")),
    KnownCompany(COHERENT, "Coherent Corp.", ("Coherent Corp.", "Coherent")),
    KnownCompany(INNOLIGHT, "Zhongji Innolight Co., Ltd.", ("Zhongji Innolight", "InnoLight")),
    KnownCompany(LUMENTUM, "Lumentum Holdings Inc.", ("Lumentum Holdings Inc.", "Lumentum")),
]


def test_the_entities_are_the_filer_and_the_companies_the_text_names_as_written() -> None:
    text = "We compete with Coherent and InnoLight in datacom transceivers. Lumentum ..."

    assert section_entities(source(), text, COMPANIES) == [
        RetainEntity(text="Lumentum Holdings Inc.", type="ORG"),
        RetainEntity(text="Coherent Corp.", type="ORG"),
        RetainEntity(text="Zhongji Innolight Co., Ltd.", type="ORG"),
    ]


def test_a_name_inside_another_word_is_not_a_mention() -> None:
    text = "Incoherent demand; Broadcomm is not a company Atlas has."

    assert section_entities(source(), text, COMPANIES) == [
        RetainEntity(text="Lumentum Holdings Inc.", type="ORG")
    ]


# --- the display metadata ----------------------------------------------------------------------


def test_the_display_metadata_names_the_company_the_form_and_the_period_when_known() -> None:
    assert display_metadata(source()) == {
        "company_name": "Lumentum",
        "form": "10-K",
        "period": "2026-06-27",
    }
    assert display_metadata(TRANSCRIPT) == {"company_name": "Lumentum", "period": "Q4 2026"}
    assert display_metadata(MANUAL_IMPORT) == {"company_name": "InnoLight"}
