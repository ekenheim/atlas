"""A Source Version the scan cannot read fails the job and leaves the pointer where it was
(atlas-beliefs ticket 18).

Seam: the `atlas` CLI records two hand-written documents (`sources import`) and enqueues the scan,
single worker passes run it, and the job and the leads are read through `/api/v1`. One document's
archived parse is removed from the archive root, as a damaged volume would.
"""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import text

from tests.harness import Atlas

STRONG = "Our lasers are sold out through next year."
MISSING = "Demand exceeds our supply."
# A language detector needs more than one short sentence to call a document English.
FILLER = (
    "The company designs and manufactures products for customers in many markets and"
    " describes its business, its employees and its facilities in the sections of this report."
)


@pytest.fixture
def atlas(database_url: str, tmp_path: Path) -> Iterator[Atlas]:
    harness = Atlas(database_url, tmp_path, "", signal_scan_lag_seconds=0)
    seeded = harness.cli("companies", "seed")
    assert seeded.returncode == 0, seeded.stderr
    yield harness
    harness.engine.dispose()


def import_html(atlas: Atlas, name: str, published: str, sentence: str) -> str:
    file = atlas.tmp_path / f"{name}.htm"
    file.write_bytes(f"<html><body><p>{FILLER}</p><p>{sentence}</p></body></html>".encode())
    result = atlas.cli(
        "sources",
        "import",
        "--company",
        "coherent",
        "--file",
        str(file),
        "--origin-url",
        f"https://filings.example.test/{name}.htm",
        "--published-at",
        published,
        "--title",
        name,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)["source_version_id"]


def test_an_unreadable_version_fails_the_job_after_the_others_and_is_read_again(
    atlas: Atlas,
) -> None:
    readable = import_html(atlas, "readable", "2025-07-31T20:00:00Z", STRONG)
    damaged = import_html(atlas, "damaged", "2025-08-01T20:00:00Z", MISSING)
    with atlas.engine.connect() as connection:
        uri = connection.execute(
            text("SELECT parsed_object_uri FROM source_version WHERE id = :id"), {"id": damaged}
        ).scalar_one()
    [removed] = list(atlas.archive.rglob(uri.rsplit("/", 1)[1]))  # the file is named by its hash
    parsed = removed.read_bytes()
    removed.unlink()

    job_id = atlas.enqueue("signals", "scan", "--key", "first")
    atlas.worker_pass()
    job = atlas.get(f"/api/v1/jobs/{job_id}")

    assert job["status"] == "failed"
    assert job["artifacts"]["stored"] == 1
    assert job["artifacts"]["scan_id"] is None
    assert [each["source_version_id"] for each in job["artifacts"]["versions_failed"]] == [damaged]
    leads = atlas.get("/api/v1/leads", origin="archive_signal")["items"]
    assert [(each["signal"]["source_version_id"], each["signal"]["quote"]) for each in leads] == [
        (readable, STRONG)
    ]
    with atlas.engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM signal_scan")).scalar_one() == 0

    removed.parent.mkdir(parents=True, exist_ok=True)
    removed.write_bytes(parsed)  # the volume is repaired
    again = atlas.enqueue("signals", "scan", "--key", "second")
    atlas.worker_pass()
    second = atlas.get(f"/api/v1/jobs/{again}")

    assert second["status"] == "succeeded", second["failures"]
    assert (second["artifacts"]["versions_selected"], second["artifacts"]["stored"]) == (2, 1)
    assert second["artifacts"]["already"] == 1  # the readable one's lead is not stored twice
