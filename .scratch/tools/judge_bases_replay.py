"""Replay the judge's basis check (R3-03) on saved argument cards.

For each `research_card.judged[*]` entry of the saved investigations, rebuild the metadata of
the documents its statement cites from the card's Facts (`company_name`, `source_title`,
`evidence_available_at`, by `claim_ids`), run the current
`atlas.investigations.meaning.verify_bases` on the entry's `clauses`, and print per card:

- first-attempt send-backs avoided: a finding sent back at attempt 1 for an unverified basis
  whose every attempt-1 vote was `supported` before the check and is clean now;
- drops rescued: the same for a finding dropped at attempt 2, whatever the reason (a clause that is one of the
  rewrite's limitations is not counted when the finding was drafted without limitations:
  the rewrite can no longer add them, so the judge is not sent them);
- the clauses still unverified.

    uv run python .scratch/tools/judge_bases_replay.py [--data DIR]...

`--data` is a pilot run folder (holding `inv-*/investigation.json`) or one investigation's
folder; by default the 0.5.4 and 0.5.5 argument pilots' folders under `.scratch/live-runs/`.
Reads saved files only; exit 0.
"""

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from atlas.investigations.grounding import date_texts  # noqa: E402
from atlas.investigations.meaning import verify_bases  # noqa: E402
from atlas.roles.contract import QuotedText  # noqa: E402
from atlas.roles.finding_judge import FindingJudgement, JudgedClause  # noqa: E402

DEFAULT_DATA = [
    ROOT / ".scratch" / "live-runs" / "pilot-0.5.4-arg",
    ROOT / ".scratch" / "live-runs" / "pilot-0.5.5-arg",
]


def cards(folders: list[Path]) -> list[tuple[str, dict[str, Any]]]:
    found: list[tuple[str, dict[str, Any]]] = []
    for folder in folders:
        files = (
            [folder / "investigation.json"]
            if (folder / "investigation.json").exists()
            else sorted(folder.glob("inv-*/investigation.json"))
        )
        for path in files:
            card = json.loads(path.read_text(encoding="utf-8"))["research_card"]
            found.append((f"{path.parent.parent.name}/{path.parent.name}", card))
    return found


def facts_of(card: dict[str, Any]) -> dict[str, dict[str, Any]]:
    facts: dict[str, dict[str, Any]] = {}
    for step in card.get("steps") or []:
        for fact in step["facts"] + step["counterevidence"]:
            facts[fact["fact_id"]] = fact
        for statement in step["statements"]:
            for fact in statement["facts"] + statement["counterevidence"]:
                facts[fact["fact_id"]] = fact
    return facts


def metadata(entry: dict[str, Any], facts: dict[str, dict[str, Any]]) -> list[str]:
    texts: list[str] = []
    for claim_id in entry["claim_ids"]:
        fact = facts.get(claim_id)
        if fact is None:
            continue
        texts.extend(fact[key] for key in ("company_name", "source_title") if fact.get(key))
        if fact.get("evidence_available_at"):
            at = datetime.fromisoformat(fact["evidence_available_at"].replace("Z", "+00:00"))
            texts.extend(date_texts(at.date()))
    return texts


def own_supported(entry: dict[str, Any]) -> bool:
    """The vote was `supported` before code checked its bases."""
    return entry["verdict"] == "supported" or entry["reason"].startswith("basis unverified")


def still_unverified(
    entry: dict[str, Any], facts: dict[str, dict[str, Any]], drafted_without_limitations: bool
) -> list[str]:
    clauses = [JudgedClause(**each) for each in entry.get("clauses") or []]
    limitations = entry.get("limitations") or []
    if drafted_without_limitations and limitations:
        clauses = [
            each
            for each in clauses
            if not any(each.text.strip() in limitation for limitation in limitations)
        ]
    judgement = FindingJudgement(
        clauses=clauses, verdict="supported", beyond=[], kinds=[], reason=""
    )
    # The quotes are not saved on the card: a clause with a basis is taken as its first
    # check found it (verified unless the card listed it as unverified).
    was = set(entry.get("unverified") or [])
    held: dict[str, list[str]] = {}
    for each in clauses:
        if each.ref and each.basis and each.text not in was:
            held.setdefault(each.ref, []).append(each.basis)
    quotes = [
        QuotedText(id=ref, source="", text=" ||| ".join(bases)) for ref, bases in held.items()
    ]
    return verify_bases(judgement, quotes, metadata=metadata(entry, facts))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", type=Path, action="append")
    args = parser.parse_args()
    totals: Counter[str] = Counter()
    for name, card in cards(args.data or DEFAULT_DATA):
        facts = facts_of(card)
        by_finding: dict[str, list[dict[str, Any]]] = {}
        for entry in card.get("judged") or []:
            by_finding.setdefault(entry["finding"], []).append(entry)
        counts: Counter[str] = Counter()
        left: list[str] = []
        for entries in by_finding.values():
            first = [e for e in entries if e["attempt"] == 1]
            second = [e for e in entries if e["attempt"] == 2]
            without = not (first and first[0].get("limitations"))
            for attempt, votes, outcome, label in (
                (1, first, "sent_back", "sent_back"),
                (2, second, "dropped", "dropped"),
            ):
                if not votes:
                    continue
                decided = next((e for e in votes if e.get("decided")), votes[0])
                if decided["outcome"] != outcome:
                    continue
                if attempt == 1 and not decided["reason"].startswith("basis unverified"):
                    continue
                counts[label] += 1
                rest = [
                    still_unverified(e, facts, without and attempt == 2)
                    for e in votes
                    if own_supported(e)
                ]
                if all(own_supported(e) for e in votes) and not any(rest):
                    counts[f"{label}_rescued"] += 1
                for each in rest:
                    left.extend(each)
        totals.update(counts)
        print(
            f"{name}: first-attempt send-backs avoided {counts['sent_back_rescued']}"
            f" of {counts['sent_back']}; drops rescued {counts['dropped_rescued']}"
            f" of {counts['dropped']}; clauses still unverified {len(left)}"
        )
        for clause in left:
            print(f"    still unverified: {clause[:120]}")
    print(
        f"TOTAL: first-attempt send-backs avoided {totals['sent_back_rescued']}"
        f" of {totals['sent_back']}; drops rescued {totals['dropped_rescued']}"
        f" of {totals['dropped']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
