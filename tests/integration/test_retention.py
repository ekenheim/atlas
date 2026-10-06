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
import shutil
from datetime import datetime
from itertools import pairwise
from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from atlas.audit import Actor
from atlas.retention import retry_failed
from tests.fakes.hindsight import RecordedHindsight
from tests.fakes.serve import Served
from tests.harness import (
    BANK,
    EDGAR_FIXTURES,
    LITE_10K,
    TEMPLATE,
    TEN_K_ANCHORS,
    Atlas,
    scrape_metrics,
)

TEMPLATE_VERSION = json.loads(TEMPLATE.read_text())["template_version"]
# What the recorded document (`upsert/09-get-document`) reports: one memory unit.
RECORDED_FACT_COUNT = cast(
    int,
    RecordedHindsight().recording("upsert/09-get-document").response_object()["memory_unit_count"],
)

LITE = "https://www.sec.gov/Archives/edgar/data/1633978"
LITE_8K = f"{LITE}/000162828026055726/lite-20260811.htm"
LITE_EX991 = f"{LITE}/000162828026055726/lite_ex991xq4fy26.htm"
LITE_10Q = f"{LITE}/000162828026030777/lite-20260328.htm"
LITE_FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK0001633978.json"
COHR = "https://www.sec.gov/Archives/edgar/data/820318"
COHR_10K = f"{COHR}/000082031826000020/iivi-20260630.htm"
COHR_10Q = f"{COHR}/000082031826000013/iivi-20260331.htm"
COHR_FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK0000820318.json"
# The Item 5 heading of Coherent's FY2026 10-K, as the filing writes it.
COHR_ITEM_5_HEADING = (
    "Item 5. MARKET FOR REGISTRANT\N{RIGHT SINGLE QUOTATION MARK}S COMMON EQUITY,"
    " RELATED STOCKHOLDER MATTERS AND ISSUER PURCHASES OF EQUITY SECURITIES"
)

# The Item headings of the fixtures' 10-Qs (trimmed early in Part I Item 1), and the Lumentum
# 8-K's Items 2.02 and 9.01 (the 10-Ks' are `TEN_K_ANCHORS`).
TEN_Q_ANCHORS = ["cover", "part-i-item-1"]
EIGHT_K_ANCHORS = ["cover", "item-2-02", "item-9-01"]
# A retain item's fields and its metadata keys, in order: the provenance keys Atlas has always
# sent, then the display keys (memory-quality ticket 04); since ticket 06 with its observation
# scopes (one per theme).
RETAIN_ITEM_FIELDS = [
    "content",
    "document_id",
    "timestamp",
    "context",
    "metadata",
    "tags",
    "entities",
    "resolve_entities",
    "observation_scopes",
]
PROVENANCE_METADATA_KEYS = [
    "source_version_id",
    "section_anchor",
    "char_start",
    "char_end",
    "available_at",
]
RETAIN_METADATA_KEYS = [*PROVENANCE_METADATA_KEYS, "company_name", "form", "period"]
# Each Lumentum filing's report date (the fixtures' submissions index, `reportDate`).
LITE_PERIODS = {"10-K": "2026-06-27", "10-Q": "2026-03-28", "8-K": "2026-08-11"}
LITE_ENTITY = {"text": "Lumentum Holdings Inc.", "type": "ORG"}
# The profile of what a retain item says (atlas.retention.context.RETAIN_PROFILE).
RETAIN_PROFILE = "retain-v2"


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


def retain_bodies(fake: RecordedHindsight) -> list[bytes]:
    """The raw body of every batch retain request Hindsight received."""
    return [
        request.content
        for request in fake.calls
        if request.method == "POST" and request.url.path.endswith("/memories")
    ]


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
        "cancelled": 0,
        "retired": 0,
    }
    assert memory["partial"] == 0
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
        # The memories Hindsight returned for the section, listed after the operation.
        assert document["memory_ids"] == [fake.derived_fact(document["document_id"])]
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
            assert item["observation_scopes"] == [["theme:photonics"]]
            assert item["metadata"] == {
                "source_version_id": version["id"],
                "section_anchor": anchor,
                "char_start": str(section["char_start"]),
                "char_end": str(section["char_end"]),
                "available_at": datetime.fromisoformat(version["available_at"]).isoformat(),
                "company_name": "Lumentum",
                "form": form,
                "period": LITE_PERIODS[form],
            }
            assert datetime.fromisoformat(str(item["timestamp"])) == datetime.fromisoformat(
                version["available_at"]
            )
            assert item["content"] == parsed[section["char_start"] : section["char_end"]]
            # Nothing else is sent: the fields and metadata keys, in their order, and no
            # extractor asked for (ATLAS_RETAIN_EXTRACTOR is unset).
            assert list(item) == RETAIN_ITEM_FIELDS
            assert list(item["metadata"]) == RETAIN_METADATA_KEYS
            assert item["entities"][0] == LITE_ENTITY
            assert item["resolve_entities"] is False
            assert section["extractor"] is None
            # What the item said is recorded on its section.
            assert section["retain_profile"] == RETAIN_PROFILE
            assert section["retain_context"] == item["context"]
            assert section["retain_entities"] == [e["text"] for e in item["entities"]]
        (operation,) = atlas.memory(version["id"])["operations"]
        assert operation["extractor"] is None
    assert len(retain_bodies(fake)) == 4
    assert all(b'"extractor"' not in body for body in retain_bodies(fake))
    item_2_02 = by_anchor(atlas.memory(atlas.version(LITE_8K)["id"]))["item-2-02"]
    assert item_2_02["section_heading"] == (
        "Item 2.02. Results of Operations and Financial Condition."
    )


def test_with_the_retain_extractor_set_every_item_asks_for_it_and_its_section_records_it(
    database_url: str, tmp_path: Path, hindsight: tuple[RecordedHindsight, Served]
) -> None:
    fake, served = hindsight
    # One section comes back with no facts, so a reprocess batch is sent too.
    fake.report_zero_facts(lambda document_id: document_id.endswith(":part-i-item-1b"))
    atlas = Atlas(database_url, tmp_path, served.url, retain_extractor="minimax")
    atlas.apply_template()

    job = atlas.ingest("lumentum")

    assert job["status"] == "succeeded", job["failures"]
    batches = fake.retained()
    assert len(batches) == 5  # the four versions, and the 10-K's reprocess
    for item in [item for batch in batches for item in batch]:
        # Hindsight's metadata routing reads this key; the provenance keys are as before.
        assert list(item) == RETAIN_ITEM_FIELDS
        assert list(item["metadata"])[-1] == "extractor"
        assert list(item["metadata"])[:5] == PROVENANCE_METADATA_KEYS
        assert item["metadata"]["extractor"] == "minimax"
    ten_k = atlas.version(LITE_10K)
    parsed = atlas.parsed(ten_k["id"])
    memory = atlas.memory(ten_k["id"])
    item_1 = by_anchor(memory)["part-i-item-1"]
    (sent,) = [i for b in batches for i in b if i["document_id"] == item_1["document_id"]]
    assert sent["metadata"] == {
        "source_version_id": ten_k["id"],
        "section_anchor": "part-i-item-1",
        "char_start": str(item_1["char_start"]),
        "char_end": str(item_1["char_end"]),
        "available_at": datetime.fromisoformat(ten_k["available_at"]).isoformat(),
        "company_name": "Lumentum",
        "form": "10-K",
        "period": "2026-06-27",
        "extractor": "minimax",
    }
    assert sent["content"] == parsed[item_1["char_start"] : item_1["char_end"]]
    # What Atlas asked for is recorded on each section and on each operation, since
    # Hindsight stores nothing about the route.
    assert memory["counts"]["completed"] == len(TEN_K_ANCHORS) - 1
    assert {d["extractor"] for d in memory["documents"]} == {"minimax"}
    retain, reprocess = memory["operations"]
    assert (retain["kind"], retain["extractor"]) == ("retain", "minimax")
    assert (reprocess["kind"], reprocess["extractor"]) == ("reprocess", "minimax")
    for url in (LITE_10Q, LITE_8K, LITE_EX991):
        assert {d["extractor"] for d in atlas.memory(atlas.version(url)["id"])["documents"]} == {
            "minimax"
        }
    atlas.engine.dispose()


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


def test_a_section_naming_another_universe_company_says_whose_it_is_and_names_both(
    atlas: Atlas, fake: RecordedHindsight
) -> None:
    # Coherent's FY2026 10-K names "Lumentum Holdings, Inc." in its Item 5 peer group.
    atlas.ingest("lumentum")
    job = atlas.ingest("coherent", company="coherent")

    assert job["status"] == "succeeded", job["failures"]
    ten_k = atlas.version(COHR_10K, "coherent")
    (batch,) = batch_for(fake, ten_k["id"])
    sent = {str(item["document_id"]).rsplit(":", 1)[1]: item for item in batch}
    item_5 = sent["part-ii-item-5"]
    assert "Lumentum Holdings, Inc." in item_5["content"]
    # The filer, then the company the text names, each as written in the universe and
    # taken as written by Hindsight.
    assert item_5["entities"] == [
        {"text": "Coherent Corp.", "type": "ORG"},
        LITE_ENTITY,
    ]
    assert item_5["resolve_entities"] is False
    assert item_5["metadata"] == {
        "source_version_id": ten_k["id"],
        "section_anchor": "part-ii-item-5",
        "char_start": item_5["metadata"]["char_start"],
        "char_end": item_5["metadata"]["char_end"],
        "available_at": "2026-08-14T12:10:05+00:00",
        "company_name": "Coherent",
        "form": "10-K",
        "period": "2026-06-30",
    }
    assert item_5["context"] == (
        "This is Coherent's annual report on Form 10-K for the period ended 2026-06-30."
        " It was made public on 2026-08-14."
        f' This section is headed "{COHR_ITEM_5_HEADING}".'
        " Coherent is speaking: this is its own document."
    )
    # A section that names no other company carries the filer alone.
    assert sent["part-i-item-1b"]["entities"] == [{"text": "Coherent Corp.", "type": "ORG"}]

    memory = atlas.memory(ten_k["id"])
    assert memory["current_retain_profile"] == RETAIN_PROFILE
    section = by_anchor(memory)["part-ii-item-5"]
    assert section["retain_profile"] == RETAIN_PROFILE
    assert section["retain_context"] == item_5["context"]
    assert section["retain_entities"] == ["Coherent Corp.", "Lumentum Holdings Inc."]


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
        assert mine["memory_ids"] is None  # the twin's sections hold the memories
        assert mine["extractor"] is None  # nothing was sent for the copy
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
    assert item_1b["memory_ids"] == []
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
        assert document["error_class"] == "permanent"
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


def test_retry_failed_resubmits_failed_sections_of_versions_in_the_window(
    atlas: Atlas, fake: RecordedHindsight
) -> None:
    # The first 10-K batch fails (derived: no failed operation was recorded); a resubmitted
    # batch is served as recorded.
    fake.hold_retains(
        "failed", where=lambda ids: any(i.endswith(":part-i-item-1a") for i in ids), times=1
    )
    atlas.ingest("lumentum")
    version_id = atlas.version(LITE_10K)["id"]
    assert atlas.memory(version_id)["counts"]["failed"] == len(TEN_K_ANCHORS)

    retried = atlas.cli("retention", "retry-failed", "--since", "2026-01-01")
    assert retried.returncode == 0, retried.stderr
    summary = json.loads(retried.stdout)
    while atlas.worker_pass():
        pass

    assert summary["sections"] == len(TEN_K_ANCHORS)
    assert summary["source_versions"] == 1
    memory = atlas.memory(version_id)
    assert memory["counts"]["failed"] == 0
    assert memory["counts"]["completed"] + memory["counts"]["zero_fact"] == len(TEN_K_ANCHORS)
    assert len(memory["operations"]) == 2  # the failed one stays visible


def test_retry_failed_leaves_versions_before_the_window_alone(
    atlas: Atlas, fake: RecordedHindsight
) -> None:
    fake.hold_retains(
        "failed", where=lambda ids: any(i.endswith(":part-i-item-1a") for i in ids), times=1
    )
    atlas.ingest("lumentum")

    retried = atlas.cli("retention", "retry-failed", "--since", "2026-09-01")  # after the 10-K

    assert retried.returncode == 0, retried.stderr
    assert json.loads(retried.stdout)["sections"] == 0
    assert atlas.memory(atlas.version(LITE_10K)["id"])["counts"]["failed"] == len(TEN_K_ANCHORS)


def test_retry_failed_applies_the_8k_selection_to_what_it_resubmits(
    atlas: Atlas, fake: RecordedHindsight
) -> None:
    # Ingested with selection off, so the 8-K cover and its EX-99.1 were both retained; every
    # batch fails (derived), as the cancelled cluster backlog did.
    fake.hold_retains("failed", where=lambda ids: True, times=10)
    atlas.ingest("lumentum")
    cover, exhibit = atlas.version(LITE_8K)["id"], atlas.version(LITE_EX991)["id"]
    assert atlas.memory(cover)["counts"]["failed"] > 0

    summary = retry_failed(
        atlas.engine,
        Actor("local-researcher"),
        since=None,
        eight_k_items=("1.01", "1.02", "2.01", "2.02", "2.05", "7.01", "8.01"),
        exhibits_only_items=("2.02", "7.01", "8.01", "9.01"),
    )

    # The 8-K is items 2.02,9.01: a press release, so its cover isn't worth the tokens.
    assert atlas.memory(cover)["counts"]["failed"] > 0  # left failed: not resubmitted
    assert atlas.memory(cover)["counts"]["pending"] == 0
    assert atlas.memory(exhibit)["counts"]["failed"] == 0
    assert atlas.memory(exhibit)["counts"]["pending"] > 0
    assert summary["skipped_by_selection"] > 0


# --- a section's outcome comes from its own document (memory-quality ticket 03) ---

CANCELLED_ERROR = "Hindsight reported the operation cancelled with no error message"
PERMANENT_ERROR = "ValueError: document exceeds the extraction schema's maximum length"


def is_10k_batch(document_ids: Any) -> bool:
    return any(str(i).endswith(":part-i-item-1a") for i in document_ids)


def is_8k_batch(document_ids: Any) -> bool:
    return any(str(i).endswith(":item-2-02") for i in document_ids)


def is_10q_batch(document_ids: Any) -> bool:
    ids = [str(i) for i in document_ids]
    return any(i.endswith(":part-i-item-1") for i in ids) and not is_10k_batch(ids)


def metric(atlas: Atlas, name: str, **labels: str) -> float:
    return scrape_metrics(atlas.api).get((name, frozenset(labels.items())), 0)


def test_a_cancelled_operation_leaves_its_sections_cancelled_not_failed_and_retry_enqueues_them(
    atlas: Atlas, fake: RecordedHindsight
) -> None:
    # The owner cancels the 10-K's retain operation before Hindsight stored anything (derived:
    # no cancelled operation was recorded); a resubmitted batch is served as recorded.
    fake.hold_retains("cancelled", where=is_10k_batch, times=1)

    job = atlas.ingest("lumentum")

    assert job["status"] == "succeeded", job["failures"]
    version_id = atlas.version(LITE_10K)["id"]
    memory = atlas.memory(version_id)
    assert memory["counts"]["cancelled"] == len(TEN_K_ANCHORS)
    assert memory["counts"]["failed"] == 0
    (operation,) = memory["operations"]
    assert (operation["status"], operation["error_class"]) == ("cancelled", "cancelled")
    for document in memory["documents"]:
        assert document["retain_state"] == "cancelled"
        assert document["error_class"] == "cancelled"
        assert document["error"] == CANCELLED_ERROR
        assert document["fact_count"] is None
    # The metric shows them apart from failed sections.
    sections = len(TEN_K_ANCHORS)
    assert metric(atlas, "atlas_retained_sections_total", outcome="cancelled") == sections
    assert metric(atlas, "atlas_retained_sections_total", outcome="failed") == 0
    assert (
        metric(atlas, "atlas_sections_not_in_memory", state="cancelled", error_class="cancelled")
        == sections
    )

    retried = atlas.cli("retention", "retry-failed", "--all-history")
    assert retried.returncode == 0, retried.stderr
    summary = json.loads(retried.stdout)
    assert summary["sections"] == sections
    assert summary["by_error_class"] == {"cancelled": sections}
    assert summary["job_class"] == "backfill"
    (retain_job,) = summary["retain_jobs"]
    assert atlas.get(f"/api/v1/jobs/{retain_job}")["job_class"] == "backfill"
    while atlas.worker_pass():
        pass

    memory = atlas.memory(version_id)
    assert memory["counts"]["cancelled"] == 0
    assert memory["counts"]["completed"] == sections
    assert all(d["error_class"] is None for d in memory["documents"])
    assert [o["status"] for o in memory["operations"]] == ["cancelled", "completed"]


def test_a_failed_operation_s_sections_each_take_the_outcome_of_their_own_document(
    atlas: Atlas, fake: RecordedHindsight
) -> None:
    # The 8-K's three sections go to Hindsight as one operation, which fails (derived): it had
    # stored the cover with facts and Item 2.02 with none, and never stored Item 9.01.
    fake.hold_retains(
        "failed",
        where=is_8k_batch,
        error_message=PERMANENT_ERROR,
        times=1,
        stored=lambda document_id: not document_id.endswith(":item-9-01"),
    )
    fake.report_zero_facts(lambda document_id: document_id.endswith(":item-2-02"))

    job = atlas.ingest("lumentum")

    assert job["status"] == "succeeded", job["failures"]
    memory = atlas.memory(atlas.version(LITE_8K)["id"])
    sections = by_anchor(memory)
    assert list(sections) == EIGHT_K_ANCHORS
    cover, item_2_02, item_9_01 = (sections[anchor] for anchor in EIGHT_K_ANCHORS)
    assert (cover["retain_state"], cover["fact_count"]) == ("completed", RECORDED_FACT_COUNT)
    assert cover["memory_ids"] == [fake.derived_fact(cover["document_id"])]
    assert (cover["error"], cover["error_class"]) == (None, None)
    # Stored with no fact: its one reprocess, then zero-fact.
    assert (item_2_02["retain_state"], item_2_02["reprocess_count"]) == ("zero_fact", 1)
    # Absent: failed with the operation's error.
    assert item_9_01["retain_state"] == "failed"
    assert (item_9_01["error"], item_9_01["error_class"]) == (PERMANENT_ERROR, "permanent")
    retain, reprocess = memory["operations"]
    assert (retain["status"], retain["error_class"]) == ("failed", "permanent")
    assert (reprocess["status"], reprocess["document_ids"]) == (
        "completed",
        [item_2_02["document_id"]],
    )


def test_a_completed_operation_with_extraction_errors_retries_its_sections_once(
    atlas: Atlas, fake: RecordedHindsight
) -> None:
    # Derived: Hindsight reports extraction errors on every 10-Q operation (so its sections
    # are partial after their retry), and on the 10-K's first operation only.
    fake.report_extraction_errors(2, where=is_10q_batch)
    fake.report_extraction_errors(1, where=is_10k_batch, times=1)

    atlas.ingest("lumentum")

    ten_q = atlas.memory(atlas.version(LITE_10Q)["id"])
    assert ten_q["counts"]["completed"] == len(TEN_Q_ANCHORS)
    assert ten_q["partial"] == len(TEN_Q_ANCHORS)
    for document in ten_q["documents"]:
        assert (document["reprocess_count"], document["extraction_errors"]) == (1, 2)
        assert document["partial"] is True
        assert document["fact_count"] == RECORDED_FACT_COUNT
    assert [o["kind"] for o in ten_q["operations"]] == ["retain", "reprocess"]

    ten_k = atlas.memory(atlas.version(LITE_10K)["id"])
    assert ten_k["counts"]["completed"] == len(TEN_K_ANCHORS)
    assert ten_k["partial"] == 0
    for document in ten_k["documents"]:
        assert (document["reprocess_count"], document["extraction_errors"]) == (1, 0)
        assert document["partial"] is False
    retain, reprocess = ten_k["operations"]
    assert (retain["kind"], reprocess["kind"]) == ("retain", "reprocess")
    assert reprocess["document_ids"] == retain["document_ids"]
    assert metric(atlas, "atlas_partial_sections") == len(TEN_Q_ANCHORS)


def test_retry_failed_by_error_class_and_company_resubmits_only_those_as_backfill(
    atlas: Atlas, fake: RecordedHindsight
) -> None:
    # Lumentum: the 10-K's operation is cancelled, the 8-K's fails for good. Coherent: every
    # operation is cancelled.
    fake.hold_retains("cancelled", where=is_10k_batch, times=1)
    fake.hold_retains("failed", where=is_8k_batch, error_message=PERMANENT_ERROR, times=1)
    atlas.ingest("lumentum")
    coherent = {"on": True}
    fake.hold_retains("cancelled", where=lambda _: coherent["on"])
    atlas.ingest("coherent", "coherent")
    coherent["on"] = False
    lite_10k, lite_8k = atlas.version(LITE_10K)["id"], atlas.version(LITE_8K)["id"]
    cohr_10k = atlas.version(COHR_10K, "coherent")["id"]
    assert atlas.memory(cohr_10k)["counts"]["cancelled"] > 0
    assert atlas.memory(lite_8k)["counts"]["failed"] == len(EIGHT_K_ANCHORS)

    retried = atlas.cli(
        "retention",
        "retry-failed",
        "--all-history",
        "--error-class",
        "cancelled",
        "--company",
        "lumentum",
    )

    assert retried.returncode == 0, retried.stderr
    summary = json.loads(retried.stdout)
    assert summary["sections"] == len(TEN_K_ANCHORS)
    assert summary["by_error_class"] == {"cancelled": len(TEN_K_ANCHORS)}
    assert summary["source_versions"] == 1
    (retain_job,) = summary["retain_jobs"]
    assert atlas.get(f"/api/v1/jobs/{retain_job}")["job_class"] == "backfill"
    assert atlas.memory(lite_10k)["counts"]["pending"] == len(TEN_K_ANCHORS)
    # The other class and the other company are left as they were.
    assert atlas.memory(lite_8k)["counts"]["failed"] == len(EIGHT_K_ANCHORS)
    assert atlas.memory(cohr_10k)["counts"]["pending"] == 0
    assert atlas.memory(cohr_10k)["counts"]["cancelled"] > 0

    unknown = atlas.cli("retention", "retry-failed", "--company", "no-such-company")
    assert unknown.returncode == 2
    assert "no company 'no-such-company'" in unknown.stderr
