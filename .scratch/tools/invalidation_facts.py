"""The invalidation step on the saved argument-plan runs (pilot-review R2-03; offline: no
database, no LLM, no network).

    uv run --no-sync python .scratch/tools/invalidation_facts.py \
        [--data .scratch/live-runs/pilot-0.5.3-arg --data .scratch/live-runs/pilot-0.5.4-arg] \
        [--list]

Each `--data` folder holds `inv-<n>/facts.json` (`GET /api/v1/facts?investigation_id=`) and
`inv-<n>/investigation.json` (`GET /api/v1/investigations/{id}`), as `pilot_runs.py` saves
them. It

1. counts every saved Fact filed under the invalidation step (the Readers' and the Skeptic's)
   by a cue proxy over its statement: `for` the thesis (sold out, record, doubling, leading,
   book-to-bill, demand outpacing capacity, ...), `against` it (not constrained, caught up,
   inventory, cancellations, price cuts, second sources, substitutes, alternatives, hedges,
   ...; checked first) or `neither`; `--list` prints each Fact with its label. The review
   reported 96 for / 23 against / 92 neither on the 8 runs; its own cue list was not saved,
   so these lists are the ones that reproduce those counts, read against the statements.
2. replays `atlas.investigations.argument.build_steps` over each saved card's Facts, kept
   statements, Reader sessions and counter-judge labels, with the invalidation Facts judged
   (a) every one `supports` the thesis Facts it is judged against (`thesis_facts`), and
   (b) the proxy's `against` Facts `contradicts`, the rest `supports`,
   and prints the invalidation step's status per card beside the saved one.

A run without a card (the Editor failed) is counted in (1) and skipped in (2).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from collections import Counter
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import RowMapping  # noqa: E402

from atlas.investigations.argument import (  # noqa: E402
    ArgumentFacts,
    ArgumentSession,
    KeptStatement,
    StepStatement,
    build_steps,
    thesis_facts,
)
from atlas.investigations.reader import ReaderState  # noqa: E402

DEFAULT_DATA = [
    ROOT / ".scratch" / "live-runs" / "pilot-0.5.3-arg",
    ROOT / ".scratch" / "live-runs" / "pilot-0.5.4-arg",
]

# Checked first: what would weaken the argument (or names what would, like Ciena's "no
# inventory build-up", which a proxy cannot tell apart).
AGAINST = [
    r"not constrained",
    r"caught up",
    r"inventory",
    r"cancel",
    r"price (cut|decrease|reduction)",
    r"second source",
    r"substitut",
    r"alternat",
    r"multi-source",
    r"dual sourc",
    r"hedge",
    r"external suppliers",
    r"push(ed)?[- ]out",
    r"cautious",
    r"uncertain",
    r"multiple .*suppliers",
]
# What argues for the thesis: scarcity, records, growth, leadership.
FOR = [
    r"sold out",
    r"record",
    r"doubl",
    r"leading",
    r"book-to-bill",
    r"tripl",
    r"outpace",
    r"not be able to meet",
    r"cannot supply",
    r"behind .*demand",
    r"primary constraint",
    r"limited by its production capacity",
    r"exceed",
    r"strong",
    r"extraordinar",
    r"over 100%",
    r"3x",
    r"80%",
    r"growth",
    r"first",
    r"largest",
    r"only company",
    r"shortage",
    r"sought-after",
    r"backlog",
    r"lead in",
    r"visibility",
    r"very little competition",
]


def cue(statement: str) -> str:
    """The proxy's label of a Fact's statement: against, for or neither."""
    said = statement.lower()
    if any(re.search(each, said) for each in AGAINST):
        return "against"
    if any(re.search(each, said) for each in FOR):
        return "for"
    return "neither"


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _when(value: str | None) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _row(fact: dict[str, Any], shown: dict[str, dict[str, Any]]) -> RowMapping:
    """A saved Fact as `argument_facts` reads it, completed from the card where it is shown."""
    assertion = fact["assertion"]
    on_card = shown.get(fact["id"], {})
    row: dict[str, Any] = {
        "id": uuid.UUID(fact["id"]),
        "assertion_id": uuid.UUID(fact["id"]),
        "step": fact["step"],
        "value_json": assertion["value_json"],
        "subject_company_id": uuid.UUID(assertion["subject_company_id"]),
        "subject_name": on_card.get("company_name", assertion["subject_company_id"]),
        "subject_slug": "",
        "quote": assertion["quote"],
        "source_version_id": uuid.UUID(assertion["source_version_id"]),
        "span_start": assertion["span_start"],
        "span_end": assertion["span_end"],
        "verification_status": assertion.get("review_state", "unreviewed"),
        "source_title": on_card.get("source_title", ""),
        "available_at": _when(on_card.get("evidence_available_at") or fact["created_at"]),
    }
    return cast(RowMapping, row)


class Run:
    """One saved investigation: its Facts, card and tasks."""

    def __init__(self, folder: Path) -> None:
        self.name = f"{folder.parent.name}/{folder.name}"
        self.facts: list[dict[str, Any]] = _load(folder / "facts.json")["items"]
        self.investigation: dict[str, Any] = _load(folder / "investigation.json")
        self.card: dict[str, Any] | None = self.investigation.get("research_card")
        self.tasks = {task["key"]: task for task in self.investigation["tasks"]}

    def invalidation(self) -> list[dict[str, Any]]:
        return [fact for fact in self.facts if fact["step"] == "invalidation"]

    def steps(self) -> list[dict[str, Any]]:
        return list((self.card or {}).get("steps") or [])

    def replay(self, relation: Callable[[dict[str, Any]], str]) -> str:
        """The invalidation step's status, rebuilt with each invalidation Reader Fact judged
        `relation(fact)` against its thesis Facts."""
        shown: dict[str, dict[str, Any]] = {}
        for step in self.steps():
            for each in [*step["facts"], *step["counterevidence"]]:
                shown[each["fact_id"]] = each
        readers = [
            f for f in self.facts if f["assertion"]["extractor_version"].startswith("reader")
        ]
        skeptics = [
            f for f in self.facts if f["assertion"]["extractor_version"].startswith("skeptic")
        ]
        supporting = [_row(f, shown) for f in readers]
        counter = [_row(f, shown) for f in skeptics]
        skeptic = self.tasks.get("skeptic", {})
        artifacts: dict[str, Any] = skeptic.get("artifacts") or {}
        labels: dict[str, dict[str, str]] = artifacts.get("counter_relations") or {}
        against: dict[uuid.UUID, list[uuid.UUID]] = {}
        for row in counter:
            key = str(row["id"])
            if key in labels:
                against[row["id"]] = [uuid.UUID(each) for each in labels[key]]
            else:
                card = shown.get(key, {})
                named = [
                    *card.get("against", []),
                    *(r["fact_id"] for r in card.get("relations", [])),
                ]
                against[row["id"]] = [uuid.UUID(each) for each in dict.fromkeys(named)]
        relations = {
            uuid.UUID(k): {uuid.UUID(f): r for f, r in v.items()} for k, v in labels.items()
        }
        request: dict[str, Any] = self.investigation.get("request") or {}
        seeds = [uuid.UUID(each) for each in request.get("seed_entity_ids") or []]
        by_id = {f["id"]: f for f in readers}
        invalidation: dict[uuid.UUID, dict[uuid.UUID, str]] = {}
        for row in supporting:
            if row["step"] != "invalidation":
                continue
            label = relation(by_id[str(row["id"])])
            invalidation[row["id"]] = {
                thesis["id"]: label for thesis in thesis_facts(supporting, row, seeds)
            }
        sessions = [
            ArgumentSession(
                task_key=key,
                round=task.get("round", 1),
                role=task["role"],
                step=(task.get("artifacts") or {}).get("step", ""),
                status=task["status"],
                state=ReaderState(
                    searches=(task.get("artifacts") or {}).get("searches") or [],
                    summary=(task.get("artifacts") or {}).get("summary"),
                ),
            )
            for key, task in self.tasks.items()
            if task["role"] in ("reader", "skeptic") and task.get("artifacts")
        ]
        facts = ArgumentFacts(
            sessions=sessions,
            supporting=supporting,
            counter=counter,
            against=against,
            relations=relations,
            invalidation=invalidation,
        )
        rows = [*supporting, *counter]
        refs = {f"c{n}": row for n, row in enumerate(rows, start=1)}
        ref_of = {str(row["id"]): ref for ref, row in refs.items()}
        statements: dict[str, StepStatement] = {}
        for step in self.steps():
            kept = [
                KeptStatement(
                    said["statement"],
                    [
                        ref_of[each["fact_id"]]
                        for each in [*said["facts"], *said["counterevidence"]]
                        if each["fact_id"] in ref_of
                    ],
                    said.get("judged"),
                )
                for said in step.get("statements") or []
            ]
            statements[step["step"]] = StepStatement(
                kept=kept, editor_status=step.get("editor_status"), unchecked=[]
            )
        checked = {uuid.UUID(each) for each in artifacts.get("challenged_fact_ids") or []}
        built = build_steps(facts, statements, refs, checked, skeptic.get("status") == "succeeded")
        return {step.step: step.status for step in built}["invalidation"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--data", type=Path, action="append")
    parser.add_argument("--list", action="store_true", help="print each Fact with its label")
    args = parser.parse_args()
    folders = [
        inv
        for data in (args.data or DEFAULT_DATA)
        for inv in sorted(data.glob("inv-*"))
        if (inv / "facts.json").exists() and (inv / "investigation.json").exists()
    ]
    runs = [Run(folder) for folder in folders]

    total: Counter[str] = Counter()
    print(f"{'run':<24} {'facts':>5} {'for':>4} {'against':>7} {'neither':>7}")
    for run in runs:
        counts = Counter(cue(fact["statement"]) for fact in run.invalidation())
        total += counts
        print(
            f"{run.name:<24} {len(run.invalidation()):>5} {counts['for']:>4}"
            f" {counts['against']:>7} {counts['neither']:>7}"
        )
        if args.list:
            for fact in run.invalidation():
                print(f"    {cue(fact['statement']):<8} {fact['statement'][:140]}")
    print(
        f"{'all':<24} {sum(total.values()):>5} {total['for']:>4} {total['against']:>7}"
        f" {total['neither']:>7}"
    )

    print()
    print(f"{'card':<24} {'saved':<10} {'(a) supports':<14} {'(b) proxy':<14}")
    statuses: Counter[str] = Counter()
    cards = 0
    for run in runs:
        if not run.steps():
            print(f"{run.name:<24} (no card)")
            continue
        cards += 1
        saved = next(s["status"] for s in run.steps() if s["step"] == "invalidation")
        every_supports = run.replay(lambda _: "supports")
        by_proxy = run.replay(
            lambda fact: "contradicts" if cue(fact["statement"]) == "against" else "supports"
        )
        statuses[every_supports] += 1
        print(f"{run.name:<24} {saved:<10} {every_supports:<14} {by_proxy:<14}")
    print(
        f"(a): {statuses['nothing_found']} of {cards} nothing_found"
        + "".join(f", {n} {s}" for s, n in sorted(statuses.items()) if s != "nothing_found")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
