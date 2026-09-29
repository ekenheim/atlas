"""Manual import (Phase 3-6a ticket 04, after the HKEXnews terms check): a document the owner
fetched by hand enters the ledger through `atlas sources import`.

Seam: the `atlas` CLI, one worker pass (the retains, against the served Hindsight fake) and
`/api/v1`, on a fresh database. The files are the synthetic PDFs in
`tests/fixtures/hkexnews/innolight/` (written by `scripts/make_hkexnews_fixtures.py`; not
HKEXnews documents).
"""

import hashlib
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from tests.fakes.hindsight import RecordedHindsight
from tests.fakes.serve import Served
from tests.harness import REPO, Atlas

FILES = REPO / "tests" / "fixtures" / "hkexnews" / "innolight" / "listedco/listconews/sehk/2026"
INTERIM_PDF = FILES / "0821" / "2026082101227.pdf"
OVERSEAS_PDF = FILES / "0904" / "2026090400456.pdf"
ORIGIN = "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0821/2026082101227.pdf"
ORIGIN_ZH = "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0904/2026090400456.pdf"
TITLE = "INTERIM RESULTS ANNOUNCEMENT FOR THE SIX MONTHS ENDED 30 JUNE 2026"


@pytest.fixture
def atlas(
    database_url: str, tmp_path: Path, hindsight: tuple[RecordedHindsight, Served]
) -> Iterator[Atlas]:
    harness = Atlas(database_url, tmp_path, hindsight[1].url)
    harness.apply_template()
    yield harness
    harness.engine.dispose()


def import_file(atlas: Atlas, *args: str) -> dict[str, Any]:
    result = atlas.cli("sources", "import", "--company", "innolight", *args)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def import_interim(atlas: Atlas) -> dict[str, Any]:
    return import_file(
        atlas,
        "--file",
        str(INTERIM_PDF),
        "--origin-url",
        ORIGIN,
        "--published-at",
        "2026-08-21T22:30+08:00",
        "--title",
        TITLE,
    )


def audit_actors(atlas: Atlas, entity_id: str) -> set[tuple[str, str]]:
    with atlas.engine.connect() as connection:
        rows = connection.execute(
            text("SELECT action, actor FROM audit_event WHERE entity_id = :id"), {"id": entity_id}
        )
        return {(row.action, row.actor) for row in rows}


def test_an_imported_pdf_is_recorded_parsed_and_retained(atlas: Atlas) -> None:
    imported = import_interim(atlas)
    atlas.worker_pass()  # the retain

    assert imported["outcome"] == "new_version"
    assert len(imported["retain_jobs"]) == 1
    version = atlas.get(f"/api/v1/source-versions/{imported['source_version_id']}")
    document = version["source_document"]
    assert document["provider"] == "manual_import"
    assert document["source_type"] == "manual_import"
    assert document["canonical_url"] == ORIGIN
    assert document["origin_url"] == ORIGIN
    assert document["title"] == TITLE
    assert document["publisher"] == "HKEXnews (Hong Kong Exchanges and Clearing Limited)"
    assert document["company_id"] == atlas.company("innolight")["id"]
    published = datetime(2026, 8, 21, 14, 30, tzinfo=UTC)
    assert datetime.fromisoformat(version["available_at"]) == published
    assert version["available_at_basis"] == "publisher_timestamp"
    assert datetime.fromisoformat(version["published_at"]) == published
    assert version["media_type"] == "application/pdf"
    assert version["raw_sha256"] == hashlib.sha256(INTERIM_PDF.read_bytes()).hexdigest()
    assert version["parse_status"] == "parsed"
    assert version["language"] == "en"
    assert version["page_anchors"]
    assert version["evidence_family"]["match"] == "founder"
    assert version["metadata"]["manual_import"] == {
        "publisher": "HKEXnews (Hong Kong Exchanges and Clearing Limited)",
        "file_name": "2026082101227.pdf",
        "imported_by": "local-researcher",
        "published_local": "2026-08-21T22:30+08:00",
    }
    (fetch,) = version["fetches"]
    assert fetch["gate_decision_id"] is None  # nothing was requested
    memory = atlas.memory(version["id"])
    assert memory["retained"]
    assert {d["retain_state"] for d in memory["documents"]} == {"completed"}
    assert ("source_version.created", "local-researcher") in audit_actors(atlas, version["id"])
    assert ("source_document.created", "local-researcher") in audit_actors(atlas, document["id"])


def test_reimporting_the_same_bytes_is_idempotent(atlas: Atlas) -> None:
    first = import_interim(atlas)
    atlas.worker_pass()

    again = import_interim(atlas)

    assert again["outcome"] == "unchanged"
    assert again["source_version_id"] == first["source_version_id"]
    assert again["source_document_id"] == first["source_document_id"]
    assert again["retain_jobs"] == []
    versions = atlas.get(f"/api/v1/sources/{first['source_document_id']}/versions")
    assert versions["total"] == 1


def test_a_chinese_import_is_archived_but_not_retained(atlas: Atlas) -> None:
    imported = import_file(
        atlas,
        "--file",
        str(OVERSEAS_PDF),
        "--origin-url",
        ORIGIN_ZH,
        "--published-at",
        "2026-09-04T19:05+08:00",
    )

    assert imported["retain_jobs"] == []
    version = atlas.get(f"/api/v1/source-versions/{imported['source_version_id']}")
    assert version["language"] == "zh"
    assert version["source_document"]["title"] == "2026090400456.pdf"  # the file name


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (
            ["--published-at", "2026-08-21T22:30"],
            "the publication time needs its UTC offset",
        ),
        (["--published-at", "21/08/2026 22:30"], "--published-at must be an ISO 8601 time"),
        (["--origin-url", "hkexnews report"], "the origin URL must be an http(s) URL"),
        (["--company", "no-such-company"], "company 'no-such-company' is not in"),
        (["--file", "/nonexistent/report.pdf"], "cannot read /nonexistent/report.pdf"),
    ],
)
def test_an_unusable_import_is_refused_and_records_nothing(
    atlas: Atlas, args: list[str], message: str
) -> None:
    values = {
        "--company": "innolight",
        "--file": str(INTERIM_PDF),
        "--origin-url": ORIGIN,
        "--published-at": "2026-08-21T22:30+08:00",
    }
    values.update(zip(args[::2], args[1::2], strict=True))

    result = atlas.cli("sources", "import", *(part for pair in values.items() for part in pair))

    assert result.returncode == 2
    assert message in result.stderr
    with atlas.engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM source_version")).scalar() == 0
