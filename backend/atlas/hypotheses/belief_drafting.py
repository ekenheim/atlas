"""The `draft_hypothesis` job for a Hypothesis over Beliefs (atlas-beliefs ticket 14).

A Hypothesis created from a theme's proven Beliefs (optionally those of some sessions) has no
investigation. One attempt of the draft:

1. **The Beliefs.** The theme's active Beliefs whose current judgement is `proven` (those
   produced by the named sessions, if any), at most `MAX_BELIEFS_PER_STEP` a step, most
   confident first. Each goes to the Editor by a short reference (`b1`, `b2`, ...) with the
   references of its load-bearing Facts' exact quotes, which are the retrieved data.
2. **The Editor** (`HYPOTHESIS_BELIEFS_EDITOR`) writes the thesis statement (citing Beliefs),
   mechanism, predictions, catalysts, falsifiers, required evidence, alternatives, unresolved
   questions and, per step, one statement citing Beliefs. Code maps every reference back to
   a Belief; a statement citing an unknown reference, another step's Belief or no Belief is set
   aside as unsupported, never kept.
3. **Each step statement is grounded and judged as a card statement is**: its cited Beliefs'
   load-bearing Facts stand in for the Claims it cites; `check_findings` holds its names,
   figures and quoted phrases to those quotes (asked again once through the Editor), and the
   finding judge (when `ATLAS_FINDING_JUDGE` is on) is asked about it, one call each (votes as
   configured); a misstated one is rewritten once and judged again, and set aside if it still
   fails. Set-aside statements are recorded in the version's `unsupported_findings`. The asks
   again and the rewrites run under the draft's role name and say the draft's rules
   (`HYPOTHESIS_REGROUND`, `HYPOTHESIS_REVISE`; ticket 25): the Editor's own words, no quotation
   marks, no qualifier the quotes lack, a thesis that says what may be true. A transcript
   quote reaches the grounding check and the judge with its speaker's label (ticket 25).
   The thesis statement is grounded and judged the same way, first, against the Facts of the
   Beliefs it cites, with the judge told it is a thesis (`finding.thesis`, `finding_judge.v5`):
   its bare hedged proposition ("may be straining ...") is caution, not a claim beyond the
   quotes, and needs no basis; its facts (actors, figures, scope words) still do. A thesis
   still misstated after its one rewrite is stored as that last text with `thesis_judged:
   misstated` and the judge's reason for it, and held at the publish gate (`thesis_misstated`),
   not refused; one still ungrounded after its one ask is refused.
4. Version 1 is written: the steps (all the proven Beliefs sent, each with its judgement and
   citations as they stand now, the kept statement where there is one), the thesis, and the
   rest of the Editor's proposal. The draft fails, recording why, when the Editor's thesis
   cites no Belief.

A Belief citation of kind `assertion` has no Fact to read a reading from: it is shown on the
step but never grounds a statement.
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import JsonValue
from sqlalchemy import Engine, RowMapping, text

from atlas.archive import open_archive
from atlas.audit import Actor, content_hash, record
from atlas.beliefs.service import Belief, get_belief, list_beliefs
from atlas.companies import load_universe
from atlas.hypotheses.model import HypothesisContent, Mechanism, VersionProvenance
from atlas.hypotheses.service import insert_version
from atlas.hypotheses.steps import STEP_ORDER, HypothesisStep, StepStatement, step_belief
from atlas.investigations.argument import fact_rows
from atlas.investigations.grounding import CheckedFinding, check_findings
from atlas.investigations.meaning import judge_findings, voting
from atlas.investigations.model import UnsupportedFinding
from atlas.investigations.speakers import with_speakers
from atlas.investigations.tasks import _judged_fact  # pyright: ignore[reportPrivateUsage]
from atlas.roles import QuotedText, RoleCaller, RoleCallFailed
from atlas.roles.editor import (
    HYPOTHESIS_BELIEFS_EDITOR,
    HYPOTHESIS_REGROUND,
    HYPOTHESIS_REVISE,
    BeliefItem,
    CardFindingDraft,
    HypothesisBeliefsRequest,
    OpenIssueItem,
)
from atlas.roles.finding_judge import judge_role
from atlas.settings import Settings

EDITOR_ACTOR = Actor("atlas-editor")
MAX_BELIEFS_PER_STEP = 8
MAX_FACTS_PER_STATEMENT = 12
_OPEN_ISSUES = 20
_BELIEF_PAGE = 500


@dataclass(frozen=True)
class ThesisVerdict:
    """The thesis statement as stored and what the finding judge said of it: `supported`,
    `misstated` (after one rewrite; the statement is then the text the judge's `reason` is
    about, the last rewrite) or None (not judged)."""

    statement: str
    judged: Literal["supported", "misstated"] | None
    reason: str | None


class DraftRefused(Exception):
    """The draft cannot be kept (its thesis is not held to its Beliefs): the reason, and what
    the job's artifacts record (`unresolved_refs`: references the Editor cited and was not sent)."""

    def __init__(self, reason: str, artifacts: dict[str, JsonValue]) -> None:
        super().__init__(reason)
        self.artifacts = artifacts


def proven_beliefs(
    engine: Engine, theme: str, session_ids: list[uuid.UUID], cutoff: datetime | None = None
) -> list[Belief]:
    """The active proven Beliefs of a theme (those of `session_ids` if any, with an as-of time
    at or before `cutoff`), at most `MAX_BELIEFS_PER_STEP` a step, most confident first within a
    step, steps in argument order."""
    with engine.connect() as connection:
        summaries, _ = list_beliefs(
            connection,
            theme=theme,
            judgement="proven",
            status="active",
            limit=_BELIEF_PAGE,
            offset=0,
        )
        wanted = [
            each
            for each in summaries
            if (cutoff is None or each.as_of <= cutoff)
            and (
                not session_ids
                or (each.produced_by is not None and each.produced_by in session_ids)
            )
        ]
        by_step: dict[str, list[Belief]] = {step: [] for step in STEP_ORDER}
        for summary in sorted(
            wanted, key=lambda each: (-each.judgement.confidence, each.created_at)
        ):
            if len(by_step[summary.step]) >= MAX_BELIEFS_PER_STEP:
                continue
            belief = get_belief(connection, summary.id)
            if belief is not None:
                by_step[summary.step].append(belief)
    return [belief for step in STEP_ORDER for belief in by_step[step]]


def _fact_citations(belief: Belief) -> list[uuid.UUID]:
    """The load-bearing Facts a Belief rests on (positive valence, kind `fact`)."""
    return [
        each.ref_id
        for each in belief.citations
        if each.kind == "fact" and each.weight == "load_bearing" and each.valence > 0
    ]


class BeliefHypothesisDrafter:
    def __init__(self, settings: Settings, engine: Engine, caller: RoleCaller) -> None:
        self._settings = settings
        self._engine = engine
        self._caller = caller

    def draft(self, hypothesis: RowMapping, run_id: uuid.UUID) -> dict[str, JsonValue]:
        beliefs = proven_beliefs(
            self._engine,
            hypothesis["theme_id"],
            list(hypothesis["session_ids"]),
            hypothesis["as_of"],
        )
        if not beliefs:
            raise RoleCallFailed("no proven Belief matches the Hypothesis's theme and sessions")
        refs = {f"b{index}": belief for index, belief in enumerate(beliefs, start=1)}
        theme = load_universe(self._settings.themes_config).themes.get(hypothesis["theme_id"])
        with self._engine.connect() as connection:
            issues = connection.execute(
                text(
                    "SELECT title, kind FROM issue WHERE theme = :theme AND status = 'active'"
                    " ORDER BY priority DESC, created_at LIMIT :limit"
                ),
                {"theme": hypothesis["theme_id"], "limit": _OPEN_ISSUES},
            ).all()
        retrieved: list[QuotedText] = []
        items: list[BeliefItem] = []
        for ref, belief in refs.items():
            quote_refs: list[str] = []
            citations = [
                each
                for each in belief.citations
                if each.weight == "load_bearing" and each.valence > 0
            ]
            for number, citation in enumerate(citations, start=1):
                quote_id = f"{ref}.{number}"
                quote_refs.append(quote_id)
                retrieved.append(
                    QuotedText(
                        id=quote_id,
                        source=f"{citation.source_version_id}#{citation.span_start}"
                        f"-{citation.span_end}",
                        text=citation.quote,
                    )
                )
            items.append(
                BeliefItem(
                    ref=ref,
                    step=belief.step,
                    statement=belief.statement,
                    judgement=belief.judgement.judgement,
                    confidence=belief.judgement.confidence,
                    as_of=belief.as_of.date().isoformat(),
                    companies=[each.display_name for each in belief.companies],
                    quote_refs=quote_refs,
                )
            )
        request = HypothesisBeliefsRequest(
            theme_id=hypothesis["theme_id"],
            theme_title=theme.title if theme else hypothesis["theme_id"],
            research_question=hypothesis["question"],
            beliefs=items,
            open_issues=[OpenIssueItem(title=row.title, kind=row.kind) for row in issues],
        )
        draft, role_call_id = self._caller.call_recorded(
            HYPOTHESIS_BELIEFS_EDITOR, request, run_id=run_id, retrieved=retrieved
        )

        unsupported: list[UnsupportedFinding] = []
        unresolved: list[str] = []  # references the Editor cited that it was not sent
        thesis_cited = list(dict.fromkeys(draft.thesis_belief_refs))
        unresolved += [ref for ref in thesis_cited if ref not in refs]
        thesis_cited = [ref for ref in thesis_cited if ref in refs]
        if not thesis_cited:
            raise DraftRefused(
                "the Editor's thesis cites no Belief it was sent",
                {"unresolved_refs": list[JsonValue](unresolved)},
            )

        said: list[tuple[str, str, list[str]]] = []  # step, statement, cited b-refs
        for each in draft.steps:
            cited = list(dict.fromkeys(each.belief_refs))
            unknown = [ref for ref in cited if ref not in refs]
            unresolved += unknown
            other = [ref for ref in cited if ref in refs and refs[ref].step != each.step]
            reason = None
            if each.step not in STEP_ORDER:
                reason = f"not a step of the argument: {each.step}"
            elif not cited:
                reason = "cites no Belief"
            elif unknown:
                reason = "cites what isn't a Belief it was sent: " + ", ".join(unknown)
            elif other:
                reason = "cites a Belief of another step: " + ", ".join(other)
            if reason is not None:
                unsupported.append(
                    UnsupportedFinding(
                        statement=each.statement,
                        claim_ids=[str(refs[ref].id) for ref in cited if ref in refs],
                        reason=reason,
                    )
                )
                continue
            said.append((each.step, each.statement, cited))
        unresolved = list(dict.fromkeys(unresolved))
        thesis, kept = self._ground_and_judge(
            hypothesis,
            run_id,
            refs,
            (draft.thesis_statement, thesis_cited),
            said,
            unsupported,
            unresolved,
        )

        steps: list[HypothesisStep] = []
        for step in STEP_ORDER:
            members = [step_belief(belief) for belief in beliefs if belief.step == step]
            if not members:
                continue
            statements = kept.get(step, [])
            first = statements[0] if statements else None
            steps.append(
                HypothesisStep(
                    step=step,
                    statement=None if first is None else first.statement,
                    statement_belief_ids=[] if first is None else first.belief_ids,
                    judged=None if first is None else first.judged,
                    statements=statements,
                    beliefs=members,
                )
            )
        content = HypothesisContent(
            thesis_statement=thesis.statement,
            thesis_judged=thesis.judged,
            thesis_misstated_reason=thesis.reason,
            mechanism=Mechanism.model_validate(draft.mechanism.model_dump()),
            measurable_predictions=draft.measurable_predictions,
            catalysts=draft.catalysts,
            falsifiers=draft.falsifiers,
            required_evidence=draft.required_evidence,
            alternative_explanations=draft.alternative_explanations,
            unresolved_questions=draft.unresolved_questions,
            findings=[],
            unsupported_findings=unsupported,
            steps=steps,
            thesis_belief_ids=[refs[ref].id for ref in thesis_cited],
        )
        provenance = VersionProvenance(
            session_ids=list(hypothesis["session_ids"]),
            belief_ids=[belief.id for belief in beliefs],
            draft_run_id=run_id,
            editor_role_call_id=role_call_id,
        )
        version = self._store(hypothesis, content, provenance)
        return {
            "version": version,
            "unresolved_refs": list[JsonValue](unresolved),
            "thesis_judged": thesis.judged,
        }

    def _ground_and_judge(
        self,
        hypothesis: RowMapping,
        run_id: uuid.UUID,
        refs: Mapping[str, Belief],
        thesis: tuple[str, list[str]],
        said: list[tuple[str, str, list[str]]],
        unsupported: list[UnsupportedFinding],
        unresolved: list[str],
    ) -> tuple[ThesisVerdict, dict[str, list[StepStatement]]]:
        """The thesis statement (grounded, asked again once if not; the draft is refused if it
        still is not) and, per step, the statements kept (grounded and judged)."""
        wanted = list(
            dict.fromkeys(
                fact
                for _, cited in [thesis, *((s, c) for _, s, c in said)]
                for ref in cited
                for fact in _fact_citations(refs[ref])
            )
        )
        with self._engine.connect() as connection:
            # A quote of a call transcript carries its speaker's label (ticket 25), for the
            # grounding check and the judge.
            rows = {
                row["id"]: row
                for row in with_speakers(
                    connection,
                    open_archive(self._settings),
                    fact_rows(connection, wanted, statements=True),
                )
            }
            names = [
                (row.display_name, row.legal_name)
                for row in connection.execute(
                    text("SELECT display_name, legal_name FROM company")
                ).all()
            ]
        claims: dict[str, Mapping[Any, Any]] = {}
        checking: list[tuple[CardFindingDraft, list[str]]] = []
        owners: list[tuple[str | None, list[str]]] = []  # step (None: the thesis), b-refs

        def add(owner: str | None, statement: str, cited: list[str]) -> bool:
            facts = list(
                dict.fromkeys(
                    fact for ref in cited for fact in _fact_citations(refs[ref]) if fact in rows
                )
            )[:MAX_FACTS_PER_STATEMENT]
            if not facts:
                return False
            fact_refs: list[str] = []
            for fact in facts:
                key = f"c{len(claims) + 1}"
                claims[key] = rows[fact]
                fact_refs.append(key)
            checking.append(
                (
                    CardFindingDraft(
                        statement=statement, claim_refs=fact_refs, limitations=[], open_questions=[]
                    ),
                    fact_refs,
                )
            )
            owners.append((owner, cited))
            return True

        if not add(None, *thesis):
            raise DraftRefused(
                "the thesis cites no Fact whose quote can ground it",
                {"unresolved_refs": list[JsonValue](unresolved)},
            )
        for step, statement, cited in said:
            if not add(step, statement, cited):
                unsupported.append(
                    UnsupportedFinding(
                        statement=statement,
                        claim_ids=[str(refs[ref].id) for ref in cited],
                        reason="its Beliefs cite no Fact whose quote can ground it",
                    )
                )
        question: str = hypothesis["question"]
        checked = check_findings(
            checking,
            claims,
            question,
            names,
            lambda again, quotes: self._caller.call_recorded(
                HYPOTHESIS_REGROUND, again, run_id=run_id, retrieved=quotes
            ),
            theses=frozenset({0}),
        )
        thesis_checked = checked.findings[0]
        if thesis_checked.ungrounded:
            raise DraftRefused(
                "the thesis statement is ungrounded in its Beliefs' quotes (asked again once): "
                + ", ".join(thesis_checked.ungrounded),
                {"unresolved_refs": list[JsonValue](unresolved)},
            )
        kept: dict[str, list[StepStatement]] = {}
        # The thesis goes to the judge first, with the same Facts and the same rewrite as a step
        # statement (ticket 24); the steps follow in the Editor's order.
        grounded: list[tuple[tuple[str | None, list[str]], CheckedFinding]] = [
            (owners[0], thesis_checked)
        ]
        for owner, each in zip(owners[1:], checked.findings[1:], strict=True):
            step = owner[0]
            assert step is not None
            if each.ungrounded:
                unsupported.append(
                    UnsupportedFinding(
                        statement=each.draft.statement,
                        claim_ids=[str(refs[ref].id) for ref in owner[1]],
                        reason="ungrounded: " + ", ".join(each.ungrounded),
                    )
                )
                continue
            grounded.append(((step, owner[1]), each))
        result = ThesisVerdict(thesis_checked.draft.statement, None, None)
        if not self._settings.finding_judge:
            for (step, cited), each in grounded[1:]:
                assert step is not None
                kept.setdefault(step, []).append(
                    StepStatement(
                        statement=each.draft.statement,
                        belief_ids=[refs[ref].id for ref in cited],
                    )
                )
            return result, kept
        meaning = judge_findings(
            [each for _, each in grounded],
            claims,
            question,
            names,
            voting(
                lambda asked, quotes: self._caller.call_recorded(
                    judge_role(asked), asked, run_id=run_id, retrieved=quotes
                ),
                self._settings.finding_judge_votes,
                self._settings.finding_judge_vote_rule,
            ),
            lambda asked, quotes: self._caller.call_recorded(
                HYPOTHESIS_REVISE, asked, run_id=run_id, retrieved=quotes
            ),
            _judged_fact,
            theses=frozenset({0}),
        )
        thesis_outcome, *step_outcomes = meaning.outcomes
        if not thesis_outcome.kept:
            # Misstated even after the one rewrite: kept, flagged for the owner at the gate (the
            # draft is not refused), as the text the reason is about: the Editor's own when it
            # was not rewritten, else its last rewrite.
            result = ThesisVerdict(
                thesis_outcome.draft.statement,
                "misstated",
                thesis_outcome.reason or "misstated",
            )
        elif thesis_outcome.judged:
            result = ThesisVerdict(thesis_outcome.draft.statement, "supported", None)
        else:  # its judge call failed: kept, not judged
            result = ThesisVerdict(thesis_outcome.draft.statement, None, None)
        for ((step, cited), _), outcome in zip(grounded[1:], step_outcomes, strict=True):
            assert step is not None
            if not outcome.kept:
                unsupported.append(
                    UnsupportedFinding(
                        statement=outcome.draft.statement,
                        claim_ids=[str(refs[ref].id) for ref in cited],
                        reason=outcome.reason or "misstated",
                    )
                )
                continue
            kept.setdefault(step, []).append(
                StepStatement(
                    statement=outcome.draft.statement,
                    belief_ids=[refs[ref].id for ref in cited],
                    judged=outcome.judged,
                )
            )
        return result, kept

    def _store(
        self, hypothesis: RowMapping, content: HypothesisContent, provenance: VersionProvenance
    ) -> int:
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
