"""Write the counter-judge's label set from the 0.5.3 argument cards (pilot-review T3).

Reads `.scratch/live-runs/pilot-0.5.3-arg/inv-{1,3,4,5}/investigation.json` (not in git: some
quotes are from licensed call transcripts; never commit them or what this writes) and writes
`.scratch/live-runs/pilot-0.5.3-arg/labeled-counter-facts.json`: one entry per pair of a
Skeptic Fact and a Fact it challenged (135 on the four cards: 50 Skeptic Facts), each with both
Facts' company, step, statement, status, quantity, period, source title and exact quote, the
reviewers' verdict on the Skeptic Fact (`review/final-verdicts.json`, when there is one), and
an empty `relation` for the lead to fill: `contradicts`, `limits`, `dates`, `qualifies`,
`supports` or `unrelated` (`atlas.roles.counter_judge`). `.scratch/tools/counter_judge_eval.py`
scores the judge against the filled file.

An existing file's filled `relation` and `note` are kept (matched by the pair), so the script
can be run again without losing labels. No network, no LLM.

    uv run python .scratch/tools/counter_relations_labels.py [--pilot DIR] [--out PATH]

It also reports what the status rule of pilot-review T3 does to the four cards: re-running
`build_steps`'s rule (a step is disputed only by a counter-Fact whose relation to one of its
Facts contradicts, limits or dates it, or is unjudged) with every relation set to `qualifies`
gives the disputed steps that remain (0), beside today's.
"""

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any, cast

REPO = Path(__file__).resolve().parents[2]
PILOT = REPO / ".scratch" / "live-runs" / "pilot-0.5.3-arg"
INVESTIGATIONS = (1, 3, 4, 5)


def fact_view(fact: dict[str, Any]) -> dict[str, Any]:
    span = fact.get("source_span") or {}
    return {
        "fact_id": fact["fact_id"],
        "company": fact.get("company_name"),
        "step": fact.get("step"),
        "statement": fact.get("statement"),
        "status": fact.get("status"),
        "quantity": fact.get("quantity"),
        "period": fact.get("period"),
        "source_title": fact.get("source_title"),
        "source_version_id": span.get("source_version_id"),
        "quote": span.get("quote"),
    }


def recorded_view(item: dict[str, Any], names: dict[str, str], titles: dict[str, str]) -> dict:
    """A Fact from `facts.json` (one the card doesn't show) in the same shape."""
    assertion = item.get("assertion") or {}
    version = str(assertion.get("source_version_id") or "")
    return {
        "fact_id": item["id"],
        "company": names.get(str(assertion.get("subject_company_id"))),
        "step": item.get("step"),
        "statement": item.get("statement"),
        "status": item.get("status"),
        "quantity": item.get("quantity"),
        "period": item.get("period"),
        "source_title": titles.get(version),
        "source_version_id": version,
        "quote": assertion.get("quote"),
    }


def card_counter(card: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Every Skeptic Fact the card shows, by ID (a step's and its statements')."""
    counter: dict[str, dict[str, Any]] = {}
    for step in card.get("steps") or []:
        for fact in step.get("counterevidence") or []:
            counter.setdefault(fact["fact_id"], fact)
        for said in step.get("statements") or []:
            for fact in said.get("counterevidence") or []:
                counter.setdefault(fact["fact_id"], fact)
    return counter


def row(fact: dict[str, Any]) -> dict[str, Any]:
    """A card Fact as the Fact row `build_steps` reads (`argument.fact_rows`' shape)."""
    span = fact["source_span"]
    return {
        "id": uuid.UUID(fact["fact_id"]),
        "assertion_id": uuid.UUID(fact["fact_id"]),
        "step": fact["step"],
        "value_json": {
            "statement": fact["statement"],
            "status": fact["status"],
            "quantity": fact.get("quantity"),
            "period": fact.get("period"),
        },
        "subject_company_id": uuid.UUID(fact["company_id"]),
        "subject_name": fact["company_name"],
        "subject_slug": None,
        "quote": span["quote"],
        "source_version_id": uuid.UUID(span["source_version_id"]),
        "span_start": span["span_start"],
        "span_end": span["span_end"],
        "verification_status": span["verification_status"],
        "source_title": fact["source_title"],
        "available_at": fact["evidence_available_at"],
    }


def disputed(card: dict[str, Any], relation: str | None) -> list[str]:
    """The card's disputed steps: as recorded (`relation` None), or as `build_steps` (pilot-
    review T3's rule) decides them with every Skeptic Fact's relation to each Fact it
    challenged set to `relation` (`unjudged`: as if no judge had run)."""
    from atlas.investigations.argument import (
        ArgumentFacts,
        KeptStatement,
        StepStatement,
        build_steps,
    )

    steps = card.get("steps") or []
    if relation is None:
        return [s["step"] for s in steps if s["status"] == "disputed"]
    counter = card_counter(card)
    supporting: dict[str, dict[str, Any]] = {}
    for step in steps:
        for fact in step.get("facts") or []:
            supporting.setdefault(fact["fact_id"], row(fact))
    counter_rows = {fact_id: row(fact) for fact_id, fact in counter.items()}
    rows = [*supporting.values(), *counter_rows.values()]
    refs = {f"c{n}": each for n, each in enumerate(rows, start=1)}
    ref_of = {str(each["id"]): ref for ref, each in refs.items()}
    against = {
        uuid.UUID(fact_id): [uuid.UUID(each) for each in fact.get("against") or []]
        for fact_id, fact in counter.items()
    }
    facts = ArgumentFacts(
        sessions=[],
        supporting=cast(Any, list(supporting.values())),
        counter=cast(Any, list(counter_rows.values())),
        against=against,
        relations={key: dict.fromkeys(value, relation) for key, value in against.items()},
    )
    statements = {
        step["step"]: StepStatement(
            kept=[
                KeptStatement(
                    said["statement"],
                    [
                        ref_of[f["fact_id"]]
                        for f in [*said["facts"], *said["counterevidence"]]
                        if f["fact_id"] in ref_of
                    ],
                    said.get("judged"),
                )
                for said in step.get("statements") or []
            ],
            editor_status=step.get("editor_status"),
            unchecked=[],
        )
        for step in steps
    }
    built = build_steps(facts, statements, cast(Any, refs), set(), skeptic_ran=True)
    return [s.step for s in built if s.status == "disputed"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--pilot", type=Path, default=PILOT)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    out_path: Path = args.out or args.pilot / "labeled-counter-facts.json"
    kept: dict[tuple[str, str], dict[str, Any]] = {}
    if out_path.is_file():
        for each in json.loads(out_path.read_text("utf-8")):
            kept[(each["counter"]["fact_id"], each["challenged"]["fact_id"])] = each

    pairs: list[dict[str, Any]] = []
    totals = dict.fromkeys(("today", "unjudged", "qualifies", "supports"), 0)
    for number in INVESTIGATIONS:
        folder = args.pilot / f"inv-{number}"
        found = json.loads((folder / "investigation.json").read_text("utf-8"))
        card = found["research_card"]
        verdicts_path = folder / "review" / "final-verdicts.json"
        verdicts: dict[str, Any] = (
            json.loads(verdicts_path.read_text("utf-8")) if verdicts_path.is_file() else {}
        )
        shown = {f["fact_id"]: f for s in card.get("steps") or [] for f in s.get("facts") or []}
        names = {
            str(f["company_id"]): str(f["company_name"])
            for s in card.get("steps") or []
            for f in [*(s.get("facts") or []), *(s.get("counterevidence") or [])]
        }
        titles = {
            str(d["source_version_id"]): str(d.get("title") or "")
            for d in found.get("documents") or []
        }
        recorded: dict[str, dict[str, Any]] = {}
        facts_path = folder / "facts.json"
        if facts_path.is_file():
            recorded = {
                str(item["id"]): item
                for item in json.loads(facts_path.read_text("utf-8")).get("items") or []
            }
        for counter_id, fact in card_counter(card).items():
            for challenged_id in fact.get("against") or []:
                if challenged_id in shown:
                    challenged = fact_view(shown[challenged_id])
                elif challenged_id in recorded:
                    challenged = recorded_view(recorded[challenged_id], names, titles)
                else:
                    challenged = {"fact_id": challenged_id, "quote": None}
                verdict = verdicts.get(counter_id) or {}
                before = kept.get((counter_id, challenged_id), {})
                pairs.append(
                    {
                        "investigation": number,
                        "question": found["question"],
                        "counter": fact_view(fact),
                        "challenged": challenged,
                        "review_verdict": verdict.get("verdict"),
                        "review_reason": verdict.get("reason"),
                        "relation": before.get("relation", ""),
                        "note": before.get("note", ""),
                    }
                )
        today = disputed(card, None)
        rule: dict[str, list[str]] = {
            each: disputed(card, each) for each in ("unjudged", "qualifies", "supports")
        }
        totals["today"] += len(today)
        for each, steps in rule.items():
            totals[each] += len(steps)
        print(
            f"inv-{number}: {len(card_counter(card))} Skeptic Facts; disputed today {today};"
            + "".join(f" all {each} {steps};" for each, steps in rule.items())
        )
    out_path.write_text(json.dumps(pairs, indent=1, ensure_ascii=False), "utf-8")
    filled = sum(1 for p in pairs if p["relation"])
    missing = sum(1 for p in pairs if not p["challenged"].get("quote"))
    print(
        f"disputed steps: {totals['today']} today; under the new rule {totals['unjudged']} with"
        f" every pair unjudged, {totals['qualifies']} all qualifies,"
        f" {totals['supports']} all supports"
    )
    print(f"{len(pairs)} pairs ({filled} labelled, {missing} without a challenged quote)")
    print(f"written: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
