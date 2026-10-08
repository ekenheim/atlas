"""Duplicate Facts across the saved pilot runs, by the rule the Reader applies (no database, no
LLM, no network).

    uv run --no-sync python .scratch/tools/fact_duplicates.py \
        [--data .scratch/live-runs/pilot-0.5.3-arg]... [--verbose]

Replays each investigation's Facts (`inv-<n>/facts.json`, oldest first by `created_at`, then
id) through `atlas.facts.duplicates.duplicate_of` (bottleneck-argument ticket 10; docs/
decisions.md, "One Fact per span"), as the Reader would have met them: each Fact against the
Facts kept before it, its own session's first (a session here is a step, the session key the
step), then the others oldest first. A Fact that matches is a duplicate and is not kept (in
production: refused to its own session, reused by another Reader). Rule (a): the same span or
the same folded quote; rule (b): an overlapping span with the same status and an alike
statement. Reports per run and question: Facts, duplicates by rule, duplicates across steps,
and how many wrong duplicates (`review/final-verdicts.json`) duplicate a wrong Fact (the
verdict that was counted again).
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from atlas.facts.duplicates import FactSpan, duplicate_of, normalized_quote  # noqa: E402


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def fact_span(fact: dict[str, Any]) -> FactSpan:
    assertion = fact["assertion"]
    return FactSpan(
        fact_id=uuid.UUID(fact["id"]),
        source_version_id=uuid.UUID(assertion["source_version_id"]),
        company_id=uuid.UUID(assertion["subject_company_id"]),
        span_start=assertion["span_start"],
        span_end=assertion["span_end"],
        quote=assertion["quote"],
        status=fact["status"],
        statement=fact["statement"],
        step=fact["step"],
        session_key=fact["step"],
    )


def rule_of(candidate: FactSpan, original: FactSpan) -> str:
    """`a` (the same span or folded quote) or `b` (overlap, same status, alike statement)."""
    same_span = (candidate.span_start, candidate.span_end) == (
        original.span_start,
        original.span_end,
    )
    same_quote = normalized_quote(candidate.quote) == normalized_quote(original.quote)
    return "a" if same_span or same_quote else "b"


def find_duplicates(items: list[dict[str, Any]]) -> dict[str, tuple[str, str]]:
    """Each duplicate Fact's id -> (the id of the kept Fact it duplicates, the rule)."""
    ordered = sorted(items, key=lambda f: (f["created_at"], f["id"]))
    kept: list[FactSpan] = []
    found: dict[str, tuple[str, str]] = {}
    for fact in ordered:
        candidate = fact_span(fact)
        own = [each for each in kept if each.session_key == candidate.session_key]
        others = [each for each in kept if each.session_key != candidate.session_key]
        match = duplicate_of(candidate, [*own, *others])
        if match is None:
            kept.append(candidate)
            continue
        found[fact["id"]] = (str(match.fact_id), rule_of(candidate, match))
    return found


def report(data: Path, verbose: bool) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for inv in sorted(data.glob("inv-*")):
        facts_path = inv / "facts.json"
        if not facts_path.exists():
            continue
        items = _load(facts_path)["items"]
        verdicts_path = inv / "review" / "final-verdicts.json"
        verdicts: dict[str, Any] = _load(verdicts_path) if verdicts_path.exists() else {}
        by_id = {f["id"]: f for f in items}
        duplicates = find_duplicates(items)
        rules = Counter(rule for _, rule in duplicates.values())
        across = sum(1 for d, (o, _) in duplicates.items() if by_id[d]["step"] != by_id[o]["step"])

        def verdict(fact_id: str, verdicts: dict[str, Any] = verdicts) -> str | None:
            return verdicts.get(fact_id, {}).get("verdict")

        wrong = [d for d in duplicates if verdict(d) == "wrong"]
        wrong_total = sum(1 for v in verdicts.values() if v.get("verdict") == "wrong")
        kept = len(items) - len(duplicates)
        row = {
            "facts": len(items),
            "duplicates": len(duplicates),
            "rule_a": rules["a"],
            "rule_b": rules["b"],
            "across_steps": across,
            "reviewed": bool(verdicts),
            "wrong_total": wrong_total,
            "wrong_duplicates": len(wrong),
            "right_duplicates": sum(1 for d in duplicates if verdict(d) == "right"),
            "wrong_duplicating_wrong": sum(
                1 for d in wrong if verdict(duplicates[d][0]) == "wrong"
            ),
        }
        if verdicts and items and kept:
            # Precision over the Facts, every one labelled: today, and with the duplicates gone.
            row["precision_today"] = round(1 - wrong_total / len(items), 3)
            row["precision_deduplicated"] = round(1 - (wrong_total - len(wrong)) / kept, 3)
        out[inv.name] = row
        print(f"{data.name}/{inv.name}: {json.dumps(row)}")
        if verbose:
            for d, (o, rule) in sorted(duplicates.items(), key=lambda kv: kv[1]):
                fd, fo = by_id[d], by_id[o]
                print(
                    f"   ({rule}) {d[:8]} ({fd['step']}, {fd['status']}, {verdict(d)})"
                    f" dup of {o[:8]} ({fo['step']}, {fo['status']}, {verdict(o)})"
                    f" span {fd['assertion']['span_start']}-{fd['assertion']['span_end']} vs"
                    f" {fo['assertion']['span_start']}-{fo['assertion']['span_end']}"
                )
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", action="append", type=Path, default=[])
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    data = args.data or [
        ROOT / ".scratch" / "live-runs" / f"pilot-{v}-arg" for v in ("0.5.3", "0.5.4", "0.5.5")
    ]
    totals: Counter[str] = Counter()
    for folder in data:
        for row in report(folder, args.verbose).values():
            if not row["reviewed"]:
                continue  # the totals are the reviewed runs'
            for key in (
                "facts",
                "duplicates",
                "rule_a",
                "rule_b",
                "across_steps",
                "wrong_total",
                "wrong_duplicates",
                "right_duplicates",
                "wrong_duplicating_wrong",
            ):
                totals[key] += row[key]
    print("TOTAL (reviewed runs):", json.dumps(dict(totals)))


if __name__ == "__main__":
    main()
