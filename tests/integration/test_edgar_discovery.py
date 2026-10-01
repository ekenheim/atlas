"""EDGAR full-text search as a discovery channel (pilot fix 12): an investigation's Scout and
Skeptic search each query's filing phrase in SEC filings beside SearXNG; the hits become
`edgar_fts` leads (filer, form, date, CIK), ranked with the web leads; a hit from a universe
company says whether Atlas has archived the filing, and one from a filer outside the universe
proposes a Candidate keyed by its CIK, without the mention extractor. SearXNG answering
nothing (or failing) doesn't stop the investigation.

Seams: `POST /api/v1/investigations`, single worker passes, `/api/v1` (the investigation,
discoveries, leads, Candidates, jobs) and the requests the fakes received. EDGAR full-text
search is the fake over the answer recorded on 2026-09-30 (`tests/fixtures/edgar-fts/`:
`"InP substrates"` in 10-Ks: AXT, Aeluma twice, Coherent), the identity sources the fake over
`tests/fixtures/identity/` (Aeluma's submissions hand-written), SearXNG the scripted fake,
LiteLLM the scripted chat fake (every role's answer is written here), Hindsight the recorded
fake, Coherent's filings the recorded EDGAR fixtures. Nothing live is called. The universe is
the repo's (AXT and Coherent in it, Aeluma not) plus NVIDIA, which Coherent's 10-K names.
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

from tests.fakes.edgar_fts import FakeEdgarFullTextSearch, FilingReply
from tests.fakes.hindsight import RecordedHindsight
from tests.fakes.identity import FakeIdentitySources
from tests.fakes.litellm import ChatReply, FakeLiteLLM
from tests.fakes.searxng import FakeSearXNG, SearchReply
from tests.fakes.serve import Served, serve
from tests.harness import THEMES, Atlas

UA = "Atlas Research ops@example.com"
QUESTION = "Who supplies the InP substrates that AI data-center lasers are made on?"
AS_OF = "2026-09-30T00:00:00Z"
SUBSTRATE = "indium phosphide substrate capacity expansion 2026"
NOTHING = "electro-absorption modulated laser shortage 800G transceivers"
INP = '"InP substrates"'
FORMS = "10-K,10-Q,8-K,20-F,6-K,40-F"
ARCHIVE = "https://www.sec.gov/Archives/edgar/data"
AXT_10K = f"{ARCHIVE}/1051627/000143774926008612/axti20251231_10k.htm"
AELUMA_10K = f"{ARCHIVE}/1828805/000121390026100584/ea0305364-10k_aeluma.htm"
AELUMA_10K_2025 = f"{ARCHIVE}/1828805/000121390025086227/ea0256331-10k_aelumainc.htm"
COHR_10K = f"{ARCHIVE}/820318/000082031826000020/iivi-20260630.htm"
AELUMA_CIK = "0001828805"
# From the Coherent FY2026 10-K (the recorded fixture's parsed text).
SUPPLY_QUOTE = (
    "we announced the expansion of our Sherman, Texas, manufacturing facility, entered into a"
    " strategic multi-year supply agreement with NVIDIA for advanced lasers and optical"
    " networking products"
)


def canonical(url: str) -> str:
    return url.replace("https://www.", "https://")


def asked(body: dict[str, Any]) -> dict[str, Any]:
    return json.loads(body["messages"][1]["content"])


# --- fixtures -------------------------------------------------------------------------------------


@pytest.fixture
def hindsight_fake() -> RecordedHindsight:
    fake = RecordedHindsight()
    fake.derive_memories()
    return fake


class Fakes:
    def __init__(self) -> None:
        self.llm = FakeLiteLLM()
        self.searxng = FakeSearXNG()
        self.edgar = FakeEdgarFullTextSearch()
        self.identity = FakeIdentitySources()


@pytest.fixture
def fakes() -> Fakes:
    return Fakes()


@pytest.fixture
def atlas(
    database_url: str,
    tmp_path: Path,
    hindsight: tuple[RecordedHindsight, Served],
    fakes: Fakes,
) -> Iterator[Atlas]:
    universe = yaml.safe_load(THEMES.read_text(encoding="utf-8"))
    universe["companies"]["nvidia"] = {
        "legal_name": "NVIDIA Corporation",
        "display_name": "NVIDIA",
        "cik": "0001045810",
        "country": "US",
        "source_path": "sec",
    }
    themes = tmp_path / "themes.yaml"
    themes.write_text(yaml.safe_dump(universe), encoding="utf-8")
    with (
        serve(fakes.llm.handle) as llm,
        serve(fakes.searxng.handle) as searxng,
        serve(fakes.edgar.handle) as edgar,
        serve(fakes.identity.handle) as identity,
    ):
        atlas = Atlas(
            database_url,
            tmp_path,
            hindsight[1].url,
            llm.url,
            themes_config=themes,
            searxng_url=searxng.url,
            investigator_passages_per_call=50,
            sec_user_agent=UA,
            sec_efts_url=f"{edgar.url}/LATEST",
            sec_files_url=f"{identity.url}/files",
            sec_data_url=identity.url,
            gleif_url=f"{identity.url}/api/v1",
            openfigi_url=identity.url,
        )
        atlas.apply_template()
        seeded = subprocess.run(
            [sys.executable, "-m", "atlas", "companies", "seed"],
            cwd=tmp_path,
            env={
                "PATH": os.environ["PATH"],
                "HOME": str(tmp_path),
                "ATLAS_DATABASE_URL": database_url,
                "ATLAS_ACTOR": "local-researcher",
                "ATLAS_ARCHIVE_ROOT": str(atlas.archive),
                "ATLAS_THEMES_CONFIG": str(themes),
            },
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert seeded.returncode == 0, seeded.stderr
        atlas.ingest_company("coherent")
        yield atlas
        atlas.engine.dispose()
        for served in (llm, searxng, edgar, identity):
            served.raise_errors()


def start(atlas: Atlas) -> dict[str, Any]:
    coherent = atlas.company("coherent")["id"]
    response = atlas.api.post(
        "/api/v1/investigations",
        json={
            "theme": "photonics",
            "question": QUESTION,
            "seed_company_ids": [coherent],
            "as_of": AS_OF,
        },
    )
    assert response.status_code == 202, response.text
    return response.json()


def investigation(atlas: Atlas, investigation_id: str) -> dict[str, Any]:
    return atlas.get(f"/api/v1/investigations/{investigation_id}")


def tasks(found: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {task["key"]: task for task in found["tasks"]}


def leads(atlas: Atlas) -> dict[str, dict[str, Any]]:
    return {lead["canonical_url"]: lead for lead in atlas.get("/api/v1/leads", limit=500)["items"]}


SCOUT = ChatReply.json(
    {
        "queries": [
            {
                "query": SUBSTRATE,
                "purpose": "feedstock: InP substrate supply",
                "filing_phrase": "InP substrates",
            },
            {"query": NOTHING, "purpose": None, "filing_phrase": None},
        ]
    },
    tokens=(900, 120),
)
NO_CLAIMS = ChatReply.json({"claims": []}, tokens=(9000, 100))
NOTHING_ACCEPTED = ChatReply.json(
    {
        "findings": [],
        "open_questions": ["Which InP substrate suppliers do AXT's customers qualify?"],
        "verdict": "needs_review",
    },
    tokens=(2000, 150),
)


# --- the Scout ------------------------------------------------------------------------------------


def test_the_scout_s_filing_phrase_finds_filings_that_become_leads_and_candidates(
    atlas: Atlas, fakes: Fakes
) -> None:
    started = start(atlas)
    fakes.llm.script_chat(SCOUT, NO_CLAIMS, NOTHING_ACCEPTED)
    # The owner's SearXNG answers nothing usable: one query fails, the other finds nothing.
    fakes.searxng.script(SUBSTRATE, SearchReply.error(429))
    fakes.searxng.script(NOTHING, SearchReply.of("no-results"))
    fakes.edgar.script(INP, FilingReply.of("inp-substrates-10k"))

    atlas.worker_pass()

    found = investigation(atlas, started["id"])
    # SearXNG's failure didn't stop it: the plan ran to its end.
    assert (found["status"], found["stop_reason"]) == ("stopped", "no_new_independent_evidence")
    scout = tasks(found)["scout"]
    assert scout["status"] == "succeeded"
    # One EDGAR search, for the query that had a filing phrase: the phrase quoted, the six
    # forms, the 18 months before the investigation's as-of time, SEC's User-Agent.
    assert fakes.edgar.searches() == [
        {
            "q": INP,
            "forms": FORMS,
            "dateRange": "custom",
            "startdt": "2025-03-30",
            "enddt": "2026-09-30",
        }
    ]
    assert fakes.edgar.user_agents() == [UA]
    discovery = atlas.get(f"/api/v1/discoveries/{scout['artifacts']['discovery_id']}")
    substrate, nothing = discovery["queries"]
    assert (substrate["status"], substrate["filing_phrase"]) == ("failed", "InP substrates")
    edgar = substrate["edgar"]
    assert (edgar["query"], edgar["status"], edgar["forms"]) == (
        INP,
        "searched",
        FORMS.split(","),
    )
    assert (edgar["start_date"], edgar["end_date"]) == ("2025-03-30", "2026-09-30")
    assert (edgar["total_hits"], edgar["result_count"], edgar["new_leads"]) == (4, 4, 4)
    assert (nothing["status"], nothing["filing_phrase"], nothing["edgar"]) == (
        "searched",
        None,
        None,
    )
    assert scout["artifacts"]["filing_searches"] == 1

    # Each hit is a Tier C lead: filer, form and date, the filing's EDGAR URL, its CIK.
    found_leads = leads(atlas)
    assert set(found_leads) == {
        canonical(u) for u in (AXT_10K, AELUMA_10K, AELUMA_10K_2025, COHR_10K)
    }
    axt = found_leads[canonical(AXT_10K)]
    assert (axt["origin"], axt["tier"], axt["url"], axt["title"]) == (
        "edgar_fts",
        "C",
        AXT_10K,
        "AXT INC 10-K filed 2026-03-17",
    )
    assert axt["published_date"] == "2026-03-17"
    assert axt["query"] == SUBSTRATE  # the query whose filing phrase found it
    assert axt["snippet"] == (
        'EDGAR full-text search matched "InP substrates" in this 10-K of AXT INC'
        " (CIK 0001051627, period ending 2025-12-31)."
    )
    filing = axt["filing"]
    assert (filing["cik"], filing["filer"], filing["ticker"], filing["form"]) == (
        "0001051627",
        "AXT INC",
        "AXTI",
        "10-K",
    )
    assert (filing["accession"], filing["document"]) == (
        "0001437749-26-008612",
        "axti20251231_10k.htm",
    )
    # AXT is a universe company whose 10-K Atlas hasn't archived: ingestable. Coherent's 10-K
    # is archived (its Source Version named). Aeluma is outside the universe.
    assert (filing["company_id"], filing["source_version_id"], filing["ingestable"]) == (
        atlas.company("axt")["id"],
        None,
        True,
    )
    coherent = found_leads[canonical(COHR_10K)]["filing"]
    assert coherent["company_id"] == atlas.company("coherent")["id"]
    assert coherent["source_version_id"] == atlas.version(COHR_10K, "coherent")["id"]
    assert coherent["ingestable"] is False
    aeluma = found_leads[canonical(AELUMA_10K)]["filing"]
    assert (aeluma["cik"], aeluma["company_id"], aeluma["ingestable"]) == (
        AELUMA_CIK,
        None,
        False,
    )

    # Ranked with the web leads, against the query and its purpose (ranking version 3): the
    # phrase EDGAR matched is what is known of the filing. A filing isn't demoted as a
    # company's own page. All four kept, their scores and reasons recorded.
    kept = {lead["canonical_url"]: lead for lead in found["leads"]}
    assert set(kept) == set(found_leads)
    axt_kept, aeluma_kept = kept[canonical(AXT_10K)], kept[canonical(AELUMA_10K)]
    assert (axt_kept["query"], axt_kept["ranking_version"]) == (SUBSTRATE, 3)
    assert aeluma_kept["reasons"] == [
        "query terms in the snippet: substrate",
        "purpose terms: inp",
        "product and layer terms: substrate, inp",
    ]
    # 60 x 0.6 / 5 query terms + 10 / 3 purpose terms + 2 x 3: over the keep threshold (15).
    assert aeluma_kept["score"] == 16.5
    assert "names AXT" in axt_kept["reasons"]
    assert not any("own site" in r for lead in kept.values() for r in lead["reasons"])
    assert scout["artifacts"]["filing_searches_skipped"] == 0

    # The filers outside the universe are proposed by CIK, with no mention extractor call.
    propose = atlas.get(f"/api/v1/jobs/{scout['artifacts']['propose_candidates_job_id']}")
    assert (propose["kind"], propose["status"]) == ("propose_candidates", "succeeded")
    assert propose["payload"] == {
        "discovery_id": scout["artifacts"]["discovery_id"],
        "filers_only": True,
    }
    artifacts = propose["artifacts"]
    assert (artifacts["filings"], artifacts["in_universe"], artifacts["new_candidates"]) == (
        4,
        2,
        1,
    )
    assert artifacts["run_id"] is None
    # Aeluma's hits are kept ones, so it is proposed (ticket 04: a filer needs a kept hit).
    assert artifacts["filers_below_threshold"] == []
    [candidate] = atlas.get("/api/v1/candidates")["items"]
    assert candidate["identity_key"] == f"cik:{AELUMA_CIK}"
    assert (candidate["name"], candidate["cik"], candidate["source_path"]) == (
        "Aeluma, Inc.",
        AELUMA_CIK,
        "sec",
    )
    assert (candidate["theme"], candidate["state"], candidate["tier"]) == (
        "photonics",
        "lead",
        "exact",
    )
    assert sorted(lead["canonical_url"] for lead in candidate["leads"]) == sorted(
        canonical(u) for u in (AELUMA_10K, AELUMA_10K_2025)
    )
    roles = [body["metadata"]["role"] for body in fakes.llm.chat_requests()]
    assert roles == ["scout", "investigator", "editor"]


def test_when_every_search_of_both_channels_fails_the_scout_retries(
    atlas: Atlas, fakes: Fakes
) -> None:
    started = start(atlas)
    fakes.llm.script_chat(SCOUT, NO_CLAIMS, NOTHING_ACCEPTED)
    fakes.searxng.script(SUBSTRATE, SearchReply.error(503), SearchReply.of("no-results"))
    fakes.searxng.script(NOTHING, SearchReply.error(503), SearchReply.of("no-results"))
    fakes.edgar.script(INP, FilingReply.error(404), FilingReply.of("no-hits"))

    found = investigation(atlas, started["id"])
    job_id = tasks(found)["scout"]["job_id"]
    atlas.worker_pass()

    job = atlas.get(f"/api/v1/jobs/{job_id}")
    assert "every search failed (2 SearXNG queries, 1 EDGAR searches)" in json.dumps(
        job["failures"]
    )
    # The retry searched again (the Scout wasn't asked again), and EDGAR's empty answer is
    # not a failure.
    found = investigation(atlas, started["id"])
    scout = tasks(found)["scout"]
    assert scout["status"] == "succeeded", job["failures"]
    discovery = atlas.get(f"/api/v1/discoveries/{scout['artifacts']['discovery_id']}")
    assert discovery["queries"][0]["edgar"]["status"] == "searched"
    assert discovery["queries"][0]["edgar"]["total_hits"] == 0
    assert [body["metadata"]["role"] for body in fakes.llm.chat_requests()] == [
        "scout",
        "investigator",
        "editor",
    ]
    assert len(fakes.edgar.calls) == 2


# --- the Skeptic ----------------------------------------------------------------------------------


def test_the_skeptic_s_filing_phrase_searches_edgar_and_reads_an_archived_filing_it_finds(
    atlas: Atlas, fakes: Fakes
) -> None:
    started = start(atlas)
    coherent = atlas.company("coherent")["id"]
    nvidia = atlas.company("nvidia")["id"]
    ten_k = atlas.version(COHR_10K, "coherent")["id"]
    claim: dict[str, JsonValue] = {
        "subject_company_id": coherent,
        "predicate": "supplies",
        "object_company_id": nvidia,
        "object_name": None,
        "object_text": None,
        "product": "advanced lasers",
        "layer": "chip-laser",
        "quote": SUPPLY_QUOTE,
        "epistemic_type": "company_claim",
    }

    def quoting(body: dict[str, Any]) -> JsonValue:
        for passage in asked(body)["retrieved_data"]:
            if SUPPLY_QUOTE in passage["text"]:
                at_ = passage["text"].index(SUPPLY_QUOTE)
                return {
                    "claims": [
                        claim
                        | {
                            "passage_id": passage["id"],
                            "quote_start": at_,
                            "quote_end": at_ + len(SUPPLY_QUOTE),
                        }
                    ]
                }
        return {"claims": []}

    def editing(body: dict[str, Any]) -> JsonValue:
        request = asked(body)["request"]
        return {
            "findings": [
                {
                    "statement": "Coherent supplies NVIDIA with advanced lasers.",
                    "claim_ids": [c["claim_id"] for c in request["claims"]],
                    "limitations": ["A company's own statement."],
                    "open_questions": [],
                }
            ],
            "open_questions": ["Is InP substrate capacity a constraint?"],
            "verdict": "needs_review",
        }

    plan = ChatReply.json(
        {
            "queries": [
                {
                    "query": "InP substrate second source qualification",
                    "checklist_item": "second_sources",
                    "filing_phrase": '"InP substrates"',
                }
            ],
            "documents": [],
        },
        tokens=(800, 90),
    )
    fakes.llm.script_role("skeptic", plan, ChatReply.json({"counterevidence": []}))
    fakes.llm.script_role("financial_analyst", ChatReply.json({"scenarios": []}))
    fakes.llm.script_chat(
        SCOUT,
        ChatReply.answer(quoting, tokens=(9000, 700)),
        ChatReply.answer(editing, tokens=(3000, 400)),
        ChatReply.answer(
            lambda body: {
                "reviews": [
                    {
                        "item_id": item["item_id"],
                        "hedge": "none",
                        "direction": "as_proposed",
                        "layer": "correct",
                        "suggested_layer": None,
                        "reasoning": "the quote states it",
                    }
                    for item in asked(body)["request"]["items"]
                ]
            }
        ),
    )
    fakes.searxng.script(SUBSTRATE, SearchReply.of("no-results"))
    fakes.searxng.script(NOTHING, SearchReply.of("no-results"))
    fakes.searxng.script("InP substrate second source qualification", SearchReply.of("no-results"))
    fakes.edgar.script(
        INP, FilingReply.of("inp-substrates-10k"), FilingReply.of("inp-substrates-10k")
    )

    atlas.worker_pass()

    found = investigation(atlas, started["id"])
    skeptic = tasks(found)["skeptic"]
    assert skeptic["status"] == "succeeded"
    # Its query went to both channels, EDGAR in the same window as the Scout's.
    assert [s["q"] for s in fakes.edgar.searches()] == [INP, INP]
    assert fakes.edgar.searches()[1]["startdt"] == "2025-03-30"
    discovery = atlas.get(f"/api/v1/discoveries/{skeptic['artifacts']['discovery_id']}")
    [query] = discovery["queries"]
    assert (query["purpose"], query["filing_phrase"]) == (
        "skeptic: second_sources",
        '"InP substrates"',
    )
    assert (query["edgar"]["query"], query["edgar"]["status"]) == (INP, "searched")
    # The Coherent 10-K hit is an archived catalog document: the Skeptic reads it.
    assert skeptic["artifacts"]["documents_from_search"] == 1
    [reading] = [
        asked(b)
        for b in fakes.llm.chat_requests()
        if b["metadata"]["role"] == "skeptic" and asked(b)["request"].get("passages") is not None
    ]
    assert reading["retrieved_data"]
    assert all(p["source"].startswith(f"{ten_k}#") for p in reading["retrieved_data"])
