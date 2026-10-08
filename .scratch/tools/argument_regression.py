"""The standing regression check on the 0.5.3 argument-plan reviews (no database, no LLM, no network).

    uv run --no-sync python .scratch/tools/argument_regression.py \
        [--data .scratch/live-runs/pilot-0.5.3-arg] \
        [--labels tests/fixtures/pilot-0.5.3-argument/labels.json] \
        [--max-right 0] [--max-pass-flagged 2]

The labels (`argument_labels.py`: Facts with the reviewers' verdicts, card statements with
their trust gate, counter-Facts) are committed. The quotes are licensed transcript text and
live only in `--data` (`inv-<n>/facts.json`, else the 400-character cut in
`inv-<n>/review/facts-compact.json`; `inv-<n>/investigation.json` for the question), so this joins them locally and runs every deterministic check Atlas has:

- Facts: `atlas.facts.service.check_status`, `check_quantity` and (R2-02) `check_period`, each
  Fact against its quote (`check_period` also against its document's date and fiscal calendar,
  joined from `inv-<n>/facts.json` and `role-calls.json`; skipped without them).
  Refusals are counted by the reviewers' verdict. A check that refuses right Facts is a regression.
- Statements: `atlas.investigations.grounding.ungrounded` against the grounds of the Facts a
  statement cites (and the question), and `atlas.investigations.argument.without_references`.
  A statement the trust gate passed that a check flags is a regression; a failing one it
  flags is a catch.
- A step-status replay through `atlas.investigations.argument.build_steps`, once it takes
  `relations`.

Each check is looked up with `getattr` when it runs, so a check a later change adds is used
as soon as it exists and reported `skipped` until then. Prints one table; exits 1 when right
Facts refused exceed `--max-right` or passing statements flagged exceed `--max-pass-flagged`.
"""

from __future__ import annotations

import argparse
import inspect
import json
import sys
from collections import Counter
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import period_regression  # noqa: E402
from atlas.assertions import InvalidAssertion  # noqa: E402
from atlas.facts.periods import FiscalYearEnd  # noqa: E402
from atlas.facts import service as facts_service  # noqa: E402
from atlas.investigations import argument as argument_module  # noqa: E402
from atlas.investigations import grounding  # noqa: E402

DEFAULT_LABELS = ROOT / "tests" / "fixtures" / "pilot-0.5.3-argument" / "labels.json"
DEFAULT_DATA = ROOT / ".scratch" / "live-runs" / "pilot-0.5.3-arg"
VERDICTS = ("right", "wrong", "off-question")


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def join_quotes(labels: dict[str, Any], data: Path) -> tuple[dict[tuple[int, str], str], dict[int, str]]:
    """The local quotes by (investigation, fact id), and each investigation's question."""
    quotes: dict[tuple[int, str], str] = {}
    questions: dict[int, str] = {}
    for n in sorted({f["investigation"] for f in labels["facts"]}):
        compact = data / f"inv-{n}" / "review" / "facts-compact.json"
        if not compact.exists():
            raise SystemExit(f"missing {compact}: the quotes are not in git; pass --data")
        for row in _load(compact):
            quotes[(n, row["fact_id"])] = row["quote"]
        # facts-compact cuts a quote at 400 characters; the Facts listing holds it whole.
        listing = data / f"inv-{n}" / "facts.json"
        if listing.exists():
            for item in _load(listing)["items"]:
                quotes[(n, item["id"])] = item["assertion"]["quote"]
        investigation = data / f"inv-{n}" / "investigation.json"
        questions[n] = _load(investigation).get("question", "") if investigation.exists() else ""
    return quotes, questions


def _bind(check: Callable[..., Any], available: dict[str, Any]) -> dict[str, Any] | None:
    """The keyword arguments `check` asks for, from `available`; None if it asks for others."""
    arguments: dict[str, Any] = {}
    for name, parameter in inspect.signature(check).parameters.items():
        if name in available:
            arguments[name] = available[name]
        elif parameter.default is inspect.Parameter.empty and parameter.kind in (
            parameter.POSITIONAL_OR_KEYWORD,
            parameter.KEYWORD_ONLY,
        ):
            return None
    return arguments


def _fact_available(fact: dict[str, Any], quote: str) -> dict[str, Any]:
    quantity = fact.get("quantity")
    available: dict[str, Any] = {
        "quote": quote,
        "status": fact["status"],
        "statement": fact["statement"],
        "period": fact.get("period"),
        "step": fact["step"],
    }
    if quantity:
        available["quantity"] = facts_service.Quantity(**quantity)
    return available


def join_documents(
    labels: dict[str, Any], data: Path
) -> dict[tuple[int, str], tuple[date, FiscalYearEnd | None]]:
    """The document date and fiscal year end of each Fact, from `inv-<n>/facts.json` and the
    Reader's result items in `inv-<n>/role-calls.json` (R2-02's `period_regression.py` joins
    them the same way); empty when the folder holds neither."""
    found: dict[tuple[int, str], tuple[date, FiscalYearEnd | None]] = {}
    for n in sorted({f["investigation"] for f in labels["facts"]}):
        listing, calls = data / f"inv-{n}" / "facts.json", data / f"inv-{n}" / "role-calls.json"
        if not (listing.exists() and calls.exists()):
            continue
        dated = period_regression.documents(_load(calls))
        for item in _load(listing)["items"]:
            version = item["assertion"]["source_version_id"]
            if version in dated:
                day, slug = dated[version]
                found[(n, item["id"])] = (day, period_regression.FISCAL_YEAR_ENDS.get(slug))
    return found


def fact_check_rows(
    labels: dict[str, Any],
    quotes: dict[tuple[int, str], str],
    documents: dict[tuple[int, str], tuple[date, FiscalYearEnd | None]] | None = None,
) -> tuple[list[tuple[str, str | dict[str, tuple[int, int]]]], int]:
    """Per Fact check: `skipped (why)` or {verdict: (refused, tested)}. And right Facts refused."""
    rows: list[tuple[str, str | dict[str, tuple[int, int]]]] = []
    right_refused = 0
    documents = documents or {}
    for name, needs in (
        ("check_status", None),
        ("check_quantity", "quantity"),
        ("check_period", "document_date"),
    ):
        check = getattr(facts_service, name, None)
        if check is None:
            rows.append((name, "skipped (not in atlas.facts.service yet)"))
            continue
        if needs == "document_date" and not documents:
            rows.append((name, "skipped (no document dates: needs facts.json and role-calls.json)"))
            continue
        refused: Counter[str] = Counter()
        tested: Counter[str] = Counter()
        unsupported = False
        for fact in labels["facts"]:
            available = _fact_available(fact, quotes[(fact["investigation"], fact["fact_id"])])
            document = documents.get((fact["investigation"], fact["fact_id"]))
            if document is not None:
                available["document_date"], available["fye"] = document
            if needs and needs not in available:
                continue
            arguments = _bind(check, available)
            if arguments is None:
                unsupported = True
                break
            tested[fact["verdict"]] += 1
            try:
                check(**arguments)
            except InvalidAssertion:
                refused[fact["verdict"]] += 1
                if fact["verdict"] == "right":
                    right_refused += 1
        if unsupported:
            rows.append((name, "skipped (signature not understood)"))
        else:
            rows.append((name, {v: (refused[v], tested[v]) for v in VERDICTS}))
    return rows, right_refused


def statement_flags(
    labels: dict[str, Any], quotes: dict[tuple[int, str], str], questions: dict[int, str]
) -> tuple[dict[str, str | dict[str, tuple[int, int]]], int]:
    """Per statement check: `skipped` or {"fail": (caught, failing), "pass": (flagged, passing)}."""
    facts = {(f["investigation"], f["fact_id"]): f for f in labels["facts"]}
    ungrounded = getattr(grounding, "ungrounded", None)
    claim_grounds = getattr(grounding, "claim_grounds", None)
    without_references = getattr(argument_module, "without_references", None)
    flagged: dict[str, Counter[str]] = {"ungrounded": Counter(), "without_references": Counter()}
    totals: Counter[str] = Counter()
    for statement in labels["statements"]:
        gate = "pass" if statement["trust_gate"] == "pass" else "fail"
        totals[gate] += 1
        n = statement["investigation"]
        cited = [
            {
                "quote": quotes[(n, i)],
                "subject_name": facts[(n, i)]["company"],
                "source_title": facts[(n, i)].get("source_title"),
            }
            for i in statement["fact_ids"] + statement["counter_fact_ids"]
            if (n, i) in facts
        ]
        if ungrounded and claim_grounds:
            ground = claim_grounds(questions.get(n, ""), cited)
            if ungrounded(statement["text"], ground):
                flagged["ungrounded"][gate] += 1
        if without_references:
            refs = {f"c{k}": {"subject_name": c["subject_name"]} for k, c in enumerate(cited, 1)}
            if without_references(statement["text"], list(refs), refs) is None:
                flagged["without_references"][gate] += 1
    present = {
        "ungrounded": bool(ungrounded and claim_grounds),
        "without_references": without_references is not None,
    }
    rows: dict[str, str | dict[str, tuple[int, int]]] = {}
    for name in flagged:
        if present[name]:
            rows[name] = {
                "fail": (flagged[name]["fail"], totals["fail"]),
                "pass": (flagged[name]["pass"], totals["pass"]),
            }
        else:
            rows[name] = "skipped (not in atlas yet)"
    pass_flagged = sum(flagged[name]["pass"] for name in flagged if present[name])
    return rows, pass_flagged


def step_replay_row() -> str:
    build_steps = getattr(argument_module, "build_steps", None)
    if build_steps is None:
        return "skipped (build_steps not found)"
    if "relations" not in inspect.signature(build_steps).parameters:
        return "skipped (build_steps takes no `relations` yet)"
    return "skipped (build_steps takes `relations`; the replay needs the relation labels)"


def render(
    fact_rows: list[tuple[str, str | dict[str, tuple[int, int]]]],
    statement_rows: dict[str, str | dict[str, tuple[int, int]]],
    replay: str,
) -> list[str]:
    lines = ["Facts (refused / tested)".ljust(34) + "".join(v.rjust(14) for v in VERDICTS)]
    for name, row in fact_rows:
        if isinstance(row, str):
            lines.append(f"  {name:<32}{row}")
        else:
            lines.append(f"  {name:<32}" + "".join(f"{row[v][0]} / {row[v][1]}".rjust(14) for v in VERDICTS))
    lines.append("Statements".ljust(34) + "fails caught".rjust(16) + "passes flagged".rjust(18))
    for name, row in statement_rows.items():
        if isinstance(row, str):
            lines.append(f"  {name:<32}{row}")
        else:
            caught, flagged = row["fail"], row["pass"]
            lines.append(
                f"  {name:<32}"
                + f"{caught[0]} / {caught[1]}".rjust(16)
                + f"{flagged[0]} / {flagged[1]}".rjust(18)
            )
    lines.append(f"Step status replay: {replay}")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--max-right", type=int, default=0, help="right Facts a check may refuse")
    parser.add_argument("--max-pass-flagged", type=int, default=2, help="passing statements a check may flag")
    args = parser.parse_args(argv)
    labels = _load(args.labels)
    quotes, questions = join_quotes(labels, args.data)

    fact_rows, right_refused = fact_check_rows(labels, quotes, join_documents(labels, args.data))
    statement_rows, pass_flagged = statement_flags(labels, quotes, questions)
    for line in render(fact_rows, statement_rows, step_replay_row()):
        print(line)
    print(f"right Facts refused: {right_refused} (max {args.max_right})")
    print(f"passing statements flagged: {pass_flagged} (max {args.max_pass_flagged})")
    bad = right_refused > args.max_right or pass_flagged > args.max_pass_flagged
    print("REGRESSION" if bad else "OK")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
