"""The live extraction smoke test's stack and report (ticket 28; `test_extraction_smoke_live.py`).

The test measures one risk: that a model counts characters poorly, so the Assertion span check
rejects true Claims as `quote_mismatch`. For every Claim the report records its predicate,
outcome and reason code and, for a `quote_mismatch`, whether its quote occurs in its passage
exactly once, several times or not at all (and the same after folding whitespace, quotes and
dashes): the numbers behind the decision on quote location ("search for a quote that occurs
exactly once in its passage"). For a quote found exactly once it also says what the later
checks (both parties named, directional language) would make of it, had it been located.

Written to `ATLAS_LIVE_RESULTS_DIR` (default under the gitignored `.scratch/live-runs/`) as
`results.json` and `summary.md`.
"""

import json
import os
import re
import uuid
from collections import Counter
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import JsonValue
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from atlas.claims.predicates import company_names, directional_cue, names_party
from tests.live.stack import DEFAULT_ADMIN_DATABASE_URL, Mode

type Occurrence = Literal["exactly_once", "multiple", "not_at_all"]

# The reason codes of the checks that run after the span check: a Claim with one of these (or
# accepted) was otherwise valid when the span check ran.
SPAN_CHECKED = {"quote_mismatch", "party_not_in_quote", "no_directional_language"}
DECISION_THRESHOLD = 0.2  # ticket 28: put quote location to the owner above ~20%

_FOLDS = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u00a0": " ",
    }
)


def occurrence(quote: str, passage: str) -> tuple[Occurrence, int]:
    """Where `quote` occurs, exactly, in `passage`, and how many times."""
    count = passage.count(quote) if quote else 0
    return _occurrence(count), count


def folded_occurrence(quote: str, passage: str) -> tuple[Occurrence, int]:
    """The same after folding whitespace runs, typographic quotes and dashes."""
    folded = _fold(quote)
    count = _fold(passage).count(folded) if folded else 0
    return _occurrence(count), count


def _occurrence(count: int) -> Occurrence:
    return "not_at_all" if count == 0 else "exactly_once" if count == 1 else "multiple"


def _fold(value: str) -> str:
    return re.sub(r"\s+", " ", value.translate(_FOLDS)).strip()


@contextmanager
def fresh_database(keep: bool) -> Generator[str]:
    """A new, empty app database on the test Postgres (dropped unless kept)."""
    admin_url = os.environ.get("ATLAS_TEST_DATABASE_URL") or DEFAULT_ADMIN_DATABASE_URL
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    name = f"atlas_live_extract_{stamp}_{uuid.uuid4().hex[:6]}"
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        yield make_url(admin_url).set(database=name).render_as_string(hide_password=False)
    finally:
        if not keep:
            with admin.connect() as connection:
                connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


@dataclass(frozen=True)
class Party:
    names: list[str]
    is_filer: bool


def after_locating(predicate: str, quote: str, subject: Party | None, target: Party | None) -> str:
    """What the checks after the span check would make of a located quote: `accepted`, or the
    first of their reason codes."""
    for party in (subject, target):
        if party is not None and not names_party(quote, party.names, is_filer=party.is_filer):
            return "party_not_in_quote"
    return (
        "accepted" if directional_cue(predicate, quote) is not None else "no_directional_language"
    )


@dataclass
class ExtractionReport:
    """What the smoke run saw: per extraction its passages, outcome, calls and tokens; per
    Claim its outcome and, for a quote mismatch, where its quote occurs."""

    mode: Mode
    model: str
    call_cap: int
    worst_case_calls: int
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    stack: dict[str, Any] = field(default_factory=dict[str, Any])
    extractions: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    claims: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    refused: str | None = None

    def add_extraction(
        self,
        name: str,
        *,
        job: dict[str, Any],
        extraction: dict[str, Any] | None,
        role_calls: dict[str, Any] | None,
    ) -> None:
        calls: list[dict[str, Any]] = role_calls["role_calls"] if role_calls else []
        passages: list[dict[str, Any]] = extraction["passages"] if extraction else []
        self.extractions.append(
            {
                "name": name,
                "job_status": job["status"],
                "job_failures": job.get("failures"),
                "extraction_id": extraction["id"] if extraction else None,
                "status": extraction["status"] if extraction else None,
                "question": extraction["question"] if extraction else None,
                "passages": [
                    {
                        "id": p["id"],
                        "section": p["section_anchor"],
                        "chars": [p["char_start"], p["char_end"]],
                        "selected_by": p["selected_by"],
                    }
                    for p in passages
                ],
                "passages_dropped": extraction["passages_dropped"] if extraction else None,
                "batches_quarantined": extraction["batches_quarantined"] if extraction else None,
                "run_id": role_calls["run_id"] if role_calls else None,
                "role_calls": [
                    {"status": c["status"], "attempts": len(c["attempts"]), "error": c["error"]}
                    for c in calls
                ],
                "llm_calls": sum(len(c["attempts"]) for c in calls),
                "tokens_in": role_calls["tokens_in"] if role_calls else 0,
                "tokens_out": role_calls["tokens_out"] if role_calls else 0,
            }
        )

    def add_claim(
        self,
        extraction: str,
        claim: dict[str, Any],
        passage: str | None,
        parties: tuple[Party | None, Party | None],
    ) -> None:
        entry: dict[str, Any] = {
            "extraction": extraction,
            "passage_id": claim["passage_id"],
            "predicate": claim["predicate"],
            "layer": claim["layer"],
            "outcome": claim["outcome"],
            "reason_code": claim["reason_code"],
            "reason": claim["reason"],
            "quote": claim["quote"],
            "quote_chars": len(claim["quote"]),
            "offsets": [claim["proposed"].get("quote_start"), claim["proposed"].get("quote_end")],
            "quote_in_passage": None,
            "occurrences": None,
            "folded_quote_in_passage": None,
            "after_locating": None,
        }
        if claim["reason_code"] == "quote_mismatch" and passage is not None:
            where, count = occurrence(claim["quote"], passage)
            folded, _ = folded_occurrence(claim["quote"], passage)
            entry |= {
                "quote_in_passage": where,
                "occurrences": count,
                "folded_quote_in_passage": folded,
            }
            if where == "exactly_once":
                entry["after_locating"] = after_locating(
                    claim["predicate"], claim["quote"], *parties
                )
        self.claims.append(entry)

    @property
    def llm_calls(self) -> int:
        return sum(e["llm_calls"] for e in self.extractions)

    def totals(self) -> dict[str, Any]:
        rejected = Counter(c["reason_code"] for c in self.claims if c["outcome"] == "rejected")
        accepted = sum(1 for c in self.claims if c["outcome"] == "accepted")
        mismatches = [c for c in self.claims if c["reason_code"] == "quote_mismatch"]
        reached = accepted + sum(n for code, n in rejected.items() if code in SPAN_CHECKED)
        share = len(mismatches) / reached if reached else None
        return {
            "proposed": len(self.claims),
            "accepted": accepted,
            "rejected": sum(rejected.values()),
            "rejected_by_reason": dict(sorted(rejected.items())),
            "reached_span_check": reached,
            "quote_mismatch": len(mismatches),
            "quote_mismatch_share": None if share is None else round(share, 3),
            "exceeds_decision_threshold": share is not None and share > DECISION_THRESHOLD,
            "quote_mismatch_by_occurrence": dict(
                Counter(str(c["quote_in_passage"]) for c in mismatches)
            ),
            "quote_mismatch_by_folded_occurrence": dict(
                Counter(str(c["folded_quote_in_passage"]) for c in mismatches)
            ),
            "located_would_be_accepted": sum(
                1 for c in mismatches if c["after_locating"] == "accepted"
            ),
            "llm_calls": self.llm_calls,
            "call_cap": self.call_cap,
            "worst_case_calls": self.worst_case_calls,
            "tokens_in": sum(e["tokens_in"] for e in self.extractions),
            "tokens_out": sum(e["tokens_out"] for e in self.extractions),
        }

    def results(self) -> dict[str, JsonValue]:
        return json.loads(
            json.dumps(
                {
                    "mode": self.mode,
                    "model": self.model,
                    "started_at": self.started_at,
                    "finished_at": datetime.now(UTC).isoformat(),
                    "refused": self.refused,
                    "stack": self.stack,
                    "totals": self.totals(),
                    "extractions": self.extractions,
                    "claims": self.claims,
                },
                default=str,
            )
        )

    def write(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        results = self.results()
        (directory / "results.json").write_text(
            json.dumps(results, indent=2) + "\n", encoding="utf-8"
        )
        (directory / "summary.md").write_text(self.summary(results), encoding="utf-8")

    def summary(self, results: dict[str, Any]) -> str:
        """A Markdown digest to copy into docs/implementation-log.md."""
        kind = {"live": f"LIVE ({self.model} via LiteLLM)", "rehearse": "REHEARSAL"}
        totals = results["totals"]
        lines = [
            f"# Live extraction smoke run: {kind[self.mode]}",
            "",
            f"- started {results['started_at']}, finished {results['finished_at']}",
        ]
        if self.mode == "rehearse":
            lines.append("- rehearsal: the scripted LiteLLM fake; **nothing was live**")
        lines.append(
            "- Hindsight: the recorded fake on localhost (ingest and the run record only; no"
            " recall: the Lumentum passages are the search selection's for the question)"
        )
        if self.refused:
            lines.append(f"- **refused**: {self.refused}")
        for alias, deployments in self.stack.get("routed_models", {}).items():
            models = ", ".join(f"{d['model']} ({d['model_id']})" for d in deployments)
            lines.append(f"- alias `{alias}` -> {models}")
        lines += [
            f"- LLM calls: {totals['llm_calls']} (cap {totals['call_cap']}, worst case"
            f" {totals['worst_case_calls']}); tokens in {totals['tokens_in']},"
            f" out {totals['tokens_out']}",
            f"- Claims proposed {totals['proposed']}, accepted {totals['accepted']}, rejected"
            f" {totals['rejected']}: {_counts(totals['rejected_by_reason'])}",
            f"- reached the span check: {totals['reached_span_check']}; quote_mismatch"
            f" {totals['quote_mismatch']} (share {totals['quote_mismatch_share']};"
            f" above {DECISION_THRESHOLD:.0%}: {totals['exceeds_decision_threshold']})",
            f"- quote_mismatch quotes in their passage: exactly"
            f" {_counts(totals['quote_mismatch_by_occurrence'])}; folded"
            f" {_counts(totals['quote_mismatch_by_folded_occurrence'])}; located exactly-once"
            f" quotes that the later checks would accept: {totals['located_would_be_accepted']}",
            "",
            "## Extractions",
            "",
            "| extraction | job | status | passages | calls | tokens in/out |",
            "|---|---|---|---|---|---|",
        ]
        for e in results["extractions"]:
            lines.append(
                f"| {e['name']} | {e['job_status']} | {e['status']} | {len(e['passages'])} |"
                f" {e['llm_calls']} | {e['tokens_in']}/{e['tokens_out']} |"
            )
        lines += [
            "",
            "## Claims",
            "",
            "| # | extraction | predicate | outcome | reason_code | quote in passage"
            " | folded | after locating | quote |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for number, c in enumerate(results["claims"], start=1):
            quote = c["quote"][:80].replace("|", "\\|").replace("\n", " ")
            lines.append(
                f"| {number} | {c['extraction']} | {c['predicate']} | {c['outcome']} |"
                f" {c['reason_code'] or ''} | {_where(c)} | {c['folded_quote_in_passage'] or ''}"
                f" | {c['after_locating'] or ''} | {quote} |"
            )
        return "\n".join(lines) + "\n"


def parties(
    claim: dict[str, Any], companies: dict[str, dict[str, Any]], filer_id: str | None
) -> tuple[Party | None, Party | None]:
    """The Claim's subject and (company) object, with the names a quote may use for them."""

    def party(company_id: str | None) -> Party | None:
        company = companies.get(company_id or "")
        if company is None:
            return None
        names = company_names(company["display_name"], company["legal_name"])
        return Party(names, is_filer=company_id == filer_id)

    return party(claim["subject_company_id"]), party(claim["object_company_id"])


def _where(claim: dict[str, Any]) -> str:
    where = claim["quote_in_passage"]
    if where is None:
        return ""
    return f"{where} ({claim['occurrences']})" if where == "multiple" else where


def _counts(counts: dict[str, int]) -> str:
    return ", ".join(f"{key} {value}" for key, value in counts.items()) or "none"
