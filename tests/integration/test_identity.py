"""Entity resolution and identity review (Phases 3-6a build ticket 02).

Seams: `atlas companies resolve` (CLI, against the identity fake served on localhost),
`/api/v1/identity-mappings` and `/api/v1/companies`, and `resolve_mention` (the function
Candidates from leads call), on a fresh database. Expected identifiers are the identity
research's recorded values (docs/research/identity-apis.md, branch `research/identity-apis`).
"""

import json
import os
import subprocess
import sys
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from atlas.api.app import create_app
from atlas.audit import verify_chain
from atlas.identity import EntityResolver, Mention
from atlas.identity.service import find_in_universe, resolve_mention
from tests.fakes.identity import FakeIdentitySources
from tests.fakes.serve import Served, serve
from tests.harness import make_settings

LUMENTUM_LEI = "549300JLWRRC38DWEF52"
COHERENT_LEI = "549300O5C25A0MMHHU33"
SOITEC_LEI = "969500ZR92SQCU9TST26"
SOITEC_ADR_CIK = "0001445214"
UA = "Atlas Research ops@example.com"

THEMES = {
    "version": 1,
    "name": "identity-test",
    "companies": {
        "lumentum": {
            "legal_name": "Lumentum Holdings Inc.",
            "display_name": "Lumentum",
            "cik": "0001633978",
            "country": "US",
            "layer": "chip-laser",
            "source_path": "sec",
            "securities": [
                {
                    "ticker": "LITE",
                    "exchange_mic": "XNAS",
                    "instrument_type": "common",
                    "currency": "USD",
                    "valid_from": "2015-08-04",
                }
            ],
        },
        "coherent": {
            "legal_name": "Coherent Corp.",
            "display_name": "Coherent",
            "cik": "0000820318",
            "country": "US",
            "layer": "chip-laser",
            "source_path": "sec",
        },
        "soitec": {
            "legal_name": "Soitec SA",
            "display_name": "Soitec",
            "country": "FR",
            "layer": "substrate",
            "source_path": "exchange:amf",
            "ignored_ciks": [{"cik": SOITEC_ADR_CIK, "reason": "unsponsored-ADR shell"}],
        },
    },
    "themes": {
        "photonics": {"title": "Photonics", "companies": ["lumentum", "coherent", "soitec"]}
    },
}


class Identity:
    def __init__(self, database_url: str, tmp_path: Path, served: Served) -> None:
        self.database_url = database_url
        self.tmp_path = tmp_path
        self.served = served
        self.themes = tmp_path / "themes.yaml"
        self.themes.write_text(yaml.safe_dump(THEMES), encoding="utf-8")
        archive = tmp_path / "archive"
        archive.mkdir()
        self.archive = archive
        self.engine = create_engine(database_url)
        self.api = TestClient(create_app(self.settings()))

    def settings(self) -> Any:
        return make_settings(
            self.archive,
            database_url=self.database_url,
            themes_config=self.themes,
            sec_user_agent=UA,
            **self.urls(),
        )

    def urls(self) -> dict[str, str]:
        url = self.served.url
        return {
            "sec_files_url": f"{url}/files",
            "sec_data_url": url,
            "gleif_url": f"{url}/api/v1",
            "openfigi_url": url,
        }

    def cli(self, *args: str, user_agent: str | None = UA) -> subprocess.CompletedProcess[str]:
        env = {
            "PATH": os.environ["PATH"],
            "HOME": str(self.tmp_path),
            "ATLAS_DATABASE_URL": self.database_url,
            "ATLAS_ACTOR": "local-researcher",
            "ATLAS_ARCHIVE_ROOT": str(self.archive),
            "ATLAS_THEMES_CONFIG": str(self.themes),
            **{f"ATLAS_{key.upper()}": value for key, value in self.urls().items()},
        }
        if user_agent:
            env["ATLAS_SEC_USER_AGENT"] = user_agent
        return subprocess.run(
            [sys.executable, "-m", "atlas", *args],
            cwd=self.tmp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )

    def resolve(self) -> dict[str, dict[str, Any]]:
        result = self.cli("companies", "resolve")
        assert result.returncode == 0, result.stderr
        return {line["slug"]: line for line in map(json.loads, result.stdout.splitlines())}

    def get(self, path: str, **params: Any) -> Any:
        response = self.api.get(path, params=params)
        assert response.status_code == 200, response.text
        return response.json()

    def companies(self) -> dict[str, dict[str, Any]]:
        return {c["slug"]: c for c in self.get("/api/v1/companies", limit=100)["items"]}

    def mappings(self, **params: Any) -> list[dict[str, Any]]:
        page = self.get("/api/v1/identity-mappings", limit=100, **params)
        assert page["total"] == len(page["items"])
        return page["items"]

    def mapping(self, slug: str, kind: str, value: str) -> dict[str, Any]:
        [found] = [
            m
            for m in self.mappings()
            if (m["company_slug"], m["kind"], m["value"]) == (slug, kind, value)
        ]
        return found

    def audit_count(self) -> int:
        with self.engine.connect() as connection:
            return connection.execute(text("SELECT count(*) FROM audit_event")).scalar_one()


@pytest.fixture
def fake() -> FakeIdentitySources:
    return FakeIdentitySources()


@pytest.fixture
def identity(database_url: str, tmp_path: Path, fake: FakeIdentitySources) -> Iterator[Identity]:
    with serve(fake.handle) as served:
        harness = Identity(database_url, tmp_path, served)
        yield harness
        harness.engine.dispose()
        served.raise_errors()


def test_resolve_commits_exact_identifiers_and_queues_the_rest(identity: Identity) -> None:
    lines = identity.resolve()

    assert lines["lumentum"]["tier"] == "corroborated"
    assert (lines["lumentum"]["committed"], lines["lumentum"]["pending"]) == (2, 1)
    assert (lines["coherent"]["committed"], lines["coherent"]["pending"]) == (2, 1)
    assert (lines["soitec"]["tier"], lines["soitec"]["committed"]) == ("candidate", 0)

    table = {
        (m["company_slug"], m["kind"], m["value"]): (m["tier"], m["review_state"])
        for m in identity.mappings()
    }
    assert table == {
        ("lumentum", "cik", "0001633978"): ("exact", "committed"),
        ("lumentum", "listing", "LITE@XNAS"): ("exact", "committed"),
        # CIK↔LEI links wait for the owner, whatever their tier.
        ("lumentum", "lei", LUMENTUM_LEI): ("corroborated", "pending"),
        ("coherent", "cik", "0000820318"): ("exact", "committed"),
        ("coherent", "listing", "COHR@XNYS"): ("exact", "committed"),
        ("coherent", "lei", COHERENT_LEI): ("corroborated", "pending"),
        # Soitec files nothing with the SEC: its LEI is a name-only candidate, and the
        # unsponsored-ADR CIK SEC's ticker file maps to "Soitec SA" is never proposed.
        ("soitec", "lei", SOITEC_LEI): ("candidate", "pending"),
    }

    queue = identity.mappings(review_state="pending")
    assert {m["company_slug"] for m in queue} == {"lumentum", "coherent", "soitec"}
    assert all(m["owner_confirmation"] for m in queue)
    coherent_lei = identity.mapping("coherent", "lei", COHERENT_LEI)
    assert coherent_lei["details"]["registration_status"] == "LAPSED"
    assert coherent_lei["source"] == "gleif"
    assert coherent_lei["source_url"].endswith(f"/api/v1/lei-records/{COHERENT_LEI}")
    assert coherent_lei["observed_at"]
    assert any(fact["source"] == "sec" for fact in coherent_lei["evidence"])

    companies = identity.companies()
    # LEIs stay unset until the owner confirms them.
    assert {slug: c["lei"] for slug, c in companies.items()} == {
        "lumentum": None,
        "coherent": None,
        "soitec": None,
    }
    assert companies["soitec"]["cik"] is None
    [lite] = companies["lumentum"]["securities"]
    # The configured listing gains its composite and share-class FIGIs and its segment.
    assert (lite["exchange_mic"], lite["segment_mic"], lite["valid_from"]) == (
        "XNAS",
        "XNGS",
        "2015-08-04",
    )
    assert (lite["figi"], lite["share_class_figi"]) == ("BBG0073F9RT7", "BBG0073F9RS8")
    [cohr] = companies["coherent"]["securities"]
    today = datetime.now(UTC).date().isoformat()
    # A listing no config names starts when Atlas observed it (no source gives its start).
    assert (cohr["ticker"], cohr["exchange_mic"], cohr["segment_mic"], cohr["figi"]) == (
        "COHR",
        "XNYS",
        "XNYS",
        "BBG000BLW102",
    )
    assert (cohr["currency"], cohr["instrument_type"], cohr["valid_from"]) == (
        "USD",
        "common",
        today,
    )
    assert cohr["review_state"] == "unreviewed"
    aliases = {
        (a["name"], a["kind"], a["valid_from"], a["valid_to"])
        for a in companies["coherent"]["aliases"]
    }
    assert ("II-VI INC", "former", "1995-10-04", "2022-09-01") in aliases
    assert ("COHERENT CORP.", "legal", None, None) in aliases


def test_a_rerun_changes_nothing(identity: Identity) -> None:
    identity.resolve()
    before, events = identity.mappings(), identity.audit_count()

    lines = identity.resolve()

    assert identity.mappings() == before
    assert identity.audit_count() == events
    assert all(line["committed"] == line["pending"] == 0 for line in lines.values())


def test_the_owner_confirms_a_cik_lei_link(identity: Identity) -> None:
    identity.resolve()
    lei = identity.mapping("lumentum", "lei", LUMENTUM_LEI)

    response = identity.api.post(
        f"/api/v1/identity-mappings/{lei['id']}/confirm", json={"note": "same entity"}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mapping"]["review_state"] == "confirmed"
    assert (body["mapping"]["reviewed_by"], body["mapping"]["review_note"]) == (
        "local-researcher",
        "same entity",
    )
    assert body["audit_event_id"] > 0
    lumentum = identity.companies()["lumentum"]
    assert lumentum["lei"] == LUMENTUM_LEI
    assert ("LUMENTUM HOLDINGS INC.", "legal", "gleif") in {
        (a["name"], a["kind"], a["source"]) for a in lumentum["aliases"]
    }
    # Once only: a confirmed mapping can't be reviewed again.
    again = identity.api.post(f"/api/v1/identity-mappings/{lei['id']}/confirm", json={})
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "invalid_transition"
    # A re-seed keeps the confirmed LEI and the resolved FIGI (config names neither).
    seeded = identity.cli("companies", "seed")
    assert seeded.returncode == 0, seeded.stderr
    lumentum = identity.companies()["lumentum"]
    assert lumentum["lei"] == LUMENTUM_LEI
    assert lumentum["securities"][0]["figi"] == "BBG0073F9RT7"
    with identity.engine.connect() as connection:
        actions = connection.execute(
            text("SELECT action FROM audit_event WHERE entity_id = :id ORDER BY id"),
            {"id": lei["id"]},
        ).scalars()
        assert list(actions) == ["identity_mapping.proposed", "identity_mapping.confirmed"]
        assert verify_chain(connection).ok


def test_the_owner_rejects_a_mapping_with_a_reason(identity: Identity) -> None:
    identity.resolve()
    lei = identity.mapping("soitec", "lei", SOITEC_LEI)

    missing = identity.api.post(f"/api/v1/identity-mappings/{lei['id']}/reject", json={})
    blank = identity.api.post(
        f"/api/v1/identity-mappings/{lei['id']}/reject", json={"reason": "  "}
    )
    response = identity.api.post(
        f"/api/v1/identity-mappings/{lei['id']}/reject", json={"reason": "check the registrant"}
    )

    assert (missing.status_code, blank.status_code) == (422, 422)
    assert response.status_code == 200, response.text
    rejected = response.json()["mapping"]
    assert (rejected["review_state"], rejected["review_note"]) == (
        "rejected",
        "check the registrant",
    )
    assert identity.companies()["soitec"]["lei"] is None
    # A rejection is kept, and a rerun doesn't propose it again.
    identity.resolve()
    assert identity.mapping("soitec", "lei", SOITEC_LEI)["review_state"] == "rejected"
    assert identity.mappings(review_state="rejected", company_id=rejected["company_id"]) != []


def test_unknown_mapping_is_404(identity: Identity) -> None:
    missing = "00000000-0000-0000-0000-000000000000"

    assert identity.api.get(f"/api/v1/identity-mappings/{missing}").status_code == 404
    response = identity.api.post(f"/api/v1/identity-mappings/{missing}/confirm", json={})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_committed_mappings_are_not_reviewable(identity: Identity) -> None:
    identity.resolve()
    cik = identity.mapping("coherent", "cik", "0000820318")

    response = identity.api.post(
        f"/api/v1/identity-mappings/{cik['id']}/reject", json={"reason": "no"}
    )

    assert response.status_code == 409


def test_resolve_needs_the_sec_user_agent(identity: Identity) -> None:
    result = identity.cli("companies", "resolve", user_agent=None)

    assert result.returncode == 2
    assert "ATLAS_SEC_USER_AGENT" in result.stderr


def test_resolve_one_company(identity: Identity, fake: FakeIdentitySources) -> None:
    result = identity.cli("companies", "resolve", "--company", "coherent")

    assert result.returncode == 0, result.stderr
    assert [json.loads(line)["slug"] for line in result.stdout.splitlines()] == ["coherent"]
    assert {m["company_slug"] for m in identity.mappings()} == {"coherent"}
    assert not any("CIK0001633978" in path for path in fake.paths())


def test_the_database_refuses_an_auto_committed_owner_link(identity: Identity) -> None:
    identity.resolve()
    lei = identity.mapping("lumentum", "lei", LUMENTUM_LEI)

    with pytest.raises(Exception, match="identity_mapping_owner_never_auto"):
        with identity.engine.begin() as connection:
            connection.execute(
                text("UPDATE identity_mapping SET review_state = 'committed' WHERE id = :id"),
                {"id": lei["id"]},
            )


# --- resolve_mention: the entry point for Candidates from leads ---


def test_mentions_of_universe_companies_resolve_without_network(identity: Identity) -> None:
    identity.resolve()
    ids = {slug: c["id"] for slug, c in identity.companies().items()}
    offline = FakeIdentitySources()

    with (
        identity.engine.connect() as connection,
        EntityResolver.from_settings(identity.settings(), transport=offline.transport) as resolver,
    ):
        by_name = resolve_mention(connection, resolver, Mention(name="Lumentum"))
        by_venue = resolve_mention(connection, resolver, Mention(ticker="LITE", mic="XNGS"))
        former = resolve_mention(
            connection, resolver, Mention(name="II-VI Inc", as_of=date(2021, 6, 30))
        )
        after_rename = find_in_universe(
            connection, Mention(name="II-VI Inc", as_of=date(2023, 1, 2))
        )

    assert (by_name.company_id, by_name.tier, by_name.matched_by) == (
        ids["lumentum"],
        "candidate",
        "name",
    )
    assert (by_venue.company_id, by_venue.tier) == (ids["lumentum"], "exact")
    # A former name identifies Coherent only inside its interval.
    assert (former.company_id, former.matched_by) == (ids["coherent"], "former name")
    assert after_rename is None
    assert offline.calls == []


def test_an_unseeded_company_resolves_externally(identity: Identity) -> None:
    identity.resolve()
    ids = {slug: c["id"] for slug, c in identity.companies().items()}
    fake = FakeIdentitySources()

    with (
        identity.engine.connect() as connection,
        EntityResolver.from_settings(identity.settings(), transport=fake.transport) as resolver,
    ):
        tsm = resolve_mention(connection, resolver, Mention(ticker="TSM", mic="XNYS"))
        by_isin = resolve_mention(connection, resolver, Mention(isin="US55024U1097"))

    # TSMC isn't in the universe: no company, a review-tier ADR.
    assert (tsm.company_id, tsm.tier) == (None, "candidate")
    assert tsm.entity is not None and tsm.entity.cik == "0001046179"
    # Lumentum's ISIN isn't stored, so it resolves externally, then to the universe's Lumentum.
    assert by_isin.company_id == ids["lumentum"]
    assert fake.calls
