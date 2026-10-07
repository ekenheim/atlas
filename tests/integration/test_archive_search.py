"""Archive term search as a service (bottleneck-argument ticket 01): `GET /api/v1/archive-search`
over the parsed English Source Versions of some companies at an as-of time.

Seam: `/api/v1` and the `atlas` CLI (`sources import`, which records and parses each document),
on a fresh database. The documents are hand-written HTML, published at chosen times for
Coherent and Lumentum; nothing is retained (no worker pass).
"""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.fakes.hindsight import RecordedHindsight
from tests.fakes.serve import Served
from tests.harness import Atlas

# Each paragraph is longer than a passage's minimum (300 characters), so each is its own passage.
SUBSTRATE = (
    "Our indium phosphide substrate supply comes from two qualified vendors, and we have "
    "signed a multi-year agreement that reserves substrate wafers for our laser production "
    "lines through fiscal 2028, because qualification of a new substrate vendor takes "
    "more than a year, during which our own production plans for the next generation of "
    "high speed transceivers would otherwise be at risk."
)
MODULATOR = (
    "Lumentum ships electro-absorption modulated lasers for 1.6T transceivers, and the "
    "modulated laser output of our Japan fab is sold out for the coming year as hyperscale "
    "customers pull in their orders ahead of the next generation of optical networks, "
    "which keeps the factory running at full capacity through the end of the fiscal year."
)
EPITAXY = (
    "Gallium arsenide epitaxy capacity in Texas was expanded in the quarter, and the added "
    "reactors allow us to double our epitaxy output for vertical cavity lasers once the new "
    "reactors are qualified by our largest datacenter customers, which we expect to complete "
    "before the end of the calendar year according to the schedule agreed with them."
)
PACKAGING = (
    "Photodetector packaging is performed at our contract assembly partner in Malaysia, which "
    "holds all the specialised test equipment, and we have no second source for photodetector "
    "packaging at present because requalifying a new assembler would take many months of work, "
    "including the reliability testing that our largest customers require of every new line."
)
PACKAGING_LATER = PACKAGING + " Customers have not yet asked us for one."


def html(*paragraphs: str) -> bytes:
    body = "".join(f"<p>{paragraph}</p>" for paragraph in paragraphs)
    return f"<html><body>{body}</body></html>".encode()


@pytest.fixture
def atlas(
    database_url: str, tmp_path: Path, hindsight: tuple[RecordedHindsight, Served]
) -> Iterator[Atlas]:
    harness = Atlas(database_url, tmp_path, hindsight[1].url)
    seeded = harness.cli("companies", "seed")
    assert seeded.returncode == 0, seeded.stderr
    yield harness
    harness.engine.dispose()


def import_html(atlas: Atlas, company: str, name: str, published: str, *paragraphs: str) -> str:
    file = atlas.tmp_path / f"{name}.htm"
    file.write_bytes(html(*paragraphs))
    result = atlas.cli(
        "sources",
        "import",
        "--company",
        company,
        "--file",
        str(file),
        "--origin-url",
        f"https://filings.example.test/{company}/{name}.htm",
        "--published-at",
        published,
        "--title",
        name,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)["source_version_id"]


def search(atlas: Atlas, query: str, *companies: str, **params: Any) -> dict[str, Any]:
    ids = [atlas.company(slug)["id"] for slug in companies]
    return atlas.get("/api/v1/archive-search", q=query, company_id=ids, **params)


def test_a_term_is_found_only_with_the_company_whose_filing_has_it(atlas: Atlas) -> None:
    coherent = import_html(
        atlas, "coherent", "coherent-10-k", "2026-03-01T12:00:00Z", SUBSTRATE, EPITAXY
    )
    lumentum = import_html(atlas, "lumentum", "lumentum-10-k", "2026-03-02T12:00:00Z", MODULATOR)

    with_coherent = search(atlas, "indium phosphide substrate vendors", "coherent")
    with_lumentum = search(atlas, "indium phosphide substrate vendors", "lumentum")
    with_both = search(atlas, "indium phosphide substrate vendors", "lumentum", "coherent")

    assert [hit["source_version_id"] for hit in with_coherent["hits"]] == [coherent]
    assert with_lumentum["hits"] == []
    assert with_lumentum["documents_searched"] == 1
    assert [hit["source_version_id"] for hit in with_both["hits"]] == [coherent]
    (hit,) = with_both["hits"]
    version = atlas.get(f"/api/v1/source-versions/{coherent}")
    assert hit["company"] == "coherent"
    assert hit["company_id"] == atlas.company("coherent")["id"]
    assert hit["title"] == "coherent-10-k"
    assert hit["provider"] == "manual_import"
    assert hit["available_at"].startswith("2026-03-01T12:00:00")
    assert hit["score"] > 0
    assert {"indium", "phosphide", "substrate"} <= set(hit["terms"])
    assert SUBSTRATE in hit["text"]
    assert hit["parser_version"] == version["current_parser_version"]
    assert hit["section_anchor"]
    assert with_both["terms"] == ["indium", "phosphide", "substrate", "vendor"]

    modulators = search(atlas, "electro-absorption modulated", "lumentum", "coherent")
    assert [h["source_version_id"] for h in modulators["hits"]] == [lumentum]


def test_as_of_excludes_a_later_version(atlas: Atlas) -> None:
    earlier = import_html(atlas, "coherent", "early", "2026-03-01T12:00:00Z", SUBSTRATE)
    later = import_html(atlas, "coherent", "late", "2026-09-01T12:00:00Z", EPITAXY)

    before = search(atlas, "gallium arsenide epitaxy", "coherent", as_of="2026-06-01T00:00:00Z")
    after = search(atlas, "gallium arsenide epitaxy", "coherent", as_of="2026-10-01T00:00:00Z")
    still = search(atlas, "indium phosphide substrate", "coherent", as_of="2026-06-01T00:00:00Z")

    assert before["hits"] == []
    assert before["documents_searched"] == 1
    assert [hit["source_version_id"] for hit in after["hits"]] == [later]
    assert after["documents_searched"] == 2
    assert [hit["source_version_id"] for hit in still["hits"]] == [earlier]


def test_a_statement_repeated_across_filings_is_one_hit(atlas: Atlas) -> None:
    older = import_html(atlas, "coherent", "older", "2026-02-10T12:00:00Z", PACKAGING)
    newer = import_html(atlas, "coherent", "newer", "2026-03-10T12:00:00Z", PACKAGING_LATER)

    found = search(atlas, "photodetector packaging second source", "coherent")

    (hit,) = found["hits"]
    assert hit["source_version_id"] == newer
    assert [other["source_version_id"] for other in hit["also_in"]] == [older]
    assert hit["also_in"][0]["title"] == "older"


def test_per_document_and_top_bound_the_hits(atlas: Atlas) -> None:
    import_html(atlas, "coherent", "many", "2026-03-01T12:00:00Z", SUBSTRATE, EPITAXY, PACKAGING)

    one = search(atlas, "substrate epitaxy packaging", "coherent", per_document=1)
    two = search(atlas, "substrate epitaxy packaging", "coherent", per_document=2, top=2)
    three = search(atlas, "substrate epitaxy packaging", "coherent", per_document=3, top=1)

    assert len(one["hits"]) == 1
    assert len(two["hits"]) == 2
    assert len(three["hits"]) == 1


def test_a_hits_offsets_round_trip_through_the_span_check(atlas: Atlas) -> None:
    version = import_html(atlas, "coherent", "spans", "2026-03-01T12:00:00Z", EPITAXY, SUBSTRATE)
    (hit,) = search(atlas, "indium phosphide substrate vendors", "coherent")["hits"]

    parsed = atlas.parsed(version)
    assert parsed[hit["char_start"] : hit["char_end"]] == hit["text"]
    quote = "multi-year agreement that reserves substrate wafers"
    start = hit["char_start"] + hit["text"].index(quote)
    response = atlas.api.post(
        "/api/v1/assertions",
        json={
            "subject_company_id": atlas.company("coherent")["id"],
            "predicate": "expands_capacity_for",
            "value_json": {"product": "InP"},
            "source_version_id": hit["source_version_id"],
            "quote": quote,
            "span_start": start,
            "span_end": start + len(quote),
            "epistemic_type": "company_claim",
            "parser_version": hit["parser_version"],
        },
    )
    assert response.status_code == 201, response.text


def test_an_unknown_company_or_a_missing_query_is_refused(atlas: Atlas) -> None:
    unknown = atlas.api.get(
        "/api/v1/archive-search",
        params={"q": "substrate", "company_id": "00000000-0000-0000-0000-000000000001"},
    )
    assert unknown.status_code == 422
    assert unknown.json()["error"]["code"] == "unknown_company"

    coherent = atlas.company("coherent")["id"]
    missing = atlas.api.get("/api/v1/archive-search", params={"company_id": coherent})
    assert missing.status_code == 422
    assert missing.json()["error"]["code"] == "invalid_request"
