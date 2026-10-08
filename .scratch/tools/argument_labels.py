"""Cut the 0.5.3 argument-plan reviews into a committable labels file.

The reviews live in `.scratch/live-runs/pilot-0.5.3-arg/inv-<n>/` (gitignored: the
quotes are licensed transcript text). This script keeps everything that is Atlas's
or the reviewers' own words (a Fact's statement, status, period, quantity, the
verdict and its reason, a card statement with its trust gate) and drops every quote
and every piece of context.

    uv run --no-sync python .scratch/tools/argument_labels.py \
        [--data .scratch/live-runs/pilot-0.5.3-arg] \
        [--out tests/fixtures/pilot-0.5.3-argument/labels.json]

`build(folder)` is the testable seam: it reads `<folder>/inv-<n>/review/
{final-verdicts,facts-compact,workflow-result}.json` and `<folder>/inv-<n>/
investigation.json` and returns the labels as a dict. No database, no network.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA = ROOT / ".scratch" / "live-runs" / "pilot-0.5.3-arg"
DEFAULT_OUT = ROOT / "tests" / "fixtures" / "pilot-0.5.3-argument" / "labels.json"

# A reason is sorted into the first category whose pattern it matches. Order matters:
# a reason that names the status is `status` even if it also says two facts merged.
# The categories are a convenience for counting, not a judgement; the reviewers'
# own `reason` stays beside them.
CATEGORY_RULES: tuple[tuple[str, str], ...] = (
    (
        "status",
        r"\bstatus\b|in_effect|in_development|in effect|in development|\bplanned\b|\bhedged\b|"
        r"\bregulatory\b|reported_by_third_party|forecast|expectation|future tense|forward[- ]looking|"
        r"forward expectation|future commitment",
    ),
    ("merged", r"\bmerg\w*|two facts|three facts|several facts"),
    (
        "context_added",
        r"(from|in) the (context|preceding|following|next|later|previous)|context_(after|before)|"
        r"not in the quote|comes? from (the )?(context|next|preceding|following|headline|a later)|"
        r"the model's addition|adds? (an inference|the )",
    ),
    ("period", r"\bperiod\b|calendar|fiscal|\bquarter\b|\bq[1-4]\b"),
    ("quantity", r"\bquantity\b|\bfigure\b|\bamount\b|range to|collapses"),
    (
        "misreading",
        r"refers? to|referent|misattribut|attribut|announced by|\bwrong\b|garbles|misread|questioner|"
        r"hypothetical|overstates|narrows|widens|\bnever says\b|does not mention|nothing in it",
    ),
)

STATUS_CATEGORY = "status"
MIN_QUOTE_LEN_FOR_SUBSTRING_CHECK = 80


def categorise(reason: str | None) -> str:
    """The keyword category of a reviewer's reason ("other" when none matches)."""
    if not reason:
        return "other"
    text = reason.lower()
    for name, pattern in CATEGORY_RULES:
        if re.search(pattern, text):
            return name
    return "other"


def _load(path: Path) -> Any:
    with path.open(encoding="utf8") as handle:
        return json.load(handle)


def _investigations(folder: Path) -> list[int]:
    found = sorted(
        int(p.name.removeprefix("inv-"))
        for p in folder.glob("inv-*")
        if p.is_dir() and p.name.removeprefix("inv-").isdigit()
    )
    if not found:
        raise SystemExit(f"no inv-<n> folders under {folder}")
    return found


def _judge_entries(card: dict[str, Any], text: str, cited: set[str]) -> list[dict[str, Any]]:
    """The finding judge's verdicts for one statement: by its text, else by its cited ids."""
    judged = card.get("judged") or []
    by_text = [j for j in judged if j.get("statement") == text]
    chosen = by_text or [j for j in judged if cited and set(j.get("claim_ids") or []) == cited]
    return [
        {
            "attempt": j.get("attempt"),
            "verdict": j.get("verdict"),
            "outcome": j.get("outcome"),
            "kinds": list(j.get("kinds") or []),
        }
        for j in chosen
    ]


def _investigation_labels(
    folder: Path, n: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], set[str]]:
    base = folder / f"inv-{n}"
    review = base / "review"
    verdicts: dict[str, Any] = _load(review / "final-verdicts.json")
    compact: list[dict[str, Any]] = _load(review / "facts-compact.json")
    workflow: dict[str, Any] = _load(review / "workflow-result.json")
    investigation: dict[str, Any] = _load(base / "investigation.json")
    card: dict[str, Any] = investigation.get("research_card") or {}
    steps: list[dict[str, Any]] = card.get("steps") or []

    # Titles are only known for Facts a card step carries.
    titles: dict[str, str | None] = {}
    for step in steps:
        for fact in step.get("facts") or []:
            titles[fact["fact_id"]] = fact.get("source_title")
        for statement in step.get("statements") or []:
            for fact in statement.get("facts") or []:
                titles.setdefault(fact["fact_id"], fact.get("source_title"))
        for fact in step.get("counterevidence") or []:
            titles.setdefault(fact["fact_id"], fact.get("source_title"))

    quotes: set[str] = {f["quote"] for f in compact if f.get("quote")}
    listing = base / "facts.json"  # facts-compact cuts a quote at 400 characters; this holds it whole
    if listing.exists():
        quotes |= {i["assertion"]["quote"] for i in _load(listing)["items"] if i.get("assertion")}

    facts: list[dict[str, Any]] = []
    for f in compact:
        v = verdicts[f["fact_id"]]
        reason = v.get("reason")
        facts.append(
            {
                "fact_id": f["fact_id"],
                "investigation": n,
                "company": f.get("company"),
                "step": f.get("step"),
                "status": f.get("status"),
                "statement": f.get("statement"),
                "quantity": f.get("quantity"),
                "period": f.get("period"),
                "source_title": titles.get(f["fact_id"]),
                "verdict": v["verdict"],
                "by": v["by"],
                "reason": reason,
                "right_reading": v.get("right_reading"),
                "reviewer_a": v.get("A"),
                "reviewer_b": v.get("B"),
                "category": categorise(reason) if v["verdict"] == "wrong" else None,
            }
        )

    review_statements = {
        (s["step"], s["index"]): s for s in (workflow.get("card") or {}).get("statements") or []
    }
    statements: list[dict[str, Any]] = []
    for step in steps:
        for index, statement in enumerate(step.get("statements") or [], start=1):
            cited = [fact["fact_id"] for fact in statement.get("facts") or []]
            counter = [c["fact_id"] for c in statement.get("counterevidence") or []]
            reviewed = review_statements.get((step["step"], index))
            if reviewed is None:
                raise SystemExit(f"inv-{n}: no review for statement {step['step']} {index}")
            statements.append(
                {
                    "investigation": n,
                    "step": step["step"],
                    "index": index,
                    "text": statement["statement"],
                    "fact_ids": cited,
                    "counter_fact_ids": counter,
                    "trust_gate": reviewed["trust_gate"],
                    "misstatement": reviewed.get("misstatement"),
                    "saved_work": reviewed.get("saved_work"),
                    "judge": _judge_entries(card, statement["statement"], set(cited)),
                }
            )
    if len(statements) != len(review_statements):
        raise SystemExit(
            f"inv-{n}: {len(statements)} card statements but {len(review_statements)} reviewed"
        )

    counter_facts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for step in steps:
        for c in step.get("counterevidence") or []:
            if c["fact_id"] in seen:
                continue
            seen.add(c["fact_id"])
            challenged = [a if isinstance(a, str) else a["fact_id"] for a in c.get("against") or []]
            verdict = verdicts.get(c["fact_id"])
            counter_facts.append(
                {
                    "fact_id": c["fact_id"],
                    "investigation": n,
                    "step": c.get("step"),
                    "on_step": step["step"],
                    "challenged_fact_ids": challenged,
                    "verdict": verdict["verdict"] if verdict else None,
                }
            )
    return facts, statements, counter_facts, quotes


def _strings(node: Any, path: str = "") -> Any:
    if isinstance(node, str):
        yield path, node
    elif isinstance(node, dict):
        for key, value in node.items():
            yield from _strings(value, f"{path}/{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from _strings(value, f"{path}[{i}]")


def embedded_quotes(labels: dict[str, Any], quotes: set[str]) -> list[str]:
    """Paths of statement and note texts that hold a long quote as Atlas or a reviewer wrote it.

    A card statement may quote the speaker ("Coherent says ..."), and a reviewer's note may
    quote the sentence it faults. Those are the writer's own words, kept as given, but the
    owner should know which they are before committing the file.
    """
    long_quotes = [q for q in quotes if len(q) >= MIN_QUOTE_LEN_FOR_SUBSTRING_CHECK]
    return [
        path
        for path, text in _strings(labels.get("statements"), "/statements")
        if any(q in text for q in long_quotes)
    ]


def _assert_no_quotes(labels: dict[str, Any], quotes: set[str]) -> None:
    """Fail if any field of the labels is a Fact's quote, or a Fact record holds one."""
    long_quotes = [q for q in quotes if len(q) >= MIN_QUOTE_LEN_FOR_SUBSTRING_CHECK]
    for path, text in _strings(labels):
        if text in quotes:
            raise AssertionError(f"a quote slipped into the labels at {path}: {text[:60]!r}")
    for path, text in _strings(labels.get("facts"), "/facts"):
        for quote in long_quotes:
            if quote in text:
                raise AssertionError(f"a quote slipped into the labels at {path}: {quote[:60]!r}")


def build(folder: Path | str) -> dict[str, Any]:
    """Cut a review folder into labels (facts, statements, counter-Facts, totals)."""
    return build_with_quotes(folder)[0]


def build_with_quotes(folder: Path | str) -> tuple[dict[str, Any], set[str]]:
    """`build`, and the Facts' quotes the guard checked against (for `embedded_quotes`)."""
    folder = Path(folder)
    facts: list[dict[str, Any]] = []
    statements: list[dict[str, Any]] = []
    counter_facts: list[dict[str, Any]] = []
    quotes: set[str] = set()
    for n in _investigations(folder):
        f, s, c, q = _investigation_labels(folder, n)
        facts += f
        statements += s
        counter_facts += c
        quotes |= q

    def per_investigation(items: list[dict[str, Any]], pick: Any = None) -> dict[str, int]:
        counts: Counter[int] = Counter(i["investigation"] for i in items if pick is None or pick(i))
        return {str(n): counts.get(n, 0) for n in _investigations(folder)}

    totals: dict[str, Any] = {
        "facts": per_investigation(facts),
        "right": per_investigation(facts, lambda i: i["verdict"] == "right"),
        "wrong": per_investigation(facts, lambda i: i["verdict"] == "wrong"),
        "off_question": per_investigation(facts, lambda i: i["verdict"] == "off-question"),
        "statements": per_investigation(statements),
        "statements_failing": per_investigation(statements, lambda i: i["trust_gate"] != "pass"),
        "counter_facts": per_investigation(counter_facts),
        "wrong_by_category": {
            category: per_investigation(
                facts, lambda i, category=category: i["verdict"] == "wrong" and i["category"] == category
            )
            for category in [name for name, _ in CATEGORY_RULES] + ["other"]
        },
    }
    labels = {
        "source": "pilot-0.5.3-arg",
        "note": "Atlas's and the reviewers' own words only; no quote and no context text.",
        "category_rules": [{"category": name, "pattern": pattern} for name, pattern in CATEGORY_RULES],
        "facts": facts,
        "statements": statements,
        "counter_facts": counter_facts,
        "totals": totals,
    }
    _assert_no_quotes(labels, quotes)
    return labels, quotes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    labels, quotes = build_with_quotes(args.data)
    for path in embedded_quotes(labels, quotes):
        print(f"warning: {path} holds a quote as written; review before committing", file=sys.stderr)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(labels, indent=1, ensure_ascii=False) + "\n", encoding="utf8")
    print(f"wrote {args.out}")
    for key, value in labels["totals"].items():
        print(f"  {key}: {json.dumps(value)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
