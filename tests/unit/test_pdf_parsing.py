"""The deterministic parser on PDFs, and the language it records, through `atlas.parsing.parse`.

Fixtures: `tests/fixtures/pdf/`, written by `scripts/make_pdf_fixtures.py`. Expected
texts are the lines that script draws, written out here by hand.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from atlas.parsing import PARSER_VERSION, PageAnchor, ParsedText, Unsupported, parse

REPO = Path(__file__).parents[2]
PDFS = REPO / "tests" / "fixtures" / "pdf"
ANNUAL_REPORT = PDFS / "annual-report-en.pdf"
RESULTS_FR = PDFS / "results-fr.pdf"
SCANNED = PDFS / "scanned.pdf"

ANNUAL_REPORT_PAGES = (
    "Photonics Example plc\nAnnual Report and Accounts 2026\n",
    "Chair's statement\n"
    "Revenue grew 18% to €412.6 million in the year ended 30 June 2026.\n"
    "Demand for 800G transceivers \u2013 driven by AI data centres \u2013 exceeded supply.\n"
    "We supply indium phosphide epitaxial wafers to “Tier 1” laser makers.\n",
    "Principal risks\n"
    "Our largest customer accounted for 31% of revenue.\n"
    "Capacity at the Newport fab will double by the end of fiscal 2027.\n",
)
# The content hash of text-v2 on the English annual report, pinned when the version was
# made. If it changes, the parser's output changed: that needs a new PARSER_VERSION.
# text-v3 changes paginated HTML only, so the hash is the same under it.
ANNUAL_REPORT_SHA256 = "49979e9fc46189f2114d3838a6e77caddc1b2e80f13317b2847c43ed8315e5e5"


def parsed(path: Path) -> ParsedText:
    result = parse(path.read_bytes(), "application/pdf")
    assert isinstance(result, ParsedText)
    return result


def test_the_checked_in_fixtures_are_exactly_what_the_script_writes(tmp_path: Path) -> None:
    subprocess.run(
        [sys.executable, str(REPO / "scripts" / "make_pdf_fixtures.py"), str(tmp_path)],
        check=True,
        capture_output=True,
    )

    written = sorted(path.name for path in tmp_path.iterdir())
    assert written == ["annual-report-en.pdf", "results-fr.pdf", "scanned.pdf"]
    for name in written:
        assert (tmp_path / name).read_bytes() == (PDFS / name).read_bytes(), name


def test_a_text_pdf_parses_to_its_text_with_one_anchor_per_page() -> None:
    result = parsed(ANNUAL_REPORT)

    assert result.parser_version == PARSER_VERSION == "text-v3"
    assert result.complete
    assert result.text == "".join(ANNUAL_REPORT_PAGES)
    # Page labels come from the PDF's /PageLabels: a roman cover, then 1, 2.
    starts = [0, len(ANNUAL_REPORT_PAGES[0]), len(ANNUAL_REPORT_PAGES[0] + ANNUAL_REPORT_PAGES[1])]
    ends = [*starts[1:], len(result.text)]
    assert result.pages == (
        PageAnchor(page=1, label="i", start=starts[0], end=ends[0]),
        PageAnchor(page=2, label="1", start=starts[1], end=ends[1]),
        PageAnchor(page=3, label="2", start=starts[2], end=ends[2]),
    )
    for anchor, page_text in zip(result.pages, ANNUAL_REPORT_PAGES, strict=True):
        assert result.text[anchor.start : anchor.end] == page_text


def test_identical_bytes_give_identical_text_and_the_pinned_hash() -> None:
    raw = ANNUAL_REPORT.read_bytes()

    first, second = parse(raw, "application/pdf"), parse(raw, "application/pdf")

    assert first == second
    assert isinstance(first, ParsedText)
    assert first.sha256 == ANNUAL_REPORT_SHA256


def test_the_pdf_parse_does_not_depend_on_the_process() -> None:
    script = (
        "import sys; from pathlib import Path; from atlas.parsing import parse; "
        "r = parse(Path(sys.argv[1]).read_bytes(), 'application/pdf'); "
        "print(r.sha256, [(a.page, a.label, a.start, a.end) for a in r.pages])"
    )
    outputs = {
        subprocess.run(
            [sys.executable, "-c", script, str(ANNUAL_REPORT)],
            env={**os.environ, "PYTHONHASHSEED": seed, "LC_ALL": "C", "TZ": zone},
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        for seed, zone in (("1", "UTC"), ("12345", "Asia/Hong_Kong"))
    }

    assert len(outputs) == 1
    assert outputs.pop().startswith(ANNUAL_REPORT_SHA256)


def test_the_declared_document_language_is_recorded_as_its_primary_subtag() -> None:
    # The catalog says /Lang (en-GB).
    assert parsed(ANNUAL_REPORT).language == "en"


def test_an_undeclared_language_is_detected_from_the_text() -> None:
    result = parsed(RESULTS_FR)

    assert result.language == "fr"
    assert result.text.startswith("Résultats du premier semestre de l'exercice 2027\n")
    assert [(anchor.page, anchor.label) for anchor in result.pages] == [(1, "1"), (2, "2")]


def test_an_image_only_pdf_is_unsupported_with_its_reason() -> None:
    result = parse(SCANNED.read_bytes(), "application/pdf")

    assert result == Unsupported(
        parser_version="text-v3",
        reason="no extractable text on any of its 2 pages (an image-only or scanned PDF)",
    )


def test_bytes_that_are_not_a_pdf_raise() -> None:
    with pytest.raises(Exception):  # any error: the ledger records the parse as failed
        parse(b"<html>not a pdf</html>", "application/pdf")


@pytest.mark.parametrize(
    ("text", "language"),
    [
        (
            "The company reported that revenue for the quarter was higher than"
            " expected, and it expects demand from its customers to grow.",
            "en",
        ),
        (
            "Die Gesellschaft hat im Geschäftsjahr einen Umsatz von 120 Millionen Euro"
            " erzielt, und wir erwarten auch für das nächste Jahr ein Wachstum.",
            "de",
        ),
        (
            "本公司截至二零二六年六月三十日止年度的收入增加百分之十八\uff0c主要由於光模塊需求強勁。",
            "zh",
        ),
        ("当社の売上高は前年同期比で増加しました。データセンター向けの需要が堅調です。", "ja"),
        ("Revenue: 412.6", "und"),
    ],
)
def test_plain_text_gets_a_detected_language(text: str, language: str) -> None:
    result = parse(text.encode("utf-8"), "text/plain")

    assert isinstance(result, ParsedText)
    assert result.language == language
    assert result.pages == ()


def test_html_declares_its_language_on_the_html_element() -> None:
    html = b'<html lang="fr-FR"><body><p>Revenue grew.</p></body></html>'

    result = parse(html, "text/html")

    assert isinstance(result, ParsedText)
    assert result.language == "fr"
    assert result.text == "Revenue grew.\n"
