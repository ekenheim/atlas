"""Recall and reflect with resolved citations: the Phase 2 gate at the API + worker seam.

Seam: the `atlas` CLI applies the template and enqueues ingests, single worker passes run
the ingest, retain, poll and reflect jobs, and everything is observed through `/api/v1` (plus
the audit trail and the requests Hindsight received). Hindsight is the recorded fake served
on localhost with `derive_memories` on (tests/fakes/hindsight.py): the recordings hold
synthetic documents, so the memories of real sections, strict-tag recalls over them, deleted
memories and reflect answers citing them are derived from recorded responses with only their
identity and content fields changed. **Reflect answer texts are written here**, so each quote
in them is chosen to match, or not match, the recorded Lumentum and Coherent EDGAR fixtures.
LiteLLM is the `/model/info` fake, so each reflect records a run; no LLM is called.
"""

import json
import os
import subprocess
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from atlas.api.app import create_app
from atlas.db.migrate import upgrade
from atlas.hindsight import HindsightGateway, RetainItem
from atlas.jobs import JobQueue, Worker, builtin_registry
from atlas.settings import Settings
from tests.fakes.hindsight import ChunkContent, RecordedHindsight
from tests.fakes.litellm import API_KEY, FakeLiteLLM
from tests.fakes.serve import Served, serve

REPO = Path(__file__).parents[2]
THEMES = REPO / "configs" / "themes" / "ai-infrastructure.yaml"
TEMPLATE = REPO / "configs" / "hindsight" / "bank-template.json"
EDGAR_FIXTURES = REPO / "tests" / "fixtures" / "edgar"
# The bank the template recordings were made in, so `apply-template` replays as recorded.
BANK = RecordedHindsight().recording("research_template/01-import-dry-run").bank_id

LITE_10K = "https://www.sec.gov/Archives/edgar/data/1633978/000162828026057358/lite-20260627.htm"
LITE_10Q = "https://www.sec.gov/Archives/edgar/data/1633978/000162828026030777/lite-20260328.htm"
COHR_10K = "https://www.sec.gov/Archives/edgar/data/820318/000082031826000020/iivi-20260630.htm"
ITEM_1 = "part-i-item-1"

# From the Lumentum FY2026 10-K's Item 1 (the recorded fixture's parsed text): a passage with
# a typographic apostrophe, and one that runs across a line break.
LITE_APOSTROPHE = (
    "Components represent foundational parts that support or enable that system\u2019s operation"
)
LITE_LINE_BREAK = "consolidated financial statements.\nWe disaggregate revenue by type of product"
# From the Coherent FY2026 10-K's Item 1.
COHR_PASSAGE = "is a vertically integrated manufacturing company"


class Atlas:
    def __init__(self, database_url: str, tmp_path: Path, hindsight: str, litellm: str | None):
        self.database_url = database_url
        self.tmp_path = tmp_path
        self.archive = tmp_path / "archive"
        self.archive.mkdir(exist_ok=True)
        self.hindsight_url = hindsight
        self.litellm_url = litellm
        self.engine = create_engine(database_url)
        self.api = TestClient(create_app(self.settings()))

    def settings(self) -> Settings:
        providers: dict[str, Any] = {}
        if self.litellm_url is not None:
            providers = {"litellm_url": self.litellm_url, "litellm_api_key": API_KEY}
        return Settings.model_validate(
            {
                "database_url": self.database_url,
                "actor": "local-researcher",
                "archive_root": self.archive,
                "themes_config": THEMES,
                "sec_fixtures_dir": EDGAR_FIXTURES,
                "hindsight_url": self.hindsight_url,
                "hindsight_bank_id": BANK,
                "retain_poll_timeout_seconds": 0.3,
                "retain_poll_interval_seconds": 0.01,
                **providers,
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
            "ATLAS_SEC_FIXTURES_DIR": str(EDGAR_FIXTURES),
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

    def worker_pass(self) -> int:
        return Worker(JobQueue(self.engine), builtin_registry(self.settings())).run_once()

    def ingest(self, company: str) -> None:
        enqueued = self.cli("ingest", "--company", company, "--key", company)
        assert enqueued.returncode == 0, enqueued.stderr
        self.worker_pass()
        job = self.get(f"/api/v1/jobs/{json.loads(enqueued.stdout)['id']}")
        assert job["status"] == "succeeded", job["failures"]

    def get(self, path: str, **params: Any) -> Any:
        response = self.api.get(path, params=params)
        assert response.status_code == 200, response.text
        return response.json()

    def company(self, slug: str) -> dict[str, Any]:
        companies = self.get("/api/v1/companies")["items"]
        return next(company for company in companies if company["slug"] == slug)

    def version(self, url: str, company: str) -> dict[str, Any]:
        documents = self.get(f"/api/v1/companies/{self.company(company)['id']}/sources", limit=100)
        document = next(d for d in documents["items"] if d["canonical_url"] == url)
        (version,) = self.get(f"/api/v1/sources/{document['id']}/versions")["items"]
        return self.get(f"/api/v1/source-versions/{version['id']}")

    def section(self, url: str, company: str, anchor: str = ITEM_1) -> dict[str, Any]:
        """The section's memory document, with its Source Version."""
        version = self.version(url, company)
        memory = self.get(f"/api/v1/source-versions/{version['id']}/memory")
        document = next(d for d in memory["documents"] if d["section_anchor"] == anchor)
        return document | {"version": version}

    def parsed(self, version_id: str) -> str:
        response = self.api.get(
            f"/api/v1/source-versions/{version_id}/content", params={"kind": "parsed"}
        )
        assert response.status_code == 200, response.text
        return response.text

    def recall(self, query: str, **scope: Any) -> Any:
        response = self.api.post("/api/v1/memory/recall", json={"query": query, "scope": scope})
        assert response.status_code == 200, response.text
        return response.json()

    def ask(self, question: str, **body: Any) -> dict[str, Any]:
        """POST a reflect question; returns the accepted response."""
        scope = body.pop("scope", {"theme_ids": ["photonics"]})
        response = self.api.post(
            "/api/v1/memory/reflect", json={"question": question, "scope": scope, **body}
        )
        assert response.status_code == 202, response.text
        return response.json()

    def reflect(self, question: str, **body: Any) -> dict[str, Any]:
        """Ask, run the worker, and return the stored answer."""
        accepted = self.ask(question, **body)
        self.worker_pass()
        return self.get(f"/api/v1/memory/reflect/{accepted['research_answer']['id']}")


@pytest.fixture
def database_url(empty_database_url: str) -> str:
    upgrade(empty_database_url)
    return empty_database_url


@pytest.fixture
def hindsight() -> Iterator[tuple[RecordedHindsight, Served]]:
    fake = RecordedHindsight()
    fake.derive_memories()
    with serve(fake.transport.handle_request) as served:
        yield fake, served
        served.raise_errors()


@pytest.fixture
def fake(hindsight: tuple[RecordedHindsight, Served]) -> RecordedHindsight:
    return hindsight[0]


@pytest.fixture
def litellm() -> Iterator[Served]:
    with serve(FakeLiteLLM().handle) as served:
        yield served
        served.raise_errors()


@pytest.fixture
def atlas(
    database_url: str,
    tmp_path: Path,
    hindsight: tuple[RecordedHindsight, Served],
    litellm: Served,
) -> Iterator[Atlas]:
    harness = Atlas(database_url, tmp_path, hindsight[1].url, litellm.url)
    applied = harness.cli("hindsight", "apply-template")
    assert applied.returncode == 0, applied.stderr
    harness.ingest("lumentum")
    yield harness
    harness.engine.dispose()


def by_kind(answer: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    return [c for c in answer["citations"] if c["kind"] == kind]


def quoted(answer: dict[str, Any], quote: str) -> dict[str, Any]:
    (citation,) = [c for c in by_kind(answer, "quote") if c["text"] == quote]
    return citation


def assert_source(source: dict[str, Any], section: dict[str, Any], company: dict[str, Any]):
    """The citation source is exactly this section of this Source Version."""
    version = section["version"]
    assert source["document_id"] == section["document_id"]
    assert source["source_version_id"] == version["id"]
    assert source["source_document_id"] == version["source_document"]["id"]
    assert source["company_id"] == company["id"]
    assert source["section_anchor"] == section["section_anchor"]
    assert source["section_char_start"] == section["char_start"]
    assert source["section_char_end"] == section["char_end"]
    assert source["available_at"] == version["available_at"]
    assert source["available_at_basis"] == "sec_acceptance"


# --- recall -------------------------------------------------------------------------------


def test_cross_company_recall_returns_memories_from_both_companies_with_resolved_provenance(
    atlas: Atlas, fake: RecordedHindsight
) -> None:
    atlas.ingest("coherent")
    lumentum, coherent = atlas.company("lumentum"), atlas.company("coherent")

    recalled = atlas.recall(
        "optical component capacity", company_ids=[lumentum["id"], coherent["id"]]
    )

    (sent,) = fake.requests("POST", "memories/recall")
    assert sent["tags"] == [f"company:{lumentum['id']}", f"company:{coherent['id']}"]
    assert sent["tags_match"] == "any_strict"
    assert recalled["scope"]["tags_match"] == "any_strict"
    memories = recalled["memories"]
    companies = {m["provenance"]["sources"][0]["company_id"] for m in memories}
    assert companies == {lumentum["id"], coherent["id"]}
    assert all(m["provenance"]["state"] == "resolved" for m in memories)
    assert recalled["counts"] == {"resolved": len(memories), "unverified": 0, "broken": 0}
    for url, company in [(LITE_10K, lumentum), (COHR_10K, coherent)]:
        section = atlas.section(url, company["slug"])
        (memory,) = [
            m
            for m in memories
            if m["provenance"]["sources"][0]["document_id"] == section["document_id"]
        ]
        assert memory["memory_id"] == fake.derived_fact(section["document_id"])
        assert memory["type"] == "world"
        (source,) = memory["provenance"]["sources"]
        assert_source(source, section, company)
        (evidence,) = [
            e
            for e in recalled["evidence"]
            if (e["source_version_id"], e["section_anchor"]) == (section["version"]["id"], ITEM_1)
        ]
        assert evidence["memory_ids"] == [memory["memory_id"]]


def test_recall_is_strictly_scoped_to_the_requested_company_or_theme(
    atlas: Atlas, fake: RecordedHindsight
) -> None:
    atlas.ingest("coherent")
    lumentum, coherent = atlas.company("lumentum"), atlas.company("coherent")

    only_coherent = atlas.recall("lasers", company_ids=[coherent["id"]])
    by_theme = atlas.recall("lasers", theme_ids=["photonics"])

    assert only_coherent["memories"]
    assert {m["provenance"]["sources"][0]["company_id"] for m in only_coherent["memories"]} == {
        coherent["id"]
    }
    assert all(f"company:{coherent['id']}" in m["tags"] for m in only_coherent["memories"])
    assert {m["provenance"]["sources"][0]["company_id"] for m in by_theme["memories"]} == {
        lumentum["id"],
        coherent["id"],
    }
    assert [(r["tags"], r["tags_match"]) for r in fake.requests("POST", "memories/recall")] == [
        ([f"company:{coherent['id']}"], "any_strict"),
        (["theme:photonics"], "any_strict"),
    ]


def test_recall_refuses_an_unknown_or_empty_scope_before_calling_hindsight(
    atlas: Atlas, fake: RecordedHindsight
) -> None:
    unknown_company = atlas.api.post(
        "/api/v1/memory/recall",
        json={"query": "q", "scope": {"company_ids": ["00000000-0000-4000-8000-000000000000"]}},
    )
    unknown_theme = atlas.api.post(
        "/api/v1/memory/recall", json={"query": "q", "scope": {"theme_ids": ["semis"]}}
    )
    empty = atlas.api.post("/api/v1/memory/recall", json={"query": "q", "scope": {}})

    assert (unknown_company.status_code, unknown_company.json()["error"]["code"]) == (
        422,
        "unknown_company",
    )
    assert (unknown_theme.status_code, unknown_theme.json()["error"]["code"]) == (
        422,
        "unknown_theme",
    )
    assert (empty.status_code, empty.json()["error"]["code"]) == (422, "invalid_request")
    assert fake.requests("POST", "memories/recall") == []


def test_recalled_observations_resolve_through_their_source_memories(
    atlas: Atlas, fake: RecordedHindsight
) -> None:
    atlas.ingest("coherent")
    lite = atlas.section(LITE_10K, "lumentum")
    cohr = atlas.section(COHR_10K, "coherent")
    observation_id = fake.derive_observation([lite["document_id"], cohr["document_id"]])

    recalled = atlas.recall("who makes lasers", theme_ids=["photonics"])

    (observation,) = [m for m in recalled["memories"] if m["type"] == "observation"]
    assert observation["memory_id"] == observation_id
    provenance = observation["provenance"]
    assert provenance["state"] == "resolved"
    lite_source, cohr_source = provenance["sources"]
    assert lite_source["memory_id"] == fake.derived_fact(lite["document_id"])
    assert cohr_source["memory_id"] == fake.derived_fact(cohr["document_id"])
    assert_source(lite_source, lite, atlas.company("lumentum"))
    assert_source(cohr_source, cohr, atlas.company("coherent"))
    # Resolved by looking the observation up (its source IDs), then each source fact.
    looked_up = [
        r.url.path.rsplit("/", 1)[1]
        for r in fake.calls
        if r.method == "GET" and "/memories/" in r.url.path
    ]
    assert looked_up[:3] == [observation_id, lite_source["memory_id"], cohr_source["memory_id"]]


def test_an_observation_whose_source_memory_was_deleted_is_broken(
    atlas: Atlas, fake: RecordedHindsight
) -> None:
    ten_k = atlas.section(LITE_10K, "lumentum")
    ten_q = atlas.section(LITE_10Q, "lumentum", anchor="cover")
    observation_id = fake.derive_observation([ten_k["document_id"], ten_q["document_id"]])
    deleted = fake.derived_fact(ten_q["document_id"])
    fake.forget(deleted)

    recalled = atlas.recall("capacity", company_ids=[atlas.company("lumentum")["id"]])

    assert deleted not in [m["memory_id"] for m in recalled["memories"]]
    (observation,) = [m for m in recalled["memories"] if m["memory_id"] == observation_id]
    assert observation["provenance"]["state"] == "broken"
    assert observation["provenance"]["reason"] == "source_memory_not_found"
    assert observation["provenance"]["missing_memory_ids"] == [deleted]
    assert observation["provenance"]["sources"] == []
    assert recalled["counts"]["broken"] == 1
    assert all(observation_id not in e["memory_ids"] for e in recalled["evidence"])


# --- reflect ------------------------------------------------------------------------------


def test_reflect_runs_as_a_job_and_the_api_returns_the_stored_answer(
    atlas: Atlas, fake: RecordedHindsight
) -> None:
    section = atlas.section(LITE_10K, "lumentum")
    fact = fake.derived_fact(section["document_id"])
    answer_text = f'Lumentum says "{LITE_APOSTROPHE.replace(chr(0x2019), chr(39))}".'
    fake.script_reflect(answer_text, [fact])

    accepted = atlas.ask("What are Lumentum's components?", scope={"theme_ids": ["photonics"]})
    pending = accepted["research_answer"]

    assert pending["status"] == "pending"
    assert pending["answer"] is None and pending["citations"] is None
    assert pending["job_id"] == accepted["job_id"]
    assert atlas.get(f"/api/v1/jobs/{accepted['job_id']}")["kind"] == "reflect"
    assert atlas.get(f"/api/v1/memory/reflect/{pending['id']}")["status"] == "pending"
    assert fake.requests("POST", "reflect") == []  # nothing asked until the job runs

    atlas.worker_pass()
    answer = atlas.get(f"/api/v1/memory/reflect/{pending['id']}")

    (sent,) = fake.requests("POST", "reflect")
    assert sent == {
        "query": "What are Lumentum's components?",
        "tags": ["theme:photonics"],
        "tags_match": "any_strict",
        "include": {"facts": {}},
    }
    assert answer["status"] == "completed"
    assert answer["job_status"] == "succeeded"
    assert answer["question"] == "What are Lumentum's components?"
    assert answer["answer"] == answer_text
    assert answer["scope"] == {
        "company_ids": [],
        "theme_ids": ["photonics"],
        "tags": ["theme:photonics"],
        "tags_match": "any_strict",
    }
    assert [(c["id"], c["type"]) for c in answer["raw_citations"]] == [(fact, "world")]
    memory, quote = answer["citations"]
    assert (memory["kind"], memory["state"], memory["memory_id"]) == ("memory", "resolved", fact)
    assert_source(memory["sources"][0], section, atlas.company("lumentum"))
    assert (quote["kind"], quote["state"]) == ("quote", "resolved")
    assert answer["counts"] == {"resolved": 2, "unverified": 0, "broken": 0}
    assert answer["evidence_missing"] is False
    assert answer["quote_rule"] == "whitespace-and-typographic-quotes-v1"
    assert answer["structured_output"] is None and answer["structured_output_error"] is None
    job = atlas.get(f"/api/v1/jobs/{accepted['job_id']}")
    assert answer["run_id"] is not None
    assert job["artifacts"]["run_id"] == answer["run_id"]

    with atlas.engine.connect() as connection:
        events = connection.execute(
            text(
                "SELECT id, action FROM audit_event WHERE entity_type = 'research_answer'"
                " AND entity_id = :id ORDER BY id"
            ),
            {"id": pending["id"]},
        ).all()
        run = connection.execute(
            text("SELECT kind, finished_at FROM run WHERE id = :id"), {"id": answer["run_id"]}
        ).one()
    assert [action for _, action in events] == [
        "research_answer.requested",
        "research_answer.answered",
    ]
    assert events[0][0] == accepted["audit_event_id"]
    assert run.kind == "reflect" and run.finished_at is not None
    verified = atlas.cli("audit", "verify")
    assert verified.returncode == 0, verified.stdout + verified.stderr


def test_quotes_are_validated_against_the_archived_text_and_a_paraphrase_is_unverified(
    atlas: Atlas, fake: RecordedHindsight
) -> None:
    section = atlas.section(LITE_10K, "lumentum")
    parsed = atlas.parsed(section["version"]["id"])
    straight = LITE_APOSTROPHE.replace("\u2019", "'")
    one_line = LITE_LINE_BREAK.replace("\n", " ")
    paraphrase = "Components are the foundational parts that enable a system's operation"
    lowercased = "components represent foundational parts"
    # Verbatim in the same 10-K, but in Item 1A: not in the section the citation leads to.
    elsewhere = "Investing in our common stock involves a high degree of risk"
    fake.script_reflect(
        f'Lumentum: "{straight}". It adds \u201c{one_line}\u201d.'
        f' In short, "{paraphrase}"; also "{lowercased}"; and "{elsewhere}".',
        [fake.derived_fact(section["document_id"])],
    )

    answer = atlas.reflect("How does Lumentum describe Components?")

    # Typographic quotes and whitespace are the only differences forgiven.
    for quote, archived in [(straight, LITE_APOSTROPHE), (one_line, LITE_LINE_BREAK)]:
        citation = quoted(answer, quote)
        assert citation["state"] == "resolved"
        span = citation["quote"]
        assert span["archived_text"] == archived
        assert parsed[span["char_start"] : span["char_end"]] == archived
        assert span["source_version_id"] == section["version"]["id"]
        assert section["char_start"] <= span["char_start"] < span["char_end"] <= section["char_end"]
        assert_source(citation["sources"][0], section, atlas.company("lumentum"))
    for quote in (paraphrase, lowercased, elsewhere):
        citation = quoted(answer, quote)
        assert (citation["state"], citation["reason"]) == ("unverified", "quote_mismatch")
        assert citation["quote"] is None and citation["sources"] == []
    (evidence,) = answer["evidence"]
    assert [q["quoted"] for q in evidence["quotes"]] == [straight, one_line]
    assert elsewhere in parsed
    assert answer["counts"] == {"resolved": 3, "unverified": 3, "broken": 0}


def test_a_chunk_only_answer_is_unverified(atlas: Atlas, fake: RecordedHindsight) -> None:
    section = atlas.section(LITE_10K, "lumentum")
    straight = LITE_APOSTROPHE.replace("\u2019", "'")
    fake.script_reflect(f'The filing says "{straight}".', [ChunkContent(section["document_id"])])

    answer = atlas.reflect("What is a Components product?")

    (chunk,) = by_kind(answer, "chunk")
    assert (chunk["state"], chunk["reason"]) == ("unverified", "no_memory_id")
    assert chunk["memory_id"] is None
    assert chunk["text"].startswith("PART I ITEM 1. BUSINESS General Overview Lumentum")
    assert chunk["sources"] == []
    # Verbatim, but nothing resolved leads to a section to check it against.
    (quote,) = by_kind(answer, "quote")
    assert (quote["state"], quote["reason"]) == ("unverified", "quote_mismatch")
    assert [c["id"] for c in answer["raw_citations"]] == [None]
    assert answer["evidence"] == []
    assert answer["evidence_missing"] is True
    assert answer["counts"] == {"resolved": 0, "unverified": 2, "broken": 0}


def test_an_answer_citing_a_deleted_memory_is_broken_and_not_evidence(
    atlas: Atlas, fake: RecordedHindsight
) -> None:
    atlas.ingest("coherent")
    lite = atlas.section(LITE_10K, "lumentum")
    cohr = atlas.section(COHR_10K, "coherent")
    deleted = fake.derived_fact(lite["document_id"])
    kept = fake.derived_fact(cohr["document_id"])
    fake.script_reflect(f'Coherent "{COHR_PASSAGE}".', [deleted, kept])
    fake.forget(deleted)

    answer = atlas.reflect("Who integrates vertically?")

    gone, resolved, quote = answer["citations"]
    assert (gone["memory_id"], gone["state"], gone["reason"]) == (
        deleted,
        "broken",
        "memory_not_found",
    )
    assert gone["missing_memory_ids"] == [deleted] and gone["sources"] == []
    assert (resolved["memory_id"], resolved["state"]) == (kept, "resolved")
    assert (quote["state"], quote["memory_id"]) == ("resolved", kept)
    (evidence,) = answer["evidence"]
    assert (evidence["source_version_id"], evidence["section_anchor"]) == (
        cohr["version"]["id"],
        ITEM_1,
    )
    assert deleted not in evidence["memory_ids"]
    assert answer["counts"] == {"resolved": 2, "unverified": 0, "broken": 1}


def test_memories_the_ledger_does_not_back_are_unverified(
    atlas: Atlas, hindsight: tuple[RecordedHindsight, Served]
) -> None:
    fake, served = hindsight
    section = atlas.section(LITE_10K, "lumentum")
    other_version = atlas.version(LITE_10Q, "lumentum")["id"]
    stranger = "srcv:00000000-0000-4000-8000-000000000000:cover"
    at = datetime(2026, 8, 1, tzinfo=UTC)
    # Retained around Atlas: a section ID the ledger never recorded, and a real section ID
    # re-retained (Hindsight's destructive upsert) with metadata naming another version.
    with HindsightGateway(served.url, BANK) as outside:
        outside.retain_batch(
            [
                RetainItem(content="Unknown.", document_id=stranger, timestamp=at),
                RetainItem(
                    content="Tampered.",
                    document_id=section["document_id"],
                    timestamp=at,
                    metadata={"source_version_id": other_version, "section_anchor": ITEM_1},
                ),
            ]
        )
    fake.script_reflect(
        "Unbacked.", [fake.derived_fact(stranger), fake.derived_fact(section["document_id"])]
    )

    answer = atlas.reflect("Anything unbacked?")

    unknown, mismatch = answer["citations"]
    assert (unknown["state"], unknown["reason"]) == ("unverified", "unknown_document")
    assert (mismatch["state"], mismatch["reason"]) == ("unverified", "metadata_mismatch")
    assert answer["evidence"] == [] and answer["evidence_missing"] is True


def test_a_cited_observation_resolves_through_its_source_facts(
    atlas: Atlas, fake: RecordedHindsight
) -> None:
    atlas.ingest("coherent")
    lite = atlas.section(LITE_10K, "lumentum")
    cohr = atlas.section(COHR_10K, "coherent")
    observation_id = fake.derive_observation([lite["document_id"], cohr["document_id"]])
    fake.script_reflect(
        f'Both make optics; Coherent "{COHR_PASSAGE}".', [observation_id], structured_output=None
    )

    answer = atlas.reflect("Compare Lumentum and Coherent", scope={"theme_ids": ["photonics"]})

    observation, quote = answer["citations"]
    assert (observation["memory_type"], observation["state"]) == ("observation", "resolved")
    assert [s["source_version_id"] for s in observation["sources"]] == [
        lite["version"]["id"],
        cohr["version"]["id"],
    ]
    assert (quote["state"], quote["sources"][0]["document_id"]) == (
        "resolved",
        cohr["document_id"],
    )
    assert [(e["source_version_id"], e["section_anchor"]) for e in answer["evidence"]] == [
        (lite["version"]["id"], ITEM_1),
        (cohr["version"]["id"], ITEM_1),
    ]


# --- structured output --------------------------------------------------------------------

SCHEMA = {
    "type": "object",
    "properties": {
        "constrained": {"type": "boolean"},
        "evidence": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["constrained", "evidence"],
}


def test_structured_output_is_validated_against_its_schema_and_errors_are_reported(
    atlas: Atlas, fake: RecordedHindsight
) -> None:
    fact = fake.derived_fact(atlas.section(LITE_10K, "lumentum")["document_id"])
    fake.script_reflect("Yes.", [fact], structured_output={"constrained": True, "evidence": []})
    fake.script_reflect("Maybe.", [fact], structured_output={"constrained": "maybe"})
    fake.script_reflect("?", [fact], structured_output_error="provider timeout")

    valid = atlas.reflect("Constrained?", response_schema=SCHEMA)
    malformed = atlas.reflect("Constrained?", response_schema=SCHEMA)
    failed = atlas.reflect("Constrained?", response_schema=SCHEMA)

    assert fake.requests("POST", "reflect")[0]["response_schema"] == SCHEMA
    assert valid["structured_output"] == {"constrained": True, "evidence": []}
    assert valid["structured_output_error"] is None
    assert valid["response_schema"] == SCHEMA
    assert malformed["status"] == "completed"
    assert malformed["structured_output"] == {"constrained": "maybe"}
    assert malformed["structured_output_error"].startswith(
        "the structured output does not match the response schema"
    )
    assert failed["structured_output"] is None
    assert failed["structured_output_error"] == "Hindsight: provider timeout"


def test_a_union_type_schema_is_refused_before_anything_is_recorded(
    atlas: Atlas, fake: RecordedHindsight
) -> None:
    union = {"type": "object", "properties": {"n": {"type": ["number", "null"]}}}
    not_an_object = {"type": "array"}

    refusals = [
        atlas.api.post(
            "/api/v1/memory/reflect",
            json={"question": "How many?", "scope": {"theme_ids": ["photonics"]}, **body},
        )
        for body in ({"response_schema": union}, {"response_schema": not_an_object})
    ]

    assert [(r.status_code, r.json()["error"]["code"]) for r in refusals] == [
        (422, "invalid_response_schema"),
        (422, "invalid_response_schema"),
    ]
    assert "union type" in refusals[0].json()["error"]["message"]
    with atlas.engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM research_answer")).scalar_one() == 0
        jobs = connection.execute(text("SELECT count(*) FROM job WHERE kind = 'reflect'"))
        assert jobs.scalar_one() == 0
    assert fake.requests("POST", "reflect") == []


def test_a_reflect_that_keeps_failing_is_recorded_as_failed(
    atlas: Atlas, hindsight: tuple[RecordedHindsight, Served]
) -> None:
    fake, served = hindsight  # nothing scripted: the fake refuses the reflect (HTTP 500)

    accepted = atlas.ask("Unanswerable?")
    atlas.worker_pass()
    answer = atlas.get(f"/api/v1/memory/reflect/{accepted['research_answer']['id']}")

    assert len(fake.requests("POST", "reflect")) == 3  # the job's bounded attempts
    assert answer["status"] == "failed"
    assert answer["job_status"] == "failed"
    assert "HindsightHTTPError" in answer["error"] and "HTTP 500" in answer["error"]
    assert answer["answer"] is None and answer["citations"] is None
    with atlas.engine.connect() as connection:
        actions = connection.execute(
            text("SELECT action FROM audit_event WHERE entity_id = :id ORDER BY id"),
            {"id": accepted["research_answer"]["id"]},
        ).scalars()
        assert list(actions) == ["research_answer.requested", "research_answer.failed"]
    served.errors.clear()  # the refused reflects were the point


def test_a_stored_answer_is_final_in_the_database(atlas: Atlas, fake: RecordedHindsight) -> None:
    fake.script_reflect(
        "Done.", [fake.derived_fact(atlas.section(LITE_10K, "lumentum")["document_id"])]
    )
    answer = atlas.reflect("Anything?")

    for statement in (
        "UPDATE research_answer SET answer_text = 'edited' WHERE id = :id",
        "UPDATE research_answer SET status = 'pending' WHERE id = :id",
        "DELETE FROM research_answer WHERE id = :id",
    ):
        with pytest.raises(DBAPIError), atlas.engine.begin() as connection:
            connection.execute(text(statement), {"id": answer["id"]})
    with pytest.raises(DBAPIError), atlas.engine.begin() as connection:
        connection.execute(text("TRUNCATE research_answer"))
    assert atlas.get(f"/api/v1/memory/reflect/{answer['id']}")["answer"] == "Done."


def test_unknown_answers_and_unconfigured_hindsight(database_url: str, tmp_path: Path) -> None:
    settings = Settings.model_validate(
        {"database_url": database_url, "actor": "local-researcher", "archive_root": tmp_path}
    )
    api = TestClient(create_app(settings))

    missing = api.get("/api/v1/memory/reflect/00000000-0000-4000-8000-000000000000")
    recall = api.post(
        "/api/v1/memory/recall", json={"query": "q", "scope": {"theme_ids": ["photonics"]}}
    )
    reflect = api.post(
        "/api/v1/memory/reflect", json={"question": "q", "scope": {"theme_ids": ["photonics"]}}
    )

    assert (missing.status_code, missing.json()["error"]["code"]) == (404, "not_found")
    assert (recall.status_code, recall.json()["error"]["code"]) == (503, "hindsight_not_configured")
    assert (reflect.status_code, reflect.json()["error"]["code"]) == (
        503,
        "hindsight_not_configured",
    )
