"""Candidates: a lead naming a company outside the universe proposes a Candidate after entity
resolution; the owner commits it (the company joins the universe in the database and its
ingest is enqueued) or rejects it with a reason, and Candidates are never deleted (spec
"Discovery", §8.3; stories 13-15, 54; ticket 09).

Seams: the `atlas` CLI (seed, enqueue `discover`), single worker passes (`discover`, then the
`propose_candidates` job it enqueues, then a committed Candidate's `ingest` and retains),
`/api/v1` (candidates, leads, companies, jobs, role calls, `/metrics`) and the requests the
fakes received. LiteLLM is the scripted chat fake (the Scout's and the mention extractor's
answers are written here), SearXNG the scripted fake over `tests/fixtures/searxng/`, the
identity sources the fake over `tests/fixtures/identity/` (plus the recorded EDGAR
submissions), and Hindsight the recorded fake. Nothing live is called.

The universe here is a test theme config without Lumentum and Soitec, so the two are
unseeded companies; Coherent is seeded.
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
from pydantic import JsonValue
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from atlas.audit import verify_chain
from tests.fakes.edgar_fts import FakeEdgarFullTextSearch, FilingReply
from tests.fakes.hindsight import RecordedHindsight
from tests.fakes.identity import FakeIdentitySources
from tests.fakes.litellm import ChatReply, FakeLiteLLM
from tests.fakes.searxng import FakeSearXNG, SearchReply
from tests.fakes.serve import Served, serve
from tests.harness import BANK, REPO, SITES, TEMPLATE, Atlas

UA = "Atlas Research ops@example.com"
QUERY = "EML laser suppliers AI transceivers capacity"
QUESTION = "Who can supply EML lasers for 1.6T transceivers?"
PROMPT = (REPO / "backend" / "atlas" / "roles" / "prompts" / "mention_extractor.v1.md").read_text(
    encoding="utf-8"
)

LUMENTUM_URL = "https://photonics-news.test/2026/09/lumentum-ramps-200g-eml-lasers"
SOITEC_URL = "https://optics-trade.test/articles/soitec-photonics-soi-demand"
BLOG_URL = "https://blog.photonics.test/who-makes-eml-lasers"
EXPLAINER_URL = "https://photonics-news.test/2026/08/eml-shortage-explained"
LUMENTUM_CIK = "0001633978"  # SEC's ticker file: LITE on Nasdaq (tests/fixtures/identity)
SOITEC_LEI = "969500ZR92SQCU9TST26"  # GLEIF full text for "Soitec SA"
SOITEC = "SOITEC"  # that record's legal name
SOITEC_ADR_CIK = "0001445214"  # an unsponsored-ADR shell (F-6EF only): never proposed
# The queries of the EDGAR full-text search tests, each with the filing phrase the Scout gives.
INP_QUERY = "InP substrate suppliers for EML laser capacity"
INP_SCOUT_QUERY: JsonValue = {
    "query": INP_QUERY,
    "purpose": "feedstock: InP substrate supply",
    "filing_phrase": "InP substrates",
}
VCSEL_QUERY = "VCSEL array suppliers for short-reach AI data center links"
SHORTAGE_QUERY = "EML laser chip shortage lead times"

# What the mention extractor names in each lead (by the lead's URL; written here).
MENTIONS: dict[str, list[dict[str, Any]]] = {
    LUMENTUM_URL: [{"name": "Lumentum Holdings Inc.", "ticker": "LITE", "exchange": "Nasdaq"}],
    SOITEC_URL: [
        {"name": "Soitec SA", "ticker": None, "exchange": None},
        {"name": "Coherent Corp.", "ticker": None, "exchange": None},
    ],
    BLOG_URL: [
        {"name": "Lumentum Holdings Inc.", "ticker": "LITE", "exchange": "Nasdaq"},
        {"name": "Acme Photonics", "ticker": None, "exchange": None},
    ],
    EXPLAINER_URL: [],
}

THEMES = {
    "version": 1,
    "name": "candidates-test",
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


def mentions(body: dict[str, Any]) -> dict[str, Any]:
    """The extractor's answer to a request: each lead's companies, found by its URL."""
    sent = json.loads(body["messages"][1]["content"])
    return {
        "leads": [
            {"lead": item["id"], "companies": MENTIONS[item["source"]]}
            for item in sent["retrieved_data"]
        ]
    }


class CandidatesAtlas(Atlas):
    def __init__(
        self,
        database_url: str,
        tmp_path: Path,
        hindsight: str,
        litellm: FakeLiteLLM,
        litellm_url: str,
        searxng: FakeSearXNG,
        searxng_url: str,
        identity: FakeIdentitySources,
        identity_url: str,
        edgar: FakeEdgarFullTextSearch,
        edgar_url: str,
    ) -> None:
        self.litellm = litellm
        self.searxng = searxng
        self.identity = identity
        self.edgar = edgar
        self.themes = tmp_path / "themes.yaml"
        self.themes.write_text(yaml.safe_dump(THEMES), encoding="utf-8")
        super().__init__(
            database_url,
            tmp_path,
            hindsight,
            litellm_url,
            searxng_url=searxng_url,
            themes_config=self.themes,
            sec_user_agent=UA,
            sec_files_url=f"{identity_url}/files",
            sec_data_url=identity_url,
            gleif_url=f"{identity_url}/api/v1",
            openfigi_url=identity_url,
            sec_efts_url=f"{edgar_url}/LATEST",
        )

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

    def discover(self, key: str) -> dict[str, Any]:
        """Script the Scout, the search and the extractor; enqueue `discover`; one worker pass
        (which runs `propose_candidates` too); the discover job."""
        self.litellm.script_chat(
            ChatReply.json({"queries": [{"query": QUERY, "purpose": "EML suppliers"}]}),
            ChatReply.answer(mentions, tokens=(700, 90)),
        )
        self.searxng.script(QUERY, SearchReply.of("unseeded-companies"))
        payload = json.dumps({"theme": "photonics", "question": QUESTION})
        job_id = self.enqueue("jobs", "enqueue", "discover", "--key", key, "--payload", payload)
        self.worker_pass()
        job = self.get(f"/api/v1/jobs/{job_id}")
        assert job["status"] == "succeeded", job["failures"]
        return job

    def candidates(self, **params: Any) -> list[dict[str, Any]]:
        return self.get("/api/v1/candidates", limit=100, **params)["items"]

    def candidate(self, name: str) -> dict[str, Any]:
        (found,) = [c for c in self.candidates() if c["name"] == name]
        return found

    def post(self, path: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        response = self.api.post(path, json=body)
        return response.status_code, response.json()


@pytest.fixture
def atlas(
    database_url: str, tmp_path: Path, hindsight: tuple[RecordedHindsight, Served]
) -> Iterator[CandidatesAtlas]:
    litellm, searxng, identity = FakeLiteLLM(), FakeSearXNG(), FakeIdentitySources()
    edgar = FakeEdgarFullTextSearch()
    with (
        serve(litellm.handle) as litellm_served,
        serve(searxng.handle) as searxng_served,
        serve(identity.handle) as identity_served,
        serve(edgar.handle) as edgar_served,
    ):
        atlas = CandidatesAtlas(
            database_url,
            tmp_path,
            hindsight[1].url,
            litellm,
            litellm_served.url,
            searxng,
            searxng_served.url,
            identity,
            identity_served.url,
            edgar,
            edgar_served.url,
        )
        atlas.apply_template()
        seeded = atlas.cli("companies", "seed")
        assert seeded.returncode == 0, seeded.stderr
        yield atlas
        atlas.engine.dispose()
        for served in (litellm_served, searxng_served, identity_served, edgar_served):
            served.raise_errors()


@pytest.fixture
def discovered(atlas: CandidatesAtlas) -> CandidatesAtlas:
    atlas.discover("photonics-1")
    return atlas


# --- proposing ---------------------------------------------------------------------------------


def test_gate_an_unseeded_company_discovered_from_a_searxng_fixture_becomes_a_candidate(
    atlas: CandidatesAtlas,
) -> None:
    discover = atlas.discover("photonics-1")

    # The discovery enqueued the proposal for its leads; the same worker pass ran it.
    propose = atlas.get(f"/api/v1/jobs/{discover['artifacts']['propose_candidates_job_id']}")
    assert propose["kind"] == "propose_candidates"
    assert propose["status"] == "succeeded", propose["failures"]
    assert propose["payload"] == {"discovery_id": discover["artifacts"]["discovery_id"]}
    artifacts = propose["artifacts"]
    assert (artifacts["leads"], artifacts["mentions"]) == (4, 5)
    assert (artifacts["in_universe"], artifacts["unresolved"], artifacts["new_candidates"]) == (
        1,
        1,
        2,
    )

    lumentum = atlas.candidate("Lumentum Holdings Inc.")
    assert lumentum["theme"] == "photonics"
    assert lumentum["state"] == "lead"
    assert lumentum["identity_key"] == f"cik:{LUMENTUM_CIK}"
    assert (lumentum["cik"], lumentum["lei"], lumentum["country"]) == (LUMENTUM_CIK, None, "US")
    assert lumentum["source_path"] == "sec"
    assert lumentum["resolution"]["entity"]["cik"] == LUMENTUM_CIK
    assert lumentum["resolution"]["company_id"] is None
    assert lumentum["tier"] == lumentum["resolution"]["tier"]
    # Two leads named it: one Candidate, linked to both, with how each named it.
    assert sorted(lead["canonical_url"] for lead in lumentum["leads"]) == [BLOG_URL, LUMENTUM_URL]
    for lead in lumentum["leads"]:
        assert (lead["mentioned_as"], lead["ticker"], lead["exchange"], lead["mic"]) == (
            "Lumentum Holdings Inc.",
            "LITE",
            "Nasdaq",
            "XNAS",
        )
    assert lumentum["company_id"] is None and lumentum["ingest_job_id"] is None

    soitec = atlas.candidate(SOITEC)
    assert soitec["identity_key"] == f"lei:{SOITEC_LEI}"
    assert (soitec["cik"], soitec["lei"], soitec["country"]) == (None, SOITEC_LEI, "FR")
    assert soitec["source_path"] is None  # no CIK: no automated source yet
    assert soitec["tier"] == "candidate"  # name only
    assert SOITEC_ADR_CIK not in json.dumps(soitec["resolution"]["proposals"])
    assert [lead["canonical_url"] for lead in soitec["leads"]] == [SOITEC_URL]

    # Coherent is in the universe and Acme Photonics identifies nothing: no Candidates.
    assert sorted(c["name"] for c in atlas.candidates()) == ["Lumentum Holdings Inc.", SOITEC]
    # Nothing is committed automatically: no company, no universe row, no ingest job.
    slugs = {company["slug"] for company in atlas.get("/api/v1/companies")["items"]}
    assert slugs == {"coherent"}
    with atlas.engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM universe_company")).scalar_one() == 0
        ingests = connection.execute(text("SELECT count(*) FROM job WHERE kind = 'ingest'"))
        assert ingests.scalar_one() == 0


def test_the_mention_extractor_reads_the_leads_as_quoted_data_in_its_own_run(
    discovered: CandidatesAtlas,
) -> None:
    scout, extractor = discovered.litellm.chat_requests()
    assert scout["metadata"]["role"] == "scout"
    assert extractor["response_format"]["json_schema"]["name"] == "mention_extractor"
    assert extractor["response_format"]["json_schema"]["strict"] is True
    # The prompt, then the answer format (the role's schema; MiniMax ignores response_format).
    system = extractor["messages"][0]["content"]
    prompt_end = system.index(PROMPT) + len(PROMPT)
    assert system[prompt_end:].lstrip().startswith("## Answer format")
    sent = json.loads(extractor["messages"][1]["content"])
    assert sent["request"] == {
        "theme_id": "photonics",
        "theme_title": "Photonics for AI data centers",
        "lead_ids": ["lead-1", "lead-2", "lead-3", "lead-4"],
    }
    by_url = {item["source"]: item for item in sent["retrieved_data"]}
    assert set(by_url) == set(MENTIONS)
    assert by_url[LUMENTUM_URL]["text"] == (
        "Lumentum Holdings Inc. ramps 200G EML laser output\n\nLumentum (Nasdaq: LITE) said it"
        " is adding indium phosphide laser capacity for 1.6T transceivers."
    )
    assert all(item["trust"] == "low" for item in sent["retrieved_data"])
    # The extractor's call is its own run's, recorded with its tokens.
    run_id = extractor["metadata"]["run_id"]
    assert run_id != scout["metadata"]["run_id"]
    calls = discovered.get(f"/api/v1/runs/{run_id}/role-calls")
    assert (calls["tokens_in"], calls["tokens_out"]) == (700, 90)
    [call] = calls["role_calls"]
    assert (call["role"], call["status"]) == ("mention_extractor", "accepted")


def test_a_lead_is_examined_once(discovered: CandidatesAtlas) -> None:
    # A second discovery returns the same leads: nothing is read or proposed again.
    discovered.litellm.script_chat(ChatReply.json({"queries": [{"query": QUERY, "purpose": None}]}))
    discovered.searxng.script(QUERY, SearchReply.of("unseeded-companies"))
    payload = json.dumps({"theme": "photonics", "question": QUESTION})
    job_id = discovered.enqueue(
        "jobs", "enqueue", "discover", "--key", "photonics-2", "--payload", payload
    )
    discovered.worker_pass()

    job = discovered.get(f"/api/v1/jobs/{job_id}")
    propose = discovered.get(f"/api/v1/jobs/{job['artifacts']['propose_candidates_job_id']}")
    assert propose["status"] == "succeeded", propose["failures"]
    assert (propose["artifacts"]["leads"], propose["artifacts"]["run_id"]) == (0, None)
    assert len(discovered.litellm.chat_requests()) == 3  # two Scouts, one extractor
    assert len(discovered.candidates()) == 2


def test_a_filing_hit_proposes_its_filer_by_cik_without_the_mention_extractor(
    atlas: CandidatesAtlas,
) -> None:
    # Pilot fix 12: the Scout's filing phrase finds Aeluma's and Coherent's 10-Ks in EDGAR.
    atlas.litellm.script_chat(
        ChatReply.json({"queries": [INP_SCOUT_QUERY]}),
        ChatReply.answer(mentions, tokens=(700, 90)),
    )
    atlas.searxng.script(INP_QUERY, SearchReply.of("unseeded-companies"))
    atlas.edgar.script('"InP substrates"', FilingReply.of("inp-substrates-aeluma-coherent"))
    payload = json.dumps({"theme": "photonics", "question": QUESTION})
    job_id = atlas.enqueue("jobs", "enqueue", "discover", "--key", "edgar-1", "--payload", payload)
    atlas.worker_pass()

    job = atlas.get(f"/api/v1/jobs/{job_id}")
    assert job["status"] == "succeeded", job["failures"]
    propose = atlas.get(f"/api/v1/jobs/{job['artifacts']['propose_candidates_job_id']}")
    assert propose["status"] == "succeeded", propose["failures"]
    artifacts = propose["artifacts"]
    # Six leads examined: the two filings by CIK, the four web leads by the extractor.
    assert (artifacts["leads"], artifacts["filings"]) == (6, 2)
    extractor = atlas.litellm.chat_requests()[1]
    sent = json.loads(extractor["messages"][1]["content"])
    assert {item["source"] for item in sent["retrieved_data"]} == set(MENTIONS)
    aeluma = atlas.candidate("Aeluma, Inc.")
    assert (aeluma["identity_key"], aeluma["cik"], aeluma["source_path"]) == (
        "cik:0001828805",
        "0001828805",
        "sec",
    )
    [lead] = aeluma["leads"]
    assert lead["canonical_url"] == (
        "https://sec.gov/Archives/edgar/data/1828805/000121390026100584/ea0305364-10k_aeluma.htm"
    )
    assert (lead["mentioned_as"], lead["ticker"]) == ("Aeluma, Inc.", "ALMU")
    # Coherent filed the other: a universe company, no Candidate.
    assert "COHERENT CORP." not in {c["name"] for c in atlas.candidates()}
    assert artifacts["filers_below_threshold"] == []


def test_gate_only_a_specific_filing_phrase_is_searched_and_only_a_kept_hit_proposes_its_filer(
    atlas: CandidatesAtlas,
) -> None:
    # Memory-directed reading, ticket 04. Three queries: a specific phrase, a bare product
    # term (searched, but its hits fall under the ranking's keep threshold) and one word that
    # is no product or layer term (not searched: the EDGAR fake has no answer for it).
    atlas.litellm.script_chat(
        ChatReply.json(
            {
                "queries": [
                    INP_SCOUT_QUERY,
                    {
                        "query": VCSEL_QUERY,
                        "purpose": "components: VCSEL sources",
                        "filing_phrase": "VCSEL",
                    },
                    {
                        "query": SHORTAGE_QUERY,
                        "purpose": "components: EML chip shortage",
                        "filing_phrase": "shortage",
                    },
                ]
            }
        )
    )
    for query in (INP_QUERY, VCSEL_QUERY, SHORTAGE_QUERY):
        atlas.searxng.script(query, SearchReply.of("no-results"))
    atlas.edgar.script('"InP substrates"', FilingReply.of("inp-substrates-aeluma-coherent"))
    atlas.edgar.script('"VCSEL"', FilingReply.of("vcsel-lidar"))
    payload = json.dumps({"theme": "photonics", "question": QUESTION})
    job_id = atlas.enqueue("jobs", "enqueue", "discover", "--key", "edgar-2", "--payload", payload)
    atlas.worker_pass()

    job = atlas.get(f"/api/v1/jobs/{job_id}")
    assert job["status"] == "succeeded", job["failures"]
    # Two searches were sent; the one-word phrase's is recorded as skipped, with the reason.
    assert [search["q"] for search in atlas.edgar.searches()] == ['"InP substrates"', '"VCSEL"']
    assert (job["artifacts"]["filing_searches"], job["artifacts"]["filing_searches_skipped"]) == (
        2,
        1,
    )
    discovery = atlas.get(f"/api/v1/discoveries/{job['artifacts']['discovery_id']}")
    assert [query["edgar"]["status"] for query in discovery["queries"]] == [
        "searched",
        "searched",
        "skipped",
    ]
    skipped = discovery["queries"][2]
    assert (skipped["status"], skipped["filing_phrase"]) == ("searched", "shortage")
    assert skipped["edgar"]["query"] == '"shortage"'
    assert skipped["edgar"]["skip_reason"] == (
        "no phrase of at least two words and no product or layer term of the lead-ranking"
        ' config: "shortage"'
    )
    assert (skipped["edgar"]["total_hits"], skipped["edgar"]["searched_at"]) == (None, None)
    assert discovery["queries"][0]["edgar"]["skip_reason"] is None

    # All four hits are leads (Tier C); only the filer with a kept hit is a Candidate.
    leads = atlas.get("/api/v1/leads", limit=50)["items"]
    assert sorted(lead["filing"]["filer"] for lead in leads) == [
        "Aeluma, Inc.",
        "COHERENT CORP.",
        "Hesai Group",
        "Ouster, Inc.",
    ]
    propose = atlas.get(f"/api/v1/jobs/{job['artifacts']['propose_candidates_job_id']}")
    assert propose["status"] == "succeeded", propose["failures"]
    artifacts = propose["artifacts"]
    assert [c["name"] for c in atlas.candidates()] == ["Aeluma, Inc."]
    assert (artifacts["filings"], artifacts["in_universe"], artifacts["new_candidates"]) == (
        2,
        1,
        1,
    )
    # The lidar makers' only hits are of the bare term: under the threshold, so they are
    # not proposed, and no registry was asked about them.
    below = {filer["filer"]: filer for filer in artifacts["filers_below_threshold"]}
    assert set(below) == {"Hesai Group", "Ouster, Inc."}
    hesai = below["Hesai Group"]
    assert (hesai["cik"], hesai["leads"], hesai["query"]) == ("0009990001", 1, VCSEL_QUERY)
    assert hesai["score"] < hesai["min_score"] == 15
    assert 'matched only the vocabulary term "vcsel" (x0.25)' in hesai["reasons"]
    assert not any("999000" in path for path in atlas.identity.paths())
    with atlas.engine.connect() as connection:
        examined = connection.execute(
            text(
                "SELECT f.filer FROM lead_examination e JOIN edgar_filing f"
                " ON f.lead_id = e.lead_id ORDER BY f.filer"
            )
        ).scalars()
        assert list(examined) == ["Aeluma, Inc.", "COHERENT CORP."]


# --- the owner's decisions ------------------------------------------------------------------------


def test_commit_adds_the_company_to_the_universe_and_enqueues_its_sec_ingest(
    discovered: CandidatesAtlas, fake: RecordedHindsight
) -> None:
    lumentum = discovered.candidate("Lumentum Holdings Inc.")

    status, body = discovered.post(
        f"/api/v1/candidates/{lumentum['id']}/commit",
        {"slug": "lumentum", "display_name": "Lumentum", "layer": "chip-laser", "note": "EMLs"},
    )

    assert status == 200, body
    committed = body["candidate"]
    assert committed["state"] == "investigating"
    assert (committed["decided_by"], committed["decision_note"]) == ("local-researcher", "EMLs")
    assert committed["ingest_note"] is None
    company = discovered.company("lumentum")
    assert committed["company_id"] == company["id"]
    assert (company["cik"], company["country"], company["source_path"]) == (
        LUMENTUM_CIK,
        "US",
        "sec",
    )
    assert (company["legal_name"], company["display_name"], company["layer"]) == (
        "Lumentum Holdings Inc.",
        "Lumentum",
        "chip-laser",
    )
    ingest = discovered.get(f"/api/v1/jobs/{committed['ingest_job_id']}")
    assert (ingest["kind"], ingest["status"], ingest["payload"]["company"]) == (
        "ingest",
        "queued",
        "lumentum",
    )
    assert "since" in ingest["payload"]  # the default lookback, like `atlas ingest`
    with discovered.engine.connect() as connection:
        event = connection.execute(
            text("SELECT actor, action, entity_id FROM audit_event WHERE id = :id"),
            {"id": body["audit_event_id"]},
        ).one()
        assert tuple(event) == ("local-researcher", "candidate.committed", lumentum["id"])
        assert verify_chain(connection).ok

    # The worker ingests it from its source path (the EDGAR fixtures) and retains it tagged
    # with the Candidate's theme: the company is in the universe.
    discovered.worker_pass()
    ingest = discovered.get(f"/api/v1/jobs/{committed['ingest_job_id']}")
    assert ingest["status"] == "succeeded", ingest["failures"]
    assert ingest["artifacts"]["company_id"] == company["id"]
    assert ingest["artifacts"]["counts"]["new_version"] > 0
    tags = {str(tag) for batch in fake.retained() for item in batch for tag in item["tags"]}
    assert {f"company:{company['id']}", "theme:photonics"} <= tags
    # A committed company resolves as a universe company from now on.
    assert discovered.get("/api/v1/candidates", state="investigating")["total"] == 1


def test_commit_without_a_cik_records_that_no_automated_source_exists(
    discovered: CandidatesAtlas,
) -> None:
    soitec = discovered.candidate(SOITEC)

    status, body = discovered.post(f"/api/v1/candidates/{soitec['id']}/commit", {})

    assert status == 200, body
    committed = body["candidate"]
    assert committed["state"] == "investigating"
    assert committed["ingest_job_id"] is None
    assert "no automated source exists yet" in committed["ingest_note"]
    company = discovered.company("soitec")  # the default slug, from the name
    assert (company["cik"], company["lei"], company["country"], company["source_path"]) == (
        None,
        SOITEC_LEI,
        "FR",
        None,
    )
    with discovered.engine.connect() as connection:
        assert (
            connection.execute(text("SELECT count(*) FROM job WHERE kind = 'ingest'")).scalar_one()
            == 0
        )


def test_reject_keeps_the_candidate_with_its_reason(discovered: CandidatesAtlas) -> None:
    soitec = discovered.candidate(SOITEC)

    status, body = discovered.post(
        f"/api/v1/candidates/{soitec['id']}/reject", {"reason": "  a substrate peer, not a lead "}
    )

    assert status == 200, body
    rejected = body["candidate"]
    assert (rejected["state"], rejected["reject_reason"]) == (
        "rejected",
        "a substrate peer, not a lead",
    )
    assert rejected["decided_by"] == "local-researcher"
    assert rejected["company_id"] is None
    assert [c["id"] for c in discovered.candidates(state="rejected")] == [soitec["id"]]
    assert discovered.get(f"/api/v1/candidates/{soitec['id']}")["leads"] == soitec["leads"]
    # A decided Candidate isn't decided again.
    for action, request in [("reject", {"reason": "again"}), ("commit", {})]:
        status, body = discovered.post(f"/api/v1/candidates/{soitec['id']}/{action}", request)
        assert (status, body["error"]["code"]) == (409, "invalid_transition")
    # Candidates are never deleted, rejected ones included.
    with pytest.raises(DBAPIError, match="never removed"):
        with discovered.engine.begin() as connection:
            connection.execute(text("DELETE FROM candidate WHERE id = :id"), {"id": soitec["id"]})
    assert len(discovered.candidates()) == 2


def test_refused_commits_and_rejects(discovered: CandidatesAtlas) -> None:
    lumentum = discovered.candidate("Lumentum Holdings Inc.")
    commit = f"/api/v1/candidates/{lumentum['id']}/commit"

    status, body = discovered.post(commit, {"slug": "coherent"})
    assert (status, body["error"]["code"]) == (409, "slug_taken")
    status, body = discovered.post(commit, {"cik": "0000000001"})
    assert (status, body["error"]["code"]) == (409, "cik_not_offered")
    status, body = discovered.post(commit, {"slug": "Not A Slug"})
    assert (status, body["error"]["code"]) == (422, "invalid_request")
    status, body = discovered.post(f"/api/v1/candidates/{lumentum['id']}/reject", {"reason": " "})
    assert (status, body["error"]["code"]) == (422, "invalid_request")
    unknown = "00000000-0000-4000-8000-000000000000"
    status, body = discovered.post(f"/api/v1/candidates/{unknown}/reject", {"reason": "x"})
    assert (status, body["error"]["code"]) == (404, "not_found")
    assert discovered.api.get(f"/api/v1/candidates/{unknown}").status_code == 404
    # Nothing changed.
    assert discovered.get(f"/api/v1/candidates/{lumentum['id']}")["state"] == "lead"


def test_metrics_count_candidates_by_state(discovered: CandidatesAtlas) -> None:
    lumentum = discovered.candidate("Lumentum Holdings Inc.")
    soitec = discovered.candidate(SOITEC)
    discovered.post(f"/api/v1/candidates/{lumentum['id']}/commit", {"slug": "lumentum"})
    discovered.post(f"/api/v1/candidates/{soitec['id']}/reject", {"reason": "not now"})

    metrics = discovered.metrics()

    expected = {
        "lead": 0,
        "investigating": 1,
        "evidence_ready": 0,
        "needs_more_evidence": 0,
        "paper_tracking": 0,
        "rejected": 1,
        "closed": 0,
    }
    for state, count in expected.items():
        assert metrics[("atlas_candidates", frozenset({("state", state)}))] == count
