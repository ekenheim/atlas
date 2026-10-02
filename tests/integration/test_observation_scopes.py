"""Observation scopes (memory-quality ticket 06): one scope per theme, no company scope.

Seam: the `atlas` CLI enqueues ingests, single worker passes run them and their retains,
and everything is observed through the requests Hindsight received and `/api/v1` (recall,
the memory-health read). Hindsight is the recorded fake with `derive_memories` on; an
observation consolidated in an explicit scope is its documented derivation
(`derive_observation(..., scope=...)`: the scope's tags alone, as the recordings
`observation_scopes/05` to `08` showed), and refuses a scope a source item didn't send.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.fakes.hindsight import RecordedHindsight
from tests.fakes.serve import Served
from tests.harness import LITE_10K, THEMES, Atlas, assert_source

COHR_10K = "https://www.sec.gov/Archives/edgar/data/820318/000082031826000020/iivi-20260630.htm"
PHOTONICS = ["theme:photonics"]


@pytest.fixture
def hindsight_fake() -> RecordedHindsight:
    fake = RecordedHindsight()
    fake.derive_memories()
    return fake


@pytest.fixture
def atlas(
    database_url: str, tmp_path: Path, hindsight: tuple[RecordedHindsight, Served]
) -> Iterator[Atlas]:
    harness = Atlas(database_url, tmp_path, hindsight[1].url)
    harness.apply_template()
    yield harness
    harness.engine.dispose()


def items(fake: RecordedHindsight) -> list[dict[str, Any]]:
    return [item for batch in fake.retained() for item in batch]


def test_a_section_of_a_company_in_one_theme_is_retained_with_that_themes_scope(
    atlas: Atlas, fake: RecordedHindsight
) -> None:
    atlas.ingest_company("lumentum")
    lumentum = atlas.company("lumentum")

    retained = items(fake)
    assert retained
    for item in retained:
        assert item["observation_scopes"] == [PHOTONICS]
        # The company, source, document type and form stay on the item for filtering.
        assert f"company:{lumentum['id']}" in item["tags"]
        assert "theme:photonics" in item["tags"]
        assert any(tag.startswith("source:") for tag in item["tags"])
        assert any(tag.startswith("doctype:") for tag in item["tags"])
        assert any(tag.startswith("form:") for tag in item["tags"])


def test_a_company_in_two_themes_is_retained_with_one_scope_per_theme(
    database_url: str, tmp_path: Path, hindsight: tuple[RecordedHindsight, Served]
) -> None:
    fake, served = hindsight
    universe = yaml.safe_load(THEMES.read_text(encoding="utf-8"))
    universe["themes"]["lasers"] = {
        "title": "Lasers",
        "description": "Laser makers.",
        "companies": ["lumentum"],
    }
    themes = tmp_path / "themes.yaml"
    themes.write_text(yaml.safe_dump(universe), encoding="utf-8")
    atlas = Atlas(database_url, tmp_path, served.url, themes_config=themes)
    atlas.apply_template()

    atlas.ingest_company("lumentum")

    retained = items(fake)
    assert retained
    for item in retained:
        assert item["observation_scopes"] == [["theme:lasers"], PHOTONICS]
        assert {"theme:lasers", "theme:photonics"} <= set(item["tags"])
    atlas.engine.dispose()


def test_a_theme_observation_draws_on_two_companies_and_a_company_recall_returns_facts_only(
    atlas: Atlas, fake: RecordedHindsight
) -> None:
    atlas.ingest_company("lumentum")
    atlas.ingest_company("coherent")
    lumentum, coherent = atlas.company("lumentum"), atlas.company("coherent")
    lite = atlas.section(LITE_10K, "lumentum")
    cohr = atlas.section(COHR_10K, "coherent")
    observation_id = fake.derive_observation(
        [lite["document_id"], cohr["document_id"]], scope=PHOTONICS
    )

    by_theme = atlas.recall("who makes lasers", theme_ids=["photonics"])

    (observation,) = [m for m in by_theme["memories"] if m["type"] == "observation"]
    assert observation["memory_id"] == observation_id
    assert observation["tags"] == PHOTONICS  # a theme observation carries no company tag
    provenance = observation["provenance"]
    assert provenance["state"] == "resolved"
    lite_source, cohr_source = provenance["sources"]
    assert lite_source["memory_id"] == fake.derived_fact(lite["document_id"])
    assert cohr_source["memory_id"] == fake.derived_fact(cohr["document_id"])
    assert_source(lite_source, lite, lumentum)
    assert_source(cohr_source, cohr, coherent)

    by_company = atlas.recall("who makes lasers", company_ids=[lumentum["id"]])

    memories = by_company["memories"]
    assert memories
    assert {m["type"] for m in memories} == {"world"}
    assert {m["provenance"]["sources"][0]["company_id"] for m in memories} == {lumentum["id"]}
    assert all(m["provenance"]["state"] == "resolved" for m in memories)


def test_the_health_read_lists_the_theme_scope(atlas: Atlas, fake: RecordedHindsight) -> None:
    atlas.ingest_company("lumentum")
    atlas.ingest_company("coherent")
    lite = atlas.section(LITE_10K, "lumentum")
    cohr = atlas.section(COHR_10K, "coherent")
    fake.derive_observation([lite["document_id"], cohr["document_id"]], scope=PHOTONICS)
    fake.derive_observation([lite["document_id"]], scope=PHOTONICS)
    fake.script_entities([])  # the read also lists entities (hand-written; not this ticket's)

    health = atlas.get("/api/v1/memory/health")

    scopes = health["observation_scopes"]
    assert scopes["status"] == "ok"
    assert scopes["total"] == 1
    assert [(s["tags"], s["count"]) for s in scopes["scopes"]] == [(PHOTONICS, 2)]
