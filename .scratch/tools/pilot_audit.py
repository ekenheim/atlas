"""The lead's deterministic checks on a reviewed pilot run (read-only against production).

`python .scratch/tools/pilot_audit.py gate <n>`: the trust gate's first half. For every accepted
Claim of the saved investigation it reads the Assertion and the parse it was checked against and
compares the archived text at the span with the quote; it writes `claims-context.json` (each
Claim with its review state and 700 characters of context either side) for the reviewers.

`python .scratch/tools/pilot_audit.py audit <n>`: checks a reviewer's artifacts against the run:
`verdicts.json` has one verdict per accepted Claim and no other, the baseline marks reach the
tenth on-question hit (or the twentieth hit), and every long quotation in `review.md` occurs in
the run's quotes, their context, the baseline hits or the card.
"""

import json
import pathlib
import re
import sys
import urllib.request

BASE = "https://atlas.ekenhome.se/api/v1"
OUT = pathlib.Path(".scratch/live-runs/pilot-0.3.0")
CONTEXT = 700


def get(path, text=False):
    with urllib.request.urlopen(BASE + path, timeout=90) as response:
        body = response.read().decode("utf-8")
    return body if text else json.loads(body)


def load(target, name):
    return json.loads((target / name).read_text(encoding="utf-8"))


def squash(text):
    return " ".join(text.split())


def gate(number):
    target = OUT / f"inv-{number}"
    investigation = load(target, "investigation.json")
    relationships = {}
    try:
        rows = load(target, "relationships.json")
        rows = rows["items"] if isinstance(rows, dict) and "items" in rows else rows
        relationships = {row["id"]: row for row in rows}
    except FileNotFoundError:
        pass
    parses = {}
    out, failures = [], []
    for item in investigation["evidence"]:
        if item.get("excluded"):
            continue
        assertion = get(f"/assertions/{item['assertion_id']}")
        key = (item["source_version_id"], assertion.get("parser_version"))
        if key not in parses:
            suffix = f"&parser_version={key[1]}" if key[1] else ""
            parses[key] = get(f"/source-versions/{key[0]}/content?kind=parsed{suffix}", text=True)
        text = parses[key]
        at_span = text[item["span_start"] : item["span_end"]]
        verbatim = at_span == item["quote"]
        if not verbatim:
            failures.append(item["claim_id"])
        out.append(
            {
                **item,
                "parser_version": assertion.get("parser_version"),
                "assertion_review_state": assertion.get("review_state"),
                "verbatim_at_span": verbatim,
                "text_at_span": None if verbatim else at_span,
                "context_before": text[max(0, item["span_start"] - CONTEXT) : item["span_start"]],
                "context_after": text[item["span_end"] : item["span_end"] + CONTEXT],
            }
        )
    (target / "claims-context.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"investigation {number}: {len(out)} accepted Claims, {len(failures)} not verbatim at their span")
    for claim_id in failures:
        print(f"  NOT VERBATIM: {claim_id}")
    card = investigation.get("research_card") or {}
    accepted = {item["claim_id"] for item in out}
    for index, finding in enumerate(card.get("findings", []), 1):
        unknown = [c for c in finding["claim_ids"] if c not in accepted]
        if unknown:
            print(f"  finding {index} cites {len(unknown)} Claims that are not accepted Evidence: {unknown}")
    print(f"  findings {len(card.get('findings', []))}, relationships saved {len(relationships)}")
    return 1 if failures else 0


def audit(number, verdicts_name="verdicts.json", review_name="review.md"):
    target = OUT / f"inv-{number}"
    investigation = load(target, "investigation.json")
    context = load(target, "claims-context.json")
    accepted = {item["claim_id"] for item in context}
    problems = []

    verdicts = load(target, verdicts_name)
    judged = [row["claim_id"] for row in verdicts.get("claims", [])]
    missing = accepted - set(judged)
    extra = set(judged) - accepted
    doubles = {c for c in judged if judged.count(c) > 1}
    if missing:
        problems.append(f"{len(missing)} accepted Claims have no verdict: {sorted(missing)}")
    if extra:
        problems.append(f"{len(extra)} verdicts name no accepted Claim: {sorted(extra)}")
    if doubles:
        problems.append(f"{len(doubles)} Claims judged twice: {sorted(doubles)}")
    for row in verdicts.get("claims", []):
        if not row.get("reason", "").strip():
            problems.append(f"verdict without a reason: {row['claim_id']}")

    baseline = load(target / "baseline", "results.json") if (target / "baseline" / "results.json").exists() else None
    if baseline:
        hits = {hit["rank"] for hit in baseline["hits"]}
        marks = {row["rank"]: row for row in verdicts.get("baseline", [])}
        on_question, needed = 0, []
        for rank in sorted(hits):
            needed.append(rank)
            if marks.get(rank, {}).get("on_question"):
                on_question += 1
                if on_question == 10:
                    break
        unmarked = [rank for rank in needed if rank not in marks]
        if unmarked:
            problems.append(f"baseline hits without a mark before the stopping point: {unmarked}")
        beyond = [rank for rank in marks if rank not in hits]
        if beyond:
            problems.append(f"baseline marks for ranks that do not exist: {beyond}")

    if review_name and (target / review_name).exists():
        review = (target / review_name).read_text(encoding="utf-8")
        haystack = [squash(item["context_before"] + item["quote"] + item["context_after"]) for item in context]
        haystack.append(squash(json.dumps(investigation, ensure_ascii=False)))
        if baseline:
            haystack += [squash(hit["text"]) for hit in baseline["hits"]]
        quotations = re.findall(r"[\"“]([^\"“”]{60,})[\"”]", review)
        unfound = []
        for quotation in quotations:
            parts = [squash(p) for p in re.split(r"\s*(?:\[…\]|\[\.\.\.\]|…|\.\.\.)\s*", quotation) if len(squash(p)) >= 25]
            if not all(any(part in hay for hay in haystack) for part in parts):
                unfound.append(quotation[:110])
        print(f"  review.md: {len(quotations)} long quotations, {len(unfound)} not found in the run's texts")
        for quotation in unfound:
            problems.append(f"quotation not found: {quotation!r}")

    print(f"investigation {number} ({verdicts_name}): {len(judged)} verdicts for {len(accepted)} accepted Claims; {len(problems)} problems")
    for problem in problems:
        print(f"  {problem}")
    return 1 if problems else 0


if __name__ == "__main__":
    command, number = sys.argv[1], int(sys.argv[2])
    sys.exit(gate(number) if command == "gate" else audit(number, *sys.argv[3:]))
