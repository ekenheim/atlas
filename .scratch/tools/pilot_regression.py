"""The lead's regression check on the pilot's reviewed data (no LLM call, no network).

    uv run --no-sync python .scratch/tools/pilot_regression.py [--data DIR]

Reads the 2026-10-07 verdict review's labelled data (`DIR`, default
`.scratch/live-runs/pilot-0.4.6`, not in git: it holds licensed transcript text):

- `labeled-claims.json`: 364 accepted Claims, each with the reviewers' final verdict (right,
  wrong, off-question). Atlas's deterministic Claim checks that judge a quote's wording
  (`atlas.claims.predicates`: the directional cue, the cue in the object's clause, the
  direction from the wording, the unrealised-language refusal) are run on each, and the
  refusals are counted by verdict. A change that refuses more right Claims is a regression.
- `labeled-findings.json`: the cards' findings (with the trust-gate verdict) and the findings
  the grounding check dropped. The grounding check (`atlas.investigations.grounding`) is run
  on each against its cited Claims' quotes: kept findings must stay grounded; dropped ones
  should pass unless they truly misquote.

Prints one table and exits 1 when a right Claim is newly refused beyond `--max-right` or a
kept finding fails grounding. Checks needing the database (party names, company resolution,
the span check) are not run here; the integration tests cover those.
"""

import argparse
import json
import pathlib
import sys
from collections import Counter

sys.path.insert(0, "backend")

from atlas.claims import predicates as P  # noqa: E402
from atlas.investigations import grounding as G  # noqa: E402


def claim_refusal(claim: dict) -> str | None:
    """The first wording-only check `claim` fails, as its reason code; None if it passes."""
    predicate, quote = claim["predicate"], claim["quote"]
    object_text = (claim.get("object_text") or "").strip()
    rule = P.PREDICATES.get(predicate)
    if rule is None:
        return "predicate_not_whitelisted"
    if P.directional_cue(predicate, quote) is None:
        return "no_directional_language"
    if rule.object_kind == "product" and object_text and not P.company_level(predicate, object_text):
        if P.object_clause_cue(predicate, quote, object_text) is None:
            return "cue_in_other_clause"
    refuse = getattr(P, "unrealised_refusal", None)
    if refuse is not None and refuse(predicate, quote, object_text) is not None:
        return "not_stated_as_fact"
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default=".scratch/live-runs/pilot-0.4.6")
    parser.add_argument("--max-right", type=int, default=1, help="right Claims a check may refuse")
    args = parser.parse_args()
    data = pathlib.Path(args.data)
    claims = json.loads((data / "labeled-claims.json").read_text(encoding="utf-8"))
    findings = json.loads((data / "labeled-findings.json").read_text(encoding="utf-8"))

    refused: Counter = Counter()
    reasons: Counter = Counter()
    right_refused: list[str] = []
    for claim in claims:
        reason = claim_refusal(claim)
        if reason is not None:
            refused[claim["verdict"]] += 1
            reasons[(claim["verdict"], reason)] += 1
            if claim["verdict"] == "right":
                right_refused.append(f"{claim['claim_id'][:8]} {reason}")
    totals = Counter(c["verdict"] for c in claims)

    kept = [f for f in findings if "trust_gate" in f]
    dropped = [f for f in findings if "dropped_by_grounding" in f]
    by_id = {c["claim_id"]: c for c in claims}
    questions = {}
    for n in range(1, 6):
        inv = data / f"inv-{n}" / "investigation.json"
        if inv.exists():
            questions[n] = json.loads(inv.read_text(encoding="utf-8")).get("question", "")

    def ungrounded(finding: dict, cited: list[str]) -> list[str]:
        # As production builds them: the cited Claims' quotes, subjects, objects and source
        # titles, and the question.
        texts = [questions.get(finding["investigation"], "")]
        for claim_id in cited:
            claim = by_id.get(claim_id) or {}
            texts += [
                claim.get("quote") or "",
                claim.get("subject") or "",
                claim.get("object_name") or "",
                claim.get("object_text") or "",
                claim.get("source_title") or "",
            ]
        return G.ungrounded(finding["statement"], G.grounds(texts))

    kept_failing = [
        f["statement"][:70]
        for f in kept
        if ungrounded(f, [c["claim_id"] for c in f.get("claims", [])])
    ]
    dropped_passing = sum(1 for f in dropped if not ungrounded(f, list(f.get("claim_ids") or [])))

    print("Claims (wording-only checks)            refused / total")
    for verdict in ("right", "wrong", "off-question"):
        print(f"  {verdict:<38} {refused[verdict]:>3} / {totals[verdict]}")
    for (verdict, reason), n in sorted(reasons.items()):
        print(f"    {verdict:<14} {reason:<28} {n}")
    print("Findings (grounding)")
    print(f"  kept findings still grounded           {len(kept) - len(kept_failing)} / {len(kept)}")
    print(f"  dropped findings now grounded          {dropped_passing} / {len(dropped)}")
    if right_refused:
        print("Right Claims refused:", ", ".join(right_refused))
    bad = len(right_refused) > args.max_right or kept_failing
    print("REGRESSION" if bad else "OK")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
