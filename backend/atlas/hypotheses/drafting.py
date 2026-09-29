"""The `draft_hypothesis` job: the Editor drafts a saved investigation's Hypothesis (version 1).

One attempt:

1. A Hypothesis whose drafting is no longer `queued` (drafted or failed) does nothing.
2. The drafting run (kind `hypothesis_draft`) is started once and kept on the Hypothesis
   across retries; the investigation's run is finished by now.
3. **The Editor** (`HYPOTHESIS_EDITOR`) is sent the research question, the research card's
   findings and open questions, the investigation's accepted Claims (excluding those from a
   task whose premise was disproven), and the disproven premises; each Claim's quote goes as
   quoted, low-trust `retrieved_data`. It proposes the thesis statement, mechanism,
   predictions, catalysts, falsifiers, required Evidence, alternatives, unresolved questions
   and findings.
4. **Code keeps only findings citing accepted Claims** (atlas.hypotheses.findings); the rest
   are recorded as unsupported findings, never promoted. Version 1 is written with its
   content hash and provenance (both runs, both Editor calls), the drafting is `drafted`, and
   the run is finished with its token totals.

An LLM quota or outage re-raises (the kind is pausable: the queue pauses and the job is
requeued). A spent token budget, or any other failure on the job's last attempt, marks the
drafting `failed` with its reason and finishes the run; nothing is invented.
"""

import uuid
from typing import Any

from pydantic import JsonValue
from sqlalchemy import Engine, RowMapping, text

from atlas.audit import Actor, content_hash, record
from atlas.companies import load_universe
from atlas.hypotheses.findings import ProposedFinding, resolve_findings
from atlas.hypotheses.model import RUN_KIND, HypothesisContent, Mechanism, VersionProvenance
from atlas.hypotheses.service import insert_version
from atlas.investigations.model import ResearchCard
from atlas.investigations.tasks import accepted_claims
from atlas.jobs.pacing import classify_failure
from atlas.jobs.queue import Artifacts, Job
from atlas.roles import QuotedText, RoleCaller, RoleCallFailed, TokenBudgetExhausted, run_usage
from atlas.roles.editor import (
    HYPOTHESIS_EDITOR,
    CardFindingSummary,
    EditorClaim,
    HypothesisEditorRequest,
)
from atlas.runs import RunNotFound, RunRecorder
from atlas.settings import Settings

EDITOR_ACTOR = Actor("atlas-editor")
_ERROR_LIMIT = 500


class HypothesisDrafter:
    def __init__(
        self, settings: Settings, engine: Engine, caller: RoleCaller, runs: RunRecorder | None
    ) -> None:
        self._settings = settings
        self._engine = engine
        self._caller = caller
        self._runs = runs

    def draft(self, job: Job) -> Artifacts:
        hypothesis_id = uuid.UUID(str(job.payload["hypothesis_id"]))
        with self._engine.connect() as connection:
            hypothesis = (
                connection.execute(
                    text("SELECT * FROM hypothesis WHERE id = :id"), {"id": hypothesis_id}
                )
                .mappings()
                .one()
            )
            investigation = (
                connection.execute(
                    text("SELECT * FROM investigation WHERE id = :id"),
                    {"id": hypothesis["investigation_id"]},
                )
                .mappings()
                .one()
            )
        if hypothesis["draft_status"] != "queued":
            return _artifacts(hypothesis_id, hypothesis["draft_status"], drafted=False)
        run_id = self._run(hypothesis)
        try:
            version = self._draft(hypothesis, investigation, run_id)
        except TokenBudgetExhausted as error:
            self._fail(hypothesis_id, run_id, f"the draft's token budget ran out: {error}")
            return _artifacts(hypothesis_id, "failed", drafted=False)
        except Exception as error:
            if classify_failure(error) is None and job.attempts >= job.max_attempts:
                message = f"{type(error).__name__}: {error}"[:_ERROR_LIMIT]
                self._fail(hypothesis_id, run_id, message)
            raise
        self._finish_run(run_id)
        return _artifacts(hypothesis_id, "drafted", drafted=True) | {"version": version}

    def _run(self, hypothesis: RowMapping) -> uuid.UUID:
        existing: uuid.UUID | None = hypothesis["draft_run_id"]
        if existing is not None:
            return existing
        if self._runs is None:
            raise RoleCallFailed("a Hypothesis draft records a run: it needs LiteLLM and Hindsight")
        run = self._runs.start(RUN_KIND)
        with self._engine.begin() as connection:
            run_id: uuid.UUID = connection.execute(
                text(
                    "UPDATE hypothesis SET draft_run_id = coalesce(draft_run_id, :run)"
                    " WHERE id = :id RETURNING draft_run_id"
                ),
                {"id": hypothesis["id"], "run": run.id},
            ).scalar_one()
        return run_id

    def _draft(self, hypothesis: RowMapping, investigation: RowMapping, run_id: uuid.UUID) -> int:
        card = ResearchCard.model_validate(investigation["research_card"])
        investigation_run: uuid.UUID = investigation["run_id"]
        with self._engine.connect() as connection:
            claims = accepted_claims(connection, investigation["id"], investigation_run)
        theme = load_universe(self._settings.themes_config).themes.get(investigation["theme"])
        request = HypothesisEditorRequest(
            theme_id=investigation["theme"],
            theme_title=theme.title if theme else investigation["theme"],
            research_question=investigation["question"],
            card_findings=[
                CardFindingSummary(
                    statement=finding.claim_text,
                    claim_ids=[str(each) for each in finding.claim_ids],
                    limitations=finding.limitations,
                    open_questions=finding.open_questions,
                )
                for finding in card.findings
            ],
            card_open_questions=card.open_questions,
            claims=[
                EditorClaim(
                    claim_id=str(c["id"]),
                    subject=c["subject_name"],
                    predicate=c["predicate"],
                    object=c["object_name"] or c["object_text"] or "",
                    product=c["product"],
                    layer=c["layer"],
                    epistemic_type=c["epistemic_type"],
                    source_title=c["source_title"],
                    source_version_id=str(c["source_version_id"]),
                )
                for c in claims
            ],
            disproven_premises=card.disproven_premises,
        )
        retrieved = [
            QuotedText(
                id=str(c["id"]),
                source=f"{c['source_version_id']}#{c['span_start']}-{c['span_end']}",
                text=c["quote"],
            )
            for c in claims
        ]
        draft, role_call_id = self._caller.call_recorded(
            HYPOTHESIS_EDITOR, request, run_id=run_id, retrieved=retrieved
        )
        findings, unsupported = resolve_findings(
            [
                ProposedFinding(f.statement, f.claim_ids, f.limitations, f.open_questions)
                for f in draft.findings
            ],
            claims,
        )
        content = HypothesisContent(
            thesis_statement=draft.thesis_statement,
            mechanism=Mechanism.model_validate(draft.mechanism.model_dump()),
            measurable_predictions=draft.measurable_predictions,
            catalysts=draft.catalysts,
            falsifiers=draft.falsifiers,
            required_evidence=draft.required_evidence,
            alternative_explanations=draft.alternative_explanations,
            unresolved_questions=draft.unresolved_questions,
            findings=findings,
            unsupported_findings=unsupported,
        )
        provenance = VersionProvenance(
            investigation_id=investigation["id"],
            investigation_run_id=investigation_run,
            research_card_role_call_id=card.editor_role_call_id,
            draft_run_id=run_id,
            editor_role_call_id=role_call_id,
        )
        with self._engine.begin() as connection:
            locked = (
                connection.execute(
                    text("SELECT * FROM hypothesis WHERE id = :id FOR UPDATE"),
                    {"id": hypothesis["id"]},
                )
                .mappings()
                .one()
            )
            if locked["draft_status"] != "queued":
                return 1  # recorded by an earlier attempt
            version = insert_version(
                connection,
                hypothesis["id"],
                1,
                origin="editor_draft",
                based_on=None,
                content=content,
                provenance=provenance,
                note=None,
                created_by=EDITOR_ACTOR.name,
            )
            new = (
                connection.execute(
                    text(
                        "UPDATE hypothesis SET draft_status = 'drafted', updated_at = now()"
                        " WHERE id = :id RETURNING *"
                    ),
                    {"id": hypothesis["id"]},
                )
                .mappings()
                .one()
            )
            record(
                connection,
                EDITOR_ACTOR,
                "hypothesis.version_drafted",
                entity_type="hypothesis_version",
                entity_id=str(version.id),
                new_hash=version.content_sha256,
            )
            record(
                connection,
                EDITOR_ACTOR,
                "hypothesis.drafted",
                entity_type="hypothesis",
                entity_id=str(hypothesis["id"]),
                old_hash=content_hash(dict(locked)),
                new_hash=content_hash(dict(new)),
            )
        return 1

    def _fail(self, hypothesis_id: uuid.UUID, run_id: uuid.UUID, message: str) -> None:
        with self._engine.begin() as connection:
            old = (
                connection.execute(
                    text("SELECT * FROM hypothesis WHERE id = :id FOR UPDATE"),
                    {"id": hypothesis_id},
                )
                .mappings()
                .one()
            )
            if old["draft_status"] != "queued":
                return
            new = (
                connection.execute(
                    text(
                        "UPDATE hypothesis SET draft_status = 'failed', draft_error = :error,"
                        " updated_at = now() WHERE id = :id RETURNING *"
                    ),
                    {"id": hypothesis_id, "error": message},
                )
                .mappings()
                .one()
            )
            record(
                connection,
                EDITOR_ACTOR,
                "hypothesis.draft_failed",
                entity_type="hypothesis",
                entity_id=str(hypothesis_id),
                old_hash=content_hash(dict(old)),
                new_hash=content_hash(dict(new)),
            )
        self._finish_run(run_id)

    def _finish_run(self, run_id: uuid.UUID) -> None:
        if self._runs is None:
            return
        with self._engine.connect() as connection:
            usage = run_usage(connection, run_id)
        try:
            self._runs.finish(run_id, tokens_in=usage.tokens_in, tokens_out=usage.tokens_out)
        except RunNotFound:
            pass  # finished by an earlier attempt


def _artifacts(hypothesis_id: uuid.UUID, status: str, *, drafted: bool) -> dict[str, JsonValue]:
    result: dict[str, Any] = {
        "hypothesis_id": str(hypothesis_id),
        "draft_status": status,
        "drafted": drafted,
    }
    return result
