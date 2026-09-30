"""The deterministic checks of Relationship review, and how they combine with the Reviewer.

An Assertion is machine-reviewed into its Relationship only when all of these hold (spec
"Relationships", "Review"; `docs/decisions.md`, "Relationship review is LLM-assisted"):

1. **Verbatim span** (`span_not_verbatim`): the quote is exactly the archived parse at its
   offsets, read again at review time (the archive checks the object's hash on every read).
2. **Tier A source** (`not_tier_a`): the quoted Source Document is Tier A (primary material:
   filings, official exchange announcements).
3. **Explicitly directional language**: a pattern list plus the Reviewer's classification.
   The patterns (`directional_language`) are the Investigator's cues for the predicate
   (`atlas.claims.directional_cue`: no cue is co-mention, `no_directional_language`) plus a
   list of **hedges** (`hedged_language`): "may", "could", "expects to", "in discussions",
   "non-binding", "reportedly" and the like, which make a statement conditional, planned or
   second-hand rather than explicit. Patterns can't tell who "we" is, so they never judge the
   direction itself: that is the Reviewer's `direction`, which must be `as_proposed`. For a
   product object the cue must also be in a clause naming the object
   (`atlas.claims.object_clause_cue`); eligibility checks that (`cue_in_other_clause`).
4. **The Reviewer confirms** (`reviewer_rejected`, `reviewer_uncertain`): its verdict is
   `confirmed`, its direction `as_proposed` (`direction_not_confirmed`) and its layer
   `correct` (`layer_not_confirmed`).

Anything short of that sends the Relationship to the exceptions queue (`needs_human_review`)
with the reasons. When the Reviewer gives no usable answer, the reason says why
(`reviewer_quarantined`, `reviewer_no_answer`). The Reviewer is asked only about Assertions
that pass the deterministic checks: the others go to a human whatever it would say.
"""

import re
from dataclasses import dataclass
from typing import Literal

from atlas.claims.predicates import directional_cue
from atlas.roles.reviewer import Direction, LayerVerdict, Verdict

LanguageVerdict = Literal["explicit", "hedged", "absent"]
ReviewOutcome = Literal["machine_reviewed", "needs_human_review"]

_HEDGES: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bmay\b"),  # lower case only: "May" is also a month
    re.compile(r"\b(?:might|could|would)\b", re.IGNORECASE),
    re.compile(r"\bpotential(?:ly)?\b", re.IGNORECASE),
    re.compile(
        r"\b(?:expects?|expected|plans?|planned|intends?|intended|anticipates?|anticipated"
        r"|aims?|seeks?|hopes?) to\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bin (?:discussions|negotiations|talks)\b", re.IGNORECASE),
    re.compile(r"\bnon-binding\b", re.IGNORECASE),
    re.compile(r"\b(?:memorandum of understanding|letter of intent)\b", re.IGNORECASE),
    re.compile(r"\b(?:MOU|LOI)\b"),
    re.compile(r"\breported(?:ly)?\b", re.IGNORECASE),
    re.compile(r"\b(?:rumou?r\w*|allegedly|speculat\w*)\b", re.IGNORECASE),
)


@dataclass(frozen=True)
class DirectionalLanguage:
    """`explicit`: a cue for the predicate and no hedge; `hedged`: a cue and a hedge (the
    first); `absent`: no cue (co-mention, or a predicate outside the whitelist)."""

    verdict: LanguageVerdict
    cue: str | None
    hedge: str | None


def directional_language(predicate: str, quote: str) -> DirectionalLanguage:
    cue = directional_cue(predicate, quote)
    if cue is None:
        return DirectionalLanguage("absent", None, None)
    found = [match for hedge in _HEDGES if (match := hedge.search(quote)) is not None]
    if found:
        return DirectionalLanguage("hedged", cue, min(found, key=lambda m: m.start())[0])
    return DirectionalLanguage("explicit", cue, None)


@dataclass(frozen=True)
class DeterministicChecks:
    verbatim_span: bool
    tier_a: bool
    language: DirectionalLanguage

    @property
    def reasons(self) -> list[str]:
        reasons: list[str] = []
        if not self.verbatim_span:
            reasons.append("span_not_verbatim")
        if not self.tier_a:
            reasons.append("not_tier_a")
        if self.language.verdict == "hedged":
            reasons.append("hedged_language")
        elif self.language.verdict == "absent":
            reasons.append("no_directional_language")
        return reasons

    @property
    def passed(self) -> bool:
        return not self.reasons


def deterministic_checks(
    *,
    predicate: str,
    quote: str,
    span_start: int,
    span_end: int,
    parsed_text: str | None,
    source_tier: str,
) -> DeterministicChecks:
    """The checks for one Assertion. `parsed_text` is its Source Version's archived parse, or
    None when it couldn't be read (then the span isn't verbatim)."""
    verbatim = (
        parsed_text is not None
        and span_end - span_start == len(quote)
        and parsed_text[span_start:span_end] == quote
    )
    return DeterministicChecks(
        verbatim_span=verbatim,
        tier_a=source_tier == "A",
        language=directional_language(predicate, quote),
    )


@dataclass(frozen=True)
class ReviewerAnswer:
    verdict: Verdict
    direction: Direction
    layer: LayerVerdict


def review_outcome(
    checks: DeterministicChecks, answer: ReviewerAnswer | None, *, missing: str | None = None
) -> tuple[ReviewOutcome, list[str]]:
    """The outcome and its reasons (empty when machine-reviewed). `answer` is None when the
    Reviewer wasn't asked (the checks failed) or gave no usable answer (`missing` says why)."""
    reasons = checks.reasons
    if answer is None:
        if missing is not None:
            reasons.append(missing)
    else:
        if answer.verdict != "confirmed":
            reasons.append(f"reviewer_{answer.verdict}")
        if answer.direction != "as_proposed":
            reasons.append("direction_not_confirmed")
        if answer.layer != "correct":
            reasons.append("layer_not_confirmed")
    if answer is None and missing is None and not reasons:
        raise ValueError("a passing Assertion needs the Reviewer's answer or why it has none")
    return ("needs_human_review" if reasons else "machine_reviewed"), reasons
