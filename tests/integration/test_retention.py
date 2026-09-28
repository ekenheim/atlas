"""Retention into memory: ingested Source Versions are retained section by section.

Seam: the `atlas` CLI enqueues, single worker passes run the ingest, retain, poll and
reprocess jobs, and everything is observed through `/api/v1` and the requests Hindsight
received. Hindsight is the recorded fake served on localhost, with `derive_retains` on: the
recordings hold synthetic documents only, so a retain of real sections is answered by the
recorded batch-retain, operation and document responses with only their identity fields
changed (see `tests/fakes/hindsight.py`). Zero-fact documents and failed or stuck
operations were never recorded; `report_zero_facts` and `hold_retains` derive them.
Expected sections come from the recorded EDGAR fixtures' Item headings.
"""

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from datetime import datetime
from itertools import pairwise
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from atlas.api.app import create_app
from atlas.db.migrate import upgrade
from atlas.jobs import JobQueue, Worker, builtin_registry
from atlas.settings import Settings
from tests.fakes.hindsight import RecordedHindsight
from tests.fakes.serve import Served, serve

REPO = Path(__file__).parents[2]
THEMES = REPO / "configs" / "themes" / "ai-infrastructure.yaml"
TEMPLATE = REPO / "configs" / "hindsight" / "bank-template.json"
TEMPLATE_VERSION = json.loads(TEMPLATE.read_text())["template_version"]
EDGAR_FIXTURES = REPO / "tests" / "fixtures" / "edgar"
# The bank the template recordings were made in, so `apply-template` replays as recorded.
BANK = RecordedHindsight().recording("research_template/01-import-dry-run").bank_id
# What the recorded document (`upsert/09-get-document`) reports: one memory unit.
RECORDED_FACT_COUNT = cast(
    int,
    RecordedHindsight().recording("upsert/09-get-document").response_object()["memory_unit_count"],
)

LITE = "https://www.sec.gov/Archives/edgar/data/1633978"
LITE_8K = f"{LITE}/000162828026055726/lite-20260811.htm"
LITE_EX991 = f"{LITE}/000162828026055726/lite_ex991xq4fy26.htm"
LITE_10K = f"{LITE}/000162828026057358/lite-20260627.htm"
LITE_10Q = f"{LITE}/000162828026030777/lite-20260328.htm"
LITE_FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK0001633978.json"
COHR = "https://www.sec.gov/Archives/edgar/data/820318"
COHR_10K = f"{COHR}/000082031826000020/iivi-20260630.htm"
COHR_10Q = f"{COHR}/000082031826000013/iivi-20260331.htm"
COHR_FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK0000820318.json"

# The Item headings of the fixtures' 10-Ks (both trimmed after Item 7) and 10-Qs (trimmed
# early in Part I Item 1), and the Lumentum 8-K's Items 2.02 and 9.01.
TEN_K_ANCHORS = [
    "cover",
    "part-i-item-1",
    "part-i-item-1a",
    "part-i-item-1b",
    "part-i-item-1c",
    "part-i-item-2",
    "part-i-item-3",
    "part-i-item-4",
    "part-ii-item-5",
    "part-ii-item-6",
    "part-ii-item-7",
]
TEN_Q_ANCHORS = ["cover", "part-i-item-1"]
EIGHT_K_ANCHORS = ["cover", "item-2-02", "item-9-01"]


class Atlas:
    def __init__(self, database_url: str, tmp_path: Path, hindsight_url: str, **settings: Any):
        self.database_url = database_url
        self.tmp_path = tmp_path
        self.archive = tmp_path / "archive"
        self.archive.mkdir(exist_ok=True)
        self.fixtures = EDGAR_FIXTURES
        self.hindsight_url = hindsight_url
        self.overrides = settings
        self.engine = create_engine(database_url)
        self.api = TestClient(create_app(self.settings()))

    def settings(self) -> Settings:
        return Settings.model_validate(
            {
                "database_url": self.database_url,
                "actor": "local-researcher",
                "archive_root": self.archive,
                "themes_config": THEMES,
                "sec_fixtures_dir": self.fixtures,
                "hindsight_url": self.hindsight_url,
                "hindsight_bank_id": BANK,
                "retain_poll_timeout_seconds": 0.3,
                "retain_poll_interval_seconds": 0.01,
                **self.overrides,
            }
        )

    def cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = {
            "PATH": os.environ["PATH"],
            "HOME": str(self.tmp_path),
            "ATLAS_DATABASE_URL": self.database_url,
            "ATLAS_ACTOR": "local-researcher",
            "ATLAS_ARCHIVE_ROOT": str(self.archive),
            "ATLAS_THEMES_CONFIG": str(THEMES),
            "ATLAS_SEC_FIXTURES_DIR": str(self.fixtures),
            "ATLAS_HINDSIGHT_URL": self.hindsight_url,
            "ATLAS_HINDSIGHT_BANK_ID": BANK,
            "ATLAS_HINDSIGHT_TEMPLATE_PATH": str(TEMPLATE),
        }
        return subprocess.run(
            [sys.executable, "-m", "atlas", *args],
            cwd=self.tmp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )

    def apply_template(self) -> None:
        applied = self.cli("hindsight", "apply-template")
        assert applied.returncode == 0, applied.stderr

    def worker_pass(self) -> int:
        return Worker(JobQueue(self.engine), builtin_registry(self.settings())).run_once()

    def enqueue(self, *args: str) -> str:
        enqueued = self.cli(*args)
        assert enqueued.returncode == 0, enqueued.stderr
        return json.loads(enqueued.stdout)["id"]

    def ingest(self, key: str, company: str = "lumentum") -> dict[str, Any]:
        """`atlas ingest`, then one worker pass (which also runs the retention jobs)."""
        job_id = self.enqueue("ingest", "--company", company, "--key", key)
        self.worker_pass()
        return self.get(f"/api/v1/jobs/{job_id}")

    def get(self, path: str, **params: Any) -> Any:
        response = self.api.get(path, params=params)
        assert response.status_code == 200, response.text
        return response.json()

    def company(self, slug: str) -> dict[str, Any]:
        companies = self.get("/api/v1/companies")["items"]
        return next(company for company in companies if company["slug"] == slug)

    def versions(self, url: str, company: str = "lumentum") -> list[dict[str, Any]]:
        documents = self.get(f"/api/v1/companies/{self.company(company)['id']}/sources", limit=100)
        document = next(d for d in documents["items"] if d["canonical_url"] == url)
        return self.get(f"/api/v1/sources/{document['id']}/versions")["items"]

    def version(self, url: str, company: str = "lumentum") -> dict[str, Any]:
        (version,) = self.versions(url, company)
        return self.get(f"/api/v1/source-versions/{version['id']}")

    def memory(self, version_id: str) -> dict[str, Any]:
        return self.get(f"/api/v1/source-versions/{version_id}/memory")

    def parsed(self, version_id: str) -> str:
        response = self.api.get(
            f"/api/v1/source-versions/{version_id}/content", params={"kind": "parsed"}
        )
        assert response.status_code == 200, response.text
        return response.text


@pytest.fixture
def database_url(empty_database_url: str) -> str:
    upgrade(empty_database_url)
    return empty_database_url


@pytest.fixture
def hindsight() -> Iterator[tuple[RecordedHindsight, Served]]:
    fake = RecordedHindsight()
    fake.derive_retains()
    with serve(fake.transport.handle_request) as served:
        yield fake, served
        served.raise_errors()


@pytest.fixture
def fake(hindsight: tuple[RecordedHindsight, Served]) -> RecordedHindsight:
    return hindsight[0]


@pytest.fixture
def atlas(database_url: str, tmp_path: Path, hindsight: tuple[RecordedHindsight, Served]):
    harness = Atlas(database_url, tmp_path, hindsight[1].url)
    harness.apply_template()
    yield harness
    harness.engine.dispose()


def batch_for(fake: RecordedHindsight, version_id: str) -> list[list[dict[str, Any]]]:
    """The retain batches whose items belong to the Source Version."""
    return [
        batch
        for batch in fake.retained()
        if all(str(item["document_id"]).startswith(f"srcv:{version_id}:") for item in batch)
    ]


def by_anchor(memory: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {document["section_anchor"]: document for document in memory["documents"]}


# --- retained section by section ---


def test_each_new_source_version_is_retained_section_by_section_and_tracked_to_completion(
    atlas: Atlas, fake: RecordedHindsight
) -> None:
    job = atlas.ingest("lumentum")

    assert job["status"] == "succeeded", job["failures"]
    assert len(job["artifacts"]["retain_jobs"]) == 4  # the parsed versions; not companyfacts
    ten_k = atlas.version(LITE_10K)
    memory = atlas.memory(ten_k["id"])

    assert memory["bank_id"] == BANK
    assert memory["retained"] is True
    assert [d["section_anchor"] for d in memory["documents"]] == TEN_K_ANCHORS
    assert memory["counts"] == {
        "pending": 0,
        "completed": len(TEN_K_ANCHORS),
        "failed": 0,
        "zero_fact": 0,
        "linked": 0,
    }
    assert memory["fact_count"] == RECORDED_FACT_COUNT * len(TEN_K_ANCHORS)
    (operation,) = memory["operations"]
    assert operation["kind"] == "retain"
    assert operation["status"] == "completed"
    assert operation["error_message"] is None
    assert operation["completed_at"] is not None
    for document in memory["documents"]:
        assert document["document_id"] == f"srcv:{ten_k['id']}:{document['section_anchor']}"
        assert document["retain_state"] == "completed"
        assert document["fact_count"] == RECORDED_FACT_COUNT
        assert document["reprocess_count"] == 0
        assert document["template_version"] == TEMPLATE_VERSION
        assert document["operation_id"] == operation["id"]
        assert document["linked_to_source_version_id"] is None
    assert operation["document_ids"] == [d["document_id"] for d in memory["documents"]]

    # The sections tile the parsed text and start at their Item headings.
    parsed = atlas.parsed(ten_k["id"])
    documents = memory["documents"]
    assert documents[0]["char_start"] == 0
    assert documents[-1]["char_end"] == len(parsed)
    assert all(a["char_end"] == b["char_start"] for a, b in pairwise(documents))
    sections = by_anchor(memory)
    assert "TABLE OF CONTENTS" in parsed[: sections["cover"]["char_end"]]
    item_1 = sections["part-i-item-1"]
    assert parsed[item_1["char_start"] : item_1["char_end"]].startswith(
        "PART I\nITEM 1. BUSINESS\n"
    )
    assert item_1["section_heading"] == "ITEM 1. BUSINESS"
    item_1b = sections["part-i-item-1b"]
    assert parsed[item_1b["char_start"] :].startswith("ITEM 1B. UNRESOLVED STAFF COMMENTS\n")
    item_5 = sections["part-ii-item-5"]
    assert parsed[item_5["char_start"] :].startswith("PART II\nITEM 5. MARKET FOR REGISTRANT")


def test_one_batch_per_source_version_with_the_specified_ids_tags_metadata_and_timestamp(
    atlas: Atlas, fake: RecordedHindsight
) -> None:
    atlas.ingest("lumentum")
    lumentum = atlas.company("lumentum")

    assert len(fake.retained()) == 4
    for url, anchors in [
        (LITE_10K, TEN_K_ANCHORS),
        (LITE_10Q, TEN_Q_ANCHORS),
        (LITE_8K, EIGHT_K_ANCHORS),
    ]:
        version = atlas.version(url)
        parsed = atlas.parsed(version["id"])
        (batch,) = batch_for(fake, version["id"])
        assert [item["document_id"] for item in batch] == [
            f"srcv:{version['id']}:{anchor}" for anchor in anchors
        ]
        form = version["source_document"]["form_type"]
        sections = by_anchor(atlas.memory(version["id"]))
        for item in batch:
            anchor = str(item["document_id"]).rsplit(":", 1)[1]
            section = sections[anchor]
            assert item["tags"] == [
                f"company:{lumentum['id']}",
                "theme:photonics",
                "source:sec_edgar",
                "doctype:filing",
                f"form:{form}",
            ]
            assert item["metadata"] == {
                "source_version_id": version["id"],
                "section_anchor": anchor,
                "char_start": str(section["char_start"]),
                "char_end": str(section["char_end"]),
                "available_at": datetime.fromisoformat(version["available_at"]).isoformat(),
            }
            assert datetime.fromisoformat(str(item["timestamp"])) == datetime.fromisoformat(
                version["available_at"]
            )
            assert item["content"] == parsed[section["char_start"] : section["char_end"]]
    item_2_02 = by_anchor(atlas.memory(atlas.version(LITE_8K)["id"]))["item-2-02"]
    assert item_2_02["section_heading"] == (
        "Item 2.02. Results of Operations and Financial Condition."
    )


def test_an_exhibit_is_retained_in_bounded_chunks_and_companyfacts_not_at_all(
    atlas: Atlas, fake: RecordedHindsight
) -> None:
    atlas.ingest("lumentum")

    exhibit = atlas.version(LITE_EX991)
    parsed = atlas.parsed(exhibit["id"])
    documents = atlas.memory(exhibit["id"])["documents"]
    assert [d["section_anchor"] for d in documents] == ["chunk-001", "chunk-002", "chunk-003"]
    assert all(d["char_end"] - d["char_start"] <= 12_000 for d in documents)
    assert [(documents[0]["char_start"], documents[-1]["char_end"])] == [(0, len(parsed))]
    assert all(parsed[d["char_end"] - 1] == "\n" for d in documents)
    assert all(d["section_heading"] is None for d in documents)
    (batch,) = batch_for(fake, exhibit["id"])
    assert {str(tag) for item in batch for tag in item["tags"]} >= {"form:8-K", "doctype:filing"}

    facts = atlas.memory(atlas.version(LITE_FACTS)["id"])
    assert facts["retained"] is False
    assert facts["documents"] == []
    assert facts["operations"] == []


def test_coherent_is_ingested_and_retained_alongside_lumentum(
    atlas: Atlas, fake: RecordedHindsight
) -> None:
    lumentum_job = atlas.ingest("lumentum")
    coherent_job = atlas.ingest("coherent", company="coherent")

    assert lumentum_job["status"] == "succeeded", lumentum_job["failures"]
    assert coherent_job["status"] == "succeeded", coherent_job["failures"]
    assert coherent_job["artifacts"]["counts"] == {
        "new_version": 3,
        "unchanged": 0,
        "not_modified": 0,
    }
    coherent = atlas.company("coherent")
    ten_k = atlas.version(COHR_10K, "coherent")
    assert ten_k["source_document"]["accession"] == "0000820318-26-000020"
    assert ten_k["available_at"] == "2026-08-14T12:10:05Z"
    for url, anchors in [(COHR_10K, TEN_K_ANCHORS), (COHR_10Q, TEN_Q_ANCHORS)]:
        memory = atlas.memory(atlas.version(url, "coherent")["id"])
        assert [d["section_anchor"] for d in memory["documents"]] == anchors
        assert memory["counts"]["completed"] == len(anchors)
    assert atlas.memory(atlas.version(COHR_FACTS, "coherent")["id"])["documents"] == []
    parsed = atlas.parsed(ten_k["id"])
    item_1 = by_anchor(atlas.memory(ten_k["id"]))["part-i-item-1"]
    assert parsed[item_1["char_start"] :].startswith("PART I\nItem 1. BUSINESS\n")

    (batch,) = batch_for(fake, ten_k["id"])
    assert batch[0]["tags"] == [
        f"company:{coherent['id']}",
        "theme:photonics",
        "source:sec_edgar",
        "doctype:filing",
        "form:10-K",
    ]
    company_tags = {
        str(tag) for items in fake.retained() for item in items for tag in item["tags"]
    } & {f"company:{atlas.company('lumentum')['id']}", f"company:{coherent['id']}"}
    assert len(company_tags) == 2  # both companies are in the bank, tagged apart


# --- idempotency and revisions ---


def test_a_replayed_identical_retain_does_no_duplicate_work(
    atlas: Atlas, fake: RecordedHindsight
) -> None:
    atlas.ingest("lumentum")
    ten_k = atlas.version(LITE_10K)
    before = atlas.memory(ten_k["id"])
    calls = len(fake.calls)

    replay = atlas.enqueue(
        "jobs", "enqueue", "retain", "--key", "replayed",
        "--payload", json.dumps({"source_version_id": ten_k["id"]}),
    )  # fmt: skip
    atlas.worker_pass()
    same_key = atlas.ingest("lumentum")  # the same ingest key: the same, finished job

    job = atlas.get(f"/api/v1/jobs/{replay}")
    assert job["status"] == "succeeded", job["failures"]
    assert job["artifacts"]["outcome"] == "already_retained"
    assert same_key["attempts"] == 1
    assert len(fake.calls) == calls  # nothing sent to Hindsight
    assert atlas.memory(ten_k["id"]) == before

    again = atlas.ingest("lumentum-again")  # a new ingest finds nothing new, so retains nothing
    assert again["artifacts"]["retain_jobs"] == []
    assert len(fake.retained()) == 4


def test_a_revised_source_gets_new_documents_while_the_old_ones_stay_auditable(
    database_url: str, tmp_path: Path, hindsight: tuple[RecordedHindsight, Served]
) -> None:
    fake, served = hindsight
    atlas = Atlas(database_url, tmp_path, served.url)
    atlas.fixtures = editable_fixtures(tmp_path)
    atlas.apply_template()
    atlas.ingest("before")
    (v1,) = atlas.versions(LITE_8K)
    old = atlas.memory(v1["id"])
    change_recorded_document(
        atlas.fixtures,
        LITE_8K,
        b"fourth quarter and full fiscal year",
        b"third quarter",
        "Wed, 12 Aug 2026 09:00:00 GMT",
    )
    batches_before = len(fake.retained())

    job = atlas.ingest("after")

    assert job["status"] == "succeeded", job["failures"]
    first, second = atlas.versions(LITE_8K)
    assert first["id"] == v1["id"]
    assert second["supersedes_version_id"] == v1["id"]
    assert job["artifacts"]["retain_jobs"] and len(job["artifacts"]["retain_jobs"]) == 1
    new = atlas.memory(second["id"])
    assert [d["section_anchor"] for d in new["documents"]] == EIGHT_K_ANCHORS
    assert [d["document_id"] for d in new["documents"]] == [
        f"srcv:{second['id']}:{anchor}" for anchor in EIGHT_K_ANCHORS
    ]
    assert new["counts"]["completed"] == len(EIGHT_K_ANCHORS)
    # The old version's documents were never re-sent, and are unchanged.
    (revised_batch,) = fake.retained()[batches_before:]
    old_ids = {d["document_id"] for d in old["documents"]}
    assert not old_ids & {item["document_id"] for item in revised_batch}
    assert atlas.memory(v1["id"]) == old
    assert "third quarter" in str(revised_batch[1]["content"])

    # Memory documents can't be deleted or re-keyed.
    with pytest.raises(DBAPIError, match="never removed"), atlas.engine.begin() as connection:
        connection.execute(
            text("DELETE FROM memory_document WHERE source_version_id = :v"), {"v": v1["id"]}
        )
    with pytest.raises(DBAPIError, match="immutable"), atlas.engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE memory_document SET hindsight_document_id = 'srcv:reused'"
                " WHERE source_version_id = :v"
            ),
            {"v": v1["id"]},
        )
    atlas.engine.dispose()


def test_a_source_version_whose_raw_bytes_are_already_retained_is_linked_not_re_retained(
    database_url: str, tmp_path: Path, hindsight: tuple[RecordedHindsight, Served]
) -> None:
    fake, served = hindsight
    atlas = Atlas(database_url, tmp_path, served.url)
    atlas.fixtures = editable_fixtures(tmp_path)
    copy_url = f"{LITE}/000162828026055726/lite_ex992copy.htm"
    add_exhibit_copy(atlas.fixtures, LITE_EX991, copy_url)
    atlas.apply_template()

    job = atlas.ingest("with-copy")

    assert job["status"] == "succeeded", job["failures"]
    original, copy = atlas.version(LITE_EX991), atlas.version(copy_url)
    assert copy["raw_sha256"] == original["raw_sha256"]
    assert copy["source_document"]["id"] != original["source_document"]["id"]
    retained = atlas.memory(original["id"])
    linked = atlas.memory(copy["id"])
    assert linked["linked_to_source_version_id"] == original["id"]
    assert linked["counts"]["linked"] == len(retained["documents"]) == 3
    assert linked["operations"] == []
    for mine, theirs in zip(linked["documents"], retained["documents"], strict=True):
        assert mine["retain_state"] == "linked"
        assert mine["document_id"] is None
        assert mine["linked_to_source_version_id"] == original["id"]
        assert (mine["section_anchor"], mine["char_start"], mine["char_end"]) == (
            theirs["section_anchor"],
            theirs["char_start"],
            theirs["char_end"],
        )
    assert batch_for(fake, copy["id"]) == []
    assert len(fake.retained()) == 4  # 8-K, EX-99.1, 10-K, 10-Q; not the copy
    atlas.engine.dispose()


# --- zero facts, failures and timeouts ---


def test_a_zero_fact_section_is_reprocessed_once_then_flagged_zero_fact(
    atlas: Atlas, fake: RecordedHindsight
) -> None:
    # "Unresolved Staff Comments: None." is the section a real extraction plausibly finds
    # nothing in. No zero-fact document was recorded, so the fake derives one.
    fake.report_zero_facts(lambda document_id: document_id.endswith(":part-i-item-1b"))

    atlas.ingest("lumentum")

    ten_k = atlas.version(LITE_10K)
    memory = atlas.memory(ten_k["id"])
    sections = by_anchor(memory)
    item_1b = sections["part-i-item-1b"]
    assert item_1b["retain_state"] == "zero_fact"
    assert item_1b["fact_count"] == 0
    assert item_1b["reprocess_count"] == 1
    assert memory["counts"]["zero_fact"] == 1
    assert memory["counts"]["completed"] == len(TEN_K_ANCHORS) - 1
    assert all(
        d["reprocess_count"] == 0 for anchor, d in sections.items() if anchor != "part-i-item-1b"
    )
    retain, reprocess = memory["operations"]
    assert (retain["kind"], reprocess["kind"]) == ("retain", "reprocess")
    assert reprocess["status"] == "completed"
    assert reprocess["document_ids"] == [item_1b["document_id"]]
    assert item_1b["operation_id"] == reprocess["id"]
    # Exactly one reprocess: the original batch, then one re-retain under the same ID.
    sent = [item for batch in fake.retained() for item in batch]
    resent = [item for item in sent if item["document_id"] == item_1b["document_id"]]
    assert len(resent) == 2
    assert resent[0] == resent[1]
    assert [len(batch) for batch in batch_for(fake, ten_k["id"])] == [len(TEN_K_ANCHORS), 1]


def test_a_failed_retain_operation_stays_visible_with_its_error(
    atlas: Atlas, fake: RecordedHindsight
) -> None:
    # No failed operation was recorded; the fake derives one from the recorded final status.
    fake.hold_retains("failed", where=lambda ids: any(i.endswith(":part-i-item-1a") for i in ids))

    job = atlas.ingest("lumentum")

    assert job["status"] == "succeeded", job["failures"]
    memory = atlas.memory(atlas.version(LITE_10K)["id"])
    (operation,) = memory["operations"]
    assert operation["status"] == "failed"
    assert operation["retry_count"] == 0
    assert operation["completed_at"] is not None
    assert memory["counts"]["failed"] == len(TEN_K_ANCHORS)
    assert memory["fact_count"] == 0
    for document in memory["documents"]:
        assert document["retain_state"] == "failed"
        assert document["fact_count"] is None
        assert document["error"] == (
            "Hindsight reported the operation failed with no error message"
        )
    # Only that version's retain failed.
    assert atlas.memory(atlas.version(LITE_10Q)["id"])["counts"]["completed"] == 2


def test_an_operation_that_never_finishes_times_out_its_polls_and_stays_pending(
    database_url: str, tmp_path: Path, hindsight: tuple[RecordedHindsight, Served]
) -> None:
    fake, served = hindsight
    fake.hold_retains("processing", where=lambda ids: any(":part-i-item-1a" in i for i in ids))
    atlas = Atlas(database_url, tmp_path, served.url, retain_poll_attempts=2)
    atlas.apply_template()

    atlas.ingest("lumentum")

    memory = atlas.memory(atlas.version(LITE_10K)["id"])
    (operation,) = memory["operations"]
    assert operation["status"] == "processing"
    assert operation["completed_at"] is None
    assert operation["last_polled_at"] is not None
    assert memory["counts"]["pending"] == len(TEN_K_ANCHORS)
    with atlas.engine.connect() as connection:
        poll = connection.execute(
            text(
                "SELECT id FROM job WHERE kind = 'poll_operation' AND payload->>'operation_id' = :o"
            ),
            {"o": operation["id"]},
        ).scalar_one()
    job = atlas.get(f"/api/v1/jobs/{poll}")
    assert job["status"] == "failed"
    assert job["attempts"] == 2
    assert all("still 'processing' after" in failure["error"] for failure in job["failures"])
    atlas.engine.dispose()


# --- preconditions and the API ---


def test_nothing_is_retained_before_a_bank_template_is_applied(
    database_url: str, tmp_path: Path, hindsight: tuple[RecordedHindsight, Served]
) -> None:
    fake, served = hindsight
    atlas = Atlas(database_url, tmp_path, served.url)

    atlas.ingest("lumentum")

    with atlas.engine.connect() as connection:
        errors = connection.execute(
            text("SELECT last_error FROM job WHERE kind = 'retain' AND status = 'failed'")
        ).scalars()
        messages = list(errors)
    assert len(messages) == 4
    assert all("atlas hindsight apply-template" in str(message) for message in messages)
    assert fake.retained() == []
    assert atlas.memory(atlas.version(LITE_10K)["id"])["documents"] == []
    atlas.engine.dispose()


def test_the_memory_route_is_404_for_an_unknown_source_version(atlas: Atlas) -> None:
    response = atlas.api.get("/api/v1/source-versions/00000000-0000-4000-8000-000000000000/memory")

    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "not_found", "message": "source version not found"}
    }


# --- fixture editing ---


def editable_fixtures(tmp_path: Path) -> Path:
    root = tmp_path / "edgar"
    shutil.copytree(EDGAR_FIXTURES, root)
    return root


def _manifest(root: Path) -> tuple[Path, dict[str, Any]]:
    path = root / "lumentum" / "manifest.json"
    return path, json.loads(path.read_text())


def change_recorded_document(
    root: Path, url: str, old: bytes, new: bytes, last_modified: str
) -> None:
    """Serve changed bytes for a recorded document, with a new Last-Modified, as SEC would."""
    path, manifest = _manifest(root)
    entry = next(entry for entry in manifest["responses"] if entry["url"] == url)
    entry["headers"]["last-modified"] = last_modified
    path.write_text(json.dumps(manifest, indent=2))
    body = root / "lumentum" / entry["file"]
    original = body.read_bytes()
    assert original.count(old) == 1
    body.write_bytes(original.replace(old, new))


def add_exhibit_copy(root: Path, exhibit_url: str, copy_url: str) -> None:
    """List a second EX-99 exhibit in the 8-K, served with exactly the first one's bytes."""
    path, manifest = _manifest(root)
    exhibit = next(entry for entry in manifest["responses"] if entry["url"] == exhibit_url)
    manifest["responses"].append({**exhibit, "url": copy_url})
    path.write_text(json.dumps(manifest, indent=2))
    headers = next(
        entry for entry in manifest["responses"] if entry["url"].endswith("-index-headers.html")
    )
    index = root / "lumentum" / headers["file"]
    listing = index.read_bytes()
    schema_entry = b"&lt;TYPE&gt;EX-101.SCH\n&lt;SEQUENCE&gt;3\n&lt;FILENAME&gt;lite-20260811.xsd"
    assert listing.count(schema_entry) == 1
    copy_name = copy_url.rsplit("/", 1)[1].encode()
    index.write_bytes(
        listing.replace(
            schema_entry, b"&lt;TYPE&gt;EX-99.2\n&lt;SEQUENCE&gt;3\n&lt;FILENAME&gt;" + copy_name
        )
    )
