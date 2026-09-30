"""The triage audit (ticket 33): how often retention triage skips a section a full reading
would retain.

Triage reads a long section in a few windows (`atlas.retention.triage`), so its recall is
unmeasured where it reads least. An audit measures it:

1. **Sample** (`create_audit`, `atlas triage audit`): the sections whose effective triage
   decision is `skip` (any method: role, rule, inherited), optionally of one company, are
   stratified by form (the document type, else the form, else the source type) and length
   band (`LENGTH_BANDS`, by the section's characters). Each stratum is shuffled with a
   generator seeded by `seed` and the stratum, and the sample is drawn round-robin across the
   strata (equal allocation, so the long sections triage reads least are represented). The
   same seed over the same decisions draws the same sample. The drawn sample (`plan`) and
   each stratum's population are stored with the audit, and a `triage_audit` job (payload
   `{"triage_audit_id"}`, `minimax`-budgeted, pausable) is enqueued in the same transaction.
2. **Judge** (the job): each sample's text is read from the archived parse at the decision's
   offsets (never refetched; a text whose hash no longer matches the decision is recorded as
   an error, not judged) and given whole to the full-section judge (`atlas.roles.
   triage_judge`), one call per section, or per overlapping chunk of `judge_max_chars` when
   longer; the section is `retain` when any chunk is (reading stops there). One row per sample
   goes into the insert-only `triage_audit` table: the section, the triage decision audited
   and how many of its windows triage read (`_windows_read`: none for a rule), the judge's
   decision, category and reason, and agreement. A judge that gives no usable answer
   (quarantined, or refused) leaves the row's decision empty, with its error.
   One attempt judges at most `triage_audit_samples_per_attempt` samples and is then
   requeued (`Requeue`: no attempt used), so it stays inside a job lease and the `minimax`
   budget paces it between attempts; a run's token budget spent requeues it the same way.
3. **Summary** (`summarize`, stored when the audit completes and computed from the rows on
   every read): the **miss rate** (skipped sections the judge would retain, of those judged)
   with its Wilson 95% interval, the same by length band, triage category, triage method and
   form, a population-weighted miss rate (each stratum's rate weighted by its share of the
   skipped sections), the misses by the judge's category, and example misses with the
   section anchor and the judge's reason.
"""

import json
import math
import random
import re
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Connection, Engine, RowMapping, text

from atlas.archive import Archive
from atlas.audit import Actor, content_hash, record
from atlas.companies import Universe
from atlas.jobs.pacing import JobClass, Requeue
from atlas.jobs.queue import Artifacts, JobQueue
from atlas.retention.decisions import section_sha256
from atlas.retention.service import SourceVersionInfo, load_version
from atlas.retention.triage import triage_document, triage_themes, window_spans
from atlas.roles import QuotedText, RoleCaller, RoleCallFailed, TokenBudgetExhausted
from atlas.roles.caller import RoleOutputQuarantined
from atlas.roles.records import run_usage
from atlas.roles.triage import TRIAGE_RUBRIC_VERSION
from atlas.roles.triage_judge import (
    TRIAGE_JUDGE,
    TRIAGE_JUDGE_RUBRIC_VERSION,
    TriageJudgement,
    TriageJudgeRequest,
    TriageJudgeSection,
)
from atlas.runs import RunNotFound, RunRecorder

AUDIT_KIND = "triage_audit"
RUN_KIND = "triage_audit"
# Upper bounds (exclusive) of the length bands, in characters; the last band is open.
LENGTH_BANDS: tuple[tuple[str, int | None], ...] = (
    ("under-2k", 2_000),
    ("2k-10k", 10_000),
    ("10k-50k", 50_000),
    ("50k-plus", None),
)
BAND_NAMES: tuple[str, ...] = tuple(name for name, _ in LENGTH_BANDS)
WILSON_Z = 1.959963984540054  # the standard normal's 97.5th percentile: a 95% interval
MAX_EXAMPLES = 10

AuditStatus = Literal["running", "completed"]


def length_band(length: int) -> str:
    """The band of a section of `length` characters."""
    for name, below in LENGTH_BANDS:
        if below is None or length < below:
            return name
    raise AssertionError("the last band is open")  # pragma: no cover


def wilson_interval(successes: int, trials: int, z: float = WILSON_Z) -> tuple[float, float]:
    """The Wilson score interval of a binomial proportion (95% by default); (0, 1) for no
    trials. Unlike the normal approximation it stays inside [0, 1] and is informative at 0 of n.
    """
    if trials == 0:
        return (0.0, 1.0)
    if not 0 <= successes <= trials:
        raise ValueError("successes must be between 0 and trials")
    p = successes / trials
    z2 = z * z
    denominator = 1 + z2 / trials
    centre = (p + z2 / (2 * trials)) / denominator
    half = z * math.sqrt(p * (1 - p) / trials + z2 / (4 * trials * trials)) / denominator
    low = 0.0 if successes == 0 else max(0.0, centre - half)
    high = 1.0 if successes == trials else min(1.0, centre + half)
    return (low, high)


# --- read models --------------------------------------------------------------------------------


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True)


class AuditStratum(_Model):
    form: str
    length_band: str
    population: int  # skipped sections in the stratum when the audit was created
    sampled: int


class MissRate(_Model):
    key: str
    judged: int
    misses: int
    miss_rate: float | None
    wilson_low: float | None
    wilson_high: float | None


class MissExample(_Model):
    sample_id: uuid.UUID
    source_version_id: uuid.UUID
    section_anchor: str
    section_heading: str | None
    form: str
    length_band: str
    length: int
    triage_method: str
    triage_category: str
    triage_reason: str
    windows_read: int
    windows_total: int
    judge_category: str
    judge_reason: str


class AuditSummary(_Model):
    sampled: int  # the drawn sample's size
    judged: int  # samples the judge decided
    unjudged: int  # samples judged with no usable answer (their error recorded)
    pending: int  # samples not judged yet
    misses: int
    miss_rate: float | None
    wilson_low: float | None
    wilson_high: float | None
    weighted_miss_rate: float | None  # strata weighted by their share of skipped sections
    by_length_band: list[MissRate]
    by_category: list[MissRate]  # by triage's category
    by_method: list[MissRate]  # by how triage decided (role, rule, inherited, ...)
    by_form: list[MissRate]
    misses_by_judge_category: dict[str, int]
    examples: list[MissExample]


class TriageAuditSample(_Model):
    id: uuid.UUID
    triage_decision_id: uuid.UUID
    source_version_id: uuid.UUID
    section_anchor: str
    section_heading: str | None
    char_start: int
    char_end: int
    form: str
    length_band: str
    triage_decision: Literal["retain", "skip"]
    triage_method: str
    triage_category: str
    triage_reason: str
    windows_read: int
    windows_total: int
    judge_decision: Literal["retain", "skip"] | None
    judge_category: str | None
    judge_reason: str | None
    judge_chunks: int
    role_call_ids: list[uuid.UUID]
    agreement: bool | None  # False: a miss (triage skipped what the judge would retain)
    error: str | None
    judged_at: datetime


class TriageAuditRun(_Model):
    id: uuid.UUID
    status: AuditStatus
    job_id: uuid.UUID
    job_status: str | None
    sample_requested: int
    sample_size: int
    company_slug: str | None
    seed: int
    population: int
    judge_rubric_version: str
    triage_rubric_version: str
    excerpt_chars: int
    windows_per_section: int
    window_overlap_chars: int
    judge_max_chars: int
    actor: str
    samples_judged: int
    created_at: datetime
    finished_at: datetime | None


class TriageAudit(TriageAuditRun):
    plan: list[uuid.UUID]  # the drawn sample's triage decisions, in judging order
    strata: list[AuditStratum]
    summary: AuditSummary
    samples: list[TriageAuditSample]


# --- creating an audit --------------------------------------------------------------------------


class AuditRefused(Exception):
    pass


@dataclass(frozen=True)
class ReaderSettings:
    """The triage reader the audit describes (windows) and the judge's chunk size."""

    excerpt_chars: int
    windows_per_section: int
    window_overlap_chars: int
    judge_max_chars: int


@dataclass(frozen=True)
class _Skipped:
    decision_id: uuid.UUID
    form: str
    band: str


_EFFECTIVE_SKIPS = (
    "SELECT t.id, t.char_end - t.char_start AS length,"
    " coalesce(d.document_type, d.form_type, d.source_type) AS form"
    " FROM (SELECT DISTINCT ON (source_version_id, section_anchor) * FROM triage_decision"
    "   ORDER BY source_version_id, section_anchor, seq DESC) AS t"
    " JOIN source_version v ON v.id = t.source_version_id"
    " JOIN source_document d ON d.id = v.source_document_id"
    " LEFT JOIN company c ON c.id = d.company_id"
    " WHERE t.decision = 'skip' AND (CAST(:company AS text) IS NULL OR c.slug = :company)"
    " ORDER BY t.source_version_id, t.section_anchor"
)


def draw_sample(
    connection: Connection, *, sample: int, company_slug: str | None, seed: int
) -> tuple[int, list[AuditStratum], list[uuid.UUID]]:
    """The skipped sections' population, its strata and the drawn sample (see the module)."""
    rows = connection.execute(text(_EFFECTIVE_SKIPS), {"company": company_slug}).all()
    strata: dict[tuple[str, str], list[_Skipped]] = {}
    for decision_id, length, form in rows:
        band = length_band(length)
        strata.setdefault((form, band), []).append(_Skipped(decision_id, form, band))
    order = sorted(strata, key=lambda key: (key[0], BAND_NAMES.index(key[1])))
    shuffled: dict[tuple[str, str], list[_Skipped]] = {}
    for key in order:
        members = sorted(strata[key], key=lambda each: str(each.decision_id))
        # Reproducibility, not secrecy: a seeded generator is the point.
        random.Random(f"triage-audit:{seed}:{key[0]}:{key[1]}").shuffle(members)  # noqa: S311
        shuffled[key] = members
    plan: list[uuid.UUID] = []
    taken = dict.fromkeys(order, 0)
    depth = 0
    while len(plan) < sample and any(depth < len(shuffled[key]) for key in order):
        for key in order:
            if len(plan) == sample:
                break
            if depth < len(shuffled[key]):
                plan.append(shuffled[key][depth].decision_id)
                taken[key] += 1
        depth += 1
    described = [
        AuditStratum(form=form, length_band=band, population=len(strata[(form, band)]), sampled=n)
        for (form, band), n in taken.items()
    ]
    return len(rows), described, plan


def create_audit(
    engine: Engine,
    actor: Actor,
    *,
    sample: int,
    company_slug: str | None,
    seed: int,
    reader: ReaderSettings,
    job_class: JobClass = "interactive",
) -> TriageAuditRun:
    """Draw the sample, record the audit and enqueue its `triage_audit` job (one transaction).

    Refused (`AuditRefused`) for a sample below 1, an unknown company, or no skipped section
    to audit.
    """
    if sample < 1:
        raise AuditRefused("the sample size must be at least 1")
    audit_id = uuid.uuid4()
    queue = JobQueue(engine, actor=actor)
    with engine.begin() as connection:
        if company_slug is not None:
            known = connection.execute(
                text("SELECT 1 FROM company WHERE slug = :slug"), {"slug": company_slug}
            ).one_or_none()
            if known is None:
                raise AuditRefused(f"unknown company {company_slug!r}")
        population, strata, plan = draw_sample(
            connection, sample=sample, company_slug=company_slug, seed=seed
        )
        if not plan:
            scope = f" of {company_slug}" if company_slug else ""
            raise AuditRefused(f"no section{scope} has an effective triage decision of skip")
        job = queue.enqueue_within(
            connection,
            AUDIT_KIND,
            f"triage_audit:{audit_id}",
            {"triage_audit_id": str(audit_id)},
            job_class=job_class,
        ).job
        fields = {
            "id": audit_id,
            "sample_requested": sample,
            "company_slug": company_slug,
            "seed": seed,
            "population": population,
            "strata": [each.model_dump(mode="json") for each in strata],
            "plan": plan,
            "judge_rubric_version": TRIAGE_JUDGE_RUBRIC_VERSION,
            "triage_rubric_version": TRIAGE_RUBRIC_VERSION,
            "excerpt_chars": reader.excerpt_chars,
            "windows_per_section": reader.windows_per_section,
            "window_overlap_chars": reader.window_overlap_chars,
            "judge_max_chars": reader.judge_max_chars,
            "job_id": job.id,
            "actor": actor.name,
        }
        connection.execute(
            text(
                "INSERT INTO triage_audit_run (id, sample_requested, company_slug, seed,"
                " population, strata, plan, judge_rubric_version, triage_rubric_version,"
                " excerpt_chars, windows_per_section, window_overlap_chars, judge_max_chars,"
                " job_id, actor) VALUES (:id, :sample_requested, :company_slug, :seed,"
                " :population, CAST(:strata AS jsonb), CAST(:plan AS uuid[]),"
                " :judge_rubric_version, :triage_rubric_version, :excerpt_chars,"
                " :windows_per_section, :window_overlap_chars, :judge_max_chars, :job_id, :actor)"
            ),
            fields | {"strata": _json(fields["strata"])},
        )
        record(
            connection,
            actor,
            "triage_audit.created",
            entity_type="triage_audit_run",
            entity_id=str(audit_id),
            new_hash=content_hash(fields),
        )
        created = _get_run(connection, audit_id)
    assert created is not None
    return created


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True)


# --- the job ------------------------------------------------------------------------------------


class TriageAuditor:
    """Runs one attempt of a `triage_audit` job (see the module)."""

    def __init__(
        self,
        engine: Engine,
        archive: Archive,
        actor: Actor,
        universe: Universe,
        caller: RoleCaller | None,
        runs: RunRecorder | None,
        *,
        samples_per_attempt: int,
    ) -> None:
        self._engine = engine
        self._archive = archive
        self._actor = actor
        self._universe = universe
        self._caller = caller
        self._runs = runs
        self._per_attempt = samples_per_attempt
        self._versions: dict[uuid.UUID, tuple[SourceVersionInfo, str]] = {}

    def run(self, audit_id: uuid.UUID) -> Artifacts:
        with self._engine.connect() as connection:
            audit = (
                connection.execute(
                    text("SELECT * FROM triage_audit_run WHERE id = :id"), {"id": audit_id}
                )
                .mappings()
                .one_or_none()
            )
            if audit is None:
                raise LookupError(f"triage audit {audit_id} does not exist")
            judged = set(
                connection.execute(
                    text(
                        "SELECT triage_decision_id FROM triage_audit"
                        " WHERE triage_audit_run_id = :id"
                    ),
                    {"id": audit_id},
                ).scalars()
            )
        base: Artifacts = {"triage_audit_id": str(audit_id)}
        if audit["status"] == "completed":
            return base | {"outcome": "already_completed"}
        todo = [each for each in audit["plan"] if each not in judged]
        batch = todo[: self._per_attempt]
        done = 0
        if batch:
            done = self._judge_batch(audit, batch)
        if len(todo) > done:
            raise Requeue(
                f"triage audit {audit_id} continues in its next attempt:"
                f" {len(todo) - done} of {len(audit['plan'])} samples left"
            )
        summary = self._complete(audit_id)
        return base | {
            "outcome": "completed",
            "judged": summary.judged,
            "misses": summary.misses,
            "miss_rate": summary.miss_rate,
        }

    def _judge_batch(self, audit: RowMapping, batch: Sequence[uuid.UUID]) -> int:
        if self._caller is None or self._runs is None:
            raise RoleCallFailed(
                "the triage audit needs LiteLLM and Hindsight configured"
                " (ATLAS_LITELLM_URL, ATLAS_LITELLM_API_KEY, ATLAS_HINDSIGHT_URL)"
            )
        run_id = self._runs.start(RUN_KIND).id
        done = 0
        try:
            for decision_id in batch:
                self._judge(audit, decision_id, run_id)
                done += 1
        except TokenBudgetExhausted as error:
            raise Requeue(
                f"triage audit {audit['id']} continues in a fresh run: the run's token budget"
                f" is spent ({error})"
            ) from error
        finally:
            self._finish(run_id)
        return done

    def _judge(self, audit: RowMapping, decision_id: uuid.UUID, run_id: uuid.UUID) -> None:
        assert self._caller is not None
        with self._engine.connect() as connection:
            decision = (
                connection.execute(
                    text(
                        "SELECT t.*, coalesce(d.document_type, d.form_type, d.source_type)"
                        " AS form FROM triage_decision t"
                        " JOIN source_version v ON v.id = t.source_version_id"
                        " JOIN source_document d ON d.id = v.source_document_id"
                        " WHERE t.id = :id"
                    ),
                    {"id": decision_id},
                )
                .mappings()
                .one()
            )
        version, parsed = self._version(decision["source_version_id"])
        section = parsed[decision["char_start"] : decision["char_end"]]
        length = decision["char_end"] - decision["char_start"]
        windows_read, windows_total = _windows_read(decision, audit)
        row: dict[str, object] = {
            "windows_read": windows_read,
            "windows_total": windows_total,
            "judge_decision": None,
            "judge_category": None,
            "judge_reason": None,
            "judge_chunks": 0,
            "role_call_ids": [],
            "agreement": None,
            "error": None,
        }
        if section_sha256(section) != decision["content_sha256"]:
            row["error"] = (
                "the archived parse no longer matches the decision's content hash; not judged"
            )
            self._insert(audit, decision, row)
            return
        chunks = window_spans(length, audit["judge_max_chars"], audit["window_overlap_chars"])
        role_calls: list[uuid.UUID] = []
        answers: list[TriageJudgement] = []
        try:
            for chunk in chunks:
                request = TriageJudgeRequest(
                    document=triage_document(version, self._universe),
                    themes=triage_themes(version, self._universe),
                    section=TriageJudgeSection(
                        anchor=decision["section_anchor"],
                        heading=decision["section_heading"],
                        length=length,
                        chunk=chunk.part,
                        chunks=chunk.parts,
                    ),
                )
                retrieved = [
                    QuotedText(
                        id=decision["section_anchor"],
                        source=f"{version.id}#{decision['section_anchor']}",
                        text=section[chunk.start : chunk.end],
                    )
                ]
                answer, role_call_id = self._caller.call_recorded(
                    TRIAGE_JUDGE, request, run_id=run_id, retrieved=retrieved
                )
                role_calls.append(role_call_id)
                answers.append(answer)
                if answer.decision == "retain":
                    break
        except RoleOutputQuarantined as quarantined:
            role_calls.append(quarantined.role_call_id)
            row |= {"role_call_ids": role_calls, "judge_chunks": len(answers)}
            row["error"] = str(quarantined)
            self._insert(audit, decision, row)
            return
        except RoleCallFailed as failed:
            row |= {"role_call_ids": role_calls, "judge_chunks": len(answers)}
            row["error"] = f"{type(failed).__name__}: {failed}"
            self._insert(audit, decision, row)
            return
        final = answers[-1]  # the retaining chunk (reading stops there), else the last
        if final.decision == "skip":
            final = answers[0]
        reason = final.reason.strip() or "no reason given"
        if len(chunks) > 1 and final.decision == "retain":
            reason = f"chunk {len(answers)}/{len(chunks)}: {reason}"
        elif len(chunks) > 1:
            reason = f"none of {len(chunks)} chunks retained: {reason}"
        row |= {
            "judge_decision": final.decision,
            "judge_category": final.category,
            "judge_reason": reason,
            "judge_chunks": len(answers),
            "role_call_ids": role_calls,
            "agreement": final.decision == decision["decision"],
        }
        self._insert(audit, decision, row)

    def _version(self, version_id: uuid.UUID) -> tuple[SourceVersionInfo, str]:
        """The version and its archived parse (read once per attempt; never refetched)."""
        if version_id not in self._versions:
            version = load_version(self._engine, version_id)
            if version.parsed_object_uri is None:
                raise RoleCallFailed(f"Source Version {version_id} has no archived parse")
            parsed = self._archive.get(version.parsed_object_uri).decode("utf-8")
            self._versions[version_id] = (version, parsed)
        return self._versions[version_id]

    def _insert(self, audit: RowMapping, decision: RowMapping, row: dict[str, object]) -> None:
        length = decision["char_end"] - decision["char_start"]
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO triage_audit (id, triage_audit_run_id, triage_decision_id,"
                    " source_version_id, section_anchor, section_heading, char_start, char_end,"
                    " form, length_band, triage_decision, triage_method, triage_category,"
                    " triage_reason, windows_read, windows_total, judge_decision,"
                    " judge_category, judge_reason, judge_chunks, role_call_ids, agreement,"
                    " error) VALUES (:id, :audit, :decision_id, :version, :anchor, :heading,"
                    " :char_start, :char_end, :form, :band, :triage_decision, :method,"
                    " :category, :reason, :windows_read, :windows_total, :judge_decision,"
                    " :judge_category, :judge_reason, :judge_chunks,"
                    " CAST(:role_call_ids AS uuid[]), :agreement, :error)"
                    " ON CONFLICT (triage_audit_run_id, triage_decision_id) DO NOTHING"
                ),
                {
                    "id": uuid.uuid4(),
                    "audit": audit["id"],
                    "decision_id": decision["id"],
                    "version": decision["source_version_id"],
                    "anchor": decision["section_anchor"],
                    "heading": decision["section_heading"],
                    "char_start": decision["char_start"],
                    "char_end": decision["char_end"],
                    "form": decision["form"],
                    "band": length_band(length),
                    "triage_decision": decision["decision"],
                    "method": decision["method"],
                    "category": decision["category"],
                    "reason": decision["reason"],
                }
                | row,
            )

    def _complete(self, audit_id: uuid.UUID) -> AuditSummary:
        with self._engine.begin() as connection:
            connection.execute(
                text("SELECT 1 FROM triage_audit_run WHERE id = :id FOR UPDATE"), {"id": audit_id}
            )
            audit = get_audit(connection, audit_id)
            assert audit is not None
            if audit.status == "completed":
                return audit.summary
            summary = audit.summary.model_dump(mode="json")
            connection.execute(
                text(
                    "UPDATE triage_audit_run SET status = 'completed', finished_at = now(),"
                    " summary = CAST(:summary AS jsonb) WHERE id = :id"
                ),
                {"id": audit_id, "summary": _json(summary)},
            )
            record(
                connection,
                self._actor,
                "triage_audit.completed",
                entity_type="triage_audit_run",
                entity_id=str(audit_id),
                new_hash=content_hash(summary),
            )
        return audit.summary

    def _finish(self, run_id: uuid.UUID) -> None:
        assert self._runs is not None
        with self._engine.connect() as connection:
            usage = run_usage(connection, run_id)
        try:
            self._runs.finish(run_id, tokens_in=usage.tokens_in, tokens_out=usage.tokens_out)
        except RunNotFound:
            pass


_READ = re.compile(r"^none of (\d+) windows read \(of (\d+)\)")


def _windows_read(decision: RowMapping, audit: RowMapping) -> tuple[int, int]:
    """How many windows of the section triage read, of how many: as its reason records it
    when it read several ("none of N windows read (of M)"); none for a rule; else one (a
    section that fits one window, a one-window reader, or the opening-only reader before
    windows), of as many as the audit's window size and overlap make."""
    total = window_spans(
        decision["char_end"] - decision["char_start"],
        audit["excerpt_chars"],
        audit["window_overlap_chars"],
    )[0].parts
    if decision["method"] == "rule":
        return 0, total
    if (match := _READ.match(decision["reason"])) is not None:
        return int(match[1]), int(match[2])
    return 1, total


# --- the summary --------------------------------------------------------------------------------


def _rate(key: str, samples: Sequence[TriageAuditSample]) -> MissRate:
    judged = [each for each in samples if each.agreement is not None]
    misses = sum(1 for each in judged if _is_miss(each))
    if not judged:
        return MissRate(
            key=key, judged=0, misses=0, miss_rate=None, wilson_low=None, wilson_high=None
        )
    low, high = wilson_interval(misses, len(judged))
    return MissRate(
        key=key,
        judged=len(judged),
        misses=misses,
        miss_rate=misses / len(judged),
        wilson_low=low,
        wilson_high=high,
    )


def _is_miss(sample: TriageAuditSample) -> bool:
    return sample.triage_decision == "skip" and sample.judge_decision == "retain"


def _grouped(
    samples: Sequence[TriageAuditSample], key: str, order: Iterable[str] | None = None
) -> list[MissRate]:
    groups: dict[str, list[TriageAuditSample]] = {}
    for sample in samples:
        groups.setdefault(str(getattr(sample, key)), []).append(sample)
    keys = [k for k in order if k in groups] if order is not None else sorted(groups)
    return [_rate(k, groups[k]) for k in keys]


def summarize(
    samples: Sequence[TriageAuditSample], strata: Sequence[AuditStratum], sampled: int
) -> AuditSummary:
    """The audit's summary from its rows (see the module)."""
    overall = _rate("all", samples)
    by_stratum = {(s.form, s.length_band): s for s in strata}
    weighted: float | None = None
    rates: list[tuple[int, float]] = []
    for (form, band), stratum in by_stratum.items():
        rate = _rate(
            f"{form}/{band}",
            [each for each in samples if (each.form, each.length_band) == (form, band)],
        )
        if rate.miss_rate is not None:
            rates.append((stratum.population, rate.miss_rate))
    covered = sum(population for population, _ in rates)
    if covered:
        weighted = sum(population * rate for population, rate in rates) / covered
    misses = [each for each in samples if _is_miss(each)]
    by_judge: dict[str, int] = {}
    for each in misses:
        assert each.judge_category is not None
        by_judge[each.judge_category] = by_judge.get(each.judge_category, 0) + 1
    return AuditSummary(
        sampled=sampled,
        judged=overall.judged,
        unjudged=sum(1 for each in samples if each.agreement is None),
        pending=sampled - len(samples),
        misses=overall.misses,
        miss_rate=overall.miss_rate,
        wilson_low=overall.wilson_low,
        wilson_high=overall.wilson_high,
        weighted_miss_rate=weighted,
        by_length_band=_grouped(samples, "length_band", BAND_NAMES),
        by_category=_grouped(samples, "triage_category"),
        by_method=_grouped(samples, "triage_method"),
        by_form=_grouped(samples, "form"),
        misses_by_judge_category=dict(sorted(by_judge.items())),
        examples=[
            MissExample(
                sample_id=each.id,
                source_version_id=each.source_version_id,
                section_anchor=each.section_anchor,
                section_heading=each.section_heading,
                form=each.form,
                length_band=each.length_band,
                length=each.char_end - each.char_start,
                triage_method=each.triage_method,
                triage_category=each.triage_category,
                triage_reason=each.triage_reason,
                windows_read=each.windows_read,
                windows_total=each.windows_total,
                judge_category=each.judge_category or "",
                judge_reason=each.judge_reason or "",
            )
            for each in misses[:MAX_EXAMPLES]
        ],
    )


# --- reads --------------------------------------------------------------------------------------

_RUN = (
    "SELECT r.id, r.status, r.job_id, j.status AS job_status, r.sample_requested,"
    " cardinality(r.plan) AS sample_size, r.company_slug, r.seed, r.population,"
    " r.judge_rubric_version, r.triage_rubric_version, r.excerpt_chars,"
    " r.windows_per_section, r.window_overlap_chars, r.judge_max_chars, r.actor,"
    " (SELECT count(*) FROM triage_audit a WHERE a.triage_audit_run_id = r.id)"
    " AS samples_judged, r.created_at, r.finished_at, r.strata, r.plan"
    " FROM triage_audit_run r LEFT JOIN job j ON j.id = r.job_id"
)


def _get_run(connection: Connection, audit_id: uuid.UUID) -> TriageAuditRun | None:
    row = (
        connection.execute(text(f"{_RUN} WHERE r.id = :id"), {"id": audit_id})
        .mappings()
        .one_or_none()
    )
    return TriageAuditRun.model_validate(dict(row)) if row is not None else None


def list_audits(
    connection: Connection, *, limit: int, offset: int
) -> tuple[list[TriageAuditRun], int]:
    """Audits, newest first, and how many there are."""
    rows = (
        connection.execute(
            text(f"{_RUN} ORDER BY r.created_at DESC, r.id LIMIT :limit OFFSET :offset"),
            {"limit": limit, "offset": offset},
        )
        .mappings()
        .all()
    )
    total = connection.execute(text("SELECT count(*) FROM triage_audit_run")).scalar_one()
    return [TriageAuditRun.model_validate(dict(row)) for row in rows], total


def get_audit(connection: Connection, audit_id: uuid.UUID) -> TriageAudit | None:
    """One audit with its strata, its samples (in judging order) and its summary."""
    row = (
        connection.execute(text(f"{_RUN} WHERE r.id = :id"), {"id": audit_id})
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    samples = [
        TriageAuditSample.model_validate(dict(each))
        for each in connection.execute(
            text(
                "SELECT id, triage_decision_id, source_version_id, section_anchor,"
                " section_heading, char_start, char_end, form, length_band, triage_decision,"
                " triage_method, triage_category, triage_reason, windows_read, windows_total,"
                " judge_decision, judge_category, judge_reason, judge_chunks, role_call_ids,"
                " agreement, error, judged_at FROM triage_audit"
                " WHERE triage_audit_run_id = :id ORDER BY seq"
            ),
            {"id": audit_id},
        ).mappings()
    ]
    strata = [AuditStratum.model_validate(each) for each in row["strata"]]
    return TriageAudit.model_validate(
        dict(row)
        | {
            "strata": strata,
            "samples": samples,
            "summary": summarize(samples, strata, row["sample_size"]),
        }
    )
