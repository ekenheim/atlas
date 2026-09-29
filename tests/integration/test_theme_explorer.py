"""The Theme explorer and the Company dossier (Phase 3-6a ticket 23; product spec §10.1 A-B).

Seam: `/api/v1/themes`, `/api/v1/themes/{id}/map` and `/api/v1/companies/{id}/dossier`.
The state they read is built through the real services: the `atlas companies seed` CLI, an
`ingest` job run by a worker pass over the recorded Lumentum EDGAR fixtures (Source Documents
and, from companyfacts, financial observations), Assertions on hedged sentences of the
Lumentum 10-K and a `review_relationships` job (hedged, so no Reviewer call), the fetch gate's
`record_decision`, and the Hindsight fake's template import and Bottlenecks refresh. A
Candidate and a pending identity mapping are inserted as rows: their own flows (discovery,
entity resolution) are ticket 09's and 02's and are tested there.

The universe is the repo's plus NVIDIA, outside the photonics theme. Expected layers and
members are the theme config's; figures are the recorded filings' (ticket 18).
"""

import json
import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx2
import pytest
import yaml
from pydantic import JsonValue
from sqlalchemy import text

from atlas.archive import open_archive
from atlas.assertions import AssertionCreate, Assertions
from atlas.audit import Actor
from atlas.jobs import HandlerRegistry, JobQueue, Worker
from atlas.ledger import record_decision
from atlas.ledger.ingest import ingest_payload
from atlas.relationships import REVIEW_RELATIONSHIPS_KIND, RelationshipReviewer
from atlas.roles import RoleCaller
from atlas.settings import Settings
from atlas.sources.gate import GateDecision
from tests.fakes.hindsight import RecordedHindsight
from tests.fakes.serve import Served
from tests.harness import LITE_10K, THEMES, Atlas, at

NOW = "2026-09-29T00:00:00Z"
# The photonics theme's companies by layer, upstream to downstream (the theme config).
LAYERS = {
    "substrate": ["axt", "soitec"],
    "epi": ["iqe"],
    "chip-laser": ["coherent", "lumentum", "macom", "stmicroelectronics"],
    "dsp": ["marvell"],
    "module": ["innolight", "applied-optoelectronics"],
    "contract-manufacturing": ["fabrinet"],
    "system": ["ciena"],
}
# Hedged sentences of the Lumentum FY2026 10-K (the recorded fixture's parsed text), so the
# review job sends each edge to the exceptions queue without asking the Reviewer.
SOLE_SOURCE = (
    "For many products, a particular contract manufacturer may be the sole source of the"
    " finished good products."
)
COMPETITIVE = (
    "Our current or potential customers may also determine to develop and produce products"
    " for their own use which may be competitive to our products."
)
YIELDS = (
    "Changes in demand and customer requirements for our products may reduce manufacturing"
    " yields, which could negatively impact our profitability."
)
GAPS = "- EML laser capacity for 1.6T transceivers is unconfirmed by any Tier A source."
NO_HINDSIGHT = "http://hindsight.invalid"  # the harness's marker for "not configured"
INNOLIGHT_PDF = "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0828/2026082800123.pdf"


class ExplorerAtlas(Atlas):
    """The harness on the repo's universe plus NVIDIA; Hindsight only when given a URL."""

    def settings(self) -> Settings:
        settings = super().settings()
        if self.hindsight_url == NO_HINDSIGHT:
            return settings.model_copy(update={"hindsight_url": None})
        return settings

    def seed(self) -> None:
        """`atlas companies seed` on this harness's universe (`Atlas.cli` seeds the repo's)."""
        seeded = subprocess.run(
            [sys.executable, "-m", "atlas", "companies", "seed"],
            cwd=self.tmp_path,
            env={
                "PATH": os.environ["PATH"],
                "HOME": str(self.tmp_path),
                "ATLAS_DATABASE_URL": self.database_url,
                "ATLAS_ACTOR": "local-researcher",
                "ATLAS_ARCHIVE_ROOT": str(self.archive),
                "ATLAS_THEMES_CONFIG": str(self.overrides["themes_config"]),
            },
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert seeded.returncode == 0, seeded.stderr

    def ingest_lumentum(self) -> None:
        enqueued = JobQueue(self.engine).enqueue(
            "ingest", "lumentum", ingest_payload("lumentum", None, None)
        )
        self.worker_pass()
        job = self.get(f"/api/v1/jobs/{enqueued.job.id}")
        assert job["status"] == "succeeded", job["failures"]

    def ids(self) -> dict[str, str]:
        return {c["slug"]: c["id"] for c in self.get("/api/v1/companies", limit=500)["items"]}

    def map(self, theme: str = "photonics") -> dict[str, Any]:
        return self.get(f"/api/v1/themes/{theme}/map")

    def dossier(self, slug: str, **params: Any) -> dict[str, Any]:
        return self.get(f"/api/v1/companies/{self.ids()[slug]}/dossier", **params)

    def edges(self, *edges: tuple[str, str | None, str, dict[str, JsonValue]]) -> None:
        """Assertions by Lumentum on the 10-K, reviewed by one `review_relationships` job."""
        with self.engine.connect() as connection:
            version_id, parsed_uri = connection.execute(
                text(
                    "SELECT v.id, v.parsed_object_uri FROM source_version v"
                    " JOIN source_document d ON d.id = v.source_document_id"
                    " WHERE d.canonical_url = :url"
                ),
                {"url": LITE_10K},
            ).one()
        archive = open_archive(self.settings())
        parsed = archive.get(parsed_uri).decode("utf-8")
        ids = self.ids()
        assertions = Assertions(self.engine, archive, Actor("local-researcher"))
        created: list[JsonValue] = []
        for predicate, target, quote, value in edges:
            start = parsed.index(quote)
            recorded = assertions.create(
                AssertionCreate(
                    subject_company_id=uuid.UUID(ids["lumentum"]),
                    predicate=predicate,
                    object_company_id=None if target is None else uuid.UUID(ids[target]),
                    value_json=value,
                    source_version_id=version_id,
                    quote=quote,
                    span_start=start,
                    span_end=start + len(quote),
                    epistemic_type="company_claim",
                )
            )
            created.append(str(recorded.assertion.id))
        queue = JobQueue(self.engine)
        queue.enqueue(REVIEW_RELATIONSHIPS_KIND, "explorer", {"assertion_ids": created})

        def refuse(request: httpx2.Request) -> httpx2.Response:
            raise AssertionError(f"the Reviewer was asked ({request.url})")

        caller = RoleCaller(
            self.engine,
            "http://reviewer.invalid",
            "unused",
            model="unused",
            extra_body={},
            token_budget=0,
            timeout=1,
            transport=httpx2.MockTransport(refuse),
        )
        with caller:
            registry = HandlerRegistry()
            reviewer = RelationshipReviewer(self.engine, archive, caller, None, per_call=10)
            registry.register(REVIEW_RELATIONSHIPS_KIND, reviewer.review, pausable=True)
            assert Worker(queue, registry).run_once() == 1


@pytest.fixture
def themes(tmp_path: Path) -> Path:
    universe = yaml.safe_load(THEMES.read_text(encoding="utf-8"))
    universe["companies"]["nvidia"] = {
        "legal_name": "NVIDIA Corporation",
        "display_name": "NVIDIA",
        "cik": "0001045810",
        "country": "US",
        "source_path": "sec",
    }
    path = tmp_path / "themes.yaml"
    path.write_text(yaml.safe_dump(universe), encoding="utf-8")
    return path


@pytest.fixture
def atlas(database_url: str, tmp_path: Path, themes: Path) -> Iterator[ExplorerAtlas]:
    atlas = ExplorerAtlas(database_url, tmp_path, NO_HINDSIGHT, themes_config=themes)
    yield atlas
    atlas.engine.dispose()


@pytest.fixture
def researched(atlas: ExplorerAtlas) -> ExplorerAtlas:
    """Seeded, Lumentum ingested, and four edges: three inside the theme, one to NVIDIA."""
    atlas.seed()
    atlas.ingest_lumentum()
    atlas.edges(
        ("depends_on", "fabrinet", SOLE_SOURCE, {"layer": "contract-manufacturing"}),
        ("competes_with", "coherent", COMPETITIVE, {"layer": "module"}),
        ("manufactures", None, YIELDS, {"layer": "module", "object_text": "optical products"}),
        ("competes_with", "nvidia", COMPETITIVE, {"layer": "system"}),
    )
    return atlas


def insert_candidate(atlas: ExplorerAtlas, theme: str, name: str, cik: str) -> None:
    resolution: dict[str, JsonValue] = {
        "mention": {"name": name},
        "tier": "exact",
        "entity": None,
        "candidates": [],
        "proposals": [],
        "review_reasons": [],
        "notes": [],
        "evidence": [],
        "dropped": [],
    }
    with atlas.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO candidate (id, theme, identity_key, name, cik, country, tier,"
                " source_path, resolution) VALUES (:id, :theme, :key, :name, :cik, 'US',"
                " 'exact', 'sec', CAST(:resolution AS jsonb))"
            ),
            {
                "id": uuid.uuid4(),
                "theme": theme,
                "key": f"cik:{cik}",
                "name": name,
                "cik": cik,
                "resolution": json.dumps(resolution),
            },
        )


# --- themes -------------------------------------------------------------------------------------


def test_themes_list_each_theme_with_its_coverage(atlas: ExplorerAtlas) -> None:
    (unseeded,) = atlas.get("/api/v1/themes")
    assert unseeded["id"] == "photonics"
    assert unseeded["title"] == "Photonics for AI data centers"
    assert (unseeded["company_count"], unseeded["companies_without_sources"]) == (12, 12)
    assert (unseeded["relationship_count"], unseeded["open_candidate_count"]) == (0, 0)
    assert unseeded["empty_layers"] == []

    atlas.seed()
    atlas.ingest_lumentum()
    insert_candidate(atlas, "photonics", "Sivers Semiconductors", "0000000001")
    (theme,) = atlas.get("/api/v1/themes")
    assert (theme["company_count"], theme["companies_without_sources"]) == (12, 11)
    assert theme["open_candidate_count"] == 1


def test_the_map_lists_the_theme_companies_by_layer_upstream_to_downstream(
    atlas: ExplorerAtlas,
) -> None:
    before = atlas.map()
    assert {
        layer["layer"]: [c["slug"] for c in layer["companies"]] for layer in before["layers"]
    } == LAYERS
    assert [layer["layer"] for layer in before["layers"]] == list(LAYERS)
    assert all(
        c["gaps"] == ["not_seeded", "no_sources"] and not c["seeded"]
        for layer in before["layers"]
        for c in layer["companies"]
    )
    assert before["unlayered"] == []
    assert "NVIDIA" not in json.dumps(before["layers"])  # not in the theme

    atlas.seed()
    atlas.ingest_lumentum()
    after = atlas.map()
    companies = {c["slug"]: c for layer in after["layers"] for c in layer["companies"]}
    lumentum = companies["lumentum"]
    assert lumentum["id"] == atlas.ids()["lumentum"]
    assert (lumentum["display_name"], lumentum["layer"], lumentum["source_path"]) == (
        "Lumentum",
        "chip-laser",
        "sec",
    )
    sources = atlas.get(f"/api/v1/companies/{lumentum['id']}/sources")["total"]
    assert lumentum["source_count"] == sources > 0
    assert (lumentum["seeded"], lumentum["gaps"]) == (True, [])
    assert (companies["coherent"]["seeded"], companies["coherent"]["gaps"]) == (
        True,
        ["no_sources"],
    )


def test_the_map_holds_the_relationships_between_theme_companies(
    researched: ExplorerAtlas,
) -> None:
    edges = researched.map()["relationships"]
    # Layer order (upstream to downstream), then subject: the NVIDIA edge is outside the theme.
    assert [
        (e["subject_name"], e["predicate"], e["object_name"] or e["object_text"]) for e in edges
    ] == [
        ("Lumentum", "competes_with", "Coherent"),
        ("Lumentum", "manufactures", "optical products"),
        ("Lumentum", "depends_on", "Fabrinet"),
    ]
    assert [e["layer"] for e in edges] == ["module", "module", "contract-manufacturing"]
    assert {e["review_state"] for e in edges} == {"needs_human_review"}
    assert all(e["evidence_count"] == 1 and e["family_count"] == 1 for e in edges)

    companies = {c["slug"]: c for layer in researched.map()["layers"] for c in layer["companies"]}
    assert companies["lumentum"]["relationship_count"] == 4  # the NVIDIA edge too
    assert companies["fabrinet"]["relationship_count"] == 1
    assert researched.get("/api/v1/themes")[0]["relationship_count"] == 3


def test_the_map_holds_the_theme_candidates_only(atlas: ExplorerAtlas) -> None:
    insert_candidate(atlas, "photonics", "Sivers Semiconductors", "0000000001")
    insert_candidate(atlas, "power", "Vicor", "0000000002")
    (candidate,) = atlas.map()["candidates"]
    assert (candidate["name"], candidate["theme"], candidate["state"]) == (
        "Sivers Semiconductors",
        "photonics",
        "lead",
    )


def test_an_unknown_theme_is_not_found(atlas: ExplorerAtlas) -> None:
    response = atlas.api.get("/api/v1/themes/power/map")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_without_hindsight_the_map_says_the_gaps_are_not_configured(atlas: ExplorerAtlas) -> None:
    assert atlas.map()["bottlenecks"] == {
        "status": "not_configured",
        "message": None,
        "model": None,
    }


def test_the_map_carries_the_bottlenecks_gaps_once_refreshed(
    database_url: str,
    tmp_path: Path,
    themes: Path,
    hindsight: tuple[RecordedHindsight, Served],
) -> None:
    atlas = ExplorerAtlas(database_url, tmp_path, hindsight[1].url, themes_config=themes)
    try:
        atlas.apply_template()
        pending = atlas.map()["bottlenecks"]
        assert pending["status"] == "not_refreshed"
        assert pending["model"]["last_refreshed_at"] is None

        hindsight[0].apply_refresh("bottlenecks", GAPS, [], refreshed_at=at(NOW))
        gaps = atlas.map()["bottlenecks"]
        assert gaps["status"] == "refreshed"
        assert (gaps["model"]["id"], gaps["model"]["content"]) == ("bottlenecks", GAPS)
        assert gaps["model"]["last_refreshed_at"] == "2026-09-29T00:00:00Z"
        assert gaps["model"]["evidence_missing"] is True  # it cites nothing
    finally:
        atlas.engine.dispose()


def test_a_hindsight_outage_never_fails_the_map(
    database_url: str, tmp_path: Path, themes: Path
) -> None:
    atlas = ExplorerAtlas(database_url, tmp_path, "http://127.0.0.1:1", themes_config=themes)
    try:
        bottlenecks = atlas.map()["bottlenecks"]
        assert (bottlenecks["status"], bottlenecks["model"]) == ("unavailable", None)
        assert bottlenecks["message"]
    finally:
        atlas.engine.dispose()


# --- dossier ------------------------------------------------------------------------------------


def test_the_dossier_holds_identity_themes_sources_and_relationships(
    researched: ExplorerAtlas,
) -> None:
    ids = researched.ids()
    dossier = researched.dossier("lumentum", as_of=NOW)
    company = dossier["company"]
    assert (company["id"], company["legal_name"], company["cik"]) == (
        ids["lumentum"],
        "Lumentum Holdings Inc.",
        "0001633978",
    )
    assert [(s["ticker"], s["exchange_mic"]) for s in company["securities"]] == [("LITE", "XNAS")]
    assert dossier["themes"] == [{"id": "photonics", "title": "Photonics for AI data centers"}]

    sources = researched.get(f"/api/v1/companies/{ids['lumentum']}/sources", limit=500)
    assert dossier["source_total"] == sources["total"]
    assert [s["id"] for s in dossier["sources"]] == [s["id"] for s in sources["items"]]
    assert LITE_10K in {s["canonical_url"] for s in dossier["sources"]}

    out = {
        (e["predicate"], e["object_name"] or e["object_text"]) for e in dossier["relationships_out"]
    }
    assert out == {
        ("depends_on", "Fabrinet"),
        ("competes_with", "Coherent"),
        ("manufactures", "optical products"),
        ("competes_with", "NVIDIA"),
    }
    assert dossier["relationships_in"] == []
    fabrinet = researched.dossier("fabrinet")
    assert [(e["subject_name"], e["predicate"]) for e in fabrinet["relationships_in"]] == [
        ("Lumentum", "depends_on")
    ]
    assert fabrinet["relationships_out"] == []
    assert fabrinet["sources"] == [] and fabrinet["source_total"] == 0
    assert researched.dossier("nvidia")["themes"] == []


def test_the_dossier_financials_are_as_of_the_cutoff(researched: ExplorerAtlas) -> None:
    def fy2026_revenue(as_of: str) -> list[dict[str, Any]]:
        figures = researched.dossier("lumentum", as_of=as_of)["financials"]["figures"]
        return [
            f
            for f in figures
            if f["metric"] == "revenue"
            and (f["period_start"], f["period_end"]) == ("2025-06-29", "2026-06-27")
        ]

    # The FY2026 10-K (net revenue $3,014.0M) was accepted 2026-08-17 20:03:17 UTC.
    (revenue,) = fy2026_revenue(NOW)
    assert Decimal(revenue["value"]) == Decimal("3014000000")
    assert revenue["available_at"] == "2026-08-17T20:03:17Z"
    assert revenue["sources"][0]["accession"] == "0001628280-26-057358"
    assert fy2026_revenue("2026-08-17T20:00:00Z") == []
    assert researched.dossier("lumentum", as_of=NOW)["financials"]["as_of"] == NOW


def test_the_dossier_lists_pending_identity_reviews(researched: ExplorerAtlas) -> None:
    ids = researched.ids()
    with researched.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO identity_mapping (id, company_id, kind, value, tier, review_state,"
                " owner_confirmation, source, source_url, observed_at, reasons)"
                " VALUES (:id, :company, 'lei', '549300M2142IVLVIJN37', 'candidate', 'pending',"
                " true, 'gleif', 'https://api.gleif.org/api/v1/lei-records/549300M2142IVLVIJN37',"
                " :observed, ARRAY['lapsed_lei'])"
            ),
            {
                "id": uuid.uuid4(),
                "company": ids["axt"],
                "observed": datetime(2026, 9, 29, tzinfo=UTC),
            },
        )
    (pending,) = researched.dossier("axt")["pending_identity_reviews"]
    assert (pending["kind"], pending["value"], pending["reasons"]) == (
        "lei",
        "549300M2142IVLVIJN37",
        ["lapsed_lei"],
    )
    assert researched.dossier("lumentum")["pending_identity_reviews"] == []
    axt = next(
        c for layer in researched.map()["layers"] for c in layer["companies"] if c["slug"] == "axt"
    )
    assert axt["pending_identity_reviews"] == 1


def test_the_dossier_lists_fetch_gate_blocks(researched: ExplorerAtlas) -> None:
    innolight = uuid.UUID(researched.ids()["innolight"])
    decided = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
    record_decision(
        researched.engine,
        Actor("local-researcher"),
        GateDecision(
            url=INNOLIGHT_PDF,
            status="blocked",
            blocked_by="terms",
            reason="HKEX's Terms of Use forbid automated access",
            site="hkexnews",
            terms=None,
            robots=None,
            user_agent_token="AtlasResearch",
            decided_at=decided,
        ),
        provider="hkexnews",
        purpose="document",
        company_id=innolight,
        job_id=None,
    )
    dossier = researched.dossier("innolight")
    (block,) = dossier["fetch_gate_blocks"]
    assert (block["url"], block["blocked_by"], block["status"]) == (
        INNOLIGHT_PDF,
        "terms",
        "blocked",
    )
    assert dossier["fetch_gate_block_total"] == 1
    assert researched.dossier("lumentum")["fetch_gate_blocks"] == []


def test_the_dossier_of_an_unknown_company_is_not_found(atlas: ExplorerAtlas) -> None:
    response = atlas.api.get(f"/api/v1/companies/{uuid.uuid4()}/dossier")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    bad = atlas.api.get(f"/api/v1/companies/{uuid.uuid4()}/dossier", params={"as_of": "2026-09-29"})
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "invalid_request"
