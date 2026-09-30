"""Replay the pilot's Investigator extraction with prompt variants (pilot-fixes ticket 03).

Pilot investigation 1 sent the Investigator 24 passages of Coherent's FY2026 10-K (its
business and risk-factor Items, chosen by recall) and got no Claim back. This script
reproduces that extraction offline and measures prompt variants on the same passages:

- **The same passages.** A throwaway database on the test Postgres, the repo's company
  universe seeded, Coherent ingested from the recorded EDGAR fixtures, and the production
  `ClaimExtractor` run over the FY2026 10-K with the pilot's question, 24 passages, 6 per
  call. Recall is stubbed to name the 10-K's Item 1 and Item 1A (what the pilot's recall
  resolved to), so the production selection picks the passages: entity-tagged windows first,
  then the recalled ones in document order.
- **The same request and checks.** Each variant is one `extract_claims` job in its own run:
  the request the production code builds (every universe company, the predicate whitelist,
  the layers), the role caller's strict JSON schema, one repair, and every proposed Claim
  judged by the production checks (quote location, whitelist, parties, directional language).
  Only the role's prompt differs.
- **The model.** Live, the configured LiteLLM (`ATLAS_LITELLM_URL`/`ATLAS_LITELLM_API_KEY`,
  or `LITELLM_URL`/`LITELLM_API_KEY`, from the environment or `--env-file`, default the repo's
  `.env`; the key is never printed) and `--model` (default MiniMax-M3). With `--rehearse`, the
  scripted LiteLLM fake answers instead (no network: a check of the harness itself). Hindsight
  is the recorded fake on localhost, used only for the ingest and the run record.

Each variant costs at most 4 calls plus one repair each (8 chat completions); `--max-calls`
(default 30) refuses a run whose worst case exceeds it. The report (per variant: Claims
proposed and accepted, rejection reasons, tokens, example accepted Claims, and every Claim)
goes to `--out` (default `.scratch/live-runs/<stamp>-investigator-replay/`) as `results.json`
and `summary.md`.

    uv run python scripts/investigator_replay.py --variant v2 \\
        --variant relaxed=docs/research/investigator-yield/variant-relaxed.md
"""

import argparse
import hashlib
import json
import os
import sys
import tempfile
import uuid
from collections import Counter
from collections.abc import Callable, Generator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import JsonValue

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:  # the test fakes and harness live in `tests/`
    sys.path.insert(0, str(REPO))

from tests.fakes.hindsight import RecordedHindsight  # noqa: E402
from tests.fakes.litellm import API_KEY, ChatReply, FakeLiteLLM  # noqa: E402
from tests.fakes.serve import serve  # noqa: E402
from tests.harness import Atlas  # noqa: E402
from tests.live.extraction_smoke import fresh_database  # noqa: E402

from atlas.archive import open_archive  # noqa: E402
from atlas.claims.extraction import (  # noqa: E402
    EXTRACT_CLAIMS_KIND,
    ClaimExtractor,
    extract_claims_payload,
)
from atlas.db.migrate import upgrade  # noqa: E402
from atlas.jobs import HandlerRegistry, Job, JobQueue, Worker  # noqa: E402
from atlas.jobs.queue import Artifacts  # noqa: E402
from atlas.jobs.resources import run_recorder  # noqa: E402
from atlas.research.provenance import Evidence  # noqa: E402
from atlas.retention.sections import split_sections  # noqa: E402
from atlas.roles import MAX_ATTEMPTS, RoleCaller  # noqa: E402
from atlas.roles.contract import PROMPTS_DIR, Prompt, Role  # noqa: E402
from atlas.roles.investigator import (  # noqa: E402
    INVESTIGATOR,
    InvestigatorClaims,
    InvestigatorRequest,
)

COHR_10K = "https://www.sec.gov/Archives/edgar/data/820318/000082031826000020/iivi-20260630.htm"
RECALLED = ("part-i-item-1", "part-i-item-1a")  # the 10-K's business and risk factors
QUESTION = (
    "For 800G/1.6T AI data-center transceivers, who supplies the laser chips (EML, CW/DFB,"
    " VCSEL), which suppliers are capacity- or allocation-constrained, and what feedstock or"
    " equipment (InP substrates, MOCVD) limits them?"
)
MAX_PASSAGES = 24  # the pilot's (settings.investigator_max_passages)
PASSAGES_PER_CALL = 6  # the pilot's (settings.investigator_passages_per_call)
CALLS_PER_VARIANT = -(-MAX_PASSAGES // PASSAGES_PER_CALL) * MAX_ATTEMPTS
RUN_TOKEN_BUDGET = 200_000  # per variant's run: never the limit on 4 calls
DEFAULT_MODEL = "MiniMax-M3"
EXAMPLES = 5


@dataclass(frozen=True)
class Variant:
    name: str
    role: Role[InvestigatorRequest, InvestigatorClaims]
    prompt_path: str


def variant(spec: str) -> Variant:
    """`v<N>` (the committed prompt `investigator.v<N>`) or `<name>=<path to a prompt file>`."""
    if "=" not in spec:
        version = int(spec.removeprefix("v"))
        prompt = Prompt.load(PROMPTS_DIR, "investigator", version)
        path = PROMPTS_DIR / f"investigator.v{version}.md"
        name = spec
    else:
        name, raw_path = spec.split("=", 1)
        path = Path(raw_path)
        raw = path.read_bytes()
        # The extractor version its Assertions record: `investigator-<name>.v1` (never a
        # committed version's).
        prompt = Prompt(
            f"investigator-{name}", 1, raw.decode("utf-8"), hashlib.sha256(raw).hexdigest()
        )
    role = Role(
        name=INVESTIGATOR.name,
        prompt=prompt,
        request=InvestigatorRequest,
        response=InvestigatorClaims,
        max_output_tokens=INVESTIGATOR.max_output_tokens,
    )
    shown = path.resolve().relative_to(REPO) if path.resolve().is_relative_to(REPO) else path
    return Variant(name, role, str(shown))


# --- the report ------------------------------------------------------------------------------


@dataclass
class Report:
    mode: str
    model: str
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    passages: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    variants: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])

    def add(
        self,
        found: Variant,
        *,
        job: dict[str, Any],
        extraction: dict[str, Any] | None,
        role_calls: dict[str, Any] | None,
        claims: list[dict[str, Any]],
    ) -> dict[str, Any]:
        calls: list[dict[str, Any]] = role_calls["role_calls"] if role_calls else []
        accepted = [c for c in claims if c["outcome"] == "accepted"]
        entry: dict[str, Any] = {
            "variant": found.name,
            "prompt": found.prompt_path,
            "prompt_sha256": found.role.prompt.sha256,
            "job_status": job["status"],
            "job_failures": job.get("failures"),
            "extraction_status": extraction["status"] if extraction else None,
            "passages": len(extraction["passages"]) if extraction else 0,
            "batches_quarantined": extraction["batches_quarantined"] if extraction else None,
            "role_calls": [
                {
                    "status": c["status"],
                    "attempts": len(c["attempts"]),
                    "error": c["error"],
                    # Why an attempt failed validation (the first errors) and its output size.
                    "failed_attempts": [
                        {
                            "tokens_out": a["tokens_out"],
                            "errors": (a["validation_errors"] or [])[:3],
                            "content_tail": a["content"][-200:],
                        }
                        for a in c["attempts"]
                        if a["validation_errors"]
                    ],
                }
                for c in calls
            ],
            "llm_calls": sum(len(c["attempts"]) for c in calls),
            "tokens_in": role_calls["tokens_in"] if role_calls else 0,
            "tokens_out": role_calls["tokens_out"] if role_calls else 0,
            "proposed": len(claims),
            "accepted": len(accepted),
            "rejections": dict(
                Counter(c["reason_code"] for c in claims if c["outcome"] != "accepted")
            ),
            "accepted_by_predicate": dict(Counter(c["predicate"] for c in accepted)),
            "proposed_by_predicate": dict(Counter(c["predicate"] for c in claims)),
            "claims": [
                {
                    key: claim[key]
                    for key in (
                        "passage_id",
                        "predicate",
                        "object_text",
                        "product",
                        "layer",
                        "quote",
                        "outcome",
                        "reason_code",
                        "reason",
                        "offset_source",
                    )
                }
                for claim in claims
            ],
        }
        self.variants.append(entry)
        return entry

    def summary(self) -> str:
        lines = [
            "# Investigator replay",
            "",
            f"- mode: {self.mode}, model: {self.model}, started {self.started_at}",
            f"- passages: {len(self.passages)} "
            f"({dict(Counter(p['section'] for p in self.passages))})",
            "",
            "| variant | calls | tokens in / out | proposed | accepted | rejections |",
            "|---|---|---|---|---|---|",
        ]
        for entry in self.variants:
            rejections = ", ".join(f"{k} {v}" for k, v in sorted(entry["rejections"].items()))
            lines.append(
                f"| {entry['variant']} | {entry['llm_calls']} | {entry['tokens_in']} /"
                f" {entry['tokens_out']} | {entry['proposed']} | {entry['accepted']} |"
                f" {rejections or '-'} |"
            )
        for entry in self.variants:
            lines += ["", f"## {entry['variant']} ({entry['prompt']})", ""]
            lines.append(f"Accepted by predicate: {entry['accepted_by_predicate'] or '-'}")
            accepted = [c for c in entry["claims"] if c["outcome"] == "accepted"]
            for claim in accepted[:EXAMPLES]:
                lines.append(
                    f"- `{claim['predicate']}` {claim['object_text'] or ''} [{claim['layer']}]:"
                    f' "{claim["quote"]}"'
                )
            rejected = [c for c in entry["claims"] if c["outcome"] != "accepted"]
            for claim in rejected[:EXAMPLES]:
                lines.append(
                    f"- rejected `{claim['predicate']}` ({claim['reason_code']}):"
                    f' "{claim["quote"]}"'
                )
        return "\n".join(lines) + "\n"

    def write(self, out: Path) -> None:
        out.mkdir(parents=True, exist_ok=True)
        results = {
            "mode": self.mode,
            "model": self.model,
            "started_at": self.started_at,
            "question": QUESTION,
            "passages": self.passages,
            "variants": self.variants,
        }
        (out / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
        (out / "summary.md").write_text(self.summary(), encoding="utf-8")


# --- the replay ------------------------------------------------------------------------------


@contextmanager
def litellm(rehearse: bool, env_file: Path) -> Generator[tuple[str, str, FakeLiteLLM | None]]:
    """The LiteLLM to call: the scripted fake, served on localhost, or the configured one."""
    if rehearse:
        fake = FakeLiteLLM()
        with serve(fake.handle) as served:
            yield served.url, API_KEY, fake
            served.raise_errors()
        return
    env = {**_dotenv(env_file), **os.environ}
    url = env.get("ATLAS_LITELLM_URL") or env.get("LITELLM_URL") or ""
    key = env.get("ATLAS_LITELLM_API_KEY") or env.get("LITELLM_API_KEY") or ""
    if not (url and key):
        raise SystemExit("set ATLAS_LITELLM_URL and ATLAS_LITELLM_API_KEY (or LITELLM_*)")
    if os.environ.get("CI"):
        raise SystemExit("CI is set: the live replay never runs in CI")
    yield url.rstrip("/"), key, None


def _dotenv(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        name, sep, value = line.strip().partition("=")
        if sep and not name.startswith("#"):
            values[name.strip()] = value.strip().strip("'\"")
    return values


def replay(
    variants: list[Variant],
    *,
    rehearse: bool,
    model: str,
    out: Path | None,
    keep_database: bool = False,
    env_file: Path = REPO / ".env",
) -> Report:
    report = Report("rehearse" if rehearse else "live", model)
    with ExitStack() as stack:
        hindsight_fake = RecordedHindsight()
        hindsight_fake.derive_memories()
        hindsight = stack.enter_context(serve(hindsight_fake.transport.handle_request))
        url, key, fake = stack.enter_context(litellm(rehearse, env_file))
        database_url = stack.enter_context(fresh_database(keep_database))
        upgrade(database_url)
        tmp = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="investigator-replay")))
        atlas = Atlas(
            database_url,
            tmp,
            hindsight.url,
            url,
            litellm_api_key=key,
            llm_role_model=model,
            run_token_budget=RUN_TOKEN_BUDGET,
            # The run records the routes of these aliases: the fake's, or live the model.
            **(
                {} if fake is not None else {"llm_extract_alias": model, "llm_reflect_alias": model}
            ),
        )
        try:
            atlas.apply_template()
            seeded = atlas.cli("companies", "seed")
            assert seeded.returncode == 0, seeded.stderr
            atlas.ingest_company("coherent")
            version = atlas.version(COHR_10K, "coherent")
            parsed = atlas.parsed(version["id"])
            settings = atlas.settings()
            queue = JobQueue(atlas.engine)
            for index, found in enumerate(variants):
                if fake is not None:
                    fake.script_chat(
                        *[ChatReply.answer(rehearsal_answer, tokens=(7000, 300))]
                        * (CALLS_PER_VARIANT // MAX_ATTEMPTS)
                    )
                registry = _registry(settings, atlas, _recall(version, parsed), found)
                payload = extract_claims_payload([uuid.UUID(version["id"])], QUESTION)
                enqueued = queue.enqueue(
                    EXTRACT_CLAIMS_KIND,
                    f"replay-{index}-{found.name}",
                    json.loads(json.dumps(payload)),
                    max_attempts=1,
                )
                Worker(queue, registry).run_once()
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
                claims: list[dict[str, Any]] = (
                    atlas.get("/api/v1/claims", extraction_id=extraction["id"], limit=500)["items"]
                    if extraction
                    else []
                )
                if extraction and not report.passages:
                    report.passages = [
                        {
                            "id": p["id"],
                            "section": p["section_anchor"],
                            "chars": [p["char_start"], p["char_end"]],
                            "selected_by": p["selected_by"],
                        }
                        for p in extraction["passages"]
                    ]
                entry = report.add(
                    found, job=job, extraction=extraction, role_calls=role_calls, claims=claims
                )
                print(
                    f"{found.name}: {entry['llm_calls']} calls, {entry['proposed']} proposed,"
                    f" {entry['accepted']} accepted, rejections {entry['rejections']}",
                    flush=True,
                )
        finally:
            atlas.api.close()
            atlas.engine.dispose()
    if out is not None:
        report.write(out)
    return report


def _registry(
    settings: Any,
    atlas: Atlas,
    recall: Callable[[str, list[uuid.UUID]], list[Evidence]],
    found: Variant,
) -> HandlerRegistry:
    """`extract_claims` as the job handler runs it, with the pilot's passage budget, the
    stubbed recall and the variant's prompt."""

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
                    max_passages=MAX_PASSAGES,
                    passages_per_call=PASSAGES_PER_CALL,
                    investigator=found.role,
                ).extract(job)

    registry = HandlerRegistry()
    registry.register(EXTRACT_CLAIMS_KIND, extract_claims, pausable=True)
    return registry


def _recall(
    version: dict[str, Any], parsed: str
) -> Callable[[str, list[uuid.UUID]], list[Evidence]]:
    """A recall that resolves to the 10-K's Items 1 and 1A, whatever the question."""
    document = version["source_document"]
    hits = [
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
        for section in split_sections(parsed, form=document["form_type"], primary=True)
        if section.anchor in RECALLED
    ]
    assert {hit.section_anchor for hit in hits} == set(RECALLED), "the 10-K's Items changed"

    def recall(question: str, company_ids: list[uuid.UUID]) -> list[Evidence]:
        return [hit for hit in hits if hit.company_id in company_ids]

    return recall


# --- the rehearsal's scripted model ------------------------------------------------------------


SELF_STATEMENT = "manufactur"


def rehearsal_answer(body: dict[str, Any]) -> JsonValue:
    """A scripted answer: for each passage sent, the first line of the filer's own text that
    says it manufactures something, as a `manufactures` Claim (quoted exactly, at its
    offsets), and one paraphrase (rejected `quote_mismatch`)."""
    asked = json.loads(body["messages"][1]["content"])
    request, passages = asked["request"], asked["retrieved_data"]
    filer = request["passages"][0]["filer_company_id"]
    claims: list[JsonValue] = []
    for passage in passages:
        text = passage["text"]
        line = next(
            (
                each.strip()
                for each in text.splitlines()
                if SELF_STATEMENT in each and "We " in each and text.count(each.strip()) == 1
            ),
            None,
        )
        if line is None:
            continue
        start = text.index(line)
        claims.append(
            {
                "passage_id": passage["id"],
                "subject_company_id": filer,
                "predicate": "manufactures",
                "object_company_id": None,
                "object_name": None,
                "object_text": "optical components",
                "product": None,
                "layer": "chip-laser",
                "quote": line,
                "quote_start": start,
                "quote_end": start + len(line),
                "epistemic_type": "company_claim",
            }
        )
    claims.append(
        {
            "passage_id": passages[0]["id"],
            "subject_company_id": filer,
            "predicate": "manufactures",
            "object_company_id": None,
            "object_name": None,
            "object_text": "lasers",
            "product": None,
            "layer": "chip-laser",
            "quote": "We make every laser in the world",
            "quote_start": 0,
            "quote_end": 32,
            "epistemic_type": "company_claim",
        }
    )
    return {"claims": claims}


def main(argv: list[str] | None = None) -> Report:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument(
        "--variant",
        action="append",
        default=[],
        help="v<N> (a committed prompt) or name=path (a prompt file); repeatable (default v2)",
    )
    parser.add_argument("--rehearse", action="store_true", help="the scripted model, offline")
    parser.add_argument("--model", default=os.environ.get("ATLAS_LLM_ROLE_MODEL") or DEFAULT_MODEL)
    parser.add_argument("--max-calls", type=int, default=30)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--keep-database", action="store_true")
    parser.add_argument("--env-file", type=Path, default=REPO / ".env")
    args = parser.parse_args(argv)
    variants = [variant(spec) for spec in args.variant or ["v2"]]
    worst = len(variants) * CALLS_PER_VARIANT
    if not args.rehearse and worst > args.max_calls:
        raise SystemExit(f"{len(variants)} variants may make {worst} calls, over --max-calls")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    mode = "rehearse" if args.rehearse else "live"
    out = args.out or REPO / ".scratch" / "live-runs" / f"{stamp}-investigator-replay-{mode}"
    report = replay(
        variants,
        rehearse=args.rehearse,
        model=args.model,
        out=out,
        keep_database=args.keep_database,
        env_file=args.env_file,
    )
    print(f"report: {out / 'summary.md'}")
    return report


if __name__ == "__main__":
    main()
