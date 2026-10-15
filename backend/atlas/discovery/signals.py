"""Archive bottleneck signals: the scorer (atlas-beliefs ticket 18; `docs/decisions.md`,
"Archive signals are leads").

A pure function of a document's parsed text, a few facts about the document and the config
(`configs/discovery/signals.yaml`, `ATLAS_SIGNALS_CONFIG`): no database, no archive, no model.
`SignalScorer.scan` reads the text sentence by sentence and returns the sentences that read
like a bottleneck, best first, each with its span and why it scored.

- **Sentences.** A line of the parsed text is a paragraph (a call transcript has one per
  speaker turn, opening with the speaker's label). A paragraph is cut at sentence ends: a full
  stop, `?` or `!` (with its closing quotes) followed by a space and a capital, digit, `$` or
  opening quote, unless the word before the stop is an abbreviation ("Inc.", "No.", "U.S.").
  A sentence is kept when it is between `min_sentence_chars` and `max_sentence_chars` long (a
  table row run together is not a statement). Offsets are code points into the text, like an
  Assertion's span, and the sentence is the text at the span, verbatim.
- **Cue families.** Each family of the config is a kind of scarcity (few suppliers, demand
  beyond supply, lead times and backlog, capacity, gates, pricing power) with phrases as regular
  expressions over the sentence (typographic apostrophes, quotes and dashes folded to ASCII,
  which keeps every offset). A phrase may name a sense in which it does not count (`unless`:
  "sold out of its position"). A sentence matching no family is no hit.
- **Negation.** A phrase preceded in its clause by a negator that governs it ("they are not sold
  out", "we have no capacity constraints", "without any shortages") is not a match. The clause
  runs back from the phrase to the last break (a comma, a dash, "but", "because"), the negator
  must be within `negation.window_words` words, and "not only", "no matter" and the like do not
  negate. A negator inside the phrase's own gap words ("demand does not exceed supply", "lead
  times have not lengthened") cancels it too. A phrase that carries its own negation ("not
  taking orders", "cannot be adequately served", "no second source") says `own_negation: true`
  and is not checked.
- **Score.** See the config's header: the families matched, weighted; a bonus when two
  families are told in one paragraph (to a sentence that scores `cooccurrence_min_own` on its
  own: a bare word cannot ride on its neighbour's cue); a bonus for a figure; then the factors
  for who speaks (a call transcript's label through `atlas.claims.speakers`: the company's
  people, an analyst, none recognised), for a question, for a risk-factors section
  (`Item 1A`, found by the sectioner), for a sentence hedged with could, may or might, and for
  safe-harbor wording.
- **The ranked read.** `cap_per_document` is the rule the ranked reads share (the leads route,
  the MCP tool, the replay script): at most `ranking.max_per_document` hits of one document
  stand among the first results, the rest after them, so one call does not fill the list. The
  scan stores every hit; only the reading order changes.
- **A hit is a lead.** Nothing here is a Claim, a Fact or Evidence: the agent that follows a hit
  reads the window and records a Fact itself.
"""

import re
from bisect import bisect_right
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from atlas.claims.speakers import (
    TRANSCRIPT_SOURCE_TYPE,
    SpeakerRefusal,
    speaker_label,
    transcript_speaker,
)
from atlas.retention.sections import split_sections

SCORER_VERSION = "signals-v2"

SpeakerKind = Literal["management", "analyst", "unknown"]


class SignalsConfigError(ValueError):
    """The signals config is missing or invalid; the message says where."""


def _compiled(pattern: str, flags: int = re.IGNORECASE) -> re.Pattern[str]:
    try:
        return re.compile(pattern, flags)
    except re.error as error:
        raise ValueError(f"not a regular expression ({error}): {pattern}") from None


class Phrase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    pattern: str
    weight: float = Field(default=1.0, gt=0, le=1)  # a factor of the family's weight
    unless: str | None = None  # in the sentence: this phrase is used in another sense
    own_negation: bool = False  # the phrase itself says "not"/"no": a negator before it is moot

    @field_validator("pattern", "unless")
    @classmethod
    def _regex(cls, value: str | None) -> str | None:
        if value is not None:
            _compiled(value)
        return value


class Family(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    weight: float = Field(gt=0, le=10)
    phrases: tuple[Phrase, ...] = Field(min_length=1)


class SpeakerFactors(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    management: float = Field(ge=0, le=3)
    unknown: float = Field(ge=0, le=3)
    analyst: float = Field(ge=0, le=3)


class Boilerplate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    sections: tuple[str, ...] = ()  # a section whose anchor ends with one: risk factors
    section_factor: float = Field(ge=0, le=1)
    hedge_words: tuple[str, ...] = ()
    hedge_factor: float = Field(ge=0, le=1)
    phrases: tuple[str, ...] = ()
    phrase_factor: float = Field(ge=0, le=1)

    @field_validator("phrases")
    @classmethod
    def _regexes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            _compiled(value)
        return values


class Negation(BaseModel):
    """What counts as a negator, where its clause ends and how far it reaches."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    negators: tuple[str, ...] = Field(min_length=1)  # regular expressions
    exceptions: tuple[str, ...] = ()  # text right after a negator that means it negates nothing
    clause_breaks: tuple[str, ...] = ()  # where a clause ends, so a negator before does not reach
    window_words: int = Field(ge=1, le=20)  # words between the negator and the phrase, at most

    @field_validator("negators", "exceptions", "clause_breaks")
    @classmethod
    def _regexes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            _compiled(value)
        return values


class Ranking(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_per_document: int = Field(ge=1, le=100)  # hits of one document among the first results


class SignalsConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: int = Field(ge=1)
    min_score: float = Field(gt=0, le=100)
    repeat_factor: float = Field(ge=0, le=1)
    cooccurrence_bonus: float = Field(ge=0, le=10)
    cooccurrence_min_own: float = Field(ge=0, le=10)
    figure_bonus: float = Field(ge=0, le=10)
    question_factor: float = Field(ge=0, le=1)
    max_sentence_chars: int = Field(ge=100, le=10_000)
    min_sentence_chars: int = Field(ge=1, le=200)
    speaker: SpeakerFactors
    boilerplate: Boilerplate
    negation: Negation
    ranking: Ranking
    figures: tuple[str, ...] = ()
    families: dict[str, Family] = Field(min_length=1)

    @field_validator("figures")
    @classmethod
    def _figure_regexes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            _compiled(value)
        return values

    @field_validator("families")
    @classmethod
    def _family_names(cls, values: dict[str, Family]) -> dict[str, Family]:
        for name in values:
            if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
                raise ValueError(f"family name {name!r} is not snake_case")
        return values


def load_signals_config(path: Path) -> SignalsConfig:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise SignalsConfigError(f"signals config {path}: {error}") from None
    try:
        return SignalsConfig.model_validate(raw)
    except ValidationError as error:
        raise SignalsConfigError(f"signals config {path}: {error}") from None


@dataclass(frozen=True)
class PhraseMatch:
    family: str
    pattern: str
    text: str  # what the pattern matched, as written


@dataclass(frozen=True)
class SignalHit:
    """One sentence that reads like a bottleneck."""

    start: int  # code points into the scanned text
    end: int
    quote: str  # the text at the span, verbatim
    section_anchor: str | None
    families: tuple[str, ...]  # the families the sentence matched, in the config's order
    matches: tuple[PhraseMatch, ...]
    score: float
    factors: Mapping[str, float]  # what made the score: the terms and the factors applied
    speaker: str | None  # a transcript sentence's speaker label
    speaker_kind: SpeakerKind | None  # None outside a call transcript


# --- sentences --------------------------------------------------------------------------------

_FOLD = {
    0x2018: "'",
    0x2019: "'",
    0x201B: "'",
    0x201C: '"',
    0x201D: '"',
    0x2010: "-",
    0x2011: "-",
    0x2012: "-",
    0x2013: "-",
    0x2014: "-",
    0x2212: "-",
    0x00A0: " ",
}
_END = re.compile(r"[.!?][\"')\]]*(?=\s+[\"'(\[]?[A-Z0-9$])")
_ABBREVIATIONS = frozenset(
    "inc corp co ltd llc plc no nos vs mr mrs ms dr st jr sr approx fig mt".split()
)
_LAST_WORD = re.compile(r"([A-Za-z][A-Za-z.]*)\.$")


def _fold(text: str) -> str:
    """The text with typographic quotes and dashes as ASCII: the same length, so offsets hold."""
    return text.translate(_FOLD)


def sentence_spans(paragraph: str) -> list[tuple[int, int]]:
    """The sentences of one paragraph: their [start, end) spans, without surrounding space."""
    spans: list[tuple[int, int]] = []
    begin = 0
    for match in _END.finditer(paragraph):
        if match.group()[0] == ".":
            word = _LAST_WORD.search(paragraph[: match.start() + 1])
            if word is not None:
                last = word.group(1)
                if (
                    last.lower() in _ABBREVIATIONS  # "Inc."
                    or ("." in last and all(len(part) == 1 for part in last.split(".")))  # "U.S."
                    or (len(last) == 1 and last.isupper())  # an initial: "J. Smith"
                ):
                    continue
        spans.append((begin, match.end()))
        begin = match.end()
    spans.append((begin, len(paragraph)))
    trimmed: list[tuple[int, int]] = []
    for start, end in spans:
        chunk = paragraph[start:end]
        lead = len(chunk) - len(chunk.lstrip())
        stop = len(chunk.rstrip())
        if stop > lead:
            trimmed.append((start + lead, start + stop))
    return trimmed


# --- the scorer -------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Compiled:
    family: str
    pattern: str
    regex: re.Pattern[str]
    weight: float
    unless: re.Pattern[str] | None
    own_negation: bool


@dataclass(frozen=True)
class _Sentence:
    start: int
    end: int
    quote: str
    matches: tuple[tuple[PhraseMatch, float, int, int], ...]  # (match, factor, start, end)


class SignalScorer:
    """The config, compiled once."""

    def __init__(self, config: SignalsConfig) -> None:
        self.config = config
        self._phrases = [
            _Compiled(
                name,
                phrase.pattern,
                _compiled(phrase.pattern),
                phrase.weight,
                _compiled(phrase.unless) if phrase.unless else None,
                phrase.own_negation,
            )
            for name, family in config.families.items()
            for phrase in family.phrases
        ]
        self._order = list(config.families)
        negation = config.negation
        self._negators = [_compiled(each) for each in negation.negators]
        self._exceptions = [_compiled(f"^(?:{each})") for each in negation.exceptions]
        self._breaks = (
            re.compile("|".join(f"(?:{each})" for each in negation.clause_breaks), re.IGNORECASE)
            if negation.clause_breaks
            else None
        )
        self._figures = [_compiled(each) for each in config.figures]
        boilerplate = config.boilerplate
        self._hedge = (
            re.compile(rf"\b(?:{'|'.join(map(re.escape, boilerplate.hedge_words))})\b")
            if boilerplate.hedge_words
            else None
        )
        self._phrase_boilerplate = [_compiled(each) for each in boilerplate.phrases]

    def scan(
        self,
        text: str,
        *,
        form_type: str | None,
        primary: bool,
        source_type: str | None,
        company_names: Sequence[str],
    ) -> list[SignalHit]:
        """The sentences of `text` that score at least `min_score`, best first (ties: earlier
        first). `form_type` and `primary` say how the sectioner cuts the text (an SEC primary
        document has its Items); a `source_type` of `transcript` makes each line a speaker's
        turn, scored by who speaks (`company_names`: the names of the company whose call it is)."""
        sections = split_sections(text, form=form_type, primary=primary)
        section_starts = [section.start for section in sections]
        transcript = source_type == TRANSCRIPT_SOURCE_TYPE
        hits: list[SignalHit] = []
        position = 0
        for line in text.split("\n"):
            line_start, position = position, position + len(line) + 1
            if not line.strip():
                continue
            offset = 0
            if transcript and (label := speaker_label(line)) is not None:
                offset = line.index(label) + len(label)
                offset += line[offset:].index(":") + 1
            sentences = self._sentences(line, line_start, offset)
            if not any(each.matches for each in sentences):
                continue
            speaker, kind = None, None
            if transcript:
                speaker, kind = _speaker(text, line_start, line_start + len(line), company_names)
            paragraph_families = {m.family for each in sentences for m, *_ in each.matches}
            for sentence in sentences:
                if not sentence.matches:
                    continue
                anchor = None
                if sections:
                    index = bisect_right(section_starts, sentence.start) - 1
                    anchor = sections[max(index, 0)].anchor
                hit = self._score(sentence, paragraph_families, anchor, speaker, kind)
                if hit is not None:
                    hits.append(hit)
        hits.sort(key=lambda each: (-each.score, each.start))
        return hits

    def _sentences(self, line: str, line_start: int, offset: int) -> list[_Sentence]:
        found: list[_Sentence] = []
        for begin, end in sentence_spans(line[offset:]):
            begin, end = begin + offset, end + offset
            length = end - begin
            if length < self.config.min_sentence_chars or length > self.config.max_sentence_chars:
                continue
            quote = line[begin:end]
            folded = _fold(quote)
            matches: list[tuple[PhraseMatch, float, int, int]] = []
            for phrase in self._phrases:
                match = phrase.regex.search(folded)
                if match is None or (phrase.unless is not None and phrase.unless.search(folded)):
                    continue
                if not phrase.own_negation and self._negated(folded, match.start(), match.end()):
                    continue
                matches.append(
                    (
                        PhraseMatch(
                            phrase.family, phrase.pattern, quote[match.start() : match.end()]
                        ),
                        phrase.weight,
                        match.start(),
                        match.end(),
                    )
                )
            found.append(_Sentence(line_start + begin, line_start + end, quote, tuple(matches)))
        return found

    def _negated(self, folded: str, start: int, end: int) -> bool:
        """Whether a negator governs the phrase that spans `start` to `end`: it stands in the same
        clause before the phrase, within `window_words` words, or inside the phrase's own gap
        words ("demand does not exceed supply"), and is not one of the exceptions ("not only")."""
        inside = folded[start:end]
        for negator in self._negators:
            for found in negator.finditer(inside):
                if not any(each.search(inside[found.end() :]) for each in self._exceptions):
                    return True
        clause = folded[:start]
        if self._breaks is not None:
            ends = [each.end() for each in self._breaks.finditer(clause)]
            if ends:
                clause = clause[ends[-1] :]
        for negator in self._negators:
            for found in negator.finditer(clause):
                after = clause[found.end() :]
                if len(after.split()) <= self.config.negation.window_words and not any(
                    each.search(after) for each in self._exceptions
                ):
                    return True
        return False

    def _score(
        self,
        sentence: _Sentence,
        paragraph_families: set[str],
        anchor: str | None,
        speaker: str | None,
        kind: SpeakerKind | None,
    ) -> SignalHit | None:
        config = self.config
        factors: dict[str, float] = {}
        families = [
            name for name in self._order if any(m.family == name for m, *_ in sentence.matches)
        ]
        total = 0.0
        for name in families:
            counted: list[tuple[float, int, int]] = []
            own = sorted(
                (
                    (factor, begin, stop)
                    for m, factor, begin, stop in sentence.matches
                    if m.family == name
                ),
                key=lambda each: (-each[0], each[1]),
            )
            for factor, begin, stop in own:
                if all(
                    stop <= other_begin or begin >= other_stop
                    for _, other_begin, other_stop in counted
                ):
                    counted.append((factor, begin, stop))
            best, extras = counted[0][0], counted[1:3]
            weight = config.families[name].weight
            total += weight * (best + config.repeat_factor * sum(each[0] for each in extras))
        factors["families"] = round(total, 3)
        if (
            len(paragraph_families) >= 2
            and config.cooccurrence_bonus
            and total >= config.cooccurrence_min_own
        ):
            total += config.cooccurrence_bonus
            factors["cooccurrence"] = config.cooccurrence_bonus
        folded = _fold(sentence.quote)
        if config.figure_bonus and any(each.search(folded) for each in self._figures):
            total += config.figure_bonus
            factors["figure"] = config.figure_bonus
        if kind is not None:
            factor = getattr(config.speaker, kind)
            total *= factor
            factors["speaker"] = factor
        if sentence.quote.rstrip().endswith("?"):
            total *= config.question_factor
            factors["question"] = config.question_factor
        boilerplate = config.boilerplate
        if anchor is not None and anchor.endswith(boilerplate.sections):
            total *= boilerplate.section_factor
            factors["risk_factors"] = boilerplate.section_factor
        if self._hedge is not None and self._hedge.search(folded):
            total *= boilerplate.hedge_factor
            factors["hedge"] = boilerplate.hedge_factor
        if any(each.search(folded) for each in self._phrase_boilerplate):
            total *= boilerplate.phrase_factor
            factors["boilerplate"] = boilerplate.phrase_factor
        score = round(total, 2)
        if score < config.min_score:
            return None
        return SignalHit(
            start=sentence.start,
            end=sentence.end,
            quote=sentence.quote,
            section_anchor=anchor,
            families=tuple(families),
            matches=tuple(match for match, *_ in sentence.matches),
            score=score,
            factors=factors,
            speaker=speaker,
            speaker_kind=kind,
        )


def cap_per_document[T](ranked: Sequence[T], document: Callable[[T], object], cap: int) -> list[T]:
    """The ranked hits as the ranked reads show them: the order given (best first), except that
    a document's hits after its first `cap` come after every hit within a cap. Stored leads are
    not touched; this is only the reading order."""
    counts: dict[object, int] = {}
    within: list[T] = []
    beyond: list[T] = []
    for each in ranked:
        key = document(each)
        counts[key] = counts.get(key, 0) + 1
        (within if counts[key] <= cap else beyond).append(each)
    return within + beyond


def _speaker(
    text: str, start: int, end: int, company_names: Sequence[str]
) -> tuple[str | None, SpeakerKind]:
    said = transcript_speaker(text, (start, end), company_names)
    if isinstance(said, SpeakerRefusal):
        label = speaker_label(text[start:end])
        if said.code == "analyst_speaking":
            return label, "analyst"
        return label, "unknown"
    return said, "management"
