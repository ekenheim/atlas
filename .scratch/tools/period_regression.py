"""The period check measured on the reviewed argument-plan Facts (no database, no LLM, no network).

    uv run --no-sync python .scratch/tools/period_regression.py \
        [--data .scratch/live-runs/pilot-0.5.3-arg --data .scratch/live-runs/pilot-0.5.4-arg] \
        [--max-right 2] [--min-listed 0] [--quiet]

R2-02 (`atlas.facts.periods`): for each `inv-<n>` under the `--data` folders (default the saved
0.5.3 and 0.5.4 pilots), join `facts.json` (the quote, statement and period), `review/final-verdicts.json`
(the reviewers' verdict by Fact id) and the document dates from `role-calls.json` (the Reader's
result items, `request.results[].items[].{source_version_id,date,company_slug}`), look up the
document company's fiscal calendar in the table below, and run `check_period`. Prints the
refusals by code and verdict with Fact ids, and the resolution `resolved_text` gives every Fact
whose quote holds a relative phrase. Exits 1 when right Facts refused exceed `--max-right`, or
fewer of the Facts the task listed as wrong are refused than `--min-listed`.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from atlas.assertions import InvalidAssertion  # noqa: E402
from atlas.facts.periods import (  # noqa: E402
    FiscalYearEnd,
    check_period,
    resolve,
    resolved_text,
)

DEFAULT_DATA = [
    ROOT / ".scratch" / "live-runs" / "pilot-0.5.3-arg",
    ROOT / ".scratch" / "live-runs" / "pilot-0.5.4-arg",
]
VERDICTS = ("right", "wrong", "off-question")
# The seven wrong Facts the task listed as the prototype's catches (8-character id prefixes).
LISTED_WRONG = (
    "8772cec7",
    "5279bc05",
    "a577e6e8",
    "a9f32c39",
    "896e96dc",
    "2c853d91",
    "7beff226",
)
# Fiscal year ends by company slug (month, day): the production lookup
# (`atlas.financials.calendar.fiscal_year_end`) reads them from filed 10-Ks; the saved runs have
# no database, so the pilot companies' are fixed here.
FISCAL_YEAR_ENDS: dict[str, FiscalYearEnd] = {
    "coherent": (6, 30),
    "lumentum": (6, 30),
    "fabrinet": (6, 30),
    "ciena": (10, 31),
    "marvell": (1, 31),
    "macom": (9, 30),
    "axt": (12, 31),
    "applied-optoelectronics": (12, 31),
    "iqe": (12, 31),
    "stmicroelectronics": (12, 31),
    "innolight": (12, 31),
    "soitec": (3, 31),
}


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def documents(role_calls: dict[str, Any]) -> dict[str, tuple[date, str]]:
    """Each Source Version the Reader was shown: its date and its company's slug."""
    found: dict[str, tuple[date, str]] = {}
    for call in role_calls["role_calls"]:
        request = call.get("request")
        if not isinstance(request, dict):
            continue
        for result in request.get("results") or []:
            for item in result.get("items") or []:
                if item.get("source_version_id") and item.get("date"):
                    found[item["source_version_id"]] = (
                        date.fromisoformat(item["date"]),
                        item.get("company_slug") or "",
                    )
    return found


def joined(data: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for folder in sorted(data.glob("inv-*")):
        verdicts = _load(folder / "review" / "final-verdicts.json")
        dated = documents(_load(folder / "role-calls.json"))
        for fact in _load(folder / "facts.json")["items"]:
            verdict = verdicts.get(fact["id"], {}).get("verdict")
            version = fact["assertion"]["source_version_id"]
            if verdict is None or version not in dated:
                continue
            day, slug = dated[version]
            rows.append(
                {
                    "where": f"{data.name}/{folder.name}",
                    "id": fact["id"],
                    "verdict": verdict,
                    "quote": fact["assertion"]["quote"],
                    "statement": fact["statement"],
                    "period": fact.get("period"),
                    "date": day,
                    "slug": slug,
                    "fye": FISCAL_YEAR_ENDS.get(slug),
                }
            )
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--data", type=Path, action="append")
    parser.add_argument("--max-right", type=int, default=2, help="right Facts it may refuse")
    parser.add_argument("--min-listed", type=int, default=0, help="listed wrong Facts it must refuse")
    parser.add_argument("--quiet", action="store_true", help="skip the resolutions")
    args = parser.parse_args(argv)
    rows = [row for data in (args.data or DEFAULT_DATA) for row in joined(data)]

    tested: Counter[str] = Counter()
    refused: dict[str, Counter[str]] = {}
    refusals: list[tuple[str, dict[str, Any], InvalidAssertion]] = []
    for row in rows:
        tested[row["verdict"]] += 1
        try:
            check_period(row["quote"], row["statement"], row["period"], row["date"], row["fye"])
        except InvalidAssertion as error:
            refused.setdefault(error.code, Counter())[row["verdict"]] += 1
            refusals.append((error.code, row, error))

    print(f"Facts joined: {len(rows)} (" + ", ".join(f"{tested[v]} {v}" for v in VERDICTS) + ")")
    print("Refused".ljust(26) + "".join(v.rjust(14) for v in VERDICTS))
    for code in ("period_misresolved", "period_other_document"):
        counts = refused.get(code, Counter())
        print(f"  {code:<24}" + "".join(str(counts[v]).rjust(14) for v in VERDICTS))
    print()
    for code, row, error in sorted(refusals, key=lambda each: (each[0], each[1]["verdict"])):
        print(
            f"{code} [{row['verdict']}] {row['id'][:8]} ({row['where']}, {row['slug']},"
            f" {row['date']}): {error.message}"
        )
        print(f"    period={row['period']!r} quote={row['quote'][:160]!r}")
    refused_ids = {row["id"][:8] for _, row, _ in refusals}
    listed = [each for each in LISTED_WRONG if each in refused_ids]
    right_refused = sum(1 for _, row, _ in refusals if row["verdict"] == "right")
    print()
    print(f"listed wrong Facts refused: {len(listed)} of {len(LISTED_WRONG)}")
    for each in LISTED_WRONG:
        print(f"  {each}: {'refused' if each in listed else 'NOT refused'}")
    if not args.quiet:
        print()
        print("Resolutions (Facts whose quote holds a relative phrase):")
        for row in rows:
            text = resolved_text(
                resolve(row["quote"], row["date"], row["fye"]), row["date"], row["fye"]
            )
            if text is not None:
                print(
                    f"  {row['id'][:8]} [{row['verdict']}] period={row['period']!r}: {text}"
                )
    print()
    print(f"right Facts refused: {right_refused} (max {args.max_right})")
    bad = right_refused > args.max_right or len(listed) < args.min_listed
    print("REGRESSION" if bad else "OK")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
