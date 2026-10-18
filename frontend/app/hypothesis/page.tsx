"use client";

// The bet: the thesis in one line, where each step stands, what would kill it and when it is
// tested, and publish when asked. Everything raw (versions, the diff, scenarios, snapshots,
// history, export, the full list of what it rests on) is in the Records, rendered when opened.
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { ArgumentStrip } from "../../components/argument-strip";
import { Predictions } from "../../components/calls";
import { DueList } from "../../components/due-list";
import {
  Findings,
  Scenarios,
  Snapshots,
  VersionContent,
  VersionDiff,
} from "../../components/hypothesis";
import {
  Counterevidence,
  HypothesisCalls,
  HypothesisSteps,
  OpenIssues,
  VersionStepRows,
} from "../../components/hypothesis-steps";
import { CheckThesisButton } from "../../components/check-thesis";
import { RecordsFold } from "../../components/records-fold";
import { edgeLabel } from "../../components/relationships";
import { Status, ThesisCheck } from "../../components/status";
import { Code, Load, Missing, Row, Timestamp } from "../../components/ui";
import {
  ApiError,
  api,
  type GateFailure,
  type Hypothesis,
  type HypothesisStatus,
  type HypothesisVersion,
  type PublishGate,
} from "../../lib/api/client";
import { weakestStep, weakestText } from "../../lib/argument";
import { plainDay } from "../../lib/format";
import {
  mechanismText,
  versionArgument,
} from "../../lib/hypothesis-page";
import {
  chosenVersion,
  explainBlock,
  explainFailure,
  needsThesisCheck,
  versionLabel,
  words,
} from "../../lib/hypotheses";
import { callsFor, stepBeliefIds, stepsOf } from "../../lib/hypothesis-steps";
import { STATES } from "../../lib/relationships";
import { routes } from "../../lib/routes";
import { forgetDecideCount } from "../../lib/decide";
import { gateFailureText } from "../../lib/status";
import { draftedProposition, proposition, rest } from "../../lib/thesis";
import { useApi, useIdParam, type Loaded } from "../../lib/use-api";

export default function HypothesisPage() {
  return (
    <Suspense>
      <Dossier />
    </Suspense>
  );
}

// Keys carry a revision, so a publication or a status change re-reads what it changed.
const loadHypothesis = (key: string) => api.hypothesis(key.split("#")[0] ?? "");
const loadGate = (key: string) => api.publishGate(key.split("#")[0] ?? "");
const loadThemes = () => api.themes();
const loadCalls = async (theme: string) => (await api.calls(theme)).items;
const loadPredictions = async (key: string) =>
  (await api.hypothesisPredictions(key.split("#")[0] ?? "")).items;

function Dossier() {
  const id = useIdParam();
  const versionParam = useSearchParams().get("version");
  const [revision, setRevision] = useState(0);
  const [notice, setNotice] = useState<string | null>(null);
  const loaded = useApi(id === null ? null : `${id}#${revision}`, loadHypothesis);
  const changed = (message: string) => {
    setNotice(message);
    forgetDecideCount();
    setRevision((each) => each + 1);
  };
  return (
    <>
      {notice && (
        <p role="status" aria-live="polite">
          {notice}
        </p>
      )}
      {loaded.state === "loading" ? (
        <div aria-busy="true">
          <span className="sk sk-title" />
          <span className="sk sk-h1" />
          <span className="sk sk-line" />
        </div>
      ) : (
        <Load loaded={loaded} what="this Hypothesis">
          {(hypothesis) => (
            <Body
              hypothesis={hypothesis}
              versionParam={versionParam}
              revision={revision}
              onChanged={changed}
            />
          )}
        </Load>
      )}
    </>
  );
}

function Body({
  hypothesis,
  versionParam,
  revision,
  onChanged,
}: {
  hypothesis: Hypothesis;
  versionParam: string | null;
  revision: number;
  onChanged: (message: string) => void;
}) {
  const router = useRouter();
  const chosen = chosenVersion(versionParam, hypothesis.versions);
  const version = hypothesis.versions.find((each) => each.version === chosen);
  const steps = version !== undefined && stepsOf(version).length > 0;
  const themes = useApi("themes", loadThemes);
  const themeTitle =
    themes.state === "ready"
      ? (themes.data.find((each) => each.id === hypothesis.theme_id)?.title ?? hypothesis.theme_id)
      : hypothesis.theme_id;
  const gate = useApi(`${hypothesis.id}#${revision}`, loadGate);
  const calls = useApi(hypothesis.theme_id, loadCalls);
  const predictions = useApi(`${hypothesis.id}#${revision}`, loadPredictions);
  const now = new Date();

  const statement = version?.content.thesis_statement ?? "";
  const drafted = version ? draftedProposition(version.content) : null;
  const lead = version ? proposition(statement, drafted) : "A Hypothesis being drafted";
  const argument = version && steps ? versionArgument(version) : null;
  const weakest = argument ? weakestStep(argument) : null;

  return (
    <div className="reader hypothesis-page">
      <p className="crumbs">
        <Link href={routes.theme(hypothesis.theme_id)}>{themeTitle}</Link>
      </p>
      <header>
        {version !== undefined && (
          <p className="kicker">
            {version.published ? (
              <Status word={{ word: `Published ${plainDay(version.published_at, now)}`, tone: "ok" }} />
            ) : (
              <Status word={{ word: "Draft", tone: "muted" }} />
            )}
            <span className="thesis-part">
              <a href="#records">
                v{version.version} {version.origin === "correction" ? "correction" : "draft"}
              </a>
            </span>
            <span className="thesis-part" aria-label="Thesis check">
              <ThesisCheck version={version} />
            </span>
          </p>
        )}
        <h1 className="reader-headline measure">{lead}</h1>
        {version !== undefined && <ThesisRest version={version} />}
        {weakest && <p className="card-weakest">{weakestText(weakest)}</p>}
        {argument && <ArgumentStrip steps={argument} />}
      </header>

      {version === undefined ? (
        <p>
          {hypothesis.draft_status === "failed"
            ? `The draft failed: ${hypothesis.draft_error ?? "no reason recorded"}.`
            : "The draft of version 1 is queued: nothing to read yet."}
        </p>
      ) : (
        <>
          <GateBanner
            hypothesis={hypothesis}
            version={version}
            gate={gate}
            onChanged={onChanged}
          />
          {steps ? (
            <section aria-label="The argument">
              <h2 className="reader-label">The argument, step by step</h2>
              <VersionStepRows version={version} theme={hypothesis.theme_id} />
            </section>
          ) : (
            <Findings hypothesisId={hypothesis.id} version={version} />
          )}

          <div className="band band-3">
            <section aria-labelledby="falsifiers-lead">
              <h2 className="reader-label" id="falsifiers-lead">
                What would falsify it
              </h2>
              {version.content.falsifiers.length === 0 ? (
                <p className="muted">None named.</p>
              ) : (
                <ul aria-label="What would falsify it" className="plain-list">
                  {version.content.falsifiers.map((each, index) => (
                    <li key={index}>
                      <span className="clamp-3" title={each}>
                        {each}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
            <div>
              <section aria-labelledby="questions">
                <h2 className="reader-label" id="questions">
                  Open questions
                </h2>
                {version.content.unresolved_questions.length === 0 ? (
                  <p className="muted">None named.</p>
                ) : (
                  <ul aria-label="Open questions" className="plain-list">
                    {version.content.unresolved_questions.map((each, index) => (
                      <li key={index}>
                        <span className="clamp-2" title={each}>
                          {each}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
              <OpenIssues theme={hypothesis.theme_id} />
            </div>
            <section aria-labelledby="due">
              <h2 className="reader-label" id="due">
                Due
              </h2>
              <DueSection
                predictions={predictions}
                calls={calls}
                hypothesis={hypothesis}
                version={version}
                now={now}
              />
            </section>
          </div>
        </>
      )}

      <RecordsFold>
        <RecordsBody
          hypothesis={hypothesis}
          version={version}
          steps={steps}
          gate={gate}
          revision={revision}
          onChanged={onChanged}
          onVersion={(next) => router.push(routes.hypothesis(hypothesis.id, next))}
        />
      </RecordsFold>
    </div>
  );
}

/** The rest of the thesis after its proposition, and the mechanism: one paragraph, three lines
 * and `More`. */
function ThesisRest({ version }: { version: HypothesisVersion }) {
  const [more, setMore] = useState(false);
  const statement = version.content.thesis_statement;
  const text = [rest(statement, draftedProposition(version.content)), mechanismText(version.content.mechanism)]
    .filter((part) => part !== "")
    .join(" ");
  if (text === "") return null;
  return (
    <div className="thesis-rest measure">
      <p className={more ? "" : "clamp-3"}>{text}</p>
      {text.length > 200 ? (
        <button type="button" className="quote-toggle" aria-expanded={more} onClick={() => setMore((each) => !each)}>
          {more ? "Less" : "More"}
        </button>
      ) : null}
    </div>
  );
}

function DueSection({
  predictions,
  calls,
  hypothesis,
  version,
  now,
}: {
  predictions: Loaded<Awaited<ReturnType<typeof api.hypothesisPredictions>>["items"]>;
  calls: Loaded<Awaited<ReturnType<typeof api.calls>>["items"]>;
  hypothesis: Hypothesis;
  version: HypothesisVersion;
  now: Date;
}) {
  if (predictions.state === "error" || calls.state === "error") return <p className="muted">Due unavailable</p>;
  if (predictions.state === "loading" || calls.state === "loading") return <span className="sk sk-line" />;
  const mine = callsFor(
    calls.data,
    hypothesis.versions.map((each) => each.id),
    stepBeliefIds(version),
  );
  return <DueList calls={mine} predictions={predictions.data} limit={4} now={now} empty="Nothing is due yet." />;
}

// --- the Records ------------------------------------------------------------------------------

function RecordsBody({
  hypothesis,
  version,
  steps,
  gate,
  revision,
  onChanged,
  onVersion,
}: {
  hypothesis: Hypothesis;
  version: HypothesisVersion | undefined;
  steps: boolean;
  gate: Loaded<PublishGate>;
  revision: number;
  onChanged: (message: string) => void;
  onVersion: (version: number) => void;
}) {
  return (
    <>
      {version !== undefined && hypothesis.versions.length > 1 && (
        <form aria-label="Choose a version" onSubmit={(event) => event.preventDefault()}>
          <div className="field">
            <label htmlFor="version">Version</label>
            <select
              id="version"
              value={version.version}
              onChange={(event) => onVersion(Number(event.target.value))}
            >
              {hypothesis.versions.map((each) => (
                <option key={each.version} value={each.version}>
                  {versionLabel(each)}
                </option>
              ))}
            </select>
          </div>
        </form>
      )}
      <Summary hypothesis={hypothesis} />
      {version !== undefined && (
        <>
          <p>
            Export version {version.version}:{" "}
            <a href={api.exportUrl(hypothesis.id, "json", version.version)}>JSON</a>
            {" · "}
            <a href={api.exportUrl(hypothesis.id, "markdown", version.version)}>Markdown</a>{" "}
            <span className="muted-small">(with citations and run metadata)</span>
          </p>
          <VersionContent version={version} />
          {steps && <Findings hypothesisId={hypothesis.id} version={version} />}
          <VersionDiff
            key={version.version}
            hypothesisId={hypothesis.id}
            versions={hypothesis.versions}
            chosen={version.version}
          />
          <Scenarios hypothesisId={hypothesis.id} version={version.version} />
        </>
      )}
      <Snapshots hypothesisId={hypothesis.id} revision={revision} />
      <Lifecycle hypothesis={hypothesis} gate={gate} onChanged={onChanged} />
      <History hypothesis={hypothesis} />
      {version !== undefined && steps && (
        <>
          <HypothesisSteps version={version} theme={hypothesis.theme_id} />
          <Counterevidence version={version} />
        </>
      )}
      <Predictions key={revision} hypothesisId={hypothesis.id} />
      {version !== undefined && (
        <HypothesisCalls
          theme={hypothesis.theme_id}
          versionIds={hypothesis.versions.map((each) => each.id)}
          beliefIds={stepBeliefIds(version)}
        />
      )}
    </>
  );
}

function Summary({ hypothesis }: { hypothesis: Hypothesis }) {
  return (
    <table>
      <caption>The Hypothesis</caption>
      <tbody>
        <Row name="Status">{words(hypothesis.status)}</Row>
        <Row name="Theme">
          <Link href={routes.theme(hypothesis.theme_id)}>{hypothesis.theme_id}</Link>
        </Row>
        <Row name="Author">{hypothesis.author}</Row>
        <Row name="Versions">
          {hypothesis.versions.length}; latest {hypothesis.latest_version ?? <Missing />}
        </Row>
        <Row name="First published">
          <Timestamp value={hypothesis.first_published_at} mode="exact" />
        </Row>
        <Row name="Next review">
          <Timestamp value={hypothesis.next_review_at} mode="exact" />
        </Row>
        {hypothesis.investigation_id === null ? (
          <Row name="Question">{hypothesis.question}</Row>
        ) : (
          <Row name="Investigation">
            <Code>{hypothesis.investigation_id}</Code>
          </Row>
        )}
      </tbody>
    </table>
  );
}

// --- the publish gate -------------------------------------------------------------------------

/** What an action needs: run it, tell the page, and show a refusal that is not a gate failure. */
function useAct(onChanged: (message: string) => void) {
  const [busy, setBusy] = useState(false);
  const [refusal, setRefusal] = useState<string | null>(null);
  const act = async (action: () => Promise<unknown>, done: string) => {
    setBusy(true);
    setRefusal(null);
    try {
      await action();
      onChanged(done);
    } catch (error) {
      if (error instanceof ApiError && error.failures.length > 0) {
        // Re-read the gate, which lists each failed check.
        onChanged(
          `The publish gate refused: ${error.failures.length} check` +
            `${error.failures.length === 1 ? "" : "s"} failed.`,
        );
      } else {
        setRefusal(error instanceof Error ? error.message : String(error));
      }
    } finally {
      setBusy(false);
    }
  };
  return { busy, refusal, act };
}

const BELIEF_CODES = new Set(["belief_not_proven", "belief_flagged"]);

/** At the top while a decision waits: the checks the version fails, in plain words, the edges
 * to approve, and the button. Gone once the latest version is published. */
function GateBanner({
  hypothesis,
  version,
  gate,
  onChanged,
}: {
  hypothesis: Hypothesis;
  version: HypothesisVersion;
  gate: Loaded<PublishGate>;
  onChanged: (message: string) => void;
}) {
  const { busy, refusal, act } = useAct(onChanged);
  const [reason, setReason] = useState("");
  if (gate.state !== "ready") return null;
  const data = gate.data;
  const latest = hypothesis.latest_version === version.version;
  const pending =
    latest &&
    data.version !== null &&
    data.blocked !== "already_published" &&
    data.blocked !== "no_version" &&
    (data.failures.length > 0 || data.blocked === null);
  if (!pending) return null;
  const canPublish = data.blocked === null;
  const overridable = data.failures.length > 0 && data.failures.every((each) => BELIEF_CODES.has(each.code));
  return (
    <section aria-labelledby="publish" className="gate-banner">
      <h2 id="publish" className="gate-title">
        Lifecycle and publication
      </h2>
      <p className="gate-lead">
        <Status word={{ word: "Needs decision", tone: "warn" }} />
        Version {data.version} is not published.
      </p>
      <GateChecks gate={data} plain />
      {needsThesisCheck(data) && data.version !== null && (
        <p>
          <CheckThesisButton
            hypothesisId={hypothesis.id}
            version={data.version}
            onChecked={onChanged}
          />
        </p>
      )}
      {canPublish && (
        <p>
          <button
            type="button"
            disabled={busy}
            onClick={() =>
              void act(
                () => api.publishVersion(hypothesis.id, data.version ?? 0),
                `Published version ${data.version}.`,
              )
            }
          >
            Publish version {data.version}
          </button>
        </p>
      )}
      {canPublish && overridable && (
        <form
          aria-label="Override and publish"
          onSubmit={(event) => {
            event.preventDefault();
            void act(
              () => api.publishOverride(hypothesis.id, data.version ?? 0, reason),
              `Published version ${data.version}, overriding the Beliefs.`,
            );
          }}
        >
          <div className="field">
            <label htmlFor="override-reason">Reason for publishing over the Beliefs</label>
            <input
              id="override-reason"
              required
              value={reason}
              onChange={(event) => setReason(event.target.value)}
            />
          </div>
          <button type="submit" disabled={busy}>
            Override and publish
          </button>
        </form>
      )}
      {refusal && <p role="alert">{refusal}</p>}
    </section>
  );
}

/** Lifecycle controls and the gate's full explanation: the Records' side of publication. */
function Lifecycle({
  hypothesis,
  gate,
  onChanged,
}: {
  hypothesis: Hypothesis;
  gate: Loaded<PublishGate>;
  onChanged: (message: string) => void;
}) {
  const { busy, refusal, act } = useAct(onChanged);
  return (
    <section aria-labelledby="lifecycle">
      <h2 id="lifecycle">Lifecycle</h2>
      <p>
        Status: <strong>{words(hypothesis.status)}</strong>. Publishing freezes the latest version
        and its Research Snapshot; it needs at least one falsifier, one unresolved question, every
        Belief it rests on proven, and the owner’s approval of every Relationship the findings
        depend on.
      </p>
      {hypothesis.allowed_transitions.length > 0 && (
        <p>
          {hypothesis.allowed_transitions.map((to: HypothesisStatus) => (
            <button
              key={to}
              type="button"
              disabled={busy}
              onClick={() =>
                void act(
                  () => api.transitionHypothesis(hypothesis.id, to),
                  `Status changed to ${words(to).toLowerCase()}.`,
                )
              }
            >
              Move to {words(to).toLowerCase()}
            </button>
          ))}
        </p>
      )}
      <Load loaded={gate} what="the publish gate">
        {(data) => <GateChecks gate={data} />}
      </Load>
      {refusal && <p role="alert">{refusal}</p>}
    </section>
  );
}

function GateChecks({ gate, plain = false }: { gate: PublishGate; plain?: boolean }) {
  const blocked = explainBlock(gate);
  return (
    <>
      {!plain && <h3>The publish gate for version {gate.version ?? "–"}</h3>}
      {blocked && <p>{blocked}</p>}
      {gate.failures.length === 0 ? (
        <p>Every check passes{blocked ? "" : ": the version can be published"}.</p>
      ) : (
        <ul aria-label="Failed checks" className="plain-list">
          {gate.failures.map((failure) => (
            <FailedCheck key={failure.code} failure={failure} plain={plain} />
          ))}
        </ul>
      )}
    </>
  );
}

function FailedCheck({ failure, plain }: { failure: GateFailure; plain: boolean }) {
  return (
    <li>
      {plain ? (
        gateFailureText(failure)
      ) : (
        <>
          <Code>{failure.code}</Code>: {explainFailure(failure)}
        </>
      )}
      {failure.relationship_ids.length > 0 && (
        <ul aria-label="Relationships needing the owner's approval">
          {failure.relationship_ids.map((id) => (
            <li key={id}>
              <EdgeNeedingApproval id={id} />
            </li>
          ))}
        </ul>
      )}
      {failure.assertion_ids.length > 0 && (
        <ul aria-label="Assertions awaiting machine review">
          {failure.assertion_ids.map((id) => (
            <li key={id}>
              <PendingAssertion id={id} />
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

function EdgeNeedingApproval({ id }: { id: string }) {
  const edge = useApi(id, api.relationship);
  if (edge.state !== "ready") {
    return <Link href={routes.relationship(id)}>Relationship {id.slice(0, 8)}</Link>;
  }
  return (
    <>
      <Link href={routes.relationship(id)}>{edgeLabel(edge.data)}</Link>{" "}
      <span className="muted-small">({STATES[edge.data.review_state]})</span>
    </>
  );
}

function PendingAssertion({ id }: { id: string }) {
  const assertion = useApi(id, api.assertion);
  if (assertion.state !== "ready") return <>Assertion {id.slice(0, 8)}</>;
  return (
    <Link href={routes.span(assertion.data.source_version_id, id)}>“{assertion.data.quote}”</Link>
  );
}

// --- history ----------------------------------------------------------------------------------

function History({ hypothesis }: { hypothesis: Hypothesis }) {
  return (
    <section aria-labelledby="history">
      <h2 id="history">History</h2>
      {hypothesis.transitions.length === 0 ? (
        <p>No status change yet: saved as a draft.</p>
      ) : (
        <table>
          <caption>Status changes, oldest first</caption>
          <thead>
            <tr>
              <th scope="col">When</th>
              <th scope="col">Change</th>
              <th scope="col">By</th>
              <th scope="col">Note</th>
            </tr>
          </thead>
          <tbody>
            {hypothesis.transitions.map((each) => (
              <tr key={each.seq}>
                <td>
                  <Timestamp value={each.at} mode="exact" />
                </td>
                <td>
                  {words(each.from_status)} → {words(each.to_status)}
                  {each.action === "publish" && <> (published version {each.version})</>}
                </td>
                <td>{each.actor}</td>
                <td>{each.note ?? <Missing />}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
