"""R2-04's measurement (offline): how many documents, and how far apart, the labelled
statements of the saved pilot cards cite, and what the dated grounds change.

For every labelled statement of the saved cards (`investigation.json`'s research card steps
joined to `review/workflow-result.json`'s `card.statements` by step and 1-based index) it
reports the distinct documents the statement's Facts cite, the spread in days of those
documents' dates (the Facts' `evidence_available_at`; a card whose Facts lack it falls back to
the `available_at` of `role-calls.json`'s Editor request, then to none) and whether the
statement names a date word (a year, a month name, "this year"...). Then it replays
`claim_grounds` + `ungrounded` over every saved statement (kept and set aside) without and
with the documents' dates, and lists any statement whose grounding verdict changes.

    uv run python .scratch/tools/statement_dates.py [--runs DIR]... [--json OUT]

Default runs: `pilot-0.5.3-arg` and `pilot-0.5.4-arg` under `.scratch/live-runs/` (of this
checkout, else of the main one). Nothing is fetched or written but the optional JSON.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from atlas.companies import load_universe
from atlas.investigations.grounding import claim_grounds, ungrounded

REPO = Path(__file__).resolve().parents[2]
DEFAULT_RUNS = ("pilot-0.5.3-arg", "pilot-0.5.4-arg")
MONTHS = (
    "january february march april may june july august september october november december"
).split()
DATE_WORD = re.compile(
    r"\b(?:20\d{2}|" + "|".join(MONTHS) + r"|fiscal|fy\d{2,4}|q[1-4]|this year|last year"
    r"|next year|by then|earlier|separately)\b",
    re.IGNORECASE,
)
LONG_APART_DAYS = 60
VERY_LONG_APART_DAYS = 120


def live_runs_dirs() -> list[Path]:
    """`.scratch/live-runs` of this checkout, then of the main one (a worktree's gitignored
    scratch is not copied)."""
    found = [REPO / ".scratch" / "live-runs"]
    try:
        common = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        found.append((REPO / common).resolve().parent / ".scratch" / "live-runs")
    except (OSError, subprocess.CalledProcessError):
        pass
    return [each for each in found if each.is_dir()]


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def day(value: str) -> date:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).date()


@dataclass
class Statement:
    run: str
    investigation: str
    step: str
    index: int
    text: str
    facts: list[dict[str, Any]]
    gate: str | None  # the label: pass / fail / None (unlabelled)
    kept: bool = True
    reason: str = ""  # why a set-aside statement was set aside
    documents: set[str] = field(default_factory=set)
    dates: list[date] = field(default_factory=list)

    @property
    def spread(self) -> int:
        return (max(self.dates) - min(self.dates)).days if self.dates else 0

    @property
    def names_a_date(self) -> bool:
        return bool(DATE_WORD.search(self.text))


def editor_dates(calls: Any) -> dict[str, str]:
    """A card without `evidence_available_at`: the Editor request's Facts by statement (a card
    written after R2-04 has `source_date` there)."""
    found: dict[str, str] = {}
    for call in calls.get("role_calls", []):
        if call["role"] == "editor" and call["prompt_name"].startswith("editor-argument"):
            for fact in call["request"].get("facts", []):
                if fact.get("source_date"):
                    found[fact["statement"]] = fact["source_date"]
    return found


def statements_of(run: Path) -> list[Statement]:
    found: list[Statement] = []
    for folder in sorted(run.glob("inv-*")):
        card_file, labels_file = folder / "investigation.json", folder / "review" / "workflow-result.json"
        if not card_file.is_file():
            continue
        card = load(card_file).get("research_card")
        if not card:
            continue
        labels: dict[tuple[str, int], str] = {}
        if labels_file.is_file():
            for each in load(labels_file)["card"]["statements"]:
                labels[(each["step"], int(each["index"]))] = each["trust_gate"]
        fallback = editor_dates(load(folder / "role-calls.json")) if (folder / "role-calls.json").is_file() else {}
        for step in card.get("steps", []):
            stood = step.get("statements") or (
                [{"statement": step["statement"], "facts": step.get("facts", [])}]
                if step.get("statement")
                else []
            )
            for index, each in enumerate(stood, start=1):
                item = Statement(
                    run.name,
                    folder.name,
                    step["step"],
                    index,
                    each["statement"],
                    each.get("facts", []),
                    labels.get((step["step"], index)),
                )
                for fact in item.facts:
                    moment = fact.get("evidence_available_at") or fallback.get(fact["statement"])
                    item.documents.add(fact["source_span"]["source_version_id"])
                    if moment:
                        item.dates.append(day(moment))
                found.append(item)
        known = {
            fact["fact_id"]: fact
            for step in card.get("steps", [])
            for fact in [
                *step.get("facts", []),
                *step.get("counterevidence", []),
                *(f for each in step.get("statements") or [] for f in each.get("facts", [])),
            ]
        }
        # A Fact set-aside statements cite but no kept statement does: from facts.json, with
        # its document's date and title from any card Fact of the same Source Version.
        by_version = {f["source_span"]["source_version_id"]: f for f in known.values()}
        by_company = {f["company_id"]: f["company_name"] for f in known.values()}
        if (folder / "facts.json").is_file():
            listed = load(folder / "facts.json")
            for item in listed["items"] if isinstance(listed, dict) else listed:
                version = item["assertion"]["source_version_id"]
                sibling = by_version.get(version)
                if item["id"] in known or not sibling:
                    continue
                known[item["id"]] = {
                    "fact_id": item["id"],
                    "company_id": item["assertion"]["subject_company_id"],
                    "company_name": by_company.get(
                        item["assertion"]["subject_company_id"], sibling["company_name"]
                    ),
                    "statement": item["statement"],
                    "source_title": sibling["source_title"],
                    "source_span": {
                        "quote": item["assertion"]["quote"],
                        "source_version_id": version,
                    },
                    "evidence_available_at": sibling["evidence_available_at"],
                }
        for each in card.get("unsupported_findings", []):
            found.append(
                Statement(
                    run.name,
                    folder.name,
                    "(set aside)",
                    0,
                    each["statement"],
                    [known[i] for i in each.get("claim_ids", []) if i in known],
                    None,
                    False,
                    reason=each.get("reason", ""),
                )
            )
    return found


def aliases() -> list[tuple[str, str]]:
    universe = load_universe(REPO / "configs" / "themes" / "ai-infrastructure.yaml")
    return [(each.display_name, each.legal_name) for each in universe.companies.values()]


def fact_row(fact: dict[str, Any], dated: bool) -> dict[str, Any]:
    """A cited Fact as the grounding check is given it (the columns `claim_grounds` reads)."""
    row: dict[str, Any] = {
        "quote": fact["source_span"]["quote"],
        "subject_name": fact["company_name"],
        "object_name": None,
        "object_text": None,  # the Editor's grounding rows carry no Fact statement
        "source_title": fact.get("source_title"),
    }
    if dated and fact.get("evidence_available_at"):
        row["available_at"] = datetime.fromisoformat(fact["evidence_available_at"].replace("Z", "+00:00"))
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--runs", action="append", help="a run directory (repeatable)")
    parser.add_argument("--json", help="write the per-statement rows here")
    args = parser.parse_args()
    runs: list[Path] = []
    for name in args.runs or DEFAULT_RUNS:
        direct = Path(name)
        candidates = [direct] if direct.is_dir() else [d / name for d in live_runs_dirs()]
        runs.append(next((c for c in candidates if c.is_dir()), direct))
    missing = [r for r in runs if not r.is_dir()]
    if missing:
        print("no such run:", *missing, file=sys.stderr)
        return 2

    everything = [s for run in runs for s in statements_of(run)]
    labelled = [s for s in everything if s.gate in {"pass", "fail"}]
    fails = [s for s in labelled if s.gate == "fail"]
    passes = [s for s in labelled if s.gate == "pass"]
    multi = [s for s in fails if len(s.documents) >= 2]
    print(f"labelled statements: {len(labelled)} ({len(fails)} fail, {len(passes)} pass)")
    print(f"fails citing 2+ documents: {len(multi)} of {len(fails)}")
    print(f"  of those, documents over {LONG_APART_DAYS} days apart: "
          f"{sum(1 for s in multi if s.spread > LONG_APART_DAYS)}")
    far_passes = [s for s in passes if len(s.documents) >= 2 and s.spread > VERY_LONG_APART_DAYS]
    print(f"passes citing documents over {VERY_LONG_APART_DAYS} days apart: {len(far_passes)}")
    print()
    print("run                 inv    step               #  gate  docs spread  names-a-date  statement")
    for s in sorted(multi + far_passes, key=lambda s: (s.gate != "fail", s.run, s.investigation, s.step, s.index)):
        print(
            f"{s.run:<19} {s.investigation:<6} {s.step:<18} {s.index}  {s.gate:<5} {len(s.documents):>3}"
            f" {s.spread:>6}  {'yes' if s.names_a_date else 'no':<12}  {s.text[:70]}"
        )
    print()
    print("fails by documents cited:", dict(sorted(Counter(len(s.documents) for s in fails).items())))
    print(
        "multi-document statements that name a date word:",
        f"{sum(1 for s in multi + far_passes if s.names_a_date)} of {len(multi) + len(far_passes)}",
    )

    # The replay: every saved statement with Facts, kept or set aside, grounded without and
    # with the dated grounds.
    names = aliases()
    changed: list[tuple[Statement, list[str], list[str]]] = []
    replayed = 0
    for s in everything:
        if not s.facts:
            continue
        replayed += 1
        before = ungrounded(s.text, claim_grounds("", [fact_row(f, False) for f in s.facts], names))
        after = ungrounded(s.text, claim_grounds("", [fact_row(f, True) for f in s.facts], names))
        if bool(before) != bool(after):
            changed.append((s, before, after))
    print()
    print(f"grounding replay over {replayed} saved statements with Facts: {len(changed)} change verdict")
    for s, before, after in changed:
        print(f"  {s.run} {s.investigation} {s.step}#{s.index} ({s.gate or 'unlabelled'}): "
              f"ungrounded {before} -> {after}: {s.text[:80]}")
        if s.reason:
            print(f"    set aside as: {s.reason[:120]}")
    became_ungrounded = [c for c in changed if c[2]]
    print(f"statements that become ungrounded: {len(became_ungrounded)} (must be 0)")
    dropped = [s for s in everything if s.reason.startswith("ungrounded")]
    now_grounded = sum(1 for s, _, a in changed if s.reason.startswith("ungrounded") and not a)
    print(f"statements set aside as ungrounded: {len(dropped)}; now grounded: {now_grounded}")
    judged_on_date = [
        x for x in everything if "without the quote stating" in x.reason or "this year" in x.reason
    ]
    print(
        f"statements the judge set aside over a date it could not see: {len(judged_on_date)}"
        " (not replayable offline: the judge is told the date from finding_judge.v4 on)"
    )
    if args.json:
        Path(args.json).write_text(
            json.dumps(
                [
                    {
                        "run": s.run,
                        "investigation": s.investigation,
                        "step": s.step,
                        "index": s.index,
                        "gate": s.gate,
                        "documents": len(s.documents),
                        "spread_days": s.spread,
                        "names_a_date": s.names_a_date,
                        "statement": s.text,
                    }
                    for s in everything
                ],
                indent=1,
            ),
            encoding="utf-8",
        )
    return 1 if became_ungrounded else 0


if __name__ == "__main__":
    raise SystemExit(main())
