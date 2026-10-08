"use client";

import Link from "next/link";
import { type FormEvent, type ReactNode, Suspense, useState } from "react";

import { Code, Load, Missing, Row, Timestamp } from "../../components/ui";
import {
  ApiError,
  api,
  type CardArgumentStep,
  type CardFact,
  type Counterevidence,
  type EvidenceItem,
  type Investigation,
  type InvestigationEvent,
  type InvestigationTask,
  type ResearchCard,
} from "../../lib/api/client";
import { edgeLabel } from "../../lib/relationships";
import { routes } from "../../lib/routes";
import { useIdParam, usePolled } from "../../lib/use-api";
import {
  ROLES,
  addedInvestigator,
  byRound,
  canSaveHypothesis,
  channelsLabel,
  skepticCompanyLine,
  skepticCoverageSummary,
  checklistLabel,
  citedTally,
  counterevidenceSummary,
  entityHopSummary,
  factLine,
  figureLabel,
  followUpBlocked,
  foundBy,
  openQuestions,
  outputParts,
  pointedOutcome,
  type CounterLine,
  type PointerGroup,
  pointerGroups,
  pointerQueryLabel,
  pointerScope,
  pointerSummary,
  partLine,
  partTally,
  PLANS,
  pointerWeight,
  readerName,
  readingOutcome,
  saidBy,
  selectionSummary,
  splitCounterevidence,
  STEP_STATUS,
  statusText,
  stepStatements,
  stepTally,
  tokenUse,
} from "../../lib/workbench";

// A running investigation is re-read this often (its tasks run on the worker).
const POLL_MS = 2000;

type Workbench = { investigation: Investigation; events: InvestigationEvent[] };

async function loadWorkbench(id: string): Promise<Workbench> {
  const [investigation, events] = await Promise.all([
    api.investigation(id),
    api.investigationEvents(id),
  ]);
  return { investigation, events: events.items };
}

const running = (data: Workbench) => data.investigation.status === "running";

function describe(error: unknown): string {
  if (error instanceof ApiError) return `${error.code}: ${error.message}`;
  return error instanceof Error ? error.message : String(error);
}

export default function InvestigationPage() {
  return (
    <Suspense>
      <Workbench />
    </Suspense>
  );
}

function Workbench() {
  const id = useIdParam();
  const [loaded, reload] = usePolled(id, loadWorkbench, POLL_MS, running);
  const [notice, setNotice] = useState<string | null>(null);
  const done = (message: string) => {
    setNotice(message);
    reload();
  };
  return (
    <>
      <p className="crumbs">
        <Link href={routes.workbench}>Research workbench</Link>
      </p>
      <Load loaded={loaded} what="the investigation">
        {({ investigation, events }) => (
          <>
            <h1>{investigation.question}</h1>
            <p role="status" aria-live="polite">
              {notice}
            </p>
            <Summary investigation={investigation} />
            <Actions investigation={investigation} onDone={done} />
            <Plan investigation={investigation} />
            <Pointers investigation={investigation} />
            <Premises investigation={investigation} onDone={done} />
            <EvidenceTray items={investigation.evidence} />
            <Contradictions investigation={investigation} />
            <Card card={investigation.research_card} />
            <Leads investigation={investigation} />
            <Events events={events} />
          </>
        )}
      </Load>
    </>
  );
}

function Summary({ investigation }: { investigation: Investigation }) {
  const { budgets, usage } = investigation;
  return (
    <table>
      <caption>Status and budget use</caption>
      <tbody>
        <Row name="Status">
          <strong>{statusText(investigation)}</strong>
          {investigation.stop_detail && (
            <>
              <br />
              <span className="muted-small">{investigation.stop_detail}</span>
            </>
          )}
        </Row>
        <Row name="Theme">{investigation.theme}</Row>
        <Row name="Plan">{PLANS[investigation.plan]}</Row>
        <Row name="Rounds">
          {usage.rounds} of {budgets.max_rounds}
        </Row>
        <Row name="Leads">
          {usage.leads} of {budgets.max_leads}
        </Row>
        <Row name="Documents">
          {usage.documents} of {budgets.max_documents}
        </Row>
        <Row name="Investigators">
          {usage.companies} of {budgets.max_companies}{" "}
          <span className="muted-small">(this round; the seeds and the companies added)</span>
        </Row>
        <Row name="Tokens">
          {tokenUse(investigation)}{" "}
          <span className="muted-small">
            ({usage.tokens_in} in, {usage.tokens_out} out)
          </span>
        </Row>
        <Row name="Schema repairs">
          {Object.entries(usage.repairs)
            .map(([role, count]) => `${role} ${count}`)
            .join(", ") || "none"}
        </Row>
        <Row name="As of">
          <Timestamp value={investigation.request.as_of_utc} />
        </Row>
        <Row name="Run">
          {investigation.run_id ? <Code>{investigation.run_id}</Code> : <Missing>not started</Missing>}
        </Row>
        <Row name="Started">
          <Timestamp value={investigation.created_at} /> by {investigation.created_by}
        </Row>
        <Row name="Stopped">
          <Timestamp value={investigation.stopped_at} />
        </Row>
      </tbody>
    </table>
  );
}

// --- actions ---------------------------------------------------------------------------------

function Actions({
  investigation,
  onDone,
}: {
  investigation: Investigation;
  onDone: (message: string) => void;
}) {
  return (
    <section aria-labelledby="actions">
      <h2 id="actions">Actions</h2>
      {investigation.resumable && <Resume investigation={investigation} onDone={onDone} />}
      <FollowUp investigation={investigation} onDone={onDone} />
      <SaveHypothesis investigation={investigation} onDone={onDone} />
    </section>
  );
}

/** A form whose submit runs `act` once, showing its error if the API refuses it. */
function ActionForm({
  label,
  act,
  children,
  describedBy,
}: {
  label: string;
  act: () => Promise<void>;
  children?: ReactNode;
  describedBy?: string;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await act();
    } catch (failure) {
      setError(describe(failure));
    } finally {
      setBusy(false);
    }
  }
  return (
    <form onSubmit={submit} aria-label={label} aria-describedby={describedBy}>
      {children}
      {error && <p role="alert">Refused: {error}</p>}
      <button type="submit" disabled={busy}>
        {label}
      </button>
    </form>
  );
}

function Resume({
  investigation,
  onDone,
}: {
  investigation: Investigation;
  onDone: (message: string) => void;
}) {
  const [budget, setBudget] = useState(String(investigation.budgets.token_budget * 2));
  return (
    <>
      <h3>Resume</h3>
      <p id="resume-hint">
        The run&apos;s token budget ran out. Resume it with a larger budget: its unfinished tasks
        continue in the same run.
      </p>
      <ActionForm
        label="Resume with this budget"
        describedBy="resume-hint"
        act={async () => {
          await api.resumeInvestigation(investigation.id, Number(budget));
          onDone(`Resumed with a token budget of ${budget}.`);
        }}
      >
        <div className="field">
          <label htmlFor="token-budget">New token budget</label>
          <input
            id="token-budget"
            type="number"
            min={investigation.budgets.token_budget + 1}
            required
            value={budget}
            onChange={(event) => setBudget(event.target.value)}
          />
        </div>
      </ActionForm>
    </>
  );
}

function FollowUp({
  investigation,
  onDone,
}: {
  investigation: Investigation;
  onDone: (message: string) => void;
}) {
  const questions = openQuestions(investigation.research_card);
  const [chosen, setChosen] = useState<string | null>(null);
  const blocked = followUpBlocked(investigation);
  return (
    <>
      <h3>Follow-up round</h3>
      <p id="follow-up-hint">
        One round, at most, on one of the research card&apos;s open questions: the same plan
        again, in the same run, within what is left of its budgets.
      </p>
      {blocked ? (
        <p>
          <strong>No follow-up now:</strong> {blocked}
        </p>
      ) : (
        <ActionForm
          label="Launch the follow-up round"
          describedBy="follow-up-hint"
          act={async () => {
            const question = chosen ?? questions[0] ?? "";
            await api.followUp(investigation.id, question);
            onDone(`Follow-up round launched on: ${question}`);
          }}
        >
          <fieldset>
            <legend>Open question to pursue</legend>
            {questions.map((question, index) => (
              <div key={question}>
                <label>
                  <input
                    type="radio"
                    name="open-question"
                    value={question}
                    checked={(chosen ?? questions[0]) === question}
                    onChange={() => setChosen(question)}
                  />{" "}
                  {question}
                </label>
                {index === 0 && chosen === null && <span className="muted-small"> (default)</span>}
              </div>
            ))}
          </fieldset>
        </ActionForm>
      )}
      {investigation.follow_ups.length > 0 && (
        <ul>
          {investigation.follow_ups.map((followUp) => (
            <li key={followUp.round}>
              Round {followUp.round}: “{followUp.question}”, launched by {followUp.requested_by}{" "}
              <Timestamp value={followUp.requested_at} /> (the card before it had{" "}
              {followUp.card_before.findings.length} finding
              {followUp.card_before.findings.length === 1 ? "" : "s"})
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

function SaveHypothesis({
  investigation,
  onDone,
}: {
  investigation: Investigation;
  onDone: (message: string) => void;
}) {
  const saved = investigation.request.hypothesis_id;
  return (
    <>
      <h3>Hypothesis</h3>
      {saved ? (
        <p>
          Saved as Hypothesis{" "}
          <Link href={routes.hypothesis(saved)}>
            <Code>{saved}</Code>
          </Link>
          .
        </p>
      ) : canSaveHypothesis(investigation) ? (
        <ActionForm
          label="Save as Hypothesis"
          act={async () => {
            const hypothesis = await api.saveHypothesis(investigation.id);
            onDone(
              `Saved as Hypothesis ${hypothesis.id} (${hypothesis.status}); the Editor drafts` +
                " its first version.",
            );
          }}
        />
      ) : (
        <p>
          A stopped investigation whose research card has a finding can be saved as a
          Hypothesis.
        </p>
      )}
    </>
  );
}

// --- the plan and premises -------------------------------------------------------------------

function Plan({ investigation }: { investigation: Investigation }) {
  return (
    <section aria-labelledby="plan">
      <h2 id="plan">Plan</h2>
      <p>
        Every seed company has an Investigator. After the Scout, the other companies its
        reading pointers name get one too, best ranked first, while the company budget has
        room.
      </p>
      {byRound(investigation.tasks).map(([round, tasks]) => (
        <table key={round}>
          <caption>
            Round {round}
            {round > 1 && " (follow-up)"}
          </caption>
          <thead>
            <tr>
              <th scope="col">Task</th>
              <th scope="col">Role</th>
              <th scope="col">After</th>
              <th scope="col">Status</th>
              <th scope="col">Output</th>
            </tr>
          </thead>
          <tbody>
            {tasks.map((task) => (
              <TaskRow
                key={task.id}
                task={task}
                added={addedInvestigator(task, investigation.pointed_companies)}
              />
            ))}
          </tbody>
        </table>
      ))}
    </section>
  );
}

function TaskRow({ task, added }: { task: InvestigationTask; added: string | null }) {
  const parts = outputParts(task.artifacts);
  return (
    <tr>
      <th scope="row">
        <Code>{task.key}</Code>
      </th>
      <td>{ROLES[task.role]}</td>
      <td>{task.depends_on.length > 0 ? task.depends_on.join(", ") : <Missing>nothing</Missing>}</td>
      <td>
        <strong>{task.status}</strong>
        {task.generation > 0 && <span className="muted-small"> (resumed {task.generation}×)</span>}
      </td>
      <td>
        {added && <p className="muted-small">{added}</p>}
        {task.detail && <p className="muted-small">{task.detail}</p>}
        {parts.length > 0 ? parts.join("; ") : !task.detail && <Missing>none yet</Missing>}
      </td>
    </tr>
  );
}

/**
 * The reading pointers: what Memory returned to the Scout (the question and each of its
 * queries) and, under its own heading, to the Skeptic (each bear-checklist item for each
 * company the accepted Claims name).
 */
function Pointers({ investigation }: { investigation: Investigation }) {
  const groups = pointerGroups(investigation.pointers);
  const scouts = groups.filter((group) => group.kind === "scout");
  const skeptics = groups.filter((group) => group.kind === "bear_checklist");
  return (
    <section aria-labelledby="pointers">
      <h2 id="pointers">Reading pointers</h2>
      <p>
        The Scout asks Memory the question and each of its queries, across the theme. An
        answer that resolves to a section of an archived Source Version is a pointer: where
        to read. Its text is Memory, not Evidence: it is never quoted and reaches no role.
      </p>
      <PointedCompanies investigation={investigation} />
      {scouts.length === 0 ? <p>No reading pointer.</p> : <PointerGroups groups={scouts} />}
      <EntityPointers investigation={investigation} />
      <h3 id="skeptic-pointers">The Skeptic&apos;s</h3>
      <p>
        The Skeptic asks Memory each bear-checklist item for each company the accepted Claims
        name, across the theme, and reads where the answers point. No Memory is sent to it.
      </p>
      {skeptics.length === 0 ? (
        <p>No reading pointer of the Skeptic&apos;s.</p>
      ) : (
        <PointerGroups groups={skeptics} />
      )}
    </section>
  );
}

/**
 * The companies the Scout's pointers name, by weight, and which of them are read: the seeds,
 * the ones an Investigator was added for, and the ones the company budget had no room for.
 */
function PointedCompanies({ investigation }: { investigation: Investigation }) {
  const companies = investigation.pointed_companies;
  if (companies.length === 0) return null;
  return (
    <table>
      <caption>
        Companies the pointers name, best ranked first (a recall pointer weighs 1 / its rank;
        an entity pointer its share of that)
      </caption>
      <thead>
        <tr>
          <th scope="col">Company</th>
          <th scope="col">In round</th>
          <th scope="col">Pointers</th>
          <th scope="col">Read?</th>
        </tr>
      </thead>
      <tbody>
        {companies.map((company) => (
          <tr key={`${company.round}:${company.company_id}`}>
            <th scope="row">
              <Link href={routes.company(company.company_id)}>{company.company_name}</Link>
            </th>
            <td>{company.round}</td>
            <td>{pointerWeight(company)}</td>
            <td>
              {pointedOutcome(company, investigation.budgets.max_companies)}
              {company.task_key && (
                <>
                  {" "}
                  <Code>{company.task_key}</Code>
                </>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/**
 * The entity hop's pointers, apart from the recall pointers: for each company the round
 * reads, the documents of other companies whose facts carry its entity in Memory.
 */
function EntityPointers({ investigation }: { investigation: Investigation }) {
  const hops = investigation.entity_hops ?? [];
  const groups = pointerGroups(investigation.entity_pointers ?? []);
  return (
    <>
      <h3 id="entity-pointers">The entity hop</h3>
      <p>
        For each company the round reads, Memory lists the facts that carry its entity; a fact
        from another company&apos;s document points there. A co-mention is a reason to read,
        never an edge or Evidence.
      </p>
      {hops.length === 0 ? (
        <p>No entity hop.</p>
      ) : (
        <ul>
          {hops.map((hop) => (
            <li key={`${hop.round}:${hop.company_id}`}>
              {hop.company_name}
              {hop.round > 1 && ` (round ${hop.round})`}: {entityHopSummary(hop)}
            </li>
          ))}
        </ul>
      )}
      {groups.length > 0 && <PointerGroups groups={groups} />}
    </>
  );
}

function PointerGroups({ groups }: { groups: PointerGroup[] }) {
  return (
    <>
      {groups.map((group) => (
        <details key={`${group.round}:${group.kind}:${group.queryIndex}`}>
          <summary>
            {pointerQueryLabel(group)}: {group.query}{" "}
            <span className="muted-small">({pointerSummary(group)})</span>
          </summary>
          <table>
            <caption>
              Where Memory pointed for {pointerQueryLabel(group).toLowerCase()}, best rank
              first
            </caption>
            <thead>
              <tr>
                <th scope="col">Rank</th>
                <th scope="col">Memory (not Evidence)</th>
                <th scope="col">Company</th>
                <th scope="col">Document and section</th>
              </tr>
            </thead>
            <tbody>
              {group.pointers.map((pointer) => (
                <tr key={pointer.id}>
                  <td>
                    {pointer.rank}
                    {pointer.scope === "theme_layer" && (
                      <>
                        <br />
                        <span className="muted-small">recalled among {pointerScope(pointer)}</span>
                      </>
                    )}
                  </td>
                  <td>
                    <strong>Memory</strong>{" "}
                    <span className="muted-small">({pointer.memory_type})</span>:{" "}
                    {pointer.memory_text}
                  </td>
                  <td>{pointer.company_name ?? <Missing />}</td>
                  <td>
                    <Link href={routes.version(pointer.source_version_id)}>
                      {pointer.source_title}
                    </Link>
                    <br />
                    <span className="muted-small">
                      {pointer.section_heading ?? pointer.section_anchor}; characters{" "}
                      {pointer.section_char_start}–{pointer.section_char_end}
                      <br />
                      {pointer.placed_by === "chunk"
                        ? `read where its fact's chunk lies (characters ${pointer.chunk_char_start ?? "?"}–${pointer.chunk_char_end ?? "?"})`
                        : "read where its words match best"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      ))}
    </>
  );
}

function Premises({
  investigation,
  onDone,
}: {
  investigation: Investigation;
  onDone: (message: string) => void;
}) {
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const open = investigation.status === "running";
  return (
    <section aria-labelledby="premises">
      <h2 id="premises">Premises</h2>
      <p>
        Every task rests on the question; each Investigator also on its company belonging in
        it. Disproving a premise cancels only the unstarted tasks that depend on it
        {open ? "." : " (while the investigation runs)."}
      </p>
      <table>
        <caption>Premises</caption>
        <thead>
          <tr>
            <th scope="col">Premise</th>
            <th scope="col">Statement</th>
            <th scope="col">Status</th>
          </tr>
        </thead>
        <tbody>
          {investigation.premises.map((premise) => (
            <tr key={premise.key}>
              <th scope="row">
                <Code>{premise.key}</Code>
              </th>
              <td>{premise.statement}</td>
              <td>
                {premise.status === "disproven" ? (
                  <>
                    <strong>disproven</strong> by {premise.disproven_by}:{" "}
                    {premise.reason}
                  </>
                ) : open ? (
                  <ActionForm
                    label={`Disprove ${premise.key}`}
                    act={async () => {
                      await api.disprovePremise(
                        investigation.id,
                        premise.key,
                        reasons[premise.key] ?? "",
                      );
                      onDone(`Premise ${premise.key} disproven.`);
                    }}
                  >
                    <div className="field">
                      <label htmlFor={`reason-${premise.key}`}>Why it is disproven</label>
                      <input
                        id={`reason-${premise.key}`}
                        required
                        value={reasons[premise.key] ?? ""}
                        onChange={(event) =>
                          setReasons((current) => ({
                            ...current,
                            [premise.key]: event.target.value,
                          }))
                        }
                      />
                    </div>
                  </ActionForm>
                ) : (
                  "open"
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

// --- Evidence, counterevidence and the card --------------------------------------------------

/** The Claim read in its direction; an accepted Claim with no object is company-level. */
function claimLabel(item: EvidenceItem): string {
  return edgeLabel(item);
}

function EvidenceTray({ items }: { items: EvidenceItem[] }) {
  return (
    <section aria-labelledby="evidence">
      <h2 id="evidence">Evidence tray</h2>
      {items.length === 0 ? (
        <p>No accepted Claim yet.</p>
      ) : (
        <table>
          <caption>Accepted Claims, oldest first; each opens its source span</caption>
          <thead>
            <tr>
              <th scope="col">Claim</th>
              <th scope="col">Quote</th>
              <th scope="col">Source</th>
              <th scope="col">Round</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.claim_id}>
                <th scope="row">
                  {claimLabel(item)}
                  <br />
                  <span className="muted-small">
                    {item.layer ?? "no layer"}
                    {item.product && <>, {item.product}</>}; <Code>{item.epistemic_type}</Code>
                    {item.excluded && <>; left out (its premise was disproven)</>}
                  </span>
                </th>
                <td>
                  <blockquote id={`quote-${item.claim_id}`} className="quote">
                    {item.quote}
                  </blockquote>
                  {saidBy(item.speaker) && (
                    <p className="muted-small">{saidBy(item.speaker)}</p>
                  )}
                  <Link
                    href={routes.span(item.source_version_id, item.assertion_id)}
                    aria-describedby={`quote-${item.claim_id}`}
                  >
                    Open source span
                  </Link>{" "}
                  <span className="muted-small">
                    characters {item.span_start}–{item.span_end}
                    {foundBy(item.passage_selected_by) &&
                      `; passage selected by ${foundBy(item.passage_selected_by)}`}
                  </span>
                </td>
                <td>
                  {item.source_title}
                  <br />
                  <span className="muted-small">
                    available <Timestamp value={item.available_at} />; Assertion{" "}
                    {item.verification_status}; witness <Code>{item.evidence_family}</Code>
                  </span>
                </td>
                <td>
                  {item.round} <span className="muted-small">({item.task_key})</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function Contradictions({ investigation }: { investigation: Investigation }) {
  const accepted = investigation.counterevidence.filter((item) => item.outcome === "accepted");
  const contradictions = accepted.filter((item) => item.kind === "contradiction");
  const context = accepted.length - contradictions.length;
  const claims = new Map(investigation.evidence.map((item) => [item.claim_id, claimLabel(item)]));
  return (
    <section aria-labelledby="contradictions">
      <h2 id="contradictions">Counterevidence and contradictions</h2>
      <p>
        The Skeptic&apos;s own search. A contradiction speaks against a named Claim: it denies,
        limits or dates its statement, and only one from an Evidence Family no supporting Claim
        uses is an independent witness. Everything else it found on the bear checklist is bear
        context about a company: it contradicts no Claim.
      </p>
      <p>{counterevidenceSummary(investigation.counterevidence)}</p>
      {contradictions.length > 0 && (
        <table>
          <caption>Accepted contradictions</caption>
          <thead>
            <tr>
              <th scope="col">Statement</th>
              <th scope="col">Quote</th>
              <th scope="col">Contradicts</th>
              <th scope="col">Independent</th>
            </tr>
          </thead>
          <tbody>
            {contradictions.map((item) => (
              <CounterevidenceRow key={item.id} item={item} claims={claims} />
            ))}
          </tbody>
        </table>
      )}
      {context > 0 && (
        <p>
          The bear context is on the <a href="#bear-context">research card</a>
          {investigation.research_card ? "." : ", once the Editor has drafted it."}
        </p>
      )}
    </section>
  );
}

function CounterevidenceRow({
  item,
  claims,
}: {
  item: Counterevidence;
  claims: Map<string, string>;
}) {
  return (
    <tr>
      <th scope="row">
        {item.statement}
        <br />
        <span className="muted-small">checklist: {item.checklist_item}</span>
      </th>
      <td>
        <blockquote id={`counter-${item.id}`} className="quote">
          {item.quote}
        </blockquote>
        {item.source_version_id && item.assertion_id && (
          <Link
            href={routes.span(item.source_version_id, item.assertion_id)}
            aria-describedby={`counter-${item.id}`}
          >
            Open source span
          </Link>
        )}
      </td>
      <td>
        {item.contradicts_claim_ids.length === 0 ? (
          <Missing />
        ) : (
          item.contradicts_claim_ids.map((id) => claims.get(id) ?? id).join("; ")
        )}
        {item.how && <span className="muted-small"> ({item.how} it)</span>}
        {item.disproves_premise && (
          <>
            <br />
            <span className="muted-small">
              disproves <Code>{item.disproves_premise}</Code>
            </span>
          </>
        )}
      </td>
      <td>
        {item.independent ? "yes" : "no"}
        {item.independence_detail && (
          <>
            <br />
            <span className="muted-small">{item.independence_detail}</span>
          </>
        )}
      </td>
    </tr>
  );
}

function Card({ card }: { card: ResearchCard | null }) {
  const questions = openQuestions(card);
  return (
    <section aria-labelledby="card">
      <h2 id="card">Research card</h2>
      {!card ? (
        <p>No research card yet: the Editor drafts it last.</p>
      ) : (
        <>
          {card.plan === "argument" ? (
            <p>
              A draft argument; the Editor&apos;s verdict: <strong>{card.editor_verdict}</strong>
              . Steps: {stepTally(card.steps ?? []) || "none"}.
              {card.unsupported_findings.length > 0 &&
                ` ${card.unsupported_findings.length} statement(s) failed the checks and were dropped.`}
            </p>
          ) : (
            <p>
              A draft; the Editor&apos;s verdict: <strong>{card.editor_verdict}</strong>, from{" "}
              {card.claims_considered} accepted Claim{card.claims_considered === 1 ? "" : "s"}.
              {card.unsupported_findings.length > 0 &&
                ` ${card.unsupported_findings.length} finding(s) citing no accepted Claim were dropped.`}
            </p>
          )}
          {card.plan === "argument" && <QuestionParts card={card} />}
          {card.plan === "argument" ? (
            <ArgumentSteps card={card} />
          ) : card.editor_failure ? (
            <EditorFailed card={card} reason={card.editor_failure} />
          ) : card.findings.length === 0 ? (
            <p>
              No finding
              {card.claims_considered === 0 &&
                ": no Claim was accepted. The card reports what was searched and read, and" +
                  " the open questions for the next round"}
              .
            </p>
          ) : (
            <ol>
              {card.findings.map((finding, index) => (
                <li key={index}>
                  {finding.claim_text}{" "}
                  <span className="muted-small">
                    ({finding.source_spans.length} source span
                    {finding.source_spans.length === 1 ? "" : "s"},{" "}
                    {finding.independent_evidence_families.length} independent witness
                    {finding.independent_evidence_families.length === 1 ? "" : "es"}
                    {finding.needs_review && "; needs review"}
                    {finding.counterevidence_ids.length > 0 &&
                      `; contradicted by ${finding.counterevidence_ids.length}`}
                    )
                  </span>
                  {finding.limitations.length > 0 && (
                    <ul className="muted-small">
                      {finding.limitations.map((limitation) => (
                        <li key={limitation}>Limitation: {limitation}</li>
                      ))}
                    </ul>
                  )}
                </li>
              ))}
            </ol>
          )}
          {card.grounding_limit && card.findings.length > 0 && (
            <p className="muted-small">
              What the check of the findings does not hold: {card.grounding_limit}
            </p>
          )}
          {card.disproven_premises.length > 0 && (
            <p>Disproven premises: {card.disproven_premises.join("; ")}</p>
          )}
          <SkepticCoverage card={card} />
          <BearContext card={card} />
          <Searched card={card} />
          <Read card={card} />
          <NotRead card={card} />
        </>
      )}
      <h3 id="open-questions">Open questions</h3>
      {questions.length === 0 ? (
        <p>None.</p>
      ) : (
        <ul aria-labelledby="open-questions">
          {questions.map((question) => (
            <li key={question}>{question}</li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** The question's parts and what the card says of each (pilot-review R2-01): answered by a
 * statement, Facts recorded but no statement, or unanswered. */
function QuestionParts({ card }: { card: ResearchCard }) {
  const parts = card.question_parts ?? [];
  if (parts.length === 0) return null;
  return (
    <>
      <h3 id="question-parts">The question&apos;s parts: {partTally(parts)}</h3>
      <ul aria-labelledby="question-parts">
        {parts.map((part) => (
          <li key={part.key}>{partLine(part)}</li>
        ))}
      </ul>
    </>
  );
}

/** The argument plan's card: each step's status and statements, each statement's cited Facts
 * one click deeper, then all the step's Facts and counterevidence: "Against", the Skeptic's
 * Facts that contradict, limit or date them, and "Also found", the rest, each with what it
 * does to them. */
function ArgumentSteps({ card }: { card: ResearchCard }) {
  const steps = card.steps ?? [];
  // The thesis an invalidation Fact is judged against: the other steps' Facts, by ID.
  const thesis = new Map(
    steps
      .filter((step) => step.step !== "invalidation")
      .flatMap((step) => step.facts)
      .map((fact) => [fact.fact_id, fact] as const),
  );
  return (
    <>
      {card.editor_failure && (
        <p role="alert">
          The Editor failed, so no step has a statement and the card needs review.{" "}
          {card.editor_failure}
        </p>
      )}
      <ol aria-label="The argument">
        {steps.map((step) => {
          const statements = stepStatements(step);
          const all = splitCounterevidence(
            step.counterevidence,
            step.facts.map((fact) => fact.fact_id),
          );
          return (
            <li key={step.step}>
              <strong>{step.title}</strong>: {STEP_STATUS[step.status]}
              {step.status === "nothing_found" ? (
                <NothingFound step={step} />
              ) : statements.length > 0 ? (
                <ul aria-label={`${step.title}: statements`}>
                  {statements.map((said, index) => {
                    const split = splitCounterevidence(
                      said.counterevidence,
                      said.facts.map((fact) => fact.fact_id),
                    );
                    return (
                      <li key={index}>
                        {said.statement}
                        {step.status === "found" && (
                          <AgainstArgument facts={said.facts} thesis={thesis} />
                        )}
                        <details>
                          <summary className="muted-small">
                            {citedTally(
                              said.facts,
                              split.against.map((each) => each.fact),
                              split.alsoFound.length,
                            )}
                          </summary>
                          <StepFacts title="Evidence" facts={said.facts} />
                          <CounterFacts title="Against" lines={split.against} />
                          <CounterFacts title="Also found" lines={split.alsoFound} />
                        </details>
                      </li>
                    );
                  })}
                </ul>
              ) : (
                <p className="muted-small">No statement: {step.asks}</p>
              )}
              {step.facts.length + step.counterevidence.length > 0 && (
                <details>
                  <summary className="muted-small">
                    All:{" "}
                    {citedTally(
                      step.facts,
                      all.against.map((each) => each.fact),
                      all.alsoFound.length,
                    )}
                  </summary>
                  <StepFacts title="Evidence" facts={step.facts} />
                  <CounterFacts title="Against" lines={all.against} />
                  <CounterFacts title="Also found" lines={all.alsoFound} />
                </details>
              )}
              {step.unchecked.length > 0 && (
                <p className="muted-small">Unchecked: {step.unchecked.join("; ")}</p>
              )}
            </li>
          );
        })}
      </ol>
    </>
  );
}

/** The invalidation step when its Reader searched and found nothing against the argument:
 * what it searched for, and its summary. */
function NothingFound({ step }: { step: CardArgumentStep }) {
  const searched = step.searched ?? [];
  return (
    <div className="muted-small">
      <p>Nothing found against the argument.</p>
      {searched.length > 0 && (
        <ul aria-label={`${step.title}: searched`}>
          {searched.map((query, index) => (
            <li key={index}>Searched: {query}</li>
          ))}
        </ul>
      )}
      {step.reader_summary && <p>{step.reader_summary}</p>}
    </div>
  );
}

/** What a found invalidation statement's Facts stand against: the thesis Facts each one
 * contradicts, limits, dates or qualifies (or could not be judged against). */
function AgainstArgument({ facts, thesis }: { facts: CardFact[]; thesis: Map<string, CardFact> }) {
  const { against } = splitCounterevidence(facts, [...thesis.keys()]);
  if (against.length === 0) return null;
  return (
    <ul className="muted-small" aria-label="Against the argument">
      {against.map(({ fact, relation }) => (
        <li key={fact.fact_id}>
          Against{relation && ` (${relation})`}:{" "}
          {(fact.against ?? [])
            .map((id) => thesis.get(id))
            .filter((each): each is CardFact => each !== undefined)
            .map((each) => `${each.company_name}: ${each.statement}`)
            .join("; ")}
        </li>
      ))}
    </ul>
  );
}

function StepFacts({ title, facts }: { title: string; facts: CardFact[] }) {
  if (facts.length === 0) return null;
  return (
    <ul className="muted-small" aria-label={title}>
      {facts.map((fact) => (
        <li key={fact.fact_id}>
          {title}: {fact.company_name}: {factLine(fact)}{" "}
          <Link href={routes.span(fact.source_span.source_version_id, fact.fact_id)}>
            {fact.source_title}
          </Link>
        </li>
      ))}
    </ul>
  );
}

function CounterFacts({ title, lines }: { title: string; lines: CounterLine[] }) {
  if (lines.length === 0) return null;
  return (
    <ul className="muted-small" aria-label={title}>
      {lines.map(({ fact, relation }) => (
        <li key={fact.fact_id}>
          {title}
          {relation && ` (${relation})`}: {fact.company_name}: {factLine(fact)}{" "}
          <Link href={routes.span(fact.source_span.source_version_id, fact.fact_id)}>
            {fact.source_title}
          </Link>
        </li>
      ))}
    </ul>
  );
}

function EditorFailed({ card, reason }: { card: ResearchCard; reason: string }) {
  const companies = card.claims_by_company ?? [];
  return (
    <>
      <p role="alert">
        No finding: the Editor failed, so this card is Atlas&apos;s own and needs review. {reason}
      </p>
      <h3 id="claims-by-company">Accepted Claims by company</h3>
      {companies.length === 0 ? (
        <p>None.</p>
      ) : (
        companies.map((company) => (
          <div key={company.company_id}>
            <h4>
              <Link href={routes.company(company.company_id)}>{company.company_name}</Link> (
              {company.claims.length} Claim{company.claims.length === 1 ? "" : "s"})
            </h4>
            <ul>
              {company.claims.map((claim) => (
                <li key={claim.claim_id}>
                  {claim.predicate} {claim.object}
                  {claim.layer && ` (${claim.layer})`}{" "}
                  <span className="muted-small">
                    in{" "}
                    <Link href={routes.version(claim.source_version_id)}>{claim.source_title}</Link>
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ))
      )}
    </>
  );
}

/** What the Skeptic did for each company the accepted Claims name: checked, or not checked and why. */
function SkepticCoverage({ card }: { card: ResearchCard }) {
  const rows = card.skeptic_coverage ?? [];
  const summary = skepticCoverageSummary(rows);
  if (summary === null) return null;
  const anyMissed = rows.some((row) => row.outcome === "not_checked");
  return (
    <>
      <h3 id="skeptic-coverage">Skeptic coverage</h3>
      <p role={anyMissed ? "alert" : undefined}>{summary}</p>
      <ul aria-labelledby="skeptic-coverage">
        {rows.map((row) => (
          <li key={row.company_id}>
            <Link href={routes.company(row.company_id)}>{row.company_name}</Link> (
            {row.claims} Claim{row.claims === 1 ? "" : "s"}): {skepticCompanyLine(row)}
            {row.documents.length > 0 && (
              <ul className="muted-small">
                {row.documents.map((document) => (
                  <li key={document.source_version_id}>
                    <Link href={routes.version(document.source_version_id)}>{document.title}</Link>
                    : {document.passages} passage{document.passages === 1 ? "" : "s"}
                  </li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ul>
    </>
  );
}

function BearContext({ card }: { card: ResearchCard }) {
  const groups = card.bear_context ?? [];
  if (groups.length === 0) return null;
  return (
    <>
      <h3 id="bear-context">Bear context</h3>
      <p>
        What the Skeptic found on the bear checklist about a company. It is attached to no Claim
        and contradicts no finding.
      </p>
      <table aria-labelledby="bear-context">
        <thead>
          <tr>
            <th scope="col">Checklist item and company</th>
            <th scope="col">What the documents say</th>
          </tr>
        </thead>
        <tbody>
          {groups.map((group) => (
            <tr key={`${group.checklist_item}:${group.company_id}`}>
              <th scope="row">
                {checklistLabel(group.checklist_item)}
                <br />
                <Link href={routes.company(group.company_id)}>{group.company_name}</Link>
              </th>
              <td>
                <ul>
                  {group.items.map((item) => {
                    const figure = figureLabel(item);
                    return (
                      <li key={item.counterevidence_id}>
                        {item.statement}
                        <blockquote id={`context-${item.counterevidence_id}`} className="quote">
                          {item.source_span.quote}
                        </blockquote>
                        {figure && <span className="muted-small">Figure: {figure}. </span>}
                        <Link
                          href={routes.span(
                            item.source_span.source_version_id,
                            item.source_span.assertion_id,
                          )}
                          aria-describedby={`context-${item.counterevidence_id}`}
                        >
                          Open source span
                        </Link>
                        {item.reason && (
                          <>
                            <br />
                            <span className="muted-small">Bear context because: {item.reason}.</span>
                          </>
                        )}
                      </li>
                    );
                  })}
                </ul>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function Searched({ card }: { card: ResearchCard }) {
  const searched = card.searched ?? [];
  if (searched.length === 0) return null;
  return (
    <>
      <h3 id="searched">What was searched</h3>
      <ul aria-labelledby="searched">
        {searched.map((search) => (
          <li key={search.discovery_id}>
            Round {search.round}: {search.queries.length} quer
            {search.queries.length === 1 ? "y" : "ies"}, {search.leads_found} lead
            {search.leads_found === 1 ? "" : "s"} found, {search.lead_ids.length} taken.
            <ul className="muted-small">
              {search.queries.map((query, index) => (
                <li key={index}>
                  {query.query}
                  {query.purpose && ` (${query.purpose})`}
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ul>
    </>
  );
}

function Read({ card }: { card: ResearchCard }) {
  const read = card.read ?? [];
  if (read.length === 0) return null;
  return (
    <table>
      <caption>What was read</caption>
      <thead>
        <tr>
          <th scope="col">Reader</th>
          <th scope="col">Documents, sections and passages</th>
          <th scope="col">Outcome</th>
        </tr>
      </thead>
      <tbody>
        {read.map((reading) => (
          <tr key={`${reading.round}:${reading.task_key}`}>
            <th scope="row">
              {readerName(reading)}
              {reading.round > 1 && ` (round ${reading.round})`}
            </th>
            <td>
              {reading.documents.length === 0 ? (
                "None."
              ) : (
                <ul>
                  {reading.documents.map((document) => (
                    <li key={document.source_version_id}>
                      <Link href={routes.version(document.source_version_id)}>
                        {document.title}
                      </Link>
                      {document.sections.length > 0 && (
                        <span className="muted-small"> {document.sections.join(", ")}</span>
                      )}
                      <span className="muted-small">
                        {" "}
                        ({document.passages} passage{document.passages === 1 ? "" : "s"}
                        {selectionSummary(document.selections) &&
                          `, selected by ${selectionSummary(document.selections)}`}
                        )
                      </span>
                      {document.selected_by === "fallback" && (
                        <span className="muted-small"> (chosen by code)</span>
                      )}
                      {document.floor && (
                        <span className="muted-small"> (the latest filing: document floor)</span>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </td>
            <td>{readingOutcome(reading)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** The companies Memory pointed to that no Investigator read: the next investigation's seeds. */
function NotRead({ card }: { card: ResearchCard }) {
  const companies = card.not_read ?? [];
  if (companies.length === 0) return null;
  return (
    <>
      <h3 id="not-read">Companies not read</h3>
      <p>
        Memory pointed to these companies, and no Investigator read them. Seed the next
        investigation with one to read it.
      </p>
      <ul aria-labelledby="not-read">
        {companies.map((company) => (
          <li key={`${company.round}:${company.company_id}`}>
            <Link href={routes.company(company.company_id)}>{company.company_name}</Link>
            {company.round > 1 && ` (round ${company.round})`}: {pointerWeight(company)};{" "}
            {channelsLabel(company.channels) && `${channelsLabel(company.channels)}; `}
            {company.reason}.
          </li>
        ))}
      </ul>
    </>
  );
}

// --- leads, documents and events -------------------------------------------------------------

function Leads({ investigation }: { investigation: Investigation }) {
  return (
    <section aria-labelledby="leads">
      <h2 id="leads">Leads and documents</h2>
      <p>Leads are Tier C: where to look, never Evidence.</p>
      {investigation.leads.length === 0 ? (
        <p>No lead.</p>
      ) : (
        <ol>
          {investigation.leads.map((lead) => (
            <li key={lead.lead_id}>
              <a href={lead.url} rel="noreferrer noopener" target="_blank">
                {lead.title || lead.canonical_url}
              </a>
              {lead.snippet && <span className="muted-small"> {lead.snippet}</span>}
            </li>
          ))}
        </ol>
      )}
      {investigation.documents.length === 0 ? (
        <p>No document read.</p>
      ) : (
        <table>
          <caption>Documents read (Source Versions)</caption>
          <thead>
            <tr>
              <th scope="col">Title</th>
              <th scope="col">Task</th>
              <th scope="col">Available</th>
            </tr>
          </thead>
          <tbody>
            {investigation.documents.map((document) => (
              <tr key={document.source_version_id}>
                <th scope="row">
                  <Link href={routes.version(document.source_version_id)}>{document.title}</Link>
                </th>
                <td>
                  <Code>{document.task_key}</Code>
                </td>
                <td>
                  <Timestamp value={document.available_at} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function Events({ events }: { events: InvestigationEvent[] }) {
  return (
    <section aria-labelledby="events">
      <h2 id="events">Events</h2>
      <table>
        <caption>What happened, in order</caption>
        <thead>
          <tr>
            <th scope="col">#</th>
            <th scope="col">Event</th>
            <th scope="col">Round</th>
            <th scope="col">Task</th>
            <th scope="col">Detail</th>
            <th scope="col">At</th>
          </tr>
        </thead>
        <tbody>
          {events.map((event) => (
            <tr key={event.seq}>
              <td>{event.seq}</td>
              <th scope="row">{event.type}</th>
              <td>{event.round ?? <Missing>–</Missing>}</td>
              <td>{event.task_key ? <Code>{event.task_key}</Code> : <Missing>–</Missing>}</td>
              <td className="muted-small">{outputParts(event.detail).join("; ")}</td>
              <td>
                <Timestamp value={event.at} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
