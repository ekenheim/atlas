"""Memory health (memory-quality ticket 02): one read of what the bank holds and what it lost.

Seam: the `atlas` CLI enqueues the ingests, single worker passes run them and their retains,
and `GET /api/v1/memory/health` is read. Hindsight is the recorded fake with `derive_retains`
on; failed, stuck, zero-fact and partial retains are its documented derivations
(`hold_retains`, `report_zero_facts`, `report_extraction_errors`), and the observation scopes
and entity listings are its hand-written ones (`script_observation_scopes`,
`script_entities`, `fail_listings`: no recording of either exists yet; see
`tests/fakes/hindsight.py`).

Sections per document come from the recorded EDGAR fixtures: Lumentum's 10-K (11 Items), 8-K
(3), 10-Q (2) and the 8-K's exhibit 99.1 (3 chunks); Coherent's 10-K (11) and 10-Q (2).
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

import pytest

from tests.fakes.hindsight import RecordedHindsight
from tests.fakes.serve import Served
from tests.harness import BANK, TEN_K_ANCHORS, Atlas

RECORDED_FACT_COUNT = cast(
    int,
    RecordedHindsight().recording("upsert/09-get-document").response_object()["memory_unit_count"],
)
TEN_K = len(TEN_K_ANCHORS)

# Two texts of one error that differ only in the operation's ID, and a second error.
CRASHED = "Retain failed in operation {}: extraction worker crashed"
CRASHED_10K = CRASHED.format("0b6f6a1e-3c1d-4f7e-9a0b-1c2d3e4f5a6b")
CRASHED_8K = CRASHED.format("9d8c7b6a-5f4e-4d3c-8b2a-1f0e9d8c7b6a")
CRASHED_GROUP = "Retain failed in operation <uuid>: extraction worker crashed"
TOO_LONG = "Error code: 400 - maximum context length is 196608 tokens; requested 250311"
TOO_LONG_GROUP = "Error code: 400 - maximum context length is <n> tokens; requested <n>"


def anchors(ids: Sequence[str]) -> list[str]:
    return sorted(document_id.rsplit(":", 1)[1] for document_id in ids)


def is_10k(ids: Sequence[str]) -> bool:
    return "part-i-item-1a" in anchors(ids)


def is_8k(ids: Sequence[str]) -> bool:
    return "item-2-02" in anchors(ids)


def is_10q(ids: Sequence[str]) -> bool:
    return anchors(ids) == ["cover", "part-i-item-1"]


@pytest.fixture
def atlas(database_url: str, tmp_path: Path, hindsight: tuple[RecordedHindsight, Served]):
    # One poll attempt, so a retain held `processing` leaves its sections pending at once.
    harness = Atlas(database_url, tmp_path, hindsight[1].url, retain_poll_attempts=1)
    harness.apply_template()
    yield harness
    harness.engine.dispose()


@pytest.fixture
def ingested(atlas: Atlas, fake: RecordedHindsight) -> Atlas:
    """Lumentum: 10-K and 8-K failed (one error, two IDs), 10-Q completed with extraction
    errors (partial), exhibit chunk-003 zero-fact. Coherent: 10-K failed (another error), 10-Q
    still processing (pending)."""
    fake.hold_retains("failed", where=is_10k, error_message=CRASHED_10K, times=1)
    fake.hold_retains("failed", where=is_8k, error_message=CRASHED_8K, times=1)
    fake.report_extraction_errors(2, where=is_10q)
    fake.report_zero_facts(lambda document_id: document_id.endswith(":chunk-003"))
    atlas.ingest("lumentum")
    fake.hold_retains("failed", where=is_10k, error_message=TOO_LONG, times=1)
    fake.hold_retains("processing", where=is_10q)
    atlas.ingest("coherent", company="coherent")
    return atlas


def by_slug(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {row["slug"]: row for row in rows}


def counts(
    *,
    total: int,
    completed: int = 0,
    failed: int = 0,
    zero_fact: int = 0,
    pending: int = 0,
    partial: int = 0,
) -> dict[str, int]:
    return {
        "total": total,
        "pending": pending,
        "completed": completed,
        "failed": failed,
        "cancelled": 0,
        "zero_fact": zero_fact,
        "linked": 0,
        "partial": partial,
        "fact_count": completed * RECORDED_FACT_COUNT,
    }


LUMENTUM = counts(total=TEN_K + 3 + 2 + 3, completed=4, failed=TEN_K + 3, zero_fact=1, partial=2)
COHERENT = counts(total=TEN_K + 2, failed=TEN_K, pending=2)


def script_listings(atlas: Atlas, fake: RecordedHindsight) -> tuple[str, str]:
    lumentum, coherent = atlas.company("lumentum")["id"], atlas.company("coherent")["id"]
    fake.script_observation_scopes(
        [
            (
                [
                    f"company:{lumentum}",
                    "doctype:filing",
                    "form:10-K",
                    "source:sec_edgar",
                    "theme:photonics",
                ],
                7,
            ),
            ([f"company:{coherent}", "doctype:filing", "form:10-Q", "theme:photonics"], 2),
            (["theme:photonics"], 1),
        ]
    )
    fake.script_entities(
        [
            ("Lumentum", 40),
            ("Coherent Corp.", 30),
            ("Lumentum Holdings Inc.", 5),
            ("Jordan Klein", 3),
            ("LITE", 2),
        ]
    )
    return lumentum, coherent


def test_the_health_read_counts_sections_per_company_and_groups_failures_by_error(
    ingested: Atlas, fake: RecordedHindsight
) -> None:
    lumentum, coherent = script_listings(ingested, fake)

    health = ingested.get("/api/v1/memory/health")

    assert health["bank_id"] == BANK
    assert health["company_id"] is None
    companies = by_slug(health["companies"])
    assert companies["lumentum"]["sections"] == LUMENTUM
    assert companies["lumentum"]["company_id"] == lumentum
    assert companies["coherent"]["sections"] == COHERENT
    # A universe company with nothing retained is listed with nothing.
    assert companies["axt"]["sections"] == counts(total=0)
    assert health["sections"] == {key: LUMENTUM[key] + COHERENT[key] for key in LUMENTUM}

    crashed, too_long = health["failed_groups"]
    assert crashed["error"] == CRASHED_GROUP
    assert crashed["count"] == TEN_K + 3
    assert crashed["companies"] == {"lumentum": TEN_K + 3}
    assert crashed["example"] in (CRASHED_10K, CRASHED_8K)
    assert crashed["example_document_id"].startswith("srcv:")
    assert crashed["first_at"] <= crashed["last_at"]
    assert too_long["error"] == TOO_LONG_GROUP
    assert too_long["count"] == TEN_K
    assert too_long["companies"] == {"coherent": TEN_K}
    assert too_long["example"] == TOO_LONG

    pending = {bucket["age"]: bucket["count"] for bucket in health["pending_by_age"]}
    assert pending == {"under_1h": 2, "1h_to_24h": 0, "1d_to_7d": 0, "over_7d": 0}

    scopes = health["observation_scopes"]
    assert scopes["status"] == "ok"
    assert scopes["reason"] is None
    assert scopes["total"] == 3
    assert [(s["tags"][0], s["count"]) for s in scopes["scopes"]] == [
        (f"company:{lumentum}", 7),
        (f"company:{coherent}", 2),
        ("theme:photonics", 1),
    ]

    entities = health["entities"]
    assert entities["status"] == "ok"
    assert (entities["total"], entities["scanned"], entities["complete"]) == (5, 5, True)
    named = by_slug(entities["companies"])
    assert [e["canonical_name"] for e in named["lumentum"]["entities"]] == [
        "Lumentum",
        "Lumentum Holdings Inc.",
        "LITE",
    ]
    assert named["lumentum"]["one_entity"] is False
    assert [e["canonical_name"] for e in named["coherent"]["entities"]] == ["Coherent Corp."]
    assert named["coherent"]["entities"][0]["mention_count"] == 30
    assert named["coherent"]["one_entity"] is True
    assert named["axt"]["entities"] == []
    assert named["axt"]["one_entity"] is False


def test_a_cancelled_operation_s_sections_are_cancelled_not_failed_in_the_health_read(
    atlas: Atlas, fake: RecordedHindsight
) -> None:
    # The owner cancels the 10-K's retain operation (ticket 03): its sections are `cancelled`,
    # a state of their own, and their group says so; the 8-K's failure stays a failure.
    fake.hold_retains("cancelled", where=is_10k, times=1)
    fake.hold_retains("failed", where=is_8k, error_message=CRASHED_8K, times=1)
    atlas.ingest("lumentum")
    fake.script_observation_scopes([])
    fake.script_entities([])

    health = atlas.get("/api/v1/memory/health")

    assert health["sections"]["cancelled"] == TEN_K
    assert health["sections"]["failed"] == 3
    groups = {(g["state"], g["error_class"]): g for g in health["failed_groups"]}
    assert set(groups) == {("cancelled", "cancelled"), ("failed", "permanent")}
    assert groups[("cancelled", "cancelled")]["count"] == TEN_K
    assert groups[("failed", "permanent")]["error"] == CRASHED_GROUP


def test_the_health_read_of_one_company_narrows_every_part_to_it(
    ingested: Atlas, fake: RecordedHindsight
) -> None:
    lumentum, _ = script_listings(ingested, fake)

    health = ingested.get("/api/v1/memory/health", company_id=lumentum)

    assert health["company_id"] == lumentum
    assert health["sections"] == LUMENTUM
    assert [c["slug"] for c in health["companies"]] == ["lumentum"]
    assert [g["error"] for g in health["failed_groups"]] == [CRASHED_GROUP]
    assert [b["count"] for b in health["pending_by_age"]] == [0, 0, 0, 0]
    assert [s["count"] for s in health["observation_scopes"]["scopes"]] == [7]
    assert health["observation_scopes"]["total"] == 3  # the bank's
    assert [c["slug"] for c in health["entities"]["companies"]] == ["lumentum"]


def test_a_failing_hindsight_listing_leaves_its_part_unavailable_and_the_rest_answers(
    ingested: Atlas, fake: RecordedHindsight
) -> None:
    fake.fail_listings(503)

    response = ingested.api.get("/api/v1/memory/health")

    assert response.status_code == 200, response.text
    health = response.json()
    for part in ("observation_scopes", "entities"):
        assert health[part]["status"] == "unavailable"
        assert "503" in health[part]["reason"]
    assert health["observation_scopes"]["scopes"] == []
    assert health["entities"]["companies"] == []
    assert by_slug(health["companies"])["lumentum"]["sections"] == LUMENTUM
    assert len(health["failed_groups"]) == 2


def test_without_hindsight_the_listings_are_unavailable(database_url: str, tmp_path: Path) -> None:
    atlas = Atlas(database_url, tmp_path, "")  # no ATLAS_HINDSIGHT_URL
    try:
        health = atlas.get("/api/v1/memory/health")
    finally:
        atlas.engine.dispose()

    assert health["sections"] == counts(total=0)
    assert health["observation_scopes"]["status"] == "unavailable"
    assert "not configured" in health["observation_scopes"]["reason"]
    assert health["entities"]["status"] == "unavailable"


def test_the_health_read_of_an_unknown_company_is_404(ingested: Atlas) -> None:
    response = ingested.api.get(
        "/api/v1/memory/health", params={"company_id": "00000000-0000-0000-0000-000000000000"}
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
