"""How far the argument plan's reading stays on the question's parts (pilot-review R2-01).

Reads the recorded argument runs offline (`.scratch/live-runs/pilot-0.5.3-arg` and
`pilot-0.5.4-arg`, gitignored: the quotes are licensed text) and prints, per question and
run:

- the Reader queries that name one of the question's terms (each Reader task's
  `searches` in `inv-<n>/investigation.json`), and
- the reviewed Facts by verdict (`inv-<n>/review/final-verdicts.json`) that carry one of the
  terms in their quote or statement (`inv-<n>/facts.json`).

Two term lists per question: the reviewers' (`TERMS`, written by hand from the question's own
words, as the R2-01 evidence counted them; case-insensitive, as written, anywhere in the text)
and code's fallback plan of the question (`atlas.investigations.question.fallback_plan`, the
plan a Reader gets when the planner's answer can't be had; matched as `names_a_part` matches a
query). A run after R2-01 adds the planner's own plan: the Scout task's `question_plan`, also
printed when the run has one.

    uv run --no-sync python .scratch/tools/question_parts_eval.py [--runs DIR ...]

Before R2-01 (2026-10-08): question 5, 0.5.4, the reviewers' terms: 6 of 24 queries; Facts
off-question 10 of 54, right 59 of 128.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from atlas.investigations.question import (  # noqa: E402
    QuestionPlan,
    fallback_plan,
    names_a_part,
)

RUNS = [ROOT / ".scratch" / "live-runs" / name for name in ("pilot-0.5.3-arg", "pilot-0.5.4-arg")]
VERDICTS = ("right", "off-question", "wrong")

# The reviewers' terms, by the question's number in the pilot (the R2-01 evidence's for
# question 5; the others from each question's own words).
TERMS: dict[int, list[str]] = {
    1: [
        "800G", "1.6T", "transceiver", "laser", "EML", "CW", "DFB", "VCSEL", "capacity", "InP",
        "indium phosphide", "substrate", "MOCVD", "Lumentum", "Coherent",
    ],
    2: [
        "indium phosphide", "InP", "substrate", "wafer", "laser", "export control", "gallium",
        "germanium", "indium",
    ],
    3: [
        "transceiver", "module", "assembly", "contract manufactur", "customer concentration",
        "qualification",
    ],
    4: ["DSP", "driver", "1.6T", "qualified", "second source", "LPO", "CPO"],
    5: [
        "coherent", "DCI", "ZR", "800ZR", "pluggable", "tunable", "ITLA", "narrow-linewidth",
        "pump", "CDM", "gold box", "Ciena", "modulator",
    ],
}  # fmt: skip


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _names_a_term(text: str, terms: Iterable[str]) -> bool:
    lowered = text.lower()
    return any(term.lower() in lowered for term in terms)


def _queries(investigation: dict[str, Any]) -> list[str]:
    return [
        str(search["query"])
        for task in investigation["tasks"]
        if task["role"] == "reader"
        for search in task["artifacts"].get("searches", [])
    ]


def _stored_plan(investigation: dict[str, Any]) -> QuestionPlan | None:
    for task in investigation["tasks"]:
        if task["key"] == "scout" and isinstance(task["artifacts"].get("question_plan"), dict):
            return QuestionPlan.model_validate(task["artifacts"]["question_plan"])
    return None


def _facts_line(verdicts: dict[str, Any], facts: dict[str, Any], carries: Any) -> str:
    counts: dict[str, list[int]] = {}
    for fact_id, verdict in verdicts.items():
        fact = facts.get(fact_id)
        if fact is None:
            continue
        text = f"{fact['assertion']['quote']} {fact['statement']}"
        tally = counts.setdefault(verdict["verdict"], [0, 0])
        tally[0] += bool(carries(text))
        tally[1] += 1
    shown = [f"{v} {counts[v][0]} of {counts[v][1]}" for v in VERDICTS if v in counts]
    shown += [f"{v} {n[0]} of {n[1]}" for v, n in sorted(counts.items()) if v not in VERDICTS]
    return ", ".join(shown)


def report(folder: Path, number: int) -> list[str]:
    investigation = _load(folder / "investigation.json")
    queries = _queries(investigation)
    verdict_file = folder / "review" / "final-verdicts.json"
    verdicts: dict[str, Any] = _load(verdict_file) if verdict_file.exists() else {}
    facts = {f["id"]: f for f in _load(folder / "facts.json")["items"]}
    lines = [f"{folder.parent.name} question {number}: {investigation['question']}"]
    terms = TERMS.get(number, [])
    named = [q for q in queries if _names_a_term(q, terms)]
    lines.append(f"  reviewers' terms: queries {len(named)} of {len(queries)}")
    if verdicts:
        lines.append(
            "    Facts carrying one: "
            + _facts_line(verdicts, facts, lambda text: _names_a_term(text, terms))
        )
    plans: list[tuple[str, QuestionPlan]] = [("fallback", fallback_plan(investigation["question"]))]
    stored = _stored_plan(investigation)
    if stored is not None:
        plans.insert(0, (f"stored ({stored.source})", stored))
    for name, plan in plans:
        keyed = [q for q in queries if names_a_part(q, plan) is not None]
        lines.append(f"  {name} plan's terms: queries {len(keyed)} of {len(queries)}")
        if verdicts:
            lines.append(
                "    Facts carrying one: "
                + _facts_line(
                    verdicts,
                    facts,
                    lambda text, plan=plan: names_a_part(text, plan) is not None,
                )
            )
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--runs", nargs="*", type=Path, default=RUNS)
    args = parser.parse_args(argv)
    for run in args.runs:
        for folder in sorted(run.glob("inv-*")):
            if not (folder / "investigation.json").exists():
                continue
            number = int(folder.name.split("-")[1])
            print("\n".join(report(folder, number)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
