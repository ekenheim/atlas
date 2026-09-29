"""The one rule for a Hypothesis finding: it cites accepted Claims of its investigation and
nothing else. A proposed finding (the Editor's or the researcher's) that cites none, or cites
anything else, is unsupported: recorded, never promoted to a finding. A kept finding is the
§7.2 claim shape with its spans, Source Versions, Assertions and Evidence Families filled in
by code from the cited Claims (atlas.investigations.tasks.card_finding)."""

from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy import RowMapping

from atlas.investigations.model import CardFinding, UnsupportedFinding
from atlas.investigations.tasks import card_finding


@dataclass(frozen=True)
class ProposedFinding:
    statement: str
    claim_ids: list[str]
    limitations: list[str] = field(default_factory=list[str])
    open_questions: list[str] = field(default_factory=list[str])


def resolve_findings(
    proposed: Sequence[ProposedFinding], claims: Sequence[RowMapping]
) -> tuple[list[CardFinding], list[UnsupportedFinding]]:
    """The findings citing only accepted Claims (in `claims`), and the unsupported rest."""
    by_id = {str(claim["id"]): claim for claim in claims}
    findings: list[CardFinding] = []
    unsupported: list[UnsupportedFinding] = []
    for each in proposed:
        cited = list(dict.fromkeys(each.claim_ids))
        unknown = [claim_id for claim_id in cited if claim_id not in by_id]
        if not cited or unknown:
            reason = (
                "cites no Claim"
                if not cited
                else "cites what isn't an accepted Claim of this investigation: "
                + ", ".join(unknown)
            )
            unsupported.append(
                UnsupportedFinding(
                    statement=each.statement, claim_ids=each.claim_ids, reason=reason
                )
            )
            continue
        findings.append(card_finding(each.statement, [by_id[c] for c in cited], each))
    return findings, unsupported
