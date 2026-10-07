"""Known answers: does Memory point at the sections a reviewed answer lies in?

The file (`configs/memory/known-answers.yaml`, memory-quality ticket 14) names, per pilot
question (a probe of `configs/memory/probes.yaml`), the Source Version sections that hold an
answer: the company, the document (its URL, its accession number, or its form and filing date),
the section anchor when known, and the sentence, so a reviewer can check it. Each answer is
labelled with the **hop** of the supply chain it is about and the **part of the bottleneck
test** it serves (the Serenity method's M1 to M6 and M10: `docs/research/` on branch
`research/serenity-skills-alignment`), so the report shows a Memory that finds every capacity
statement and no second-source statement for what it is.

Validated at load (`KnownAnswersError`): unique IDs, every question a probe of the probe set,
every company in the universe, a known hop and test part, a sentence. Against a running Atlas
every answer is **resolved** before anything is scored: its document must exist and contain
its sentence (typography and whitespace folded), and a given anchor must be the section the
sentence lies in; an answer without an anchor gets the section the sentence lies in (the
report lists it, for the file). An answer that does not resolve is an **error**, never a miss.

Then each question is recalled as an investigation's pointer recalls are (the question and its
Scout-style queries, each scoped to the probe's themes; `POST /api/v1/memory/recall`, no LLM
call), the resolved sections of every answer are merged **by rank** (each recall's first
section, then each one's second, and so on; each section once), and recall at 10 and at 50 is
the share of the answers whose section is among the first 10 or 50. Reported per question, per
hop, per test part and overall, against the file's thresholds (on the overall figures).
"""

import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal, Self, cast

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from atlas.companies import Universe
from atlas.conformance.api import AtlasApi, AtlasApiError
from atlas.research.probes import ProbeSet
from atlas.research.service import ResearchScope, reading_index_recall
from atlas.retention.sections import split_sections
from atlas.settings import Settings

Hop = Literal["demand", "system", "module", "chip", "substrate", "feedstock", "equipment"]
HOPS: tuple[Hop, ...] = (
    "demand",
    "system",
    "module",
    "chip",
    "substrate",
    "feedstock",
    "equipment",
)
TestPart = Literal[
    "demand_vs_capacity", "second_source", "pricing_power", "bom_share", "financing_dilution"
]
TEST_PARTS: tuple[TestPart, ...] = (
    "demand_vs_capacity",
    "second_source",
    "pricing_power",
    "bom_share",
    "financing_dilution",
)
CUTOFFS = (10, 50)
MIN_ANSWERS = 20  # the ticket's floor for the configured file


class KnownAnswersError(ValueError):
    """The known-answers file is invalid."""


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DocumentRef(_Config):
    """Which Source Document: its URL, else its accession number (the primary document, or
    `exhibit` by its document type, e.g. EX-99.1), else its form and filing date."""

    url: str | None = None
    accession: str | None = None
    exhibit: str | None = None
    form: str | None = None
    filed: date | None = None

    @model_validator(mode="after")
    def _identifies(self) -> Self:
        if not (self.url or self.accession or (self.form and self.filed)):
            raise ValueError("a document needs its url, its accession, or its form and filed date")
        return self

    def describe(self) -> str:
        if self.url:
            return self.url
        if self.accession:
            return f"accession {self.accession}" + (f" {self.exhibit}" if self.exhibit else "")
        return f"{self.form} filed {self.filed}" + (f" {self.exhibit}" if self.exhibit else "")


class KnownAnswer(_Config):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    question: str  # a probe ID
    company: str  # a universe slug
    document: DocumentRef
    section: str | None = None  # the anchor; None: found from the sentence when run
    sentence: str = Field(min_length=20)
    hop: Hop
    test: TestPart
    # Where the answer comes from: the pilot review quotes the fact (`review_quote`), the review
    # names it missing and the sentence is the archive's (`review_gap`), or the question asks for
    # it in its own words and no review covers it (`question`).
    basis: Literal["review_quote", "review_gap", "question"]
    review: str = Field(min_length=1)  # the pilot review's item (or why there is none)


class Thresholds(_Config):
    recall_at_10: float = Field(ge=0, le=1)
    recall_at_50: float = Field(ge=0, le=1)


class KnownAnswerSet(_Config):
    version: int = Field(ge=1)
    thresholds: Thresholds
    answers: tuple[KnownAnswer, ...]

    @model_validator(mode="after")
    def _unique(self) -> Self:
        ids = [answer.id for answer in self.answers]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"answer IDs must be unique: {', '.join(duplicates)}")
        return self


def load_known_answers(
    path: Path, universe: Universe, probes: ProbeSet, *, min_answers: int = MIN_ANSWERS
) -> KnownAnswerSet:
    """The file, validated against the universe and the probe set; raises `KnownAnswersError`."""
    try:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
        answers = KnownAnswerSet.model_validate(raw)
    except (OSError, yaml.YAMLError, ValidationError) as error:
        raise KnownAnswersError(f"{path}: {error}") from error
    if len(answers.answers) < min_answers:
        raise KnownAnswersError(
            f"{path}: {len(answers.answers)} answers; at least {min_answers} are required"
        )
    questions = {probe.id for probe in probes.probes}
    for answer in answers.answers:
        if answer.question not in questions:
            raise KnownAnswersError(f"{path}: {answer.id}: unknown question {answer.question}")
        if answer.company not in universe.companies:
            raise KnownAnswersError(f"{path}: {answer.id}: unknown company {answer.company}")
    return answers


# --- folding: find a sentence whatever its typography -------------------------------------------

# Typographic quotes, hyphens, dashes and the no-break space, by code point, as ASCII.
_FOLD = str.maketrans(
    {
        0x2018: "'",
        0x2019: "'",
        0x201C: '"',
        0x201D: '"',
        0x2010: "-",
        0x2011: "-",
        0x2012: "-",
        0x2013: "-",
        0x2014: "-",
        0x00A0: " ",
    }
)
_SPACE = re.compile(r"\s+")


def fold(text: str) -> tuple[str, list[int]]:
    """`text` with typographic quotes, hyphens and dashes made ASCII and every run of
    whitespace one space; and for each folded character, its offset in `text`."""
    folded: list[str] = []
    offsets: list[int] = []
    for match in re.finditer(r"\s+|\S", text):
        piece = match.group()
        if piece.isspace():
            if folded and folded[-1] != " ":
                folded.append(" ")
                offsets.append(match.start())
            continue
        folded.append(piece.translate(_FOLD))
        offsets.append(match.start())
    return "".join(folded), offsets


def find_sentence(text: str, sentence: str) -> tuple[int, int] | None:
    """Where `sentence` lies in `text` ([start, end) code points), typography and whitespace
    folded; None when it doesn't occur."""
    haystack, offsets = fold(text)
    needle = _SPACE.sub(" ", sentence.translate(_FOLD)).strip()
    at = haystack.find(needle)
    if at < 0 or not needle:
        return None
    return offsets[at], offsets[at + len(needle) - 1] + 1


# --- resolving answers against Atlas -------------------------------------------------------------

SectionKey = tuple[str, str]  # (source document ID, section anchor)


class ResolvedAnswer(BaseModel):
    id: str
    question: str
    company: str
    hop: Hop
    test: TestPart
    source_document_id: str
    source_version_id: str
    canonical_url: str
    section: str
    section_found_by: Literal["file", "sentence"]  # given in the file, or found when run
    in_memory: bool  # the section has a memory document in the bank (any retain state)
    retain_state: str | None

    @property
    def key(self) -> SectionKey:
        return (self.source_document_id, self.section)


class AnswerError(BaseModel):
    id: str
    error: str


def resolve_answers(
    api: AtlasApi, answers: Sequence[KnownAnswer]
) -> tuple[list[ResolvedAnswer], list[AnswerError]]:
    """Each answer's section in the running Atlas, or why it has none (an error, not a miss)."""
    companies = {c["slug"]: str(c["id"]) for c in api.pages("/companies")}
    sources: dict[str, list[dict[str, Any]]] = {}
    resolved: list[ResolvedAnswer] = []
    errors: list[AnswerError] = []
    for answer in answers:
        try:
            if answer.company not in companies:
                raise _Unresolved(f"company {answer.company} is not in this Atlas")
            company_id = companies[answer.company]
            if company_id not in sources:
                sources[company_id] = list(api.pages(f"/companies/{company_id}/sources"))
            resolved.append(_resolve(api, answer, sources[company_id]))
        except (_Unresolved, AtlasApiError) as error:
            errors.append(AnswerError(id=answer.id, error=str(error)))
    return resolved, errors


class _Unresolved(Exception):
    pass


def _resolve(api: AtlasApi, answer: KnownAnswer, sources: list[dict[str, Any]]) -> ResolvedAnswer:
    candidates = _documents(api, answer.document, sources)
    if not candidates:
        raise _Unresolved(f"no Source Document matches {answer.document.describe()}")
    holding_sentence: list[tuple[dict[str, Any], str, str, tuple[int, int]]] = []
    for document in candidates:
        version_id = document.get("latest_version_id")
        if version_id is None:
            continue
        version = api.get(f"/source-versions/{version_id}")
        recorded = version.get("parser_version")
        parsed = api.text(
            f"/source-versions/{version_id}/content",
            kind="parsed",
            **({"parser_version": recorded} if recorded else {}),
        )
        span = find_sentence(parsed, answer.sentence)
        if span is not None:
            holding_sentence.append((document, str(version_id), parsed, span))
    if len(holding_sentence) != 1:
        where = "is not in" if not holding_sentence else "is in more than one of"
        raise _Unresolved(f"the sentence {where} the documents of {answer.document.describe()}")
    document, version_id, parsed, span = holding_sentence[0]
    memory = api.get(f"/source-versions/{version_id}/memory")
    retained = cast(list[dict[str, Any]], memory.get("documents") or [])
    holding = next(
        (d for d in retained if d["char_start"] <= span[0] and span[1] <= d["char_end"]), None
    )
    if holding is not None:
        anchor = str(holding["section_anchor"])
    else:
        primary = document.get("document_type") == document.get("form_type")
        sections = split_sections(parsed, form=document.get("form_type"), primary=primary)
        containing = [s for s in sections if s.start <= span[0] and span[1] <= s.end]
        if not containing:
            raise _Unresolved(
                f"the sentence crosses a section boundary in {answer.document.describe()}"
            )
        anchor = containing[0].anchor
    if answer.section is not None and answer.section != anchor:
        raise _Unresolved(
            f"the sentence is in section {anchor}, not {answer.section}, of"
            f" {answer.document.describe()}"
        )
    return ResolvedAnswer(
        id=answer.id,
        question=answer.question,
        company=answer.company,
        hop=answer.hop,
        test=answer.test,
        source_document_id=str(document["id"]),
        source_version_id=str(version_id),
        canonical_url=str(document["canonical_url"]),
        section=anchor,
        section_found_by="file" if answer.section is not None else "sentence",
        in_memory=holding is not None,
        retain_state=None if holding is None else str(holding["retain_state"]),
    )


def _documents(
    api: AtlasApi, ref: DocumentRef, sources: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """The Source Documents the reference may mean: one for a URL; a filing's documents for an
    accession or a form and date (narrowed to `exhibit` if given; the sentence then decides)."""
    if ref.url:
        return [s for s in sources if ref.url in (s["canonical_url"], s["origin_url"])]
    if ref.accession:
        wanted = ref.accession.replace("-", "")
        return [
            s
            for s in sources
            if (s.get("accession") or "").replace("-", "") == wanted and _is_part(s, ref.exhibit)
        ]
    found: list[dict[str, Any]] = []
    for source in sources:
        if source.get("form_type") != ref.form or not _is_part(source, ref.exhibit):
            continue
        versions = api.get(f"/sources/{source['id']}/versions")["items"]
        # Available at EDGAR's dissemination time (UTC): a filing made late in the US evening
        # is available on the next UTC day.
        filed = ref.filed
        assert filed is not None  # a reference with neither url nor accession has its date
        days = [
            abs((date.fromisoformat(str(v["available_at"])[:10]) - filed).days) for v in versions
        ]
        if any(day <= 1 for day in days):
            found.append(source)
    return found


def _is_part(source: Mapping[str, Any], exhibit: str | None) -> bool:
    return exhibit is None or source.get("document_type") == exhibit


# --- recalling and scoring ----------------------------------------------------------------------


def ranked_sections(answers: Iterable[Mapping[str, Any]]) -> list[SectionKey]:
    """The distinct sections several recall answers point at, merged by rank: every answer's
    first resolved section, then every answer's second, and so on."""
    per_answer: list[list[SectionKey]] = []
    for answer in answers:
        keys: list[SectionKey] = []
        for memory in cast(list[dict[str, Any]], answer.get("memories") or []):
            provenance = cast(dict[str, Any], memory.get("provenance") or {})
            if provenance.get("state") != "resolved":
                continue
            for source in cast(list[dict[str, Any]], provenance.get("sources") or []):
                key = (str(source["source_document_id"]), str(source["section_anchor"]))
                if key not in keys:
                    keys.append(key)
        per_answer.append(keys)
    merged: list[SectionKey] = []
    for rank in range(max((len(keys) for keys in per_answer), default=0)):
        for keys in per_answer:
            if rank < len(keys) and keys[rank] not in merged:
                merged.append(keys[rank])
    return merged


class Recall(BaseModel):
    answers: int
    at_10: float | None  # None: no answer to find
    at_50: float | None
    found_at_10: int
    found_at_50: int


def _recall(answers: Sequence[ResolvedAnswer], ranks: Mapping[str, int | None]) -> Recall:
    found = {k: sum(1 for a in answers if (ranks[a.id] or 10**9) <= k) for k in CUTOFFS}
    total = len(answers)
    return Recall(
        answers=total,
        at_10=round(found[10] / total, 4) if total else None,
        at_50=round(found[50] / total, 4) if total else None,
        found_at_10=found[10],
        found_at_50=found[50],
    )


class AnswerOutcome(BaseModel):
    answer: ResolvedAnswer
    rank: int | None  # the section's place in its question's merged ranking; None: absent


class QuestionRecalls(BaseModel):
    question: str
    recalls: int
    failed_recalls: list[str]
    sections_ranked: int


DEFAULT_RECALL_MAX_TOKENS: int = Settings.model_fields["pointer_recall_max_tokens"].default
"""What investigations recall with unless configured (`ATLAS_POINTER_RECALL_MAX_TOKENS`)."""


class KnownAnswersReport(BaseModel):
    max_tokens: int = DEFAULT_RECALL_MAX_TOKENS  # the recalls' results budget in tokens
    verdict: Literal["passed", "failed"]
    reason: str | None
    thresholds: Thresholds
    answers: int
    errors: list[AnswerError]
    overall: Recall
    by_question: dict[str, Recall]
    by_hop: dict[str, Recall]
    by_test_part: dict[str, Recall]
    outcomes: list[AnswerOutcome]
    recalls: list[QuestionRecalls]
    anchors_found: dict[str, str]  # answer ID -> anchor, for answers the file gives none


def run_known_answers(
    api: AtlasApi,
    answer_set: KnownAnswerSet,
    probes: ProbeSet,
    *,
    max_tokens: int = DEFAULT_RECALL_MAX_TOKENS,
    as_of: datetime | None = None,
) -> KnownAnswersReport:
    """Resolve every answer, recall every question, and score (read-only; no LLM call).

    Each recall is the investigations' (`atlas.research.service.reading_index_recall`, the one
    builder) at `max_tokens` of results, recency judged from `as_of` (default: now)."""
    as_of = as_of or datetime.now(UTC)
    resolved, errors = resolve_answers(api, answer_set.answers)
    asked = {answer.question for answer in answer_set.answers}
    ranks: dict[str, int | None] = {}
    recalls: list[QuestionRecalls] = []
    for probe in probes.probes:
        if probe.id not in asked:
            continue
        answers: list[dict[str, Any]] = []
        failed: list[str] = []
        for text in (probe.question, *probe.queries):
            request = reading_index_recall(
                text,
                ResearchScope(theme_ids=list(probe.scope.theme_ids)),
                max_tokens=max_tokens,
                as_of=as_of,
            )
            body = request.model_dump(mode="json", exclude_none=True)
            try:
                answers.append(cast(dict[str, Any], api.post("/memory/recall", body)))
            except AtlasApiError as error:
                failed.append(f"{text[:60]}: {error}")
        ranking = ranked_sections(answers)
        place = {key: index for index, key in enumerate(ranking, start=1)}
        for answer in resolved:
            if answer.question == probe.id:
                ranks[answer.id] = place.get(answer.key)
        recalls.append(
            QuestionRecalls(
                question=probe.id,
                recalls=len(answers) + len(failed),
                failed_recalls=failed,
                sections_ranked=len(ranking),
            )
        )
    overall = _recall(resolved, ranks)

    def grouped(label: str, values: Sequence[str]) -> dict[str, Recall]:
        return {
            value: _recall([a for a in resolved if getattr(a, label) == value], ranks)
            for value in values
        }

    thresholds = answer_set.thresholds
    reasons: list[str] = []
    if errors:
        reasons.append(f"{len(errors)} answers did not resolve (an error, not a miss)")
    if any(r.failed_recalls for r in recalls):
        reasons.append("recalls failed")
    if (overall.at_10 or 0) < thresholds.recall_at_10:
        reasons.append(f"recall at 10 {overall.at_10} is below {thresholds.recall_at_10}")
    if (overall.at_50 or 0) < thresholds.recall_at_50:
        reasons.append(f"recall at 50 {overall.at_50} is below {thresholds.recall_at_50}")
    by_id = {a.id: a for a in answer_set.answers}
    return KnownAnswersReport(
        max_tokens=max_tokens,
        verdict="failed" if reasons else "passed",
        reason="; ".join(reasons) or None,
        thresholds=thresholds,
        answers=len(answer_set.answers),
        errors=errors,
        overall=overall,
        by_question=grouped("question", sorted(asked)),
        by_hop=grouped("hop", HOPS),
        by_test_part=grouped("test", TEST_PARTS),
        outcomes=[AnswerOutcome(answer=a, rank=ranks.get(a.id)) for a in resolved],
        recalls=recalls,
        anchors_found={a.id: a.section for a in resolved if by_id[a.id].section is None},
    )
