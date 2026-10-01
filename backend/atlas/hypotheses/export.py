"""The Hypothesis dossier export: one version with its citations and run metadata, as JSON
(`HypothesisExport`) or Markdown (`render_markdown`, the same content as text).

Every finding's citations are numbered in order of first use; a citation is the cited
Claim's exact quote and span, its Assertion (with its review state when the version was
written and now) and its Source Version and Document (title, publisher, URL, availability).
The run metadata is the investigation (question, as-of time, stop, budgets), each run behind
the version (code, Hindsight and template versions, routed models, tokens) and each Editor
call (prompt name, version and SHA-256, model, status).
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Connection, text

from atlas.hypotheses.model import Hypothesis, HypothesisVersion
from atlas.investigations.model import Budgets, SourceSpan
from atlas.roles import run_usage
from atlas.runs import Run

EXPORT_FORMAT = "atlas.hypothesis-dossier"
EXPORT_FORMAT_VERSION = 1


class Citation(BaseModel):
    model_config = ConfigDict(frozen=True)

    number: int
    claim_id: uuid.UUID
    assertion_id: uuid.UUID
    quote: str
    span_start: int
    span_end: int
    verification_status: str  # when the version was written
    verification_status_now: str
    source_version_id: uuid.UUID
    source_document_id: uuid.UUID
    title: str
    publisher: str
    url: str
    form_type: str | None
    accession: str | None
    source_tier: str
    available_at: datetime


class ExportFinding(BaseModel):
    model_config = ConfigDict(frozen=True)

    claim_text: str
    citations: list[int]
    independent_evidence_families: list[str]
    limitations: list[str]
    open_questions: list[str]
    needs_review: bool
    counterevidence_ids: list[uuid.UUID]
    evidence_available_at: datetime


class ExportCompany(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    slug: str
    name: str


class ExportInvestigation(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    theme: str
    question: str
    as_of: datetime
    stop_reason: str | None
    stop_detail: str | None
    budgets: Budgets
    run_id: uuid.UUID | None


class ExportRoleCall(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    run_id: uuid.UUID
    role: str
    prompt_name: str
    prompt_version: int
    prompt_sha256: str
    model: str
    status: str


class RunMetadata(BaseModel):
    model_config = ConfigDict(frozen=True)

    investigation: ExportInvestigation
    runs: list[Run]
    role_calls: list[ExportRoleCall]


class HypothesisExport(BaseModel):
    model_config = ConfigDict(frozen=True)

    format: Literal["atlas.hypothesis-dossier"]
    format_version: int
    exported_at: datetime
    hypothesis_id: uuid.UUID
    theme_id: str
    status: str
    author: str
    related_companies: list[ExportCompany]
    created_at: datetime
    first_published_at: datetime | None
    version: HypothesisVersion
    findings: list[ExportFinding]
    citations: list[Citation]
    run_metadata: RunMetadata


def build_export(
    connection: Connection,
    hypothesis: Hypothesis,
    version: HypothesisVersion,
    exported_at: datetime,
) -> HypothesisExport:
    citations: list[Citation] = []
    numbers: dict[tuple[uuid.UUID, uuid.UUID], int] = {}
    findings: list[ExportFinding] = []
    for finding in version.content.findings:
        cited: list[int] = []
        for span in finding.source_spans:
            key = (span.claim_id, span.assertion_id)
            if key not in numbers:
                numbers[key] = len(numbers) + 1
                citations.append(_citation(connection, numbers[key], span))
            cited.append(numbers[key])
        findings.append(
            ExportFinding(
                claim_text=finding.claim_text,
                citations=cited,
                independent_evidence_families=finding.independent_evidence_families,
                limitations=finding.limitations,
                open_questions=finding.open_questions,
                needs_review=finding.needs_review,
                counterevidence_ids=finding.counterevidence_ids,
                evidence_available_at=finding.validity_dates.evidence_available_at,
            )
        )
    companies = [
        ExportCompany(id=row.id, slug=row.slug, name=row.display_name)
        for row in connection.execute(
            text(
                "SELECT c.id, c.slug, c.display_name FROM unnest(CAST(:ids AS uuid[]))"
                " WITH ORDINALITY AS r(id, n) JOIN company c ON c.id = r.id ORDER BY r.n"
            ),
            {"ids": hypothesis.related_company_ids},
        ).all()
    ]
    return HypothesisExport(
        format=EXPORT_FORMAT,
        format_version=EXPORT_FORMAT_VERSION,
        exported_at=exported_at,
        hypothesis_id=hypothesis.id,
        theme_id=hypothesis.theme_id,
        status=hypothesis.status,
        author=hypothesis.author,
        related_companies=companies,
        created_at=hypothesis.created_at,
        first_published_at=hypothesis.first_published_at,
        version=version,
        findings=findings,
        citations=citations,
        run_metadata=_run_metadata(connection, version),
    )


def _citation(connection: Connection, number: int, span: SourceSpan) -> Citation:
    row = (
        connection.execute(
            text(
                "SELECT d.id AS document_id, d.title, d.publisher, d.canonical_url, d.form_type,"
                " d.accession, d.source_tier, v.available_at, a.verification_status"
                " FROM source_version v JOIN source_document d ON d.id = v.source_document_id"
                " JOIN assertion a ON a.id = :assertion WHERE v.id = :version"
            ),
            {"version": span.source_version_id, "assertion": span.assertion_id},
        )
        .mappings()
        .one()
    )
    return Citation(
        number=number,
        claim_id=span.claim_id,
        assertion_id=span.assertion_id,
        quote=span.quote,
        span_start=span.span_start,
        span_end=span.span_end,
        verification_status=span.verification_status,
        verification_status_now=row["verification_status"],
        source_version_id=span.source_version_id,
        source_document_id=row["document_id"],
        title=row["title"],
        publisher=row["publisher"],
        url=row["canonical_url"],
        form_type=row["form_type"],
        accession=row["accession"],
        source_tier=row["source_tier"],
        available_at=row["available_at"],
    )


def _run_metadata(connection: Connection, version: HypothesisVersion) -> RunMetadata:
    provenance = version.provenance
    row = (
        connection.execute(
            text("SELECT * FROM investigation WHERE id = :id"),
            {"id": provenance.investigation_id},
        )
        .mappings()
        .one()
    )
    investigation = ExportInvestigation(
        id=row["id"],
        theme=row["theme"],
        question=row["question"],
        as_of=row["as_of"],
        stop_reason=row["stop_reason"],
        stop_detail=row["stop_detail"],
        budgets=Budgets(
            max_rounds=row["max_rounds"],
            max_leads=row["max_leads"],
            max_documents=row["max_documents"],
            max_companies=row["max_companies"],
            token_budget=row["token_budget"],
        ),
        run_id=row["run_id"],
    )
    run_ids = [
        each
        for each in dict.fromkeys((provenance.investigation_run_id, provenance.draft_run_id))
        if each is not None
    ]
    runs: list[Run] = []
    for run_id in run_ids:
        run_row = (
            connection.execute(text("SELECT * FROM run WHERE id = :id"), {"id": run_id})
            .mappings()
            .one()
        )
        values = dict(run_row)
        if values["finished_at"] is None:  # still open: its tokens so far
            usage = run_usage(connection, run_id)
            values |= {"tokens_in": usage.tokens_in, "tokens_out": usage.tokens_out}
        runs.append(Run.model_validate(values))
    call_ids = [
        each
        for each in (provenance.research_card_role_call_id, provenance.editor_role_call_id)
        if each is not None
    ]
    role_calls = [
        ExportRoleCall.model_validate(dict(each))
        for each in connection.execute(
            text(
                "SELECT id, run_id, role, prompt_name, prompt_version, prompt_sha256, model,"
                " status FROM role_call WHERE id = ANY(:ids) ORDER BY started_at, id"
            ),
            {"ids": call_ids},
        ).mappings()
    ]
    return RunMetadata(investigation=investigation, runs=runs, role_calls=role_calls)


# --- Markdown ---------------------------------------------------------------------------------


def render_markdown(export: HypothesisExport) -> str:
    version = export.version
    content = version.content
    state = (
        f"published {_time(version.published_at)} by {version.published_by}"
        if version.published_at is not None
        else "not published (a draft)"
    )
    lines = [
        f"# Hypothesis: {_one_line(content.thesis_statement)}",
        "",
        f"- Hypothesis: `{export.hypothesis_id}`, version {version.version} ({state})",
        f"- Status: {export.status}",
        f"- Theme: {export.theme_id}",
        f"- Companies: {', '.join(c.name for c in export.related_companies) or 'none'}",
        f"- Author: {export.author}; version written by {version.created_by}"
        f" at {_time(version.created_at)}",
        f"- Content SHA-256: `{version.content_sha256}`",
    ]
    if version.note:
        lines.append(f"- Note: {_one_line(version.note)}")
    lines += ["", "## Thesis statement", "", _one_line(content.thesis_statement), ""]
    mechanism = content.mechanism
    lines += [
        "## Mechanism",
        "",
        f"- Demand driver: {_or_none(mechanism.demand_driver)}",
        f"- Possible constraint: {_or_none(mechanism.possible_constraint)}",
        f"- Economic capture question: {_or_none(mechanism.economic_capture_question)}",
        "",
    ]
    for title, items in (
        ("Measurable predictions", content.measurable_predictions),
        ("Catalysts", content.catalysts),
        ("Falsifiers", content.falsifiers),
        ("Required evidence", content.required_evidence),
        ("Alternative explanations", content.alternative_explanations),
        ("Unresolved questions", content.unresolved_questions),
    ):
        lines += [f"## {title}", ""]
        lines += [f"- {_one_line(item)}" for item in items] or ["- none"]
        lines.append("")
    lines += ["## Findings", ""]
    if not export.findings:
        lines += ["No finding cites accepted Evidence.", ""]
    for n, finding in enumerate(export.findings, start=1):
        refs = "".join(f"[{c}]" for c in finding.citations)
        lines.append(f"{n}. {_one_line(finding.claim_text)} {refs}")
        if finding.limitations:
            lines.append(f"   - Limitations: {'; '.join(map(_one_line, finding.limitations))}")
        if finding.open_questions:
            lines.append(
                f"   - Open questions: {'; '.join(map(_one_line, finding.open_questions))}"
            )
        lines.append(
            f"   - Needs review: {'yes' if finding.needs_review else 'no'}; independent Evidence"
            f" Families: {len(finding.independent_evidence_families)}"
        )
        if finding.counterevidence_ids:
            listed = ", ".join(f"`{each}`" for each in finding.counterevidence_ids)
            lines.append(f"   - Contradicted by independent counterevidence: {listed}")
    lines.append("")
    if content.contradictions:
        lines += ["## Contradictions (the Skeptic's counterevidence)", ""]
        for each in content.contradictions:
            span = each.source_span
            witness = "independent" if each.independent else "not independent"
            lines.append(
                f"- `{each.counterevidence_id}` ({each.checklist_item}, {witness}):"
                f' {_one_line(each.statement)} "{_one_line(span.quote)}" (Source Version'
                f" `{span.source_version_id}`, characters {span.span_start}-{span.span_end};"
                f" Assertion `{span.assertion_id}`)"
            )
        lines.append("")
    if content.unsupported_findings:
        lines += ["## Unsupported findings (not promoted)", ""]
        lines += [
            f"- {_one_line(each.statement)} ({each.reason})"
            for each in content.unsupported_findings
        ]
        lines.append("")
    lines += ["## Citations", ""]
    for citation in export.citations:
        lines.append(
            f'[{citation.number}] "{_one_line(citation.quote)}" — {_one_line(citation.title)},'
            f" {citation.publisher}, available {_time(citation.available_at)}. <{citation.url}>"
            f" (Source Version `{citation.source_version_id}`, characters"
            f" {citation.span_start}-{citation.span_end}; Assertion `{citation.assertion_id}`,"
            f" {citation.verification_status_now})"
        )
    if not export.citations:
        lines.append("None.")
    meta = export.run_metadata
    investigation = meta.investigation
    lines += [
        "",
        "## Run metadata",
        "",
        f"- Investigation `{investigation.id}`: {_one_line(investigation.question)}"
        f" (theme {investigation.theme}, as of {_time(investigation.as_of)}, stopped"
        f" {investigation.stop_reason}; run `{investigation.run_id}`)",
    ]
    for run in meta.runs:
        models = ", ".join(
            f"{alias} → {'/'.join(d.model for d in deployments) or 'unrouted'}"
            for alias, deployments in run.routed_models.items()
        )
        lines.append(
            f"- Run `{run.id}` ({run.kind}): code {run.code_version}, Hindsight"
            f" {run.hindsight_version}, template {run.template_version}, models {models or 'none'};"
            f" tokens {run.tokens_in} in, {run.tokens_out} out"
        )
    for call in meta.role_calls:
        lines.append(
            f"- Role call `{call.id}`: {call.role}, prompt {call.prompt_name}"
            f" v{call.prompt_version} (`{call.prompt_sha256[:12]}`), model {call.model},"
            f" {call.status}"
        )
    lines += ["", f"Exported {_time(export.exported_at)}.", ""]
    return "\n".join(lines)


def _one_line(value: str) -> str:
    return " ".join(value.split())


def _or_none(value: str | None) -> str:
    return _one_line(value) if value else "not established"


def _time(value: datetime | None) -> str:
    return value.isoformat() if value is not None else "unknown"
