"""The deterministic parser, on the recorded Lumentum EDGAR documents."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from atlas.parsing import PARSER_VERSION, parse

ARCHIVES = (
    Path(__file__).parents[1]
    / "fixtures"
    / "edgar"
    / "lumentum"
    / "www.sec.gov"
    / "Archives"
    / "edgar"
    / "data"
    / "1633978"
)
DOCUMENTS = sorted(ARCHIVES.glob("*/lite*.htm"))
FORM_8K = ARCHIVES / "000162828026055726" / "lite-20260811.htm"
FORM_10K = ARCHIVES / "000162828026057358" / "lite-20260627.htm"
# The content hashes of html-text-v1 on each fixture, pinned when the version was made.
# If one changes, the parser's output changed: that needs a new PARSER_VERSION.
GOLDEN = json.loads((Path(__file__).parents[1] / "fixtures" / "parser" / "golden.json").read_text())
SEC_EDGE_SCRIPT = (
    b'<script type="text/javascript"  src="/KSRe0AD3p8BYYbpDUqIn/EQS3hbNfLJf4tLS3/'
    b'XgdUa3RMAg/ZlE8/IkgkRic"></script>'
)


def test_all_four_recorded_filing_documents_are_covered() -> None:
    assert sorted(path.name for path in DOCUMENTS) == sorted(GOLDEN[PARSER_VERSION])
    assert len(DOCUMENTS) == 4


@pytest.mark.parametrize("path", DOCUMENTS, ids=lambda path: path.name)
def test_the_same_bytes_give_the_same_text_and_the_pinned_hash(path: Path) -> None:
    raw = path.read_bytes()

    first, second = parse(raw, "text/html"), parse(raw, "text/html")

    assert first is not None and second is not None
    assert first.text == second.text
    assert first.parser_version == PARSER_VERSION == "html-text-v1"
    assert first.complete
    assert hashlib.sha256(first.encoded()).hexdigest() == first.sha256
    assert first.sha256 == GOLDEN[PARSER_VERSION][path.name]


def test_the_parse_does_not_depend_on_the_process() -> None:
    script = (
        "import sys; from pathlib import Path; from atlas.parsing import parse; "
        "print(parse(Path(sys.argv[1]).read_bytes(), 'text/html').sha256)"
    )
    hashes = {
        subprocess.run(
            [sys.executable, "-c", script, str(FORM_10K)],
            env={**os.environ, "PYTHONHASHSEED": seed, "LC_ALL": "C", "TZ": zone},
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        for seed, zone in (("1", "UTC"), ("12345", "America/New_York"))
    }

    assert hashes == {GOLDEN[PARSER_VERSION][FORM_10K.name]}


def test_text_keeps_the_filing_statements_and_drops_hidden_and_active_content() -> None:
    parsed = parse(FORM_10K.read_bytes(), "text/html")

    assert parsed is not None
    text = parsed.text
    # A statement from the 10-K body, with its entities decoded.
    assert (
        "Our common stock is listed on the Nasdaq Global Select Market under the symbol "
        "\u201cLITE.\u201d"
    ) in text
    # SEC's edge-injected script, the <head> and the hidden inline-XBRL header are gone.
    assert "KSRe0" not in text
    assert "<" not in text.split("\n")[0]
    assert "lite-20260627" not in text  # the <title>
    assert "xbrli" not in text
    assert "\u00a0" not in text
    assert text.endswith("\n")
    assert "\n\n" not in text


def test_table_cells_are_tab_separated_on_one_line() -> None:
    parsed = parse(FORM_8K.read_bytes(), "text/html")

    assert parsed is not None
    assert "Common Stock, par value of $0.001 per share\tLITE\tNasdaq Global Select Market\n" in (
        parsed.text
    )


def test_a_different_sec_edge_script_does_not_change_the_parse() -> None:
    raw = FORM_8K.read_bytes()
    assert raw.count(SEC_EDGE_SCRIPT) == 1
    variant = raw.replace(SEC_EDGE_SCRIPT, b'<script type="text/javascript" src="/other"></script>')

    original, varied = parse(raw, "text/html"), parse(variant, "text/html")

    assert original is not None and varied is not None
    assert varied.sha256 == original.sha256


def test_a_changed_statement_changes_the_parse() -> None:
    raw = FORM_8K.read_bytes()
    changed = raw.replace(b"fourth quarter and full fiscal year", b"third quarter", 1)
    assert changed != raw

    original, edited = parse(raw, "text/html"), parse(changed, "text/html")

    assert original is not None and edited is not None
    assert edited.sha256 != original.sha256
    assert "reported results for its third quarter ended June 27, 2026" in edited.text


def test_markup_rules_on_a_small_document() -> None:
    html = (
        b"<?xml version='1.0' encoding='ASCII'?><html><head><title>T</title>"
        b"<style>p{}</style></head><body><p>One&#160;&amp;  two</p>"
        b"<div style='DISPLAY: none'>hidden<p>deeper</p></div><p>three<br/>four</p>"
        b"<pre>a  b\nc</pre><!-- comment --><script>alert(1)</script></body></html>"
    )

    parsed = parse(html, "text/html")

    assert parsed is not None
    assert parsed.text == "One & two\nthree\nfour\na b\nc\n"


def test_undecodable_bytes_make_an_incomplete_parse() -> None:
    parsed = parse(b"<p>caf\xc3 \x81</p>", "text/html")

    assert parsed is not None
    assert not parsed.complete
    assert "\ufffd" in parsed.text


def test_windows_1252_is_the_fallback_charset() -> None:
    parsed = parse(b"<p>\x93quoted\x94</p>", "text/html")

    assert parsed is not None
    assert parsed.complete
    assert parsed.text == "\u201cquoted\u201d\n"


def test_plain_text_is_normalized_by_the_same_line_rules() -> None:
    parsed = parse(b"  first\r\n\r\n second   line \rthird\n", "text/plain")

    assert parsed is not None
    assert parsed.text == "first\nsecond line\nthird\n"


def test_json_and_other_media_types_are_not_parsed() -> None:
    assert parse(b"{}", "application/json") is None
    assert parse(b"\x00", "application/octet-stream") is None
