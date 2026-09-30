"""Parser versions (pilot fix 04): a new parser version parses new Source Versions only.

Seam: the `atlas` CLI (`sources import`) and `/api/v1`, on a fresh database. The document is
shaped like Coherent's FY2026 10-K around two page breaks (the markup of the recorded filing,
styles shortened). The version "recorded before `text-v3`" is inserted directly, as the ledger
recorded it then: the same raw bytes, with its `text-v2` parse (written here by hand from
v2's rules: page numbers and back-links in the text) in the archive.
"""

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from atlas.archive import Namespace, open_archive
from tests.fakes.hindsight import RecordedHindsight
from tests.fakes.serve import Served
from tests.harness import Atlas

ORIGIN = "https://filings.example.test/coherent/fy2026-10-k.htm"
ORIGIN_BEFORE = "https://filings.example.test/coherent/fy2026-10-k-recorded-earlier.htm"
PAGE_BREAK = '<hr style="page-break-after:always"/>'
BACK_LINK = (
    '<div style="min-height:42.75pt;width:100%"><div><span>'
    '<a href="#i994ba7cf1bc444699c20cbef454a6f29_7">Table of Contents</a></span></div></div>'
)
FIRST_HALF = (
    "Our vertically integrated technology platform includes the in-house design and manufacture"
)
SECOND_HALF = "of transceivers and many of their critical components, including lasers."
CAPACITY = "We continue to expand our global InP capacity."


def footer(page_number: int) -> str:
    return (
        '<div style="height:42.75pt;position:relative;width:100%">'
        '<div style="bottom:0;position:absolute;width:100%">'
        f'<div style="text-align:center"><span>{page_number}</span></div></div></div>'
    )


def paragraph(line: str) -> str:
    return f'<div style="margin-top:6pt;text-align:justify"><span>{line}</span></div>'


def filing(capacity: str = CAPACITY) -> bytes:
    body = (
        paragraph("Sources of Supply")
        + paragraph(f"{FIRST_HALF} ")
        + footer(9)
        + PAGE_BREAK
        + BACK_LINK
        + paragraph(SECOND_HALF)
        + paragraph(capacity)
        + footer(10)
        + PAGE_BREAK
        + BACK_LINK
        + paragraph("Item 1A. RISK FACTORS")
    )
    return f"<html><body>{body}</body></html>".encode()


PARSE_V2 = (
    f"Sources of Supply\n{FIRST_HALF}\n9\nTable of Contents\n{SECOND_HALF}\n{CAPACITY}\n"
    "10\nTable of Contents\nItem 1A. RISK FACTORS\n"
)
PARSE_V3 = f"Sources of Supply\n{FIRST_HALF} {SECOND_HALF}\n{CAPACITY}\nItem 1A. RISK FACTORS\n"
WHOLE_QUOTE = "includes the in-house design and manufacture of transceivers"


@pytest.fixture
def atlas(
    database_url: str, tmp_path: Path, hindsight: tuple[RecordedHindsight, Served]
) -> Iterator[Atlas]:
    harness = Atlas(database_url, tmp_path, hindsight[1].url)
    harness.apply_template()
    yield harness
    harness.engine.dispose()


def import_filing(atlas: Atlas, origin: str, content: bytes) -> dict[str, Any]:
    file = atlas.tmp_path / "fy2026-10-k.htm"
    file.write_bytes(content)
    result = atlas.cli(
        "sources",
        "import",
        "--company",
        "coherent",
        "--file",
        str(file),
        "--origin-url",
        origin,
        "--published-at",
        "2026-08-18T16:30-04:00",
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def record_under_text_v2(atlas: Atlas, recorded: dict[str, Any]) -> str:
    """The same document as `recorded`, at `ORIGIN_BEFORE`, as the ledger recorded it under
    `text-v2`: the same raw bytes, the v2 parse archived, the parse columns saying so."""
    parsed_uri = open_archive(atlas.settings()).put(Namespace.PARSED, PARSE_V2.encode())
    with atlas.engine.begin() as connection:
        document_id = connection.execute(
            text(
                "INSERT INTO source_document (id, company_id, provider, canonical_url,"
                " origin_url, accession, form_type, document_type, source_type, title,"
                " publisher, source_tier, license_class, first_seen_at)"
                " SELECT gen_random_uuid(), company_id, provider, :url, :url, accession,"
                " form_type, document_type, source_type, title, publisher, source_tier,"
                " license_class, first_seen_at"
                " FROM source_document WHERE id = :document RETURNING id"
            ),
            {"document": recorded["source_document_id"], "url": ORIGIN_BEFORE},
        ).scalar_one()
        return str(
            connection.execute(
                text(
                    "INSERT INTO source_version (id, source_document_id, version_number,"
                    " raw_sha256, comparison_sha256, comparison_rule, object_uri, byte_size,"
                    " media_type, content_sha256, parsed_object_uri, parser_version,"
                    " parse_status, language, available_at, available_at_basis, fetched_at,"
                    " fetch_status, metadata)"
                    " SELECT gen_random_uuid(), :document, 1, raw_sha256, comparison_sha256,"
                    " comparison_rule, object_uri, byte_size, media_type, :content_sha256,"
                    " :parsed_object_uri, 'text-v2', parse_status, language, available_at,"
                    " available_at_basis, fetched_at, fetch_status, metadata"
                    " FROM source_version WHERE id = :id RETURNING id"
                ),
                {
                    "document": document_id,
                    "id": recorded["source_version_id"],
                    "content_sha256": hashlib.sha256(PARSE_V2.encode()).hexdigest(),
                    "parsed_object_uri": parsed_uri,
                },
            ).scalar_one()
        )


def create_assertion(atlas: Atlas, version_id: str, quote: str, start: int) -> Any:
    return atlas.api.post(
        "/api/v1/assertions",
        json={
            "subject_company_id": atlas.company("coherent")["id"],
            "predicate": "manufactures",
            "value_json": {"product": "transceivers"},
            "source_version_id": version_id,
            "quote": quote,
            "span_start": start,
            "span_end": start + len(quote),
            "epistemic_type": "company_claim",
        },
    )


def test_a_new_version_is_parsed_without_page_artifacts_and_its_raw_bytes_are_untouched(
    atlas: Atlas,
) -> None:
    imported = import_filing(atlas, ORIGIN, filing())

    version = atlas.get(f"/api/v1/source-versions/{imported['source_version_id']}")
    assert version["parser_version"] == "text-v3"
    assert version["parse_status"] == "parsed"
    assert atlas.parsed(version["id"]) == PARSE_V3
    assert version["content_sha256"] == hashlib.sha256(PARSE_V3.encode()).hexdigest()
    raw = atlas.api.get(f"/api/v1/source-versions/{version['id']}/content", params={"kind": "raw"})
    assert raw.content == filing()
    assert version["raw_sha256"] == hashlib.sha256(filing()).hexdigest()
    # A quote across the former page break is now an exact span of the parse.
    created = create_assertion(atlas, version["id"], WHOLE_QUOTE, PARSE_V3.index(WHOLE_QUOTE))
    assert created.status_code == 201, created.text


def test_a_version_parsed_before_text_v3_keeps_its_parse_and_its_assertion_spans(
    atlas: Atlas,
) -> None:
    earlier = record_under_text_v2(atlas, import_filing(atlas, ORIGIN, filing()))
    # An Assertion made on the v2 parse: its span lies after the first page's artifacts, so
    # the same quote is at other offsets in a v3 parse of the same bytes.
    start = PARSE_V2.index(CAPACITY)
    assert start != PARSE_V3.index(CAPACITY)
    created = create_assertion(atlas, earlier, CAPACITY, start)
    assert created.status_code == 201, created.text
    assertion_id = created.json()["assertion"]["id"]

    # The same bytes again, with `text-v3` now the parser: no new version and no re-parse.
    again = import_filing(atlas, ORIGIN_BEFORE, filing())

    assert (again["outcome"], again["source_version_id"]) == ("unchanged", earlier)
    version = atlas.get(f"/api/v1/source-versions/{earlier}")
    assert version["parser_version"] == "text-v2"
    assert version["content_sha256"] == hashlib.sha256(PARSE_V2.encode()).hexdigest()
    assert atlas.parsed(earlier) == PARSE_V2
    assertion = atlas.get(f"/api/v1/assertions/{assertion_id}")
    assert (assertion["span_start"], assertion["span_end"]) == (start, start + len(CAPACITY))
    assert atlas.parsed(earlier)[assertion["span_start"] : assertion["span_end"]] == CAPACITY
    # A quote across the page artifacts is still no span of the v2 parse.
    refused = create_assertion(atlas, earlier, WHOLE_QUOTE, PARSE_V3.index(WHOLE_QUOTE))
    assert refused.status_code == 422, refused.text
    assert refused.json()["error"]["code"] == "quote_mismatch"

    # A revised document is a new version, parsed by `text-v3`; the earlier one is unchanged.
    revised_capacity = "We doubled our global InP capacity."
    revised = import_filing(atlas, ORIGIN_BEFORE, filing(revised_capacity))

    assert revised["outcome"] == "new_version"
    latest = atlas.get(f"/api/v1/source-versions/{revised['source_version_id']}")
    assert latest["parser_version"] == "text-v3"
    assert atlas.parsed(latest["id"]) == PARSE_V3.replace(CAPACITY, revised_capacity)
    assert atlas.get(f"/api/v1/source-versions/{earlier}")["parser_version"] == "text-v2"
    assert atlas.parsed(earlier) == PARSE_V2
