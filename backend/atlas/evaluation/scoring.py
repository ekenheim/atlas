"""Scoring a case: each gold expectation against what Atlas produced, as a check.

Every check carries the metric it feeds (methodology §7). A metric's score for the case is the
share of its checks that held; the case passes when all of them hold. Semantics per key:

- `claims`: `accepted: true` needs an accepted Claim with that subject, predicate and object
  (and source and exact quote, if given); `false` needs none (rejected or never proposed are
  both right). Recall (`relationship_recall`) and precision (`relationship_precision`).
- `relationships`: `present` needs the edge (subject, predicate, object or object text, and
  layer if given), in `review_state` with `reasons_include` if given; `absent` needs no such
  edge in any state; `not_verified` needs none machine-reviewed or approved.
- `citations`: an Assertion of that source quotes exactly the gold quote, and (`resolved`) its
  span in the archived parse is that quote (`citation_correctness`).
- `evidence_families`: the sources' distinct Evidence Families number exactly `count`
  (`independent_families`).
- `forbidden_sources`: no investigation document, Claim, Assertion or counterevidence comes
  from them (`as_of_isolation`).
- `answer`: `evidence_missing` means no accepted Claim and no finding (or at least one, when
  false); `must_not_mention` entities appear in no accepted Claim and no finding.
- `financials`: the as-of observation of the period key has the gold value (and accession
  and linkage, if given) (`as_of_isolation`).
- `investigation`: the stop reason is one of the gold's; at least `min_contradictions`
  independent contradictions and `min_findings` findings on the card
  (`contradiction_discovery`).
"""

from decimal import Decimal, InvalidOperation
from typing import Any, cast

from pydantic import JsonValue

from atlas.evaluation.gold import Case, GoldClaim, GoldRelationship
from atlas.evaluation.store import Check

_VERIFIED = ("machine_reviewed", "approved")


def score(case: Case, observed: dict[str, JsonValue]) -> list[Check]:
    gold = case.gold
    checks: list[Check] = []
    claims = _list(observed, "claims")
    for index, claim in enumerate(gold.claims):
        checks.append(_claim(f"claims[{index}]", claim, claims))
    edges = _list(observed, "relationships")
    for index, edge in enumerate(gold.relationships):
        checks.append(_relationship(f"relationships[{index}]", edge, edges))
    assertions = _list(observed, "assertions")
    for index, citation in enumerate(gold.citations):
        quoting = [
            a for a in assertions if a["source"] == citation.source and a["quote"] == citation.quote
        ]
        state = (
            "resolved"
            if any(a["resolves"] for a in quoting)
            else ("broken" if quoting else "absent")
        )
        checks.append(
            Check(
                key=f"citations[{index}]",
                metric="citation_correctness",
                expected=citation.model_dump(mode="json"),
                observed={"state": state, "assertions": len(quoting)},
                passed=state == citation.state,
            )
        )
    if gold.evidence_families is not None:
        families = cast(dict[str, Any], observed.get("families") or {})
        keys = gold.evidence_families.sources or [
            s.key for s in case.sources if s.kind == "document"
        ]
        distinct = {families.get(key) or f"alone:{key}" for key in keys}
        checks.append(
            Check(
                key="evidence_families",
                metric="independent_families",
                expected=gold.evidence_families.model_dump(mode="json"),
                observed={"count": len(distinct), "families": {k: families.get(k) for k in keys}},
                passed=len(distinct) == gold.evidence_families.count,
            )
        )
    investigation = cast(dict[str, Any] | None, observed.get("investigation"))
    if gold.forbidden_sources:
        used = _used_sources(observed, investigation)
        leaked = sorted(set(gold.forbidden_sources) & used)
        checks.append(
            Check(
                key="forbidden_sources",
                metric="as_of_isolation",
                expected={"not_used": gold.forbidden_sources},
                observed={"used": sorted(used), "leaked": list[JsonValue](leaked)},
                passed=not leaked,
            )
        )
    if gold.answer is not None:
        checks.extend(
            _answer(
                gold.answer.evidence_missing, gold.answer.must_not_mention, claims, investigation
            )
        )
    figures = _list(observed, "financials")
    for index, financial in enumerate(gold.financials):
        seen: dict[str, Any] = figures[index] if index < len(figures) else {}
        passed = (
            _decimal(seen.get("value")) == financial.value
            and (financial.accession is None or seen.get("accession") == financial.accession)
            and (financial.linkage is None or seen.get("linkage") == financial.linkage)
        )
        checks.append(
            Check(
                key=f"financials[{index}]",
                metric="as_of_isolation",
                expected=financial.model_dump(mode="json"),
                observed=seen,
                passed=passed,
            )
        )
    if gold.investigation is not None:
        checks.extend(_investigation(gold.investigation.model_dump(), investigation))
    return checks


def _list(observed: dict[str, JsonValue], key: str) -> list[dict[str, Any]]:
    value = observed.get(key)
    return (
        [cast(dict[str, Any], v) for v in value if isinstance(v, dict)]
        if isinstance(value, list)
        else []
    )


def _decimal(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value)) if value is not None else None
    except InvalidOperation:
        return None


def _claim(key: str, gold: GoldClaim, claims: list[dict[str, Any]]) -> Check:
    matching = [
        c
        for c in claims
        if c["outcome"] == "accepted"
        and (c["subject"], c["predicate"], c["object"])
        == (gold.subject, gold.predicate, gold.object)
        and (gold.source is None or c["source"] == gold.source)
        and (gold.quote is None or c["quote"] == gold.quote)
    ]
    proposed = [
        {k: c[k] for k in ("subject", "predicate", "object", "outcome", "reason_code", "source")}
        for c in claims
        if (c["subject"], c["predicate"]) == (gold.subject, gold.predicate)
    ]
    return Check(
        key=key,
        metric="relationship_recall" if gold.accepted else "relationship_precision",
        expected=gold.model_dump(mode="json"),
        observed={"accepted": len(matching), "proposed": proposed},
        passed=bool(matching) == gold.accepted,
    )


def _relationship(key: str, gold: GoldRelationship, edges: list[dict[str, Any]]) -> Check:
    matching = [
        e
        for e in edges
        if (e["subject"], e["predicate"]) == (gold.subject, gold.predicate)
        and e["object"] == gold.object
        and (gold.object_text is None or e["object_text"] == gold.object_text)
        and (gold.layer is None or e["layer"] == gold.layer)
    ]
    if gold.expect == "present":
        fitting = [
            e
            for e in matching
            if (gold.review_state is None or e["review_state"] == gold.review_state)
            and set(gold.reasons_include) <= set(e["reasons"])
        ]
        passed = bool(fitting)
    elif gold.expect == "absent":
        passed = not matching
    else:
        passed = not [e for e in matching if e["review_state"] in _VERIFIED]
    return Check(
        key=key,
        metric="relationship_recall" if gold.expect == "present" else "relationship_precision",
        expected=gold.model_dump(mode="json", exclude_defaults=True),
        observed={
            "edges": [
                {k: e[k] for k in ("layer", "review_state", "reasons", "evidence")}
                for e in matching
            ]
        },
        passed=passed,
    )


def _used_sources(observed: dict[str, JsonValue], investigation: dict[str, Any] | None) -> set[str]:
    used = {c["source"] for c in _list(observed, "claims") if c["source"]}
    used |= {a["source"] for a in _list(observed, "assertions") if a["source"]}
    if investigation is not None:
        used |= {d for d in investigation["documents"] if d}
        used |= {c["source"] for c in investigation["counterevidence"] if c["source"]}
    return used


def _answer(
    evidence_missing: bool | None,
    must_not_mention: list[str],
    claims: list[dict[str, Any]],
    investigation: dict[str, Any] | None,
) -> list[Check]:
    accepted = [c for c in claims if c["outcome"] == "accepted"]
    findings = cast(list[dict[str, Any]], investigation["findings"]) if investigation else []
    checks: list[Check] = []
    if evidence_missing is not None:
        nothing = not accepted and not findings
        checks.append(
            Check(
                key="answer.evidence_missing",
                metric="as_of_isolation",
                expected=evidence_missing,
                observed={"accepted_claims": len(accepted), "findings": len(findings)},
                passed=nothing == evidence_missing,
            )
        )
    if must_not_mention:
        named = {c["subject"] for c in accepted} | {c["object"] for c in accepted if c["object"]}
        named |= {e for f in findings for e in f["entities"] if e}
        found = sorted(set(must_not_mention) & named)
        checks.append(
            Check(
                key="answer.must_not_mention",
                metric="as_of_isolation",
                expected=must_not_mention,
                observed={"mentioned": list[JsonValue](found)},
                passed=not found,
            )
        )
    return checks


def _investigation(gold: dict[str, Any], found: dict[str, Any] | None) -> list[Check]:
    if found is None:
        return [
            Check(
                key="investigation",
                metric="contradiction_discovery",
                expected=gold,
                observed=None,
                passed=False,
            )
        ]
    checks: list[Check] = []
    if gold["stop_reason"] is not None:
        checks.append(
            Check(
                key="investigation.stop_reason",
                metric="contradiction_discovery",
                expected=gold["stop_reason"],
                observed={"stop_reason": found["stop_reason"], "detail": found["stop_detail"]},
                passed=found["stop_reason"] in gold["stop_reason"],
            )
        )
    if gold["min_contradictions"] is not None:
        independent = [c for c in found["contradictions"] if c["independent"]]
        checks.append(
            Check(
                key="investigation.min_contradictions",
                metric="contradiction_discovery",
                expected=gold["min_contradictions"],
                observed={"independent_contradictions": len(independent)},
                passed=len(independent) >= gold["min_contradictions"],
            )
        )
    if gold["min_findings"] is not None:
        checks.append(
            Check(
                key="investigation.min_findings",
                metric="contradiction_discovery",
                expected=gold["min_findings"],
                observed={"findings": len(found["findings"])},
                passed=len(found["findings"]) >= gold["min_findings"],
            )
        )
    return checks
