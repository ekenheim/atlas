"""The difference between two versions of a Hypothesis, as its claims (findings) changed.

A claim is a finding's statement with the Assertions it cites: the same statement (compared
casefolded, whitespace collapsed) citing the same Assertions is the same claim. Each claim of
either version is:

- `new`: only in the later version;
- `unchanged`: in both, and the later version names no counterevidence it didn't before;
- `contradicted`: in the earlier version, and either the later one lists new counterevidence
  for it, or it was dropped and one of its Assertions has since been disputed, rejected or
  superseded (the Assertions' review state now, when the diff is read);
- `removed`: dropped from the later version with no such contradiction (the researcher's
  correction, say).

`fields_changed` names the other content fields (thesis statement, mechanism, predictions,
...) whose values differ.
"""

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Connection, text

from atlas.hypotheses.model import HypothesisContent, HypothesisVersion
from atlas.investigations.model import CardFinding

ClaimChange = Literal["new", "contradicted", "unchanged", "removed"]
_CONTRADICTING_STATES = ("disputed", "rejected", "superseded")
_FIELDS = (
    "thesis_statement",
    "mechanism",
    "measurable_predictions",
    "catalysts",
    "falsifiers",
    "required_evidence",
    "alternative_explanations",
    "unresolved_questions",
)


class Contradiction(BaseModel):
    model_config = ConfigDict(frozen=True)

    assertion_id: uuid.UUID | None  # an Assertion now disputed, rejected or superseded
    verification_status: str | None
    counterevidence_id: uuid.UUID | None  # or counterevidence the later version lists


class DiffClaim(BaseModel):
    model_config = ConfigDict(frozen=True)

    change: ClaimChange
    claim_text: str
    claim_ids: list[uuid.UUID]
    assertion_ids: list[uuid.UUID]
    contradictions: list[Contradiction]


class DiffCounts(BaseModel):
    model_config = ConfigDict(frozen=True)

    new: int
    contradicted: int
    unchanged: int
    removed: int


class HypothesisDiff(BaseModel):
    model_config = ConfigDict(frozen=True)

    hypothesis_id: uuid.UUID
    from_version: int
    to_version: int
    from_sha256: str
    to_sha256: str
    claims: list[DiffClaim]
    counts: DiffCounts
    fields_changed: list[str]


def diff_versions(
    connection: Connection,
    hypothesis_id: uuid.UUID,
    earlier: HypothesisVersion,
    later: HypothesisVersion,
) -> HypothesisDiff:
    before = {_key(each): each for each in earlier.content.findings}
    after = {_key(each): each for each in later.content.findings}
    states = _assertion_states(
        connection,
        [a for key in before.keys() - after.keys() for a in key[1]],
    )
    claims: list[DiffClaim] = []
    for key, finding in before.items():
        if key in after:
            known = set(finding.counterevidence_ids)
            new_counter = [c for c in after[key].counterevidence_ids if c not in known]
            contradictions = [
                Contradiction(assertion_id=None, verification_status=None, counterevidence_id=c)
                for c in new_counter
            ]
            change: ClaimChange = "contradicted" if contradictions else "unchanged"
            claims.append(_claim(change, after[key], contradictions))
            continue
        contradictions = [
            Contradiction(assertion_id=a, verification_status=states[a], counterevidence_id=None)
            for a in key[1]
            if states.get(a) in _CONTRADICTING_STATES
        ]
        claims.append(
            _claim("contradicted" if contradictions else "removed", finding, contradictions)
        )
    claims.extend(_claim("new", finding, []) for key, finding in after.items() if key not in before)
    counts = {change: 0 for change in ("new", "contradicted", "unchanged", "removed")}
    for claim in claims:
        counts[claim.change] += 1
    return HypothesisDiff(
        hypothesis_id=hypothesis_id,
        from_version=earlier.version,
        to_version=later.version,
        from_sha256=earlier.content_sha256,
        to_sha256=later.content_sha256,
        claims=claims,
        counts=DiffCounts.model_validate(counts),
        fields_changed=_fields_changed(earlier.content, later.content),
    )


def _key(finding: CardFinding) -> tuple[str, tuple[uuid.UUID, ...]]:
    statement = " ".join(finding.claim_text.split()).casefold()
    return statement, tuple(sorted({span.assertion_id for span in finding.source_spans}))


def _claim(
    change: ClaimChange, finding: CardFinding, contradictions: list[Contradiction]
) -> DiffClaim:
    return DiffClaim(
        change=change,
        claim_text=finding.claim_text,
        claim_ids=finding.claim_ids,
        assertion_ids=list(dict.fromkeys(span.assertion_id for span in finding.source_spans)),
        contradictions=contradictions,
    )


def _assertion_states(
    connection: Connection, assertion_ids: list[uuid.UUID]
) -> dict[uuid.UUID, str]:
    if not assertion_ids:
        return {}
    rows = connection.execute(
        text("SELECT id, verification_status FROM assertion WHERE id = ANY(:ids)"),
        {"ids": list(set(assertion_ids))},
    ).all()
    return {row.id: row.verification_status for row in rows}


def _fields_changed(earlier: HypothesisContent, later: HypothesisContent) -> list[str]:
    before = earlier.model_dump(mode="json")
    after = later.model_dump(mode="json")
    return [name for name in _FIELDS if before[name] != after[name]]
