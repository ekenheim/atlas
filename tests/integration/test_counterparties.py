"""Counterparty companies (pilot-fixes ticket 05): a company outside the universe that an
accepted quote names becomes a `counterparty` company, so the edge has its other end.

Seams: the `atlas` CLI (seed, ingest, enqueue), single worker passes (`extract_claims`,
`review_relationships`, `discover` + `propose_candidates`), `/api/v1` (claims, companies,
relationships, the theme map, the Company dossier, candidates, investigations), the audit
trail and the requests the identity fake received. The Source Version is the recorded
Coherent FY2026 10-K, which names NVIDIA (a supply agreement) and Huawei (past sales).
LiteLLM is the scripted chat fake (**the Investigator's answers are written here**), the
identity sources the fake over `tests/fixtures/identity/` (hand-written: see its manifest),
Hindsight the recorded fake, SearXNG the scripted fake. Nothing live is called.

The universe here is a test theme config with Coherent only, so NVIDIA is outside it.
"""

import json
import os
import subprocess
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import JsonValue
from sqlalchemy import text

from atlas.audit import verify_chain
from tests.fakes.hindsight import RecordedHindsight
from tests.fakes.identity import FakeIdentitySources
from tests.fakes.litellm import ChatReply, FakeLiteLLM
from tests.fakes.searxng import FakeSearXNG, SearchReply
from tests.fakes.serve import Served, serve
from tests.harness import BANK, SITES, TEMPLATE, Atlas

UA = "Atlas Research ops@example.com"
COHR_10K = "https://www.sec.gov/Archives/edgar/data/820318/000082031826000020/iivi-20260630.htm"
QUESTION = "Who does Coherent supply lasers to, and who supplies Coherent?"
NVIDIA_CIK = "0001045810"  # SEC's ticker file: "NVIDIA CORP", NVDA on Nasdaq (hand-written)
HUAWEI_LEI = "5493000SYNTHETIC0327"  # the synthetic GLEIF record with the other name "Huawei"

# From the Coherent FY2026 10-K (the recorded fixture's parsed text).
SUPPLY_QUOTE = (
    "we announced the expansion of our Sherman, Texas, manufacturing facility, entered into a"
    " strategic multi-year supply agreement with NVIDIA for advanced lasers and optical"
    " networking products"
)
INVESTMENT_QUOTE = "NVIDIA made a $2 billion investment in the Company"
# Names NVIDIA and the filer, but states no sale: no language expressing `supplies`.
AGREEMENT_QUOTE = (
    "the Company entered into a multi-year strategic agreement with NVIDIA to advance the"
    " development of advanced optics technologies"
)
HUAWEI_QUOTE = "we received an inquiry from BIS concerning past product sales to Huawei"
# The stock performance graph's peer group: names companies, states no relation.
PEER_GROUP_QUOTE = (
    "The Company\N{RIGHT SINGLE QUOTATION MARK}s peer group includes IPG Photonics Corp.,"
    " Wolfspeed Inc., Lumentum Holdings, Inc., Corning, Inc., MKS Instruments, Inc., and"
    " Honeywell International, Inc."
)

SEARCH = "EML laser suppliers AI transceivers capacity"
UNIVERSE: dict[str, Any] = {
    "version": 1,
    "name": "counterparties-test",
    "companies": {
        "coherent": {
            "legal_name": "Coherent Corp.",
            "display_name": "Coherent",
            "cik": "0000820318",
            "country": "US",
            "layer": "chip-laser",
            "source_path": "sec",
        },
    },
    "themes": {
        "photonics": {
            "title": "Photonics for AI data centers",
            "description": "Lasers and optics for AI data centers.",
            "companies": ["coherent"],
        }
    },
}


# --- the harness --------------------------------------------------------------------------------


class CounterpartyAtlas(Atlas):
    """Atlas over the Coherent-only universe, with the scripted LiteLLM, the identity fake
    (unless `identity_url` is None: entity resolution not configured) and SearXNG."""

    def __init__(
        self,
        database_url: str,
        tmp_path: Path,
        hindsight_url: str,
        litellm_url: str,
        searxng_url: str,
        identity_url: str | None,
    ) -> None:
        self.themes = tmp_path / "themes.yaml"
        self.write_universe(UNIVERSE)
        identity: dict[str, Any] = {}
        if identity_url is not None:
            identity = {
                "sec_user_agent": UA,
                "sec_files_url": f"{identity_url}/files",
                "sec_data_url": identity_url,
                "gleif_url": f"{identity_url}/api/v1",
                "openfigi_url": identity_url,
            }
        super().__init__(
            database_url,
            tmp_path,
            hindsight_url,
            litellm_url,
            searxng_url=searxng_url,
            themes_config=self.themes,
            # Every passage the recall finds, in one call: the universe has no second company
            # to tag a passage with, so the question's recall chooses them.
            investigator_max_passages=2000,
            investigator_passages_per_call=2000,
            **identity,
        )

    def write_universe(self, universe: dict[str, Any]) -> None:
        self.themes.write_text(yaml.safe_dump(universe), encoding="utf-8")

    def cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        """The `atlas` CLI with this test's theme config."""
        env = {
            "PATH": os.environ["PATH"],
            "HOME": str(self.tmp_path),
            "ATLAS_DATABASE_URL": self.database_url,
            "ATLAS_ACTOR": "local-researcher",
            "ATLAS_ARCHIVE_ROOT": str(self.archive),
            "ATLAS_THEMES_CONFIG": str(self.themes),
            "ATLAS_SOURCE_SITES_CONFIG": str(SITES),
            "ATLAS_SEC_FIXTURES_DIR": str(self.fixtures),
            "ATLAS_SEC_8K_ITEMS": "*",
            "ATLAS_SEC_8K_EXHIBITS_ONLY_ITEMS": "",
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

    def companies(self, **params: Any) -> list[dict[str, Any]]:
        return self.get("/api/v1/companies", limit=100, **params)["items"]

    def ten_k(self) -> str:
        return self.version(COHR_10K, "coherent")["id"]

    def audit(self, entity_type: str) -> list[tuple[str, str]]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                text("SELECT actor, action FROM audit_event WHERE entity_type = :type ORDER BY id"),
                {"type": entity_type},
            )
            return [(row.actor, row.action) for row in rows]


@pytest.fixture
def hindsight_fake() -> RecordedHindsight:
    fake = RecordedHindsight()
    fake.derive_memories()
    return fake


@pytest.fixture
def llm() -> FakeLiteLLM:
    return FakeLiteLLM()


@pytest.fixture
def identity() -> FakeIdentitySources:
    return FakeIdentitySources()


@pytest.fixture
def searxng() -> FakeSearXNG:
    return FakeSearXNG()


@pytest.fixture
def start(
    database_url: str,
    tmp_path: Path,
    hindsight: tuple[RecordedHindsight, Served],
    llm: FakeLiteLLM,
    identity: FakeIdentitySources,
    searxng: FakeSearXNG,
) -> Iterator[Callable[..., CounterpartyAtlas]]:
    """Start Atlas with Coherent seeded and ingested; `resolution=False` leaves entity
    resolution unconfigured (no `ATLAS_SEC_USER_AGENT`)."""
    with (
        serve(llm.handle) as litellm_served,
        serve(searxng.handle) as searxng_served,
        serve(identity.handle) as identity_served,
    ):
        started: list[CounterpartyAtlas] = []

        def begin(*, resolution: bool = True) -> CounterpartyAtlas:
            atlas = CounterpartyAtlas(
                database_url,
                tmp_path,
                hindsight[1].url,
                litellm_served.url,
                searxng_served.url,
                identity_served.url if resolution else None,
            )
            started.append(atlas)
            atlas.apply_template()
            seeded = atlas.cli("companies", "seed")
            assert seeded.returncode == 0, seeded.stderr
            atlas.ingest_company("coherent")
            return atlas

        yield begin
        for atlas in started:
            atlas.engine.dispose()
        for served in (litellm_served, searxng_served, identity_served):
            served.raise_errors()


@pytest.fixture
def atlas(start: Callable[..., CounterpartyAtlas]) -> CounterpartyAtlas:
    return start()


# --- helpers ------------------------------------------------------------------------------------


def asked(body: dict[str, Any]) -> dict[str, Any]:
    """The user message of a chat request: `{"request": ..., "retrieved_data": [...]}`."""
    return json.loads(body["messages"][1]["content"])


def claim(**fields: JsonValue) -> dict[str, JsonValue]:
    return {
        "object_company_id": None,
        "object_name": None,
        "object_text": None,
        "product": None,
        "layer": "chip-laser",
        "epistemic_type": "company_claim",
        **fields,
    }


def quoting(*claims: dict[str, JsonValue]) -> Callable[[dict[str, Any]], JsonValue]:
    """An Investigator answer quoting the passages it is sent (the passage holding each
    quote, and the quote's offsets in it)."""

    def respond(body: dict[str, Any]) -> JsonValue:
        passages = asked(body)["retrieved_data"]
        answered: list[JsonValue] = []
        for each in claims:
            quote = str(each["quote"])
            holding = [p for p in passages if quote in p["text"]]
            assert holding, f"no passage sent holds {quote!r}"
            start = holding[0]["text"].index(quote)
            answered.append(
                each
                | {
                    "passage_id": holding[0]["id"],
                    "quote_start": start,
                    "quote_end": start + len(quote),
                }
            )
        return {"claims": answered}

    return respond


def extract(
    atlas: CounterpartyAtlas, llm: FakeLiteLLM, key: str, *claims: dict[str, JsonValue]
) -> list[dict[str, Any]]:
    """Script the Investigator, run an `extract_claims` job over the 10-K; its Claims."""
    llm.script_chat(ChatReply.answer(quoting(*claims)))
    payload = json.dumps({"source_version_ids": [atlas.ten_k()], "question": QUESTION})
    job_id = atlas.enqueue("jobs", "enqueue", "extract_claims", "--key", key, "--payload", payload)
    atlas.worker_pass()
    job = atlas.get(f"/api/v1/jobs/{job_id}")
    assert job["status"] == "succeeded", job["failures"]
    found = atlas.get("/api/v1/claims", extraction_id=job["artifacts"]["extraction_id"], limit=500)
    return found["items"]


def supply_to(atlas: CounterpartyAtlas, name: str | None = "NVIDIA", **fields: JsonValue):
    return claim(
        subject_company_id=atlas.company("coherent")["id"],
        predicate="supplies",
        object_name=name,
        product="advanced lasers",
        quote=SUPPLY_QUOTE,
        **fields,
    )


def with_nvidia(atlas: CounterpartyAtlas, llm: FakeLiteLLM) -> dict[str, Any]:
    """The supply agreement's Claim accepted: NVIDIA is a counterparty. Returns the company."""
    (accepted,) = extract(atlas, llm, "cohr-10k", supply_to(atlas))
    assert accepted["outcome"] == "accepted", accepted
    return atlas.company("nvidia")


def reviewing(body: dict[str, Any]) -> JsonValue:
    """A Reviewer answer confirming every item it is sent."""
    return {
        "reviews": [
            {
                "item_id": item["item_id"],
                "verdict": "confirmed",
                "direction": "as_proposed",
                "layer": "correct",
                "suggested_layer": None,
                "reasoning": "the quote states the supply agreement",
            }
            for item in asked(body)["request"]["items"]
        ]
    }


# --- the gate -----------------------------------------------------------------------------------


def test_gate_a_named_company_outside_the_universe_becomes_a_counterparty_and_the_claim_an_edge(
    atlas: CounterpartyAtlas, llm: FakeLiteLLM, identity: FakeIdentitySources
) -> None:
    coherent = atlas.company("coherent")
    assert [c["slug"] for c in atlas.companies()] == ["coherent"]

    (accepted,) = extract(atlas, llm, "cohr-10k", supply_to(atlas))

    # The Investigator was told it may name a company outside the list (prompt v4).
    [body] = llm.chat_requests()
    assert [c["company_id"] for c in asked(body)["request"]["companies"]] == [coherent["id"]]
    assert "`object_name`" in body["messages"][0]["content"]
    # The name resolved to exactly one SEC registrant: a counterparty, not a researched company.
    nvidia = atlas.company("nvidia")
    assert nvidia["role"] == "counterparty" and coherent["role"] == "researched"
    assert (nvidia["legal_name"], nvidia["display_name"]) == ("NVIDIA CORP", "NVIDIA")
    assert (nvidia["cik"], nvidia["lei"], nvidia["country"]) == (NVIDIA_CIK, None, "US")
    assert (nvidia["source_path"], nvidia["layer"], nvidia["securities"]) == (None, None, [])
    origin = nvidia["counterparty"]
    assert (origin["named_as"], origin["source"]) == ("NVIDIA", "sec")
    assert origin["source_url"].endswith(f"/submissions/CIK{NVIDIA_CIK}.json")
    assert coherent["counterparty"] is None
    assert [c["slug"] for c in atlas.companies(role="counterparty")] == ["nvidia"]
    assert [c["slug"] for c in atlas.companies(role="researched")] == ["coherent"]
    # Deterministic: SEC's ticker file and submissions, GLEIF by name; no listing lookup.
    paths = identity.paths()
    assert any(path.endswith("/company_tickers_exchange.json") for path in paths)
    assert any(path.endswith(f"/submissions/CIK{NVIDIA_CIK}.json") for path in paths)
    assert identity.openfigi_batches == []

    # The Claim is an Assertion with a company object, at the quote's exact span.
    assert (accepted["outcome"], accepted["reason_code"]) == ("accepted", None)
    assert accepted["object_company_id"] == nvidia["id"]
    assert accepted["proposed"]["object_name"] == "NVIDIA"
    assert accepted["proposed"]["object_company_id"] is None
    assertion = atlas.get(f"/api/v1/assertions/{accepted['assertion_id']}")
    assert (assertion["subject_company_id"], assertion["predicate"]) == (
        coherent["id"],
        "supplies",
    )
    assert assertion["object_company_id"] == nvidia["id"]
    assert assertion["extractor_version"] == "investigator.v5"
    parsed = atlas.parsed(atlas.ten_k())
    assert parsed[assertion["span_start"] : assertion["span_end"]] == SUPPLY_QUOTE
    # Audited, in the Claim's transaction, by the Investigator.
    assert atlas.audit("company") == [
        ("local-researcher", "company.created"),
        ("atlas-investigator", "company.counterparty_created"),
    ]
    with atlas.engine.connect() as connection:
        assert verify_chain(connection).ok
        assert connection.execute(text("SELECT count(*) FROM universe_company")).scalar_one() == 0

    # The edge has both ends: on the edge table, the theme map and both dossiers.
    llm.script_chat(ChatReply.answer(reviewing))
    review_id = atlas.enqueue(
        "jobs", "enqueue", "review_relationships", "--key", "sweep", "--payload", "{}"
    )
    atlas.worker_pass()
    review = atlas.get(f"/api/v1/jobs/{review_id}")
    assert review["status"] == "succeeded", review["failures"]
    (edge,) = atlas.get("/api/v1/relationships")["items"]
    assert (edge["subject_name"], edge["predicate"], edge["object_name"]) == (
        "Coherent",
        "supplies",
        "NVIDIA",
    )
    assert edge["object_company_id"] == nvidia["id"]
    assert edge["review_state"] == "machine_reviewed"
    assert atlas.get("/api/v1/relationships", company_id=nvidia["id"])["total"] == 1

    theme = atlas.get("/api/v1/themes/photonics/map")
    assert [e["id"] for e in theme["relationships"]] == [edge["id"]]
    assert theme["theme"]["relationship_count"] == 1
    # A counterparty is on the map as an edge's end, never as a theme company.
    members = [c["slug"] for layer in theme["layers"] for c in layer["companies"]]
    assert members + [c["slug"] for c in theme["unlayered"]] == ["coherent"]
    assert theme["theme"]["company_count"] == 1
    (listed,) = theme["counterparties"]
    assert (listed["id"], listed["slug"], listed["display_name"]) == (
        nvidia["id"],
        "nvidia",
        "NVIDIA",
    )
    assert (listed["cik"], listed["lei"], listed["relationship_count"]) == (NVIDIA_CIK, None, 1)

    dossier = atlas.get(f"/api/v1/companies/{nvidia['id']}/dossier")
    assert dossier["company"]["role"] == "counterparty"
    assert [e["id"] for e in dossier["relationships_in"]] == [edge["id"]]
    assert (dossier["relationships_out"], dossier["themes"], dossier["sources"]) == ([], [], [])
    out = atlas.get(f"/api/v1/companies/{coherent['id']}/dossier")["relationships_out"]
    assert [e["id"] for e in out] == [edge["id"]]


def test_a_later_claim_reuses_the_counterparty(
    atlas: CounterpartyAtlas, llm: FakeLiteLLM, identity: FakeIdentitySources
) -> None:
    nvidia = with_nvidia(atlas, llm)
    coherent = atlas.company("coherent")
    calls = len(identity.calls)

    by_name, by_id = extract(
        atlas,
        llm,
        "cohr-10k-again",
        supply_to(atlas),
        claim(
            subject_company_id=nvidia["id"],
            predicate="owns",
            object_company_id=coherent["id"],
            layer="system",
            quote=INVESTMENT_QUOTE,
            epistemic_type="direct_source_statement",
        ),
    )

    # The counterparty is a known company now: listed for the Investigator by its ID and
    # names, found by name without asking SEC or GLEIF again, and usable as a subject.
    second = asked(llm.chat_requests()[-1])["request"]
    names = {c["company_id"]: c["names"] for c in second["companies"]}
    assert "NVIDIA" in names[nvidia["id"]]
    assert len(identity.calls) == calls
    assert (by_name["outcome"], by_name["object_company_id"]) == ("accepted", nvidia["id"])
    assert (by_id["outcome"], by_id["subject_company_id"]) == ("accepted", nvidia["id"])
    assert [c["slug"] for c in atlas.companies()] == ["coherent", "nvidia"]
    assert [action for _, action in atlas.audit("company")].count(
        "company.counterparty_created"
    ) == 1


# --- names that make no counterparty --------------------------------------------------------------


def test_only_a_name_one_registry_entity_answers_to_and_a_quote_that_passes_makes_a_counterparty(
    atlas: CounterpartyAtlas, llm: FakeLiteLLM
) -> None:
    coherent = atlas.company("coherent")["id"]
    peers = claim(subject_company_id=coherent, predicate="competes_with", quote=PEER_GROUP_QUOTE)

    huawei, unresolved, ambiguous, unnamed, co_mention, no_object = extract(
        atlas,
        llm,
        "cohr-10k",
        # One GLEIF record answers to "Huawei" and SEC's ticker file has none: a counterparty.
        claim(
            subject_company_id=coherent,
            predicate="supplies",
            object_name="Huawei",
            quote=HUAWEI_QUOTE,
        ),
        # No source has an entity of this name.
        peers | {"object_name": "IPG Photonics Corp."},
        # Two GLEIF records answer to "Corning".
        peers | {"object_name": "Corning"},
        # The quote must contain the name: nothing is looked up for a name it doesn't.
        peers | {"object_name": "NVIDIA"},
        # NVIDIA resolves, but the quote states no sale: no Assertion, so no company either.
        supply_to(atlas) | {"quote": AGREEMENT_QUOTE},
        supply_to(atlas, None),
    )

    assert (huawei["outcome"], huawei["reason_code"]) == ("accepted", None)
    company = atlas.company("huawei")
    assert huawei["object_company_id"] == company["id"]
    assert company["role"] == "counterparty"
    assert (company["legal_name"], company["display_name"]) == (
        "Huawei Technologies Co., Ltd.",
        "Huawei",
    )
    assert (company["cik"], company["lei"], company["country"]) == (None, HUAWEI_LEI, "CN")
    assert company["counterparty"]["source"] == "gleif"
    assert company["counterparty"]["source_url"].endswith(f"/lei-records/{HUAWEI_LEI}")

    rejected = [unresolved, ambiguous, unnamed, co_mention, no_object]
    assert [c["reason_code"] for c in rejected] == [
        "unresolved_company",
        "ambiguous_company",
        "party_not_in_quote",
        "no_directional_language",
        "missing_object",
    ]
    assert all(c["outcome"] == "rejected" and c["assertion_id"] is None for c in rejected)
    assert all(c["object_company_id"] is None for c in rejected)
    assert "IPG Photonics Corp." in unresolved["reason"]
    assert "Corning" in ambiguous["reason"] and "2" in ambiguous["reason"]
    assert "NVIDIA" in unnamed["reason"]
    assert "object_name" in no_object["reason"]
    # Only the accepted Claim's company exists.
    assert [c["slug"] for c in atlas.companies()] == ["coherent", "huawei"]


def test_without_entity_resolution_a_named_company_is_unresolved_and_never_created(
    start: Callable[..., CounterpartyAtlas], llm: FakeLiteLLM, identity: FakeIdentitySources
) -> None:
    atlas = start(resolution=False)

    (rejected,) = extract(atlas, llm, "cohr-10k", supply_to(atlas))

    assert (rejected["outcome"], rejected["reason_code"]) == ("rejected", "unresolved_company")
    assert "ATLAS_SEC_USER_AGENT" in rejected["reason"]
    assert rejected["object_company_id"] is None
    assert [c["slug"] for c in atlas.companies()] == ["coherent"]
    assert identity.calls == []
    assert atlas.get("/api/v1/assertions")["total"] == 0


# --- not researched -------------------------------------------------------------------------------


def test_a_counterparty_is_never_ingested_and_never_an_investigation_seed(
    atlas: CounterpartyAtlas, llm: FakeLiteLLM
) -> None:
    nvidia = with_nvidia(atlas, llm)

    refused = atlas.cli("ingest", "--company", "nvidia")
    assert refused.returncode == 2
    assert "counterparty" in refused.stderr
    # A job enqueued by hand fails the same way and fetches nothing.
    payload = json.dumps({"company": "nvidia"})
    job_id = atlas.enqueue(
        "jobs", "enqueue", "ingest", "--key", "nvda", "--payload", payload, "--max-attempts", "1"
    )
    atlas.worker_pass()
    job = atlas.get(f"/api/v1/jobs/{job_id}")
    assert job["status"] == "failed"
    assert "counterparty" in job["failures"][-1]["error"]
    assert atlas.get(f"/api/v1/companies/{nvidia['id']}/sources")["total"] == 0

    seeded = atlas.api.post(
        "/api/v1/investigations",
        json={
            "theme": "photonics",
            "question": "Who supplies NVIDIA?",
            "seed_company_ids": [nvidia["id"]],
        },
    )
    assert seeded.status_code == 422, seeded.text
    assert "counterparty" in seeded.json()["error"]["message"]
    assert atlas.get("/api/v1/investigations")["total"] == 0


# --- promotion ------------------------------------------------------------------------------------


def test_adding_a_counterparty_to_the_theme_config_makes_it_a_researched_company(
    atlas: CounterpartyAtlas, llm: FakeLiteLLM
) -> None:
    nvidia = with_nvidia(atlas, llm)
    companies = UNIVERSE["companies"] | {
        "nvidia": {
            "legal_name": "NVIDIA Corporation",
            "display_name": "NVIDIA",
            "cik": NVIDIA_CIK,
            "country": "US",
            "layer": "system",
            "source_path": "sec",
        }
    }
    atlas.write_universe(UNIVERSE | {"companies": companies})

    seeded = atlas.cli("companies", "seed")

    assert seeded.returncode == 0, seeded.stderr
    researched = atlas.company("nvidia")
    assert researched["id"] == nvidia["id"]  # the same company: its Assertions stay
    assert (researched["role"], researched["source_path"], researched["layer"]) == (
        "researched",
        "sec",
        "system",
    )
    assert researched["legal_name"] == "NVIDIA Corporation"
    assert researched["counterparty"]["named_as"] == "NVIDIA"  # how it came to be known
    assert atlas.audit("company")[-1] == ("local-researcher", "company.updated")
    assert atlas.get("/api/v1/assertions")["items"][0]["object_company_id"] == nvidia["id"]
    # It can be ingested now.
    enqueued = atlas.cli("ingest", "--company", "nvidia")
    assert enqueued.returncode == 0, enqueued.stderr


def test_a_lead_naming_a_counterparty_proposes_a_candidate_and_its_commit_promotes_the_company(
    atlas: CounterpartyAtlas, llm: FakeLiteLLM, searxng: FakeSearXNG
) -> None:
    nvidia = with_nvidia(atlas, llm)

    def mentions(body: dict[str, Any]) -> JsonValue:
        """The mention extractor's answer: the first lead names NVIDIA, the rest no company."""
        leads = asked(body)["retrieved_data"]
        named: list[JsonValue] = [{"name": "NVIDIA", "ticker": None, "exchange": None}]
        return {
            "leads": [
                {"lead": lead["id"], "companies": named if position == 0 else []}
                for position, lead in enumerate(leads)
            ]
        }

    llm.script_chat(
        ChatReply.json({"queries": [{"query": SEARCH, "purpose": "EML suppliers"}]}),
        ChatReply.answer(mentions),
    )
    searxng.script(SEARCH, SearchReply.of("unseeded-companies"))
    payload = json.dumps({"theme": "photonics", "question": "Who buys EML lasers?"})
    discover_id = atlas.enqueue(
        "jobs", "enqueue", "discover", "--key", "leads", "--payload", payload
    )
    atlas.worker_pass()
    discover = atlas.get(f"/api/v1/jobs/{discover_id}")
    assert discover["status"] == "succeeded", discover["failures"]
    propose = atlas.get(f"/api/v1/jobs/{discover['artifacts']['propose_candidates_job_id']}")
    assert propose["status"] == "succeeded", propose["failures"]

    # A counterparty is not in the universe: the lead's mention proposes a Candidate.
    assert (propose["artifacts"]["in_universe"], propose["artifacts"]["new_candidates"]) == (0, 1)
    (candidate,) = atlas.get("/api/v1/candidates")["items"]
    assert (candidate["state"], candidate["company_id"]) == ("lead", None)

    committed = atlas.api.post(
        f"/api/v1/candidates/{candidate['id']}/commit",
        json={"cik": NVIDIA_CIK, "country": "US", "layer": "system"},
    )

    assert committed.status_code == 200, committed.text
    decided = committed.json()["candidate"]
    assert (decided["state"], decided["company_id"]) == ("investigating", nvidia["id"])
    promoted = atlas.company("nvidia")  # the counterparty's row, promoted in place
    assert promoted["id"] == nvidia["id"]
    assert (promoted["role"], promoted["source_path"], promoted["layer"]) == (
        "researched",
        "sec",
        "system",
    )
    assert [c["slug"] for c in atlas.companies()] == ["coherent", "nvidia"]
    assert ("local-researcher", "company.promoted") in atlas.audit("company")
    ingest = atlas.get(f"/api/v1/jobs/{decided['ingest_job_id']}")
    assert (ingest["kind"], ingest["payload"]["company"]) == ("ingest", "nvidia")
    theme = atlas.get("/api/v1/themes/photonics/map")
    assert "nvidia" in [c["slug"] for c in theme["layers"][-1]["companies"]]  # system
    assert theme["counterparties"] == []
    with atlas.engine.connect() as connection:
        assert verify_chain(connection).ok
