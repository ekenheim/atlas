"""The argument cards' statements with the reviewers' labels, for the finding judge's eval
(pilot 0.5.3, fix T2).

Reads each `inv-N/investigation.json` (its `research_card`: every step's kept statements, each
with its cited Facts and counterevidence) and `inv-N/review/workflow-result.json` (the blind
review: `card.statements`, one per statement by `step` and 1-based `index` within the step,
with `trust_gate` `pass`/`fail` and, for a fail, `misstatement`) under the pilot directory, and
writes `labeled-statements.json` beside them: one entry per statement, in card order:

    {"investigation": 3, "question": "...", "step": "invalidation", "index": 3,
     "statement": "...", "trust_gate": "fail", "misstatement": "...",
     "facts": [{"fact_id", "kind": "fact" | "counter", "company_name", "status", "statement",
                "quantity", "period", "source_title", "quote", "source_version_id",
                "span_start", "span_end"}, ...]}

`quantity` is written as the judge is sent it (`value unit (metric)`). An investigation with
no card (0.5.3's question 2) is skipped. The output holds quotes from licensed call
transcripts: it is local only (`.scratch/live-runs/` is gitignored); never commit it.

    uv run python .scratch/tools/argument_statement_labels.py [--pilot DIR] [--out PATH]

Then: `uv run python .scratch/tools/finding_judge_eval.py --argument --dry-run`.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
PILOT = REPO / ".scratch" / "live-runs" / "pilot-0.5.3-arg"


def quantity_text(quantity: Any) -> str | None:
    """A Fact's quantity as the judge is sent it (`atlas.investigations.argument`)."""
    if not isinstance(quantity, dict):
        return None
    return f"{quantity.get('value')} {quantity.get('unit')} ({quantity.get('metric')})"


def cited(fact: dict[str, Any], kind: str) -> dict[str, Any]:
    span = fact.get("source_span") or {}
    return {
        "fact_id": fact.get("fact_id"),
        "kind": kind,
        "company_name": fact.get("company_name"),
        "status": fact.get("status"),
        "statement": fact.get("statement"),
        "quantity": quantity_text(fact.get("quantity")),
        "period": fact.get("period"),
        "source_title": fact.get("source_title"),
        "quote": span.get("quote"),
        "source_version_id": span.get("source_version_id"),
        "span_start": span.get("span_start"),
        "span_end": span.get("span_end"),
    }


def labelled_statements(pilot: Path) -> list[dict[str, Any]]:
    """Every statement of every card under `pilot`, with its label (see the module)."""
    entries: list[dict[str, Any]] = []
    for directory in sorted(pilot.glob("inv-*"), key=lambda p: int(p.name.split("-")[1])):
        number = int(directory.name.split("-")[1])
        found = json.loads((directory / "investigation.json").read_text("utf-8"))
        card = found.get("research_card")
        if not card:
            continue
        review = json.loads((directory / "review" / "workflow-result.json").read_text("utf-8"))
        labels = {(s["step"], int(s["index"])): s for s in review["card"]["statements"]}
        for step in card.get("steps") or []:
            for index, said in enumerate(step.get("statements") or [], start=1):
                label = labels.get((step["step"], index))
                if label is None:
                    raise SystemExit(f"inv-{number}: no label for {step['step']} {index}")
                entries.append(
                    {
                        "investigation": number,
                        "question": found["question"],
                        "step": step["step"],
                        "index": index,
                        "statement": said["statement"],
                        "trust_gate": label.get("trust_gate"),
                        "misstatement": label.get("misstatement"),
                        "facts": [cited(f, "fact") for f in said.get("facts") or []]
                        + [cited(f, "counter") for f in said.get("counterevidence") or []],
                    }
                )
        mine = {(e["step"], e["index"]) for e in entries if e["investigation"] == number}
        unmatched = set(labels) - mine
        if unmatched:
            raise SystemExit(f"inv-{number}: labels without a statement: {sorted(unmatched)}")
    return entries


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--pilot", type=Path, default=PILOT)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    entries = labelled_statements(args.pilot)
    out = args.out or args.pilot / "labeled-statements.json"
    out.write_text(json.dumps(entries, indent=1, ensure_ascii=False), "utf-8")
    fails = sum(1 for e in entries if e["trust_gate"] == "fail")
    passes = sum(1 for e in entries if e["trust_gate"] == "pass")
    print(f"{len(entries)} statements ({fails} fail, {passes} pass) -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
