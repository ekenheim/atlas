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
    best_rank: int


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
