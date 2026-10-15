"""The lead judges a Belief under the owner's policy (docs/decisions.md, "The lead judges
Beliefs; the owner audits", 2026-10-15). The only way the lead sets a judgement.

It refuses unless every rule holds:
- the Belief is active, unjudged by the owner, and atomic (`atlas.beliefs.atomicity`);
- no flag is open and no citation of valence <= -0.75 stands;
- every load-bearing Fact of positive valence was judged right by the blind review given
  (`--review`: a JSON file with {"final": {fact_id: "right"|"wrong"|"off_question"}});
- for `proven`, at least one of those Facts is the company's own words or a filing
  (status not `reported_by_third_party`);
- the Belief's statement is judged `supported` against those Facts by a fresh call to
  `POST /api/v1/statements/judge` (the finding judge, one vote).
Then it posts the judgement with actor `lead` and a reason naming the evidence. `--dry-run`
checks everything except the write.

    python .scratch/tools/lead_judge.py --belief <id> --review <final-verdicts.json>
        --judgement proven|disproven|undecidable --confidence 0.8 --question "<the question>"
        [--note "..."] [--base-url URL] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from atlas.beliefs.atomicity import compound_reasons  # noqa: E402


def call(base: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    request = urllib.request.Request(
        base + path,
        data=None if body is None else json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="GET" if body is None else "POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        text = error.read().decode("utf-8", errors="replace")
        try:
            return error.code, json.loads(text)
        except ValueError:
            return error.code, {"error": text[:500]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--belief", required=True)
    parser.add_argument("--review", required=True, type=Path)
    parser.add_argument("--judgement", required=True, choices=["proven", "disproven", "undecidable"])
    parser.add_argument("--confidence", required=True, type=float)
    parser.add_argument("--question", required=True)
    parser.add_argument("--note", default="")
    parser.add_argument("--base-url", default="https://atlas.ekenhome.se")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    base = args.base_url.rstrip("/") + "/api/v1"
    refusals: list[str] = []

    status, belief = call(base, f"/beliefs/{args.belief}")
    if status != 200:
        print(json.dumps({"refused": "belief_unreadable", "http": status, "answer": belief}))
        return 2
    judgement = belief.get("judgement") or {}
    history = belief.get("history") or []
    if belief.get("status") != "active":
        refusals.append(f"the Belief is {belief.get('status')}, not active")
    if any((h.get("actor") or "") == "owner" for h in history) or judgement.get("actor") == "owner":
        refusals.append("the owner has judged this Belief; the lead never re-judges it")
    compound = compound_reasons(belief["statement"])
    if compound:
        refusals.append("compound: " + "; ".join(compound))
    if belief.get("open_flags"):
        refusals.append(f"open flags: {belief['open_flags']}")
    standing = [c for c in belief.get("citations", []) if (c.get("valence") or 0) <= -0.75 and c.get("stands", True)]
    if standing:
        refusals.append(f"{len(standing)} citation(s) of valence <= -0.75 stand")

    review = json.loads(args.review.read_text(encoding="utf-8"))["final"]
    load_bearing = [
        c for c in belief.get("citations", [])
        if c.get("weight") == "load_bearing" and (c.get("valence") or 0) > 0 and c.get("kind", "fact") == "fact"
    ]
    if not load_bearing:
        refusals.append("no load-bearing Fact of positive valence")
    for citation in load_bearing:
        verdict = review.get(citation["ref_id"])
        if verdict != "right":
            refusals.append(f"load-bearing Fact {citation['ref_id'][:8]} reviewed {verdict or 'never'}")
    if args.judgement == "proven":
        own = []
        for citation in load_bearing:
            s, fact = call(base, f"/facts/{citation['ref_id']}")
            if s == 200 and fact.get("status") != "reported_by_third_party":
                own.append(citation["ref_id"])
        if not own:
            refusals.append("proven needs a load-bearing Fact in the company's own words or a filing")

    verdict_line = None
    if not refusals:
        s, judged = call(base, "/statements/judge", {
            "question": args.question,
            "statement": belief["statement"],
            "fact_ids": [c["ref_id"] for c in load_bearing][:12],
            "votes": 1,
        })
        if s != 200:
            refusals.append(f"the judge call failed (HTTP {s})")
        elif judged.get("verdict") != "supported":
            refusals.append(f"the judge says {judged.get('verdict')}: {json.dumps(judged.get('beyond') or judged.get('reason') or '')[:300]}")
        else:
            verdict_line = "the judge (one vote) supports the statement against its load-bearing Facts"

    if refusals:
        print(json.dumps({"belief": args.belief, "refused": refusals}, indent=1))
        return 1
    reason = (
        f"Lead judgement under the owner's policy (2026-10-15): atomic; {verdict_line}; "
        f"load-bearing Facts {', '.join(c['ref_id'][:8] for c in load_bearing)} judged right by blind review "
        f"({args.review.name}); no open flag or standing contradiction."
        + (f" {args.note}" if args.note else "")
    )
    if args.dry_run:
        print(json.dumps({"belief": args.belief, "would_judge": args.judgement, "confidence": args.confidence, "reason": reason}, indent=1))
        return 0
    s, answer = call(base, f"/beliefs/{args.belief}/judge", {
        "actor": "lead", "judgement": args.judgement, "confidence": args.confidence, "reason": reason,
    })
    print(json.dumps({"http": s, "belief": args.belief, "judgement": (answer.get("judgement") or {}).get("judgement"), "reason": reason}, indent=1))
    return 0 if s == 200 else 1


if __name__ == "__main__":
    sys.exit(main())
