"""Live extraction smoke test (Phase 3-6a ticket 28): the Investigator on real MiniMax output.

**Opt-in and never in CI.** It needs the `live` marker *and* `ATLAS_LIVE_TESTS` (`1`: live,
`rehearse`: the scripted LiteLLM fake); without it the test is skipped. Run it with
`scripts/live-extraction-smoke.sh` (`docs/runbooks.md`, "Live extraction smoke test").

What it measures: whether the Assertion span check rejects true Claims as `quote_mismatch`
because the model counts characters poorly. Three bounded extractions run over the recorded
EDGAR fixtures, ingested into a throwaway database:

1. the Lumentum FY2026 10-K's Item 1 (its first passages),
2. the Lumentum Q4 FY2026 earnings release (8-K EX-99.1; its first passages),
3. the Coherent FY2026 10-K's entity-tagged passages (NVIDIA, Lumentum: supplier-rich).

The Lumentum documents name no other known company, so no passage of theirs is entity-tagged;
their passages are chosen as recall hits, from a **stubbed recall** that names those sections
(no Hindsight recall is made). Hindsight is the recorded fake on localhost, used only for the
ingest and the run record; the Investigator's calls go to the real LiteLLM (`--model`,
default MiniMax-M3), or in a rehearsal to the scripted fake.

**Call cap.** At most `PASSAGES` passages per extraction, all in one call, and one repair per
call: at most `WORST_CASE_CALLS` (6) chat completions, under the cap of 10. Each extraction's
run has a `RUN_TOKEN_BUDGET` token budget, and a job gets one attempt (no retry). The report
(`tests/live/extraction_smoke.py`) lists every Claim's outcome and, for a `quote_mismatch`,
whether its quote occurs in its passage exactly once, several times or not at all.
"""

import json
import os
import subprocess
import sys
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import JsonValue

from atlas.archive import open_archive
from atlas.claims.extraction import EXTRACT_CLAIMS_KIND, ClaimExtractor, extract_claims_payload
from atlas.db.migrate import upgrade
from atlas.jobs import HandlerRegistry, Job, JobQueue, Pacing, Worker
from atlas.jobs.queue import Artifacts
from atlas.jobs.resources import run_recorder
from atlas.llm_routes import LiteLLMError, LiteLLMRoutes
from atlas.research.provenance import Evidence
from atlas.retention.sections import split_sections
from atlas.roles import MAX_ATTEMPTS, RoleCaller
from atlas.settings import Settings
from tests.fakes.hindsight import RecordedHindsight
from tests.fakes.litellm import API_KEY, ChatReply, FakeLiteLLM
from tests.fakes.serve import Served, serve
from tests.harness import ITEM_1, LITE_10K, THEMES, Atlas
from tests.live.extraction_smoke import ExtractionReport, fresh_database, parties
from tests.live.stack import REFUSED, Mode, live_mode

CALL_CAP = 10  # ticket 28: at most ~10 MiniMax calls
PASSAGES = 4  # per extraction, all sent in one call
RUN_TOKEN_BUDGET = 40_000  # per extraction's run (input + output)
DEFAULT_MODEL = "MiniMax-M3"

LITE_EX991 = (
    "https://www.sec.gov/Archives/edgar/data/1633978/000162828026055726/lite_ex991xq4fy26.htm"
)
COHR_10K = "https://www.sec.gov/Archives/edgar/data/820318/000082031826000020/iivi-20260630.htm"
QUESTION = (
    "Which products does the company make, and which suppliers, customers, competitors,"
    " manufacturing capacity or dependencies does this text state?"
)


@dataclass(frozen=True)
class Plan:
    """One extraction: a Source Version and how its passages are chosen."""

    name: str
    company: str
    url: str
    # Sections the stubbed recall names (None: every section); () : entity tags only.
    recalled: tuple[str, ...] | None
    question: str | None


PLANS = [
    Plan("lumentum-10k-item-1", "lumentum", LITE_10K, (ITEM_1,), QUESTION),
    Plan("lumentum-ex-99-1", "lumentum", LITE_EX991, None, QUESTION),
    Plan("coherent-10k-entity-tagged", "coherent", COHR_10K, (), None),
]
WORST_CASE_CALLS = len(PLANS) * MAX_ATTEMPTS  # one batch per extraction: PASSAGES per call
assert WORST_CASE_CALLS <= CALL_CAP

# From the Coherent FY2026 10-K (the rehearsal's scripted answers quote it).
SUPPLY_QUOTE = (
    "we announced the expansion of our Sherman, Texas, manufacturing facility, entered into a"
    " strategic multi-year supply agreement with NVIDIA for advanced lasers and optical"
    " networking products"
)


# --- the stack -------------------------------------------------------------------------------


@dataclass
class SmokeStack:
    mode: Mode
    model: str
    litellm_url: str
    litellm_api_key: str
    hindsight: Served
    llm: FakeLiteLLM | None

    @property
    def aliases(self) -> list[str]:
        """The aliases the run records: the fake's routed ones, or live the model itself
        unless ATLAS_LLM_EXTRACT_ALIAS/ATLAS_LLM_REFLECT_ALIAS name others."""
        if self.llm is not None:
            return ["atlas-extract", "atlas-reflect"]
        env = os.environ.get
        return list(
            dict.fromkeys(
                [
                    env("ATLAS_LLM_EXTRACT_ALIAS") or self.model,
                    env("ATLAS_LLM_REFLECT_ALIAS") or self.model,
                ]
            )
        )

    def preflight(self) -> dict[str, Any]:
        """Refuse (pytest exit status 4) before any model call if the run can't be made."""
        if self.mode == "live" and os.environ.get("CI"):
            raise _Refused("CI is set: the live smoke test never runs in CI")
        if not (self.litellm_url and self.litellm_api_key):
            raise _Refused("ATLAS_LITELLM_URL and ATLAS_LITELLM_API_KEY are required")
        try:
            with LiteLLMRoutes(self.litellm_url, self.litellm_api_key) as litellm:
                routes = litellm.routes(self.aliases)
        except LiteLLMError as error:
            raise _Refused(f"LiteLLM: {error}") from None
        return {
            "model": self.model,
            "routed_models": {
                alias: [each.model_dump(mode="json") for each in deployments]
                for alias, deployments in routes.items()
            },
        }


class _Refused(Exception):
    pass


@pytest.fixture(scope="module")
def stack() -> Iterator[SmokeStack]:
    mode = live_mode()
    assert mode is not None  # tests/live/conftest.py skips the test otherwise
    model = os.environ.get("ATLAS_LLM_ROLE_MODEL") or DEFAULT_MODEL
    fake = RecordedHindsight()
    fake.derive_memories()
    with serve(fake.transport.handle_request) as hindsight:
        if mode == "rehearse":
            llm = FakeLiteLLM()
            with serve(llm.handle) as litellm:
                yield SmokeStack(mode, model, litellm.url, API_KEY, hindsight, llm)
                litellm.raise_errors()
        else:
            yield SmokeStack(
                mode,
                model,
                os.environ.get("ATLAS_LITELLM_URL", "").rstrip("/"),
                os.environ.get("ATLAS_LITELLM_API_KEY", ""),
                hindsight,
                None,
            )
        hindsight.raise_errors()


@pytest.fixture(scope="module")
def report(stack: SmokeStack) -> Iterator[ExtractionReport]:
    run = ExtractionReport(stack.mode, stack.model, CALL_CAP, WORST_CASE_CALLS)
    yield run
    if results := os.environ.get("ATLAS_LIVE_RESULTS_DIR"):
        run.write(Path(results))


@pytest.fixture(scope="module")
def atlas(
    stack: SmokeStack, report: ExtractionReport, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[Atlas]:
    try:
        report.stack = stack.preflight()
    except _Refused as error:
        report.refused = str(error)
        if results := os.environ.get("ATLAS_LIVE_RESULTS_DIR"):
            report.write(Path(results))
        pytest.exit(f"live extraction smoke test refused: {error}", returncode=REFUSED)
    keep = os.environ.get("ATLAS_LIVE_KEEP_DATABASE", "").strip().lower() in {"1", "true", "yes"}
    tmp_path = tmp_path_factory.mktemp("extraction-smoke")
    with fresh_database(keep) as database_url:
        upgrade(database_url)
        if keep:
            report.stack["database"] = database_url.rsplit("/", 1)[-1]
        aliases = stack.aliases
        harness = Atlas(
            database_url,
            tmp_path,
            stack.hindsight.url,
            stack.litellm_url,
            themes_config=_themes(tmp_path),
            litellm_api_key=stack.litellm_api_key,
            llm_role_model=stack.model,
            llm_extract_alias=aliases[0],
            llm_reflect_alias=aliases[-1],
            run_token_budget=RUN_TOKEN_BUDGET,
        )
        harness.apply_template()
        seeded = _seed(harness)
        assert seeded.returncode == 0, seeded.stderr
        harness.ingest_company("lumentum")
        harness.ingest_company("coherent")
        yield harness
        harness.api.close()
        harness.engine.dispose()


def _themes(tmp_path: Path) -> Path:
    """The repo's universe plus NVIDIA, which the Coherent 10-K names."""
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


# --- the smoke run ---------------------------------------------------------------------------


def test_investigator_claims_on_recorded_filings_are_reported(
    atlas: Atlas, stack: SmokeStack, report: ExtractionReport
) -> None:
    settings = atlas.settings()
    versions = {plan.name: atlas.version(plan.url, plan.company) for plan in PLANS}
    recall = _stubbed_recall(atlas, versions)
    queue = JobQueue(atlas.engine, pacing=Pacing.from_settings(settings))
    worker = Worker(queue, _registry(settings, atlas, recall))
    if stack.llm is not None:
        reply = ChatReply.answer(_rehearsal_answer, tokens=(9000, 700))
        stack.llm.script_chat(*[reply] * len(PLANS))

    companies = {c["id"]: c for c in atlas.get("/api/v1/companies")["items"]}
    for plan in PLANS:
        version = versions[plan.name]
        payload = extract_claims_payload([uuid.UUID(version["id"])], plan.question)
        enqueued = queue.enqueue(
            EXTRACT_CLAIMS_KIND, f"smoke-{plan.name}", _json(payload), max_attempts=1
        )
        worker.run_once()
        job = atlas.get(f"/api/v1/jobs/{enqueued.job.id}")
        artifacts: dict[str, Any] = job.get("artifacts") or {}
        extraction = (
            atlas.get(f"/api/v1/claim-extractions/{artifacts['extraction_id']}")
            if "extraction_id" in artifacts
            else None
        )
        role_calls = (
            atlas.get(f"/api/v1/runs/{artifacts['run_id']}/role-calls")
            if "run_id" in artifacts
            else None
        )
        report.add_extraction(plan.name, job=job, extraction=extraction, role_calls=role_calls)
        if extraction is None:
            continue
        parsed = atlas.parsed(version["id"])
        by_passage = {p["id"]: p for p in extraction["passages"]}
        filer = version["source_document"]["company_id"]
        claims = atlas.get("/api/v1/claims", extraction_id=extraction["id"], limit=500)["items"]
        for claim in sorted(claims, key=lambda c: (c["role_call_id"], c["created_at"])):
            passage = by_passage.get(claim["passage_id"])
            text = parsed[passage["char_start"] : passage["char_end"]] if passage else None
            report.add_claim(plan.name, claim, text, parties(claim, companies, filer))

    totals = report.totals()
    print(json.dumps(totals, indent=2))
    assert report.llm_calls <= CALL_CAP, f"{report.llm_calls} LLM calls, over the cap"
    for extraction in report.extractions:
        assert extraction["job_status"] == "succeeded", extraction
        assert extraction["passages"], f"{extraction['name']}: no passage chosen"
    if stack.llm is not None:
        _check_rehearsal(report)


def _seed(atlas: Atlas) -> subprocess.CompletedProcess[str]:
    """`atlas companies seed` with the test universe (the harness CLI names the repo's)."""
    return subprocess.run(
        [sys.executable, "-m", "atlas", "companies", "seed"],
        cwd=atlas.tmp_path,
        env={
            "PATH": os.environ["PATH"],
            "HOME": str(atlas.tmp_path),
            "ATLAS_DATABASE_URL": atlas.database_url,
            "ATLAS_ACTOR": "live-test",
            "ATLAS_ARCHIVE_ROOT": str(atlas.archive),
            "ATLAS_THEMES_CONFIG": str(atlas.settings().themes_config),
        },
        capture_output=True,
        text=True,
        timeout=120,
    )


def _registry(
    settings: Settings, atlas: Atlas, recall: Callable[[str, list[uuid.UUID]], list[Evidence]]
) -> HandlerRegistry:
    """`extract_claims` as the job handler runs it, but with the stubbed recall."""

    def extract_claims(job: Job) -> Artifacts:
        with run_recorder(settings, atlas.engine) as runs:
            caller = RoleCaller.from_settings(settings, atlas.engine)
            assert caller is not None
            with caller:
                return ClaimExtractor(
                    atlas.engine,
                    open_archive(settings),
                    caller,
                    runs,
                    recall=recall,
                    max_passages=PASSAGES,
                    passages_per_call=PASSAGES,
                ).extract(job)

    registry = HandlerRegistry()
    registry.register(EXTRACT_CLAIMS_KIND, extract_claims, pausable=True)
    return registry


def _stubbed_recall(
    atlas: Atlas, versions: dict[str, dict[str, Any]]
) -> Callable[[str, list[uuid.UUID]], list[Evidence]]:
    """A recall that resolves to the sections the plans name, whatever the question."""
    hits: list[Evidence] = []
    for plan in PLANS:
        if plan.recalled == ():
            continue
        version = versions[plan.name]
        document = version["source_document"]
        sections = split_sections(
            atlas.parsed(version["id"]),
            form=document["form_type"],
            primary=document["document_type"] is not None
            and document["document_type"] == document["form_type"],
        )
        for section in sections:
            if plan.recalled is not None and section.anchor not in plan.recalled:
                continue
            hits.append(
                Evidence(
                    source_version_id=uuid.UUID(version["id"]),
                    source_document_id=uuid.UUID(document["id"]),
                    company_id=uuid.UUID(document["company_id"]),
                    form_type=document["form_type"],
                    section_anchor=section.anchor,
                    section_heading=None,
                    section_char_start=section.start,
                    section_char_end=section.end,
                    available_at=version["available_at"],
                    available_at_basis=version["available_at_basis"],
                    memory_ids=[],
                    quotes=[],
                )
            )

    def recall(question: str, company_ids: list[uuid.UUID]) -> list[Evidence]:
        return [hit for hit in hits if hit.company_id in company_ids]

    return recall


def _json(payload: dict[str, Any]) -> dict[str, JsonValue]:
    return json.loads(json.dumps(payload))


# --- the rehearsal ---------------------------------------------------------------------------


def _rehearsal_answer(body: dict[str, Any]) -> JsonValue:
    """A scripted Investigator answer over the passages sent: the Coherent supply agreement
    quoted at its offsets (accepted) and again one character off (a mismatch whose quote
    occurs once and would be accepted if located); in the first passage, a line one
    character off (occurs once), the filer's name at the wrong offsets (occurs several
    times) and a paraphrase (occurs nowhere)."""
    asked = json.loads(body["messages"][1]["content"])
    request, passages = asked["request"], asked["retrieved_data"]
    ids = {c["names"][-1]: c["company_id"] for c in request["companies"]}
    names = {c["company_id"]: c["names"] for c in request["companies"]}
    claims: list[JsonValue] = []
    supplies: dict[str, JsonValue] = {
        "subject_company_id": _named(ids, "Coherent"),
        "predicate": "supplies",
        "object_company_id": _named(ids, "NVIDIA"),
        "product": "advanced lasers",
        "layer": "chip-laser",
    }
    for passage in passages:
        if SUPPLY_QUOTE in passage["text"]:
            start = passage["text"].index(SUPPLY_QUOTE)
            claims.append(_claim(passage["id"], SUPPLY_QUOTE, start, **supplies))
            claims.append(_claim(passage["id"], SUPPLY_QUOTE, start + 1, **supplies))
    first, filer = passages[0], request["passages"][0]["filer_company_id"]
    text = first["text"]
    product: dict[str, JsonValue] = {
        "subject_company_id": filer,
        "predicate": "manufactures",
        "object_text": "optical components",
        "layer": "module",
    }
    line = next(
        (
            each.strip()
            for each in text.splitlines()
            if len(each.strip()) >= 40 and text.count(each.strip()) == 1
        ),
        None,
    )
    if line is not None:
        claims.append(_claim(first["id"], line, text.index(line) + 1, **product))
    repeated = next((n for n in names[filer] if text.count(n) >= 2), None)
    if repeated is not None:
        start = 1 if text.startswith(repeated) else 0
        claims.append(_claim(first["id"], repeated, start, **product))
    paraphrase = f"{names[filer][-1]} makes lasers for every datacenter network in the world"
    claims.append(_claim(first["id"], paraphrase, 0, **product))
    return {"claims": claims}


def _named(ids: dict[str, str], name: str) -> str:
    return next(company_id for known, company_id in ids.items() if name in known)


def _claim(passage_id: str, quote: str, start: int, **fields: JsonValue) -> JsonValue:
    return {
        "passage_id": passage_id,
        "object_company_id": None,
        "object_text": None,
        "product": None,
        "epistemic_type": "company_claim",
        "quote": quote,
        "quote_start": start,
        "quote_end": start + len(quote),
        **fields,
    }


def _check_rehearsal(report: ExtractionReport) -> None:
    """The scripted answers' outcomes, as the report must classify them."""
    totals = report.totals()
    assert totals["llm_calls"] == len(PLANS)
    assert totals["tokens_in"] == 9000 * len(PLANS)
    outcomes = {
        (c["predicate"], c["outcome"], c["quote_in_passage"], c["after_locating"])
        for c in report.claims
    }
    assert ("supplies", "accepted", None, None) in outcomes
    assert ("supplies", "rejected", "exactly_once", "accepted") in outcomes
    assert ("manufactures", "rejected", "not_at_all", None) in outcomes
    assert ("manufactures", "rejected", "multiple", None) in outcomes
    located = [c for c in report.claims if c["quote_in_passage"] == "exactly_once"]
    assert {c["extraction"] for c in located} == {plan.name for plan in PLANS}
    assert all(c["reason_code"] == "quote_mismatch" for c in located)
    assert totals["located_would_be_accepted"] == sum(
        1 for c in located if c["after_locating"] == "accepted"
    )
