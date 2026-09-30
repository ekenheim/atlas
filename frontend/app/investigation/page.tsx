"use client";

import Link from "next/link";
import { type FormEvent, type ReactNode, Suspense, useState } from "react";

import { Code, Load, Missing, Row, Timestamp } from "../../components/ui";
import {
  ApiError,
  api,
  type Counterevidence,
  type EvidenceItem,
  type Investigation,
  type InvestigationEvent,
  type InvestigationTask,
  type ResearchCard,
} from "../../lib/api/client";
import { routes } from "../../lib/routes";
import { useIdParam, usePolled } from "../../lib/use-api";
import {
  ROLES,
  byRound,
  canSaveHypothesis,
  followUpBlocked,
  openQuestions,
  outputParts,
  readerName,
  readingOutcome,
  statusText,
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
        <Row name="Rounds">
          {usage.rounds} of {budgets.max_rounds}
        </Row>
        <Row name="Leads">
          {usage.leads} of {budgets.max_leads}
        </Row>
        <Row name="Documents">
          {usage.documents} of {budgets.max_documents}
        </Row>
        <Row name="Tokens">
          {tokenUse(investigation)}{" "}
          <span className="muted-small">
            ({usage.tokens_in} in, {usage.tokens_out} out)
          </span>
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
              <TaskRow key={task.id} task={task} />
            ))}
          </tbody>
        </table>
      ))}
    </section>
  );
}

function TaskRow({ task }: { task: InvestigationTask }) {
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
        {task.detail && <p className="muted-small">{task.detail}</p>}
        {parts.length > 0 ? parts.join("; ") : !task.detail && <Missing>none yet</Missing>}
      </td>
    </tr>
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

function claimLabel(item: EvidenceItem): string {
  return `${item.subject_name} ${item.predicate} ${item.object_name ?? item.object_text ?? "?"}`;
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
                    {item.layer}
                    {item.product && <>, {item.product}</>}; <Code>{item.epistemic_type}</Code>
                    {item.excluded && <>; left out (its premise was disproven)</>}
                  </span>
                </th>
                <td>
                  <blockquote id={`quote-${item.claim_id}`} className="quote">
                    {item.quote}
                  </blockquote>
                  <Link
                    href={routes.span(item.source_version_id, item.assertion_id)}
                    aria-describedby={`quote-${item.claim_id}`}
                  >
                    Open source span
                  </Link>{" "}
                  <span className="muted-small">
                    characters {item.span_start}–{item.span_end}
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
  const rejected = investigation.counterevidence.length - accepted.length;
  const claims = new Map(investigation.evidence.map((item) => [item.claim_id, claimLabel(item)]));
  return (
    <section aria-labelledby="contradictions">
      <h2 id="contradictions">Counterevidence and contradictions</h2>
      <p>
        The Skeptic&apos;s own search against the accepted Claims. Only counterevidence from an
        Evidence Family no supporting Claim uses is an independent witness.
        {rejected > 0 && ` ${rejected} proposed item${rejected === 1 ? " was" : "s were"} rejected.`}
      </p>
      {accepted.length === 0 ? (
        <p>No accepted counterevidence.</p>
      ) : (
        <table>
          <caption>Accepted counterevidence</caption>
          <thead>
            <tr>
              <th scope="col">Statement</th>
              <th scope="col">Quote</th>
              <th scope="col">Contradicts</th>
              <th scope="col">Independent</th>
            </tr>
          </thead>
          <tbody>
            {accepted.map((item) => (
              <CounterevidenceRow key={item.id} item={item} claims={claims} />
            ))}
          </tbody>
        </table>
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
          <p>
            A draft; the Editor&apos;s verdict: <strong>{card.editor_verdict}</strong>, from{" "}
            {card.claims_considered} accepted Claim{card.claims_considered === 1 ? "" : "s"}.
            {card.unsupported_findings.length > 0 &&
              ` ${card.unsupported_findings.length} finding(s) citing no accepted Claim were dropped.`}
          </p>
          {card.findings.length === 0 ? (
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
          {card.disproven_premises.length > 0 && (
            <p>Disproven premises: {card.disproven_premises.join("; ")}</p>
          )}
          <Searched card={card} />
          <Read card={card} />
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
                        ({document.passages} passage{document.passages === 1 ? "" : "s"})
                      </span>
                      {document.selected_by === "fallback" && (
                        <span className="muted-small"> (chosen by code)</span>
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
