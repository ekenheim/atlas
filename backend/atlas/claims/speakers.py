"""Who says a transcript's words (pilot-fixes ticket 22; `docs/decisions.md`, "Claim checks: an
analyst's words are not the company's").

A call or conference transcript (a Source Version whose Source Document has source type
`transcript`) is parsed one paragraph per line, each opening with its speaker's label
(`tradingview-transcript-v1`): "Alex Example (President and CEO, Example Photonics Inc): ...",
"Sam Sample (Analyst, Example Securities): ...", "Operator: ...". A quote is evidence of what
the company says only when the company's own people say it, so the speaker of a quote is found
from those labels:

- **The paragraphs** a quote covers are the lines its span overlaps. A quote over paragraphs of
  two speakers (or over a labelled and an unlabelled one) is refused `speaker_mixed`.
- **The label** is the start of the line up to its first ": ": a name of at most 80 characters
  without parentheses or a colon, optionally followed by one parenthetical, the speaker's role.
  A line with no such start has no label.
- **The company's people.** The label's parenthetical names the speaker's title and firm
  ("title, firm"; the firm is what follows its first comma, or the whole parenthetical when it
  has none). The speaker is the company's when that firm names the company whose transcript it
  is, by one of its names (`atlas.claims.predicates.mentions` through the typographic fold:
  the matcher the party check uses), and the parenthetical doesn't say "Analyst".
- **Refused otherwise.** A parenthetical with "Analyst" in it, or a title and another firm, is
  `analyst_speaking`; a paragraph with no label, a label with no parenthetical ("Operator") or
  a parenthetical that is a title alone and names no firm is `speaker_unknown`. The transcripts
  Atlas records carry affiliations, so an unlabelled paragraph is refused, not guessed.

The Investigator's Claims (`atlas.claims.extraction`) and the Skeptic's counterevidence
(`atlas.investigations.skeptic`) both ask `transcript_speaker`; nothing else decides it.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from atlas.claims.predicates import fold, mentions

TRANSCRIPT_SOURCE_TYPE = "transcript"

SpeakerRefusalCode = Literal["speaker_mixed", "analyst_speaking", "speaker_unknown"]

_LABEL = re.compile(r"(?P<name>[^():\n]{1,80}?)(?:\s*\((?P<role>[^()\n]{1,200})\))?:\s")
_ANALYST = re.compile(r"\banalyst\b", re.IGNORECASE)


@dataclass(frozen=True)
class SpeakerRefusal:
    """Why a transcript quote is not the company's own words."""

    code: SpeakerRefusalCode
    message: str


def speaker_label(line: str) -> str | None:
    """The speaker label `line` opens with ("Name (Title, Firm)", "Operator"), or None."""
    match = _LABEL.match(line)
    if match is None:
        return None
    return line[: match.end()].rstrip()[:-1].strip()


def transcript_speaker(
    text: str, span: tuple[int, int], company_names: Sequence[str]
) -> str | SpeakerRefusal:
    """The label of the company speaker whose words `text[span[0]:span[1]]` are, or why they
    are not the company's (`company_names`: the names of the company whose transcript it is)."""
    start, end = span
    labels = [speaker_label(line) for line in _lines(text, start, max(end, start + 1))]
    distinct = list(dict.fromkeys(labels))
    if len(distinct) > 1:
        shown = "; ".join(label or "a paragraph with no speaker label" for label in distinct)
        return SpeakerRefusal(
            "speaker_mixed",
            f"the quote runs over the paragraphs of more than one speaker ({shown}): a quote is"
            " one speaker's words",
        )
    label = distinct[0] if distinct else None
    company = company_names[0] if company_names else "the company"
    if label is None:
        return SpeakerRefusal(
            "speaker_unknown",
            "the paragraph the quote is in has no speaker label, so nothing shows that"
            f" {company}'s people said it",
        )
    match = _LABEL.match(label + ": ")
    role = (match["role"] or "").strip() if match is not None else ""
    if not role:
        return SpeakerRefusal(
            "speaker_unknown",
            f"the speaker label {label!r} has no affiliation, so nothing shows that"
            f" {company}'s people said it",
        )
    if _ANALYST.search(role):
        return SpeakerRefusal(
            "analyst_speaking",
            f"the quote is the words of {label}, an analyst: an analyst's question or remark is"
            f" context, not a statement by {company}",
        )
    title, comma, firm = role.partition(",")
    affiliation = firm if comma else title
    if mentions(fold(affiliation), [fold(name) for name in company_names]):
        return label
    if comma:
        return SpeakerRefusal(
            "analyst_speaking",
            f"the quote is the words of {label}, who speaks for another firm than {company}:"
            f" only {company}'s own people make its statements",
        )
    return SpeakerRefusal(
        "speaker_unknown",
        f"the speaker label {label!r} names no firm, so nothing shows that {company}'s people"
        " said it",
    )


def _lines(text: str, start: int, end: int) -> list[str]:
    """The lines of `text` that `[start, end)` overlaps, whole."""
    first = text.rfind("\n", 0, start) + 1
    last = text.find("\n", max(end - 1, start))
    return text[first : len(text) if last < 0 else last].split("\n")
