"""PDF Source Versions and their language: parse, page anchors, Assertions, retention.

Seams: the source ledger at the adapter boundary (`SourceLedger.record`, which every
adapter's fetch goes through; the exchange adapters that fetch PDFs are later tickets),
then `/api/v1` and `enqueue_retains` (what an ingest calls for its new versions), on a
fresh database. The PDFs are `tests/fixtures/pdf/` (scripts/make_pdf_fixtures.py); the
expected texts are the lines that script draws.
"""

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from atlas.api.app import create_app
from atlas.archive import open_archive
from atlas.audit import Actor
from atlas.companies import load_universe, seed
from atlas.jobs import JobQueue, Worker, builtin_registry
from atlas.ledger import SourceLedger
from atlas.retention import enqueue_retains
from atlas.sources import FetchedDocument, HttpValidators, SourceCandidate
from tests.fakes.hindsight import RecordedHindsight
from tests.fakes.serve import Served
from tests.harness import BANK, REPO, THEMES, make_settings

PDFS = REPO / "tests" / "fixtures" / "pdf"
ACTOR = "pdf-test-researcher"
FOLDER = "https://www.sec.gov/Archives/edgar/data/1633978/000000000026000001"
AT = datetime(2026, 9, 29, 14, 0, tzinfo=UTC)

# Page 2 (label "1") of the annual report, as scripts/make_pdf_fixtures.py draws it.
COVER = "Photonics Example plc\nAnnual Report and Accounts 2026\n"
REVENUE_QUOTE = "Revenue grew 18% to €412.6 million in the year ended 30 June 2026."
REVENUE_START = len(COVER) + len("Chair's statement\n")


class Atlas:
    def __init__(self, database_url: str, engine: Engine, tmp_path: Path, **overrides: Any) -> None:
        self.engine = engine
        self.settings = make_settings(
            tmp_path / "archive",
            database_url=database_url,
            actor=ACTOR,
            themes_config=THEMES,
            **overrides,
        )
        (tmp_path / "archive").mkdir()
        with engine.begin() as connection:
            (seeded,) = seed(connection, Actor(ACTOR), load_universe(THEMES), ["lumentum"])
        self.company_id = seeded.company_id
        self.ledger = SourceLedger(engine, open_archive(self.settings), Actor(ACTOR))
        self.api = TestClient(create_app(self.settings))

    def record(self, name: str, language: str | None = None) -> str:
        """Record a fixture PDF as an adapter's fetch; returns its Source Version's ID."""
        url = f"{FOLDER}/{name}"
        candidate = SourceCandidate(
            provider_id="sec_edgar",
            kind="sec_filing_document",
            url=url,
            title=name,
            document_type="PDF",
            discovered_at=AT,
            available_at=AT,
            available_at_basis="observed_discovery",
            language=language,
        )
        fetched = FetchedDocument(
            candidate=candidate,
            url=url,
            fetched_at=AT,
            not_modified=False,
            content=(PDFS / name).read_bytes(),
            media_type="application/pdf",
            validators=HttpValidators(),
            attempts=(),
        )
        recorded = self.ledger.record(fetched, company_id=self.company_id)
        return str(recorded.source_version_id)

    def get(self, path: str, **params: Any) -> Any:
        response = self.api.get(path, params=params)
        assert response.status_code == 200, response.text
        return response.json()

    def parsed(self, version_id: str) -> str:
        response = self.api.get(
            f"/api/v1/source-versions/{version_id}/content", params={"kind": "parsed"}
        )
        assert response.status_code == 200, response.text
        return response.content.decode("utf-8")

    def assert_quote(self, version_id: str, quote: str, start: int, **extra: Any) -> Any:
        return self.api.post(
            "/api/v1/assertions",
            json={
                "subject_company_id": str(self.company_id),
                "predicate": "reported_revenue_growth",
                "source_version_id": version_id,
                "quote": quote,
                "span_start": start,
                "span_end": start + len(quote),
                "epistemic_type": "company_claim",
                **extra,
            },
        )


@pytest.fixture
def atlas(database_url: str, engine: Engine, tmp_path: Path) -> Atlas:
    return Atlas(database_url, engine, tmp_path)


def test_a_pdf_version_has_its_text_language_and_page_anchors(atlas: Atlas) -> None:
    version = atlas.get(f"/api/v1/source-versions/{atlas.record('annual-report-en.pdf')}")

    assert version["media_type"] == "application/pdf"
    assert version["parse_status"] == "parsed"
    assert version["parser_version"] == "text-v2"
    assert version["language"] == "en"
    text = atlas.parsed(version["id"])
    assert text.startswith(COVER + "Chair's statement\n" + REVENUE_QUOTE + "\n")
    anchors = version["page_anchors"]
    assert [(a["page"], a["label"]) for a in anchors] == [(1, "i"), (2, "1"), (3, "2")]
    assert anchors[0] == {"page": 1, "label": "i", "start": 0, "end": len(COVER)}
    assert anchors[2]["end"] == len(text)
    assert text[anchors[1]["start"] : anchors[1]["end"]].startswith("Chair's statement\n")
    assert text[anchors[2]["start"] : anchors[2]["end"]].startswith("Principal risks\n")


def test_the_same_pdf_bytes_make_no_new_version(atlas: Atlas) -> None:
    first = atlas.record("annual-report-en.pdf")

    assert atlas.record("annual-report-en.pdf") == first


def test_an_assertion_on_a_pdf_binds_its_exact_span_and_names_its_page(atlas: Atlas) -> None:
    version_id = atlas.record("annual-report-en.pdf")

    created = atlas.assert_quote(version_id, REVENUE_QUOTE, REVENUE_START)
    shifted = atlas.assert_quote(version_id, REVENUE_QUOTE, REVENUE_START + 1)
    labelled = atlas.assert_quote(
        version_id, REVENUE_QUOTE, REVENUE_START, page_or_anchor="Chair's statement"
    )
    across = atlas.assert_quote(
        version_id, "Accounts 2026\nChair's statement", len(COVER) - len("Accounts 2026\n")
    )

    assert created.status_code == 201, created.text
    assertion = created.json()["assertion"]
    assert (assertion["quote"], assertion["span_start"]) == (REVENUE_QUOTE, REVENUE_START)
    # Physical page 2 carries the label "1": the label is what a reader finds printed.
    assert assertion["page_or_anchor"] == "page 1 (PDF page 2)"
    assert shifted.status_code == 422
    assert shifted.json()["error"]["code"] == "quote_mismatch"
    assert labelled.json()["assertion"]["page_or_anchor"] == "Chair's statement"
    assert across.status_code == 201, across.text
    assert across.json()["assertion"]["page_or_anchor"] == "pages i\u20131 (PDF pages 1\u20132)"


def test_an_image_only_pdf_is_unsupported_and_cannot_be_quoted(atlas: Atlas) -> None:
    version = atlas.get(f"/api/v1/source-versions/{atlas.record('scanned.pdf')}")

    assert version["parse_status"] == "unsupported"
    assert version["parser_version"] == "text-v2"
    assert version["parse_error"] == (
        "no extractable text on any of its 2 pages (an image-only or scanned PDF)"
    )
    assert version["content_sha256"] is None
    assert version["content"]["parsed"] is None
    assert version["page_anchors"] is None
    refused = atlas.assert_quote(version["id"], "Revenue", 0)
    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "no_parsed_text"


def test_a_non_english_pdf_is_archived_with_its_language_and_never_retained(
    atlas: Atlas,
) -> None:
    french = atlas.record("results-fr.pdf")
    english = atlas.record("annual-report-en.pdf")
    scanned = atlas.record("scanned.pdf")

    version = atlas.get(f"/api/v1/source-versions/{french}")
    retains = enqueue_retains(atlas.engine, [uuid.UUID(v) for v in (french, english, scanned)])

    assert version["language"] == "fr"
    assert version["parse_status"] == "parsed"
    assert atlas.parsed(french).startswith("Résultats du premier semestre")
    # Only the English, parsed version gets a retain job.
    assert len(retains) == 1
    job = atlas.get(f"/api/v1/jobs/{retains[0]}")
    assert job["payload"] == {"source_version_id": english}


def test_an_adapter_declared_language_overrides_the_parse(atlas: Atlas) -> None:
    # An exchange that lists this document as Chinese is believed over the text.
    version = atlas.get(f"/api/v1/source-versions/{atlas.record('results-fr.pdf', 'zh')}")

    assert version["language"] == "zh"
    assert enqueue_retains(atlas.engine, [uuid.UUID(version["id"])]) == []


def test_a_retain_job_for_a_non_english_version_retains_nothing(
    database_url: str,
    engine: Engine,
    tmp_path: Path,
    hindsight: tuple[RecordedHindsight, Served],
) -> None:
    # A retain enqueued by hand (`atlas jobs enqueue retain`) still refuses. The served
    # fake fails the test on any request it can't answer: none is made.
    _, served = hindsight
    atlas = Atlas(database_url, engine, tmp_path, hindsight_url=served.url, hindsight_bank_id=BANK)
    french = atlas.record("results-fr.pdf")
    queue = JobQueue(engine, actor=Actor(ACTOR))
    job = queue.enqueue("retain", "retain-french", {"source_version_id": french}).job

    assert Worker(queue, builtin_registry(atlas.settings)).run_once() == 1

    done = atlas.get(f"/api/v1/jobs/{job.id}")
    assert done["status"] == "succeeded", done["failures"]
    assert done["artifacts"]["outcome"] == "not_retainable"
    assert done["artifacts"]["language"] == "fr"
    assert atlas.get(f"/api/v1/source-versions/{french}/memory")["documents"] == []
