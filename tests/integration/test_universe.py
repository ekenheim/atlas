"""The photonics universe (Phases 3-6a build ticket 01): 12 companies, their supply-chain
layer and source path, seeded from config, and the SEC ingest's refusal of non-SEC filers.

Seams: `atlas companies seed` and `atlas ingest` (CLI), one worker pass, `/api/v1`, on a fresh
database. Expected identities come from the seed-list research (branch `research/seed-list`,
docs/research/seed-list.md), never from the config the code reads.
"""

import json
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from atlas.api.app import create_app
from atlas.jobs import JobQueue, Worker, builtin_registry
from atlas.settings import Settings
from tests.harness import THEMES, make_settings

# slug -> (layer, source path, SEC CIK or None, SEC forms or None for the default)
PHOTONICS = {
    "axt": ("substrate", "sec", "0001051627", None),
    "soitec": ("substrate", "exchange:amf", None, None),
    "iqe": ("epi", "exchange:fca-nsm", None, None),
    "coherent": ("chip-laser", "sec", "0000820318", None),
    "lumentum": ("chip-laser", "sec", "0001633978", None),
    "macom": ("chip-laser", "sec", "0001493594", None),
    "stmicroelectronics": ("chip-laser", "sec", "0000932787", ["20-F", "6-K"]),
    "marvell": ("dsp", "sec", "0001835632", None),
    "innolight": ("module", "exchange:hkex", None, None),
    "applied-optoelectronics": ("module", "sec", "0001158114", None),
    "fabrinet": ("contract-manufacturing", "sec", "0001408710", None),
    "ciena": ("system", "sec", "0000936395", None),
}
# SEC's ticker files map these to Soitec, IQE and Innolight, but they hold only depositary
# F-6EF registrations for unsponsored ADRs (seed-list finding 3).
UNSPONSORED_ADR_CIKS = {
    "soitec": "0001445214",
    "iqe": "0001550405",
    "innolight": "0002150915",
}

STM_CIK = "0000932787"
STM_ARCHIVES = "https://www.sec.gov/Archives/edgar/data/932787"


class Universe:
    """A migrated database, the `atlas` CLI (with a chosen theme config), one worker pass and
    the API; no Hindsight."""

    def __init__(self, database_url: str, tmp_path: Path, fixtures: Path) -> None:
        self.database_url = database_url
        self.tmp_path = tmp_path
        self.archive = tmp_path / "archive"
        self.archive.mkdir(exist_ok=True)
        self.fixtures = fixtures
        self.engine = create_engine(database_url)
        self.api = TestClient(create_app(self.settings()))

    def settings(self) -> Settings:
        return make_settings(
            self.archive,
            database_url=self.database_url,
            themes_config=THEMES,
            sec_fixtures_dir=self.fixtures,
            sec_8k_items="*",
            sec_8k_exhibits_only_items="",
        )

    def cli(self, *args: str, themes: Path = THEMES) -> subprocess.CompletedProcess[str]:
        env = {
            "PATH": os.environ["PATH"],
            "HOME": str(self.tmp_path),
            "ATLAS_DATABASE_URL": self.database_url,
            "ATLAS_ACTOR": "local-researcher",
            "ATLAS_ARCHIVE_ROOT": str(self.archive),
            "ATLAS_THEMES_CONFIG": str(themes),
            "ATLAS_SEC_FIXTURES_DIR": str(self.fixtures),
            "ATLAS_SEC_8K_ITEMS": "*",
            "ATLAS_SEC_8K_EXHIBITS_ONLY_ITEMS": "",
        }
        return subprocess.run(
            [sys.executable, "-m", "atlas", *args],
            cwd=self.tmp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )

    def seed(self) -> list[dict[str, Any]]:
        seeded = self.cli("companies", "seed")
        assert seeded.returncode == 0, seeded.stderr
        return [json.loads(line) for line in seeded.stdout.splitlines()]

    def worker_pass(self) -> int:
        return Worker(JobQueue(self.engine), builtin_registry(self.settings())).run_once()

    def get(self, path: str, **params: Any) -> Any:
        response = self.api.get(path, params=params)
        assert response.status_code == 200, response.text
        return response.json()

    def companies(self) -> dict[str, dict[str, Any]]:
        page = self.get("/api/v1/companies", limit=100)
        assert page["total"] == len(page["items"])
        return {company["slug"]: company for company in page["items"]}

    def count(self, table: str) -> int:
        with self.engine.connect() as connection:
            return connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()


@pytest.fixture
def universe(database_url: str, tmp_path: Path) -> Iterator[Universe]:
    fixtures = tmp_path / "edgar"
    fixtures.mkdir()
    harness = Universe(database_url, tmp_path, fixtures)
    yield harness
    harness.engine.dispose()


def theme_config(tmp_path: Path, change: dict[str, dict[str, Any]]) -> Path:
    """A copy of the theme config with some companies' fields changed."""
    document = yaml.safe_load(THEMES.read_text())
    for slug, fields in change.items():
        document["companies"][slug].update(fields)
    path = tmp_path / "themes.yaml"
    path.write_text(yaml.safe_dump(document))
    return path


# --- the universe ---


def test_the_photonics_theme_seeds_the_twelve_companies_with_layer_and_source_path(
    universe: Universe,
) -> None:
    universe.seed()

    companies = universe.companies()
    assert {
        slug: (c["layer"], c["source_path"], c["cik"], c["sec_forms"])
        for slug, c in companies.items()
    } == PHOTONICS
    assert companies["stmicroelectronics"]["legal_name"] == "STMicroelectronics N.V."
    assert companies["innolight"]["country"] == "CN"
    one = universe.get(f"/api/v1/companies/{companies['soitec']['id']}")
    assert (one["layer"], one["source_path"]) == ("substrate", "exchange:amf")


def test_seeding_again_changes_nothing_and_audits_nothing(universe: Universe) -> None:
    first = universe.seed()
    events = universe.count("audit_event")
    second = universe.seed()

    # 12 companies plus Lumentum's one security, each created once.
    assert sum(each["changes"] for each in first) == events == 13
    assert [each["changes"] for each in second] == [0] * 12
    assert universe.count("audit_event") == events


def test_a_changed_layer_is_updated_in_place_and_audited(universe: Universe) -> None:
    universe.seed()
    before = universe.companies()["macom"]
    changed = theme_config(universe.tmp_path, {"macom": {"layer": "module"}})

    reseeded = universe.cli("companies", "seed", themes=changed)

    assert reseeded.returncode == 0, reseeded.stderr
    changes = {
        json.loads(line)["company"]: json.loads(line)["changes"]
        for line in reseeded.stdout.splitlines()
    }
    assert changes["macom"] == 1
    assert sum(changes.values()) == 1
    after = universe.companies()["macom"]
    assert (after["id"], after["layer"]) == (before["id"], "module")


def test_unsponsored_adr_ciks_are_never_a_company_filer(universe: Universe) -> None:
    universe.seed()

    companies = universe.companies()
    ciks = {c["cik"] for c in companies.values()}
    assert ciks.isdisjoint(UNSPONSORED_ADR_CIKS.values())
    for slug in UNSPONSORED_ADR_CIKS:
        assert companies[slug]["cik"] is None
        assert companies[slug]["source_path"] != "sec"


def test_a_config_using_an_ignored_adr_cik_as_a_filer_is_refused(universe: Universe) -> None:
    as_filer = theme_config(
        universe.tmp_path,
        {"soitec": {"source_path": "sec", "cik": UNSPONSORED_ADR_CIKS["soitec"], "exchange": None}},
    )

    result = universe.cli("companies", "seed", themes=as_filer)

    assert result.returncode == 2
    assert UNSPONSORED_ADR_CIKS["soitec"] in result.stderr
    assert "ignored" in result.stderr
    assert universe.count("company") == 0


def test_a_config_giving_an_exchange_company_a_cik_is_refused(universe: Universe) -> None:
    with_cik = theme_config(universe.tmp_path, {"iqe": {"cik": "0000000001"}})

    result = universe.cli("companies", "seed", themes=with_cik)

    assert result.returncode == 2
    assert "companies.iqe" in result.stderr
    assert "not an SEC filer" in result.stderr


# --- the SEC ingest and source paths ---


# Every source path has an adapter now: Innolight (exchange:hkex) since ticket 04
# (tests/integration/test_hkexnews.py), IQE (exchange:fca-nsm) since ticket 05
# (test_fca_nsm.py) and Soitec (exchange:amf) since ticket 06 (test_amf.py), so the
# "no adapter" refusal has no company left to test it with.


def write_stm_fixtures(root: Path) -> None:
    """Hand-written EDGAR responses for STMicroelectronics (not recorded from SEC): a
    submissions index with a 20-F, a 6-K and an 11-K, their primary documents, and a
    companyfacts stub. Only the shape matters: which forms the ingest picks."""
    filings = [
        ("0000932787-26-000031", "20-F", "2026-02-26", "2026-02-26T12:01:05.000Z", "stm-20f.htm"),
        ("0000932787-26-000077", "6-K", "2026-07-23", "2026-07-23T06:02:11.000Z", "stm-6k.htm"),
        ("0000932787-26-000080", "11-K", "2026-06-20", "2026-06-20T15:30:00.000Z", "stm-11k.htm"),
    ]
    submissions = {
        "cik": STM_CIK,
        "name": "STMicroelectronics N.V.",
        "filings": {
            "recent": {
                "accessionNumber": [f[0] for f in filings],
                "filingDate": [f[2] for f in filings],
                "reportDate": ["", "", ""],
                "acceptanceDateTime": [f[3] for f in filings],
                "form": [f[1] for f in filings],
                "items": ["", "", ""],
                "primaryDocument": [f[4] for f in filings],
            }
        },
    }
    responses: list[dict[str, Any]] = []

    def add(url: str, body: bytes, content_type: str) -> None:
        file = url.removeprefix("https://")
        (root / file).parent.mkdir(parents=True, exist_ok=True)
        (root / file).write_bytes(body)
        responses.append({"url": url, "file": file, "headers": {"content-type": content_type}})

    add(
        f"https://data.sec.gov/submissions/CIK{STM_CIK}.json",
        json.dumps(submissions).encode(),
        "application/json",
    )
    add(
        f"https://data.sec.gov/api/xbrl/companyfacts/CIK{STM_CIK}.json",
        json.dumps({"cik": 932787, "entityName": "STMicroelectronics N.V.", "facts": {}}).encode(),
        "application/json",
    )
    for accession, form, _, _, document in filings:
        folder = accession.replace("-", "")
        body = f"<html><body><p>STMicroelectronics {form} report.</p></body></html>"
        add(f"{STM_ARCHIVES}/{folder}/{document}", body.encode(), "text/html")
    (root / "manifest.json").write_text(json.dumps({"responses": responses}))


def test_stmicroelectronics_is_ingested_from_its_20f_and_6k_filings(universe: Universe) -> None:
    write_stm_fixtures(universe.fixtures / "stmicroelectronics")
    enqueued = universe.cli("ingest", "--company", "stmicroelectronics", "--key", "stm")
    assert enqueued.returncode == 0, enqueued.stderr

    universe.worker_pass()

    job = universe.get(f"/api/v1/jobs/{json.loads(enqueued.stdout)['id']}")
    assert job["status"] == "succeeded", job["last_error"]
    stm = universe.companies()["stmicroelectronics"]
    sources = universe.get(f"/api/v1/companies/{stm['id']}/sources", limit=100)["items"]
    assert sorted(s["form_type"] or s["source_type"] for s in sources) == sorted(
        ["20-F", "6-K", "xbrl_companyfacts"]
    )
