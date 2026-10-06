"""The memory probe set (memory-quality ticket 02): fixed recalls whose answers measure the
reading index before and after a change to Memory.

- **The probe file** (`configs/memory/probes.yaml`): each probe is one pilot question
  (`.scratch/pilot/pilot-plan.md`, verbatim) with its Scout-style queries and its scope (theme
  slugs). It is validated at load: a probe without a scope, or with a theme the universe
  doesn't have, is refused (`ProbeConfigError`).
- **The report** of one recall answer (`POST /api/v1/memory/recall`'s `RecallResponse`, as
  JSON): memories returned, citations resolved, distinct sections and companies the resolved
  ones lead to, the share of observations, the **repeats** (memories whose text, case and
  whitespace folded, an earlier memory of the same answer already has: an observation beside
  the fact under it, or one sentence in two quarters' filings), the **superseded** (facts
  returned beside an observation of the same answer that was built from them: the places
  `prefer_observations` gives to other memories) and the companies ranked by
  **pointer weight** the way an investigation ranks them (`atlas.investigations.companies`:
  one pointer per resolved memory and distinct section, weighing 1 / its rank in the answer).

Pure: no I/O but reading the probe file. `scripts/memory_probe.py` runs the recalls.
"""

import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from atlas.companies import Universe
from atlas.investigations.companies import rank_companies
from atlas.research.service import RecallResponse

ProbeKind = Literal["question", "query"]
_SPACE = re.compile(r"\s+")


class ProbeConfigError(ValueError):
    """The probe file is invalid."""


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProbeScope(_Config):
    theme_ids: tuple[str, ...] = Field(min_length=1)


class Probe(_Config):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    question: str = Field(min_length=1)
    scope: ProbeScope
    queries: tuple[str, ...] = Field(min_length=1)


class ProbeSet(_Config):
    version: int = Field(ge=1)
    probes: tuple[Probe, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique(self) -> Self:
        ids = [probe.id for probe in self.probes]
        if len(set(ids)) != len(ids):
            raise ValueError("probe IDs must be unique")
        return self

    def recalls(self) -> list["ProbeRecall"]:
        """Every recall the set asks for: each probe's question, then its queries."""
        return [
            ProbeRecall(
                probe_id=probe.id,
                kind="question" if index == 0 else "query",
                index=index,
                text=text,
                theme_ids=list(probe.scope.theme_ids),
            )
            for probe in self.probes
            for index, text in enumerate((probe.question, *probe.queries))
        ]


class ProbeRecall(BaseModel):
    probe_id: str
    kind: ProbeKind
    index: int  # 0: the question; 1..: its queries
    text: str
    theme_ids: list[str]


def load_probes(path: Path, universe: Universe) -> ProbeSet:
    """The probe set, validated against the universe's themes; raises `ProbeConfigError`."""
    try:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
        probes = ProbeSet.model_validate(raw)
    except (OSError, yaml.YAMLError, ValidationError) as error:
        raise ProbeConfigError(f"{path}: {error}") from error
    for probe in probes.probes:
        unknown = [theme for theme in probe.scope.theme_ids if theme not in universe.themes]
        if unknown:
            raise ProbeConfigError(f"{path}: probe {probe.id}: unknown theme {', '.join(unknown)}")
    return probes


class RankedCompany(BaseModel):
    company_id: str
    name: str | None
    pointers: int
    score: float
    best_rank: int | None  # never None here: a probe ranks recall pointers only


class ProbeMeasure(BaseModel):
    memories: int
    resolved: int
    sections: int
    companies: int
    observations: int
    observation_share: float
    repeats: int
    superseded: int
    ranking: list[RankedCompany]


def _folded(text: str) -> str:
    return _SPACE.sub(" ", text).strip().casefold()


type Answer = RecallResponse | Mapping[str, Any]


def _parsed(answer: Answer) -> RecallResponse:
    return answer if isinstance(answer, RecallResponse) else RecallResponse.model_validate(answer)


def _pointers(answer: RecallResponse) -> list[tuple[int, str | None, tuple[str, str]]]:
    """(rank, company ID, section) per resolved memory and distinct section."""
    pointers: list[tuple[int, str | None, tuple[str, str]]] = []
    for rank, memory in enumerate(answer.memories, start=1):
        if memory.provenance.state != "resolved":
            continue
        seen: set[tuple[str, str]] = set()
        for source in memory.provenance.sources:
            section = (str(source.source_version_id), source.section_anchor)
            if section in seen:
                continue
            seen.add(section)
            company = None if source.company_id is None else str(source.company_id)
            pointers.append((rank, company, section))
    return pointers


def measure(answers: Sequence[Answer], names: Mapping[str, str] | None = None) -> ProbeMeasure:
    """The measures over one or more recall answers (several: the probe set's total, where
    sections and companies are counted once and each company's pointers add up)."""
    parsed = [_parsed(answer) for answer in answers]
    memories = [memory for answer in parsed for memory in answer.memories]
    resolved = sum(1 for memory in memories if memory.provenance.state == "resolved")
    observations = sum(1 for memory in memories if memory.type == "observation")
    repeats = 0
    for answer in parsed:
        seen: set[str] = set()
        for memory in answer.memories:
            folded = _folded(memory.text)
            if folded in seen:
                repeats += 1
            seen.add(folded)
    # A fact returned beside an observation of the same answer that was built from it: the
    # place `prefer_observations` would give to another memory.
    superseded = 0
    for answer in parsed:
        sources = {
            source.memory_id
            for memory in answer.memories
            if memory.type == "observation"
            for source in memory.provenance.sources
        }
        superseded += sum(
            1
            for memory in answer.memories
            if memory.type != "observation" and memory.memory_id in sources
        )
    pointers = [pointer for answer in parsed for pointer in _pointers(answer)]
    ranks: dict[str, list[int]] = {}
    for rank, company, _ in pointers:
        if company is not None:
            ranks.setdefault(company, []).append(rank)
    ranking = [
        RankedCompany(
            company_id=company,
            name=(names or {}).get(company),
            pointers=weight.pointers,
            score=weight.score,
            best_rank=weight.best_rank,
        )
        for company, weight in rank_companies(ranks)
    ]
    return ProbeMeasure(
        memories=len(memories),
        resolved=resolved,
        sections=len({section for _, _, section in pointers}),
        companies=len({company for _, company, _ in pointers if company is not None}),
        observations=observations,
        observation_share=round(observations / len(memories), 4) if memories else 0.0,
        repeats=repeats,
        superseded=superseded,
        ranking=ranking,
    )


class ProbeResult(BaseModel):
    recall: ProbeRecall
    measure: ProbeMeasure | None
    error: str | None = None


class ProbeReport(BaseModel):
    results: list[ProbeResult]
    by_probe: dict[str, ProbeMeasure]
    total: ProbeMeasure


def report(
    results: Iterable[tuple[ProbeRecall, Answer | str]],
    names: Mapping[str, str] | None = None,
) -> ProbeReport:
    """The report over each recall's answer (or its error text)."""
    rows: list[ProbeResult] = []
    answered: dict[str, list[Answer]] = {}
    for recall, answer in results:
        if isinstance(answer, str):
            rows.append(ProbeResult(recall=recall, measure=None, error=answer))
            continue
        rows.append(ProbeResult(recall=recall, measure=measure([answer], names)))
        answered.setdefault(recall.probe_id, []).append(answer)
    return ProbeReport(
        results=rows,
        by_probe={probe: measure(answers, names) for probe, answers in answered.items()},
        total=measure([a for answers in answered.values() for a in answers], names),
    )


def summary(probe_report: ProbeReport, *, top: int = 10) -> str:
    """The report as Markdown: a table per recall, the totals, and the ranking."""
    lines = [
        "| Probe | Recall | Memories | Resolved | Sections | Companies | Observations | Repeats"
        " | Superseded |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for row in probe_report.results:
        label = f"{row.recall.kind} {row.recall.index}"
        if row.measure is None:
            lines.append(f"| {row.recall.probe_id} | {label} | failed: {row.error} | | | | | | |")
            continue
        m = row.measure
        lines.append(
            f"| {row.recall.probe_id} | {label} | {m.memories} | {m.resolved} | {m.sections}"
            f" | {m.companies} | {m.observation_share:.0%} | {m.repeats} | {m.superseded} |"
        )
    lines += [
        "",
        "| Probe | Memories | Resolved | Sections | Companies | Observations | Repeats"
        " | Superseded |",
    ]
    lines.append("|---|---|---|---|---|---|---|---|")
    for probe, m in [*probe_report.by_probe.items(), ("total", probe_report.total)]:
        lines.append(
            f"| {probe} | {m.memories} | {m.resolved} | {m.sections} | {m.companies}"
            f" | {m.observation_share:.0%} | {m.repeats} | {m.superseded} |"
        )
    lines += ["", f"Companies by pointer weight (all probes, top {top}):", ""]
    for place, company in enumerate(probe_report.total.ranking[:top], start=1):
        lines.append(
            f"{place}. {company.name or company.company_id}: {company.score}"
            f" ({company.pointers} pointers, best rank {company.best_rank})"
        )
    return "\n".join(lines) + "\n"


# --- The bank's balance (pilot-review ticket 24) ---------------------------------------------

DEFAULT_WINDOW_DAYS = 730
PRE_WINDOW_ALERT = 0.25


class CompanyBalance(BaseModel):
    company_id: str
    name: str | None
    pointers: int
    score: float
    share: float  # of the total pointer weight
    dated: int  # pointers whose version's `available_at` is known
    pre_window: int  # of those, before the intake window
    pre_window_share: float | None  # None: no dated pointer


class Balance(BaseModel):
    window_days: int
    window_start: str
    total_score: float
    pointers: int
    dated: int
    pre_window: int
    pre_window_share: float | None
    companies: list[CompanyBalance]  # every researched company, weight order, 0 ones last
    outside_universe_pointers: int
    outside_universe_score: float
    zero_weight: list[str]
    over_pre_window: list[str]


def _share(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def pointed_versions(answers: Sequence[Answer]) -> list[str]:
    """The distinct Source Versions the answers' resolved memories lead to, sorted."""
    return sorted(
        {section[0] for answer in answers for _, _, section in _pointers(_parsed(answer))}
    )


def balance(
    answers: Sequence[Answer],
    researched: Mapping[str, str],
    available_at: Mapping[str, datetime],
    *,
    now: datetime,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> Balance:
    """How the probe's pointers spread over the researched companies (ID to name, each listed
    even with none) and over time: per company its pointers, pointer weight and share of the
    total weight, and the share of its pointers whose Source Version (ID to `available_at`; a
    version missing from it is undated and left out of the shares) was available before
    `now` minus `window_days`. Weight is the probe's own (one pointer per resolved memory and
    section, 1 / rank in its answer)."""
    start = now - timedelta(days=window_days)
    ranks: dict[str, list[int]] = {}
    dated: dict[str, int] = {}
    old: dict[str, int] = {}
    for answer in answers:
        for rank, company, (version, _) in _pointers(_parsed(answer)):
            if company is None:
                continue
            ranks.setdefault(company, []).append(rank)
            when = available_at.get(version)
            if when is not None:
                dated[company] = dated.get(company, 0) + 1
                old[company] = old.get(company, 0) + (1 if when < start else 0)
    weights = dict(rank_companies(ranks))
    total = sum(weight.score for weight in weights.values())
    rows: list[CompanyBalance] = []
    for company, name in researched.items():
        weight = weights.get(company)
        rows.append(
            CompanyBalance(
                company_id=company,
                name=name,
                pointers=weight.pointers if weight else 0,
                score=weight.score if weight else 0.0,
                share=round(weight.score / total, 4) if weight and total else 0.0,
                dated=dated.get(company, 0),
                pre_window=old.get(company, 0),
                pre_window_share=_share(old.get(company, 0), dated.get(company, 0)),
            )
        )
    rows.sort(key=lambda row: (-row.score, row.name or row.company_id))
    outside = [w for company, w in weights.items() if company not in researched]
    all_dated, all_old = sum(dated.values()), sum(old.values())
    return Balance(
        window_days=window_days,
        window_start=start.isoformat(),
        total_score=round(total, 4),
        pointers=sum(w.pointers for w in weights.values()),
        dated=all_dated,
        pre_window=all_old,
        pre_window_share=_share(all_old, all_dated),
        companies=rows,
        outside_universe_pointers=sum(w.pointers for w in outside),
        outside_universe_score=round(sum(w.score for w in outside), 4),
        zero_weight=[row.name or row.company_id for row in rows if row.pointers == 0],
        over_pre_window=[
            row.name or row.company_id
            for row in rows
            if row.pre_window_share is not None and row.pre_window_share > PRE_WINDOW_ALERT
        ],
    )


def balance_summary(result: Balance) -> str:
    """The balance as Markdown: the top line, then one row per researched company."""
    zero = ", ".join(result.zero_weight) or "none"
    over = ", ".join(result.over_pre_window) or "none"
    lines = [
        f"**Balance:** companies at 0 weight: {zero}. Pre-window share above"
        f" {PRE_WINDOW_ALERT:.0%}: {over}.",
        "",
        f"Pointers by company (all probes; window {result.window_days} days, from"
        f" {result.window_start[:10]}):",
        "",
        "| Company | Pointers | Weight | Share | Pre-window | Pre-window share |",
        "|---|---|---|---|---|---|",
    ]
    for row in result.companies:
        old = "n/a" if row.pre_window_share is None else f"{row.pre_window_share:.0%}"
        lines.append(
            f"| {row.name or row.company_id} | {row.pointers} | {row.score} | {row.share:.0%}"
            f" | {row.pre_window}/{row.dated} | {old} |"
        )
    overall = "n/a" if result.pre_window_share is None else f"{result.pre_window_share:.0%}"
    lines.append(
        f"| all | {result.pointers} | {result.total_score} | | {result.pre_window}/{result.dated}"
        f" | {overall} |"
    )
    if result.outside_universe_pointers:
        lines += [
            "",
            f"Outside the researched companies: {result.outside_universe_pointers} pointers,"
            f" weight {result.outside_universe_score}.",
        ]
    return "\n".join(lines) + "\n"
