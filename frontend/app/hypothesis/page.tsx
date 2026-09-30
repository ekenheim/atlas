"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import {
  Findings,
  Scenarios,
  Snapshots,
  VersionContent,
  VersionDiff,
} from "../../components/hypothesis";
import { edgeLabel } from "../../components/relationships";
import { Code, Load, Missing, Row, Timestamp } from "../../components/ui";
import {
  ApiError,
  api,
  type GateFailure,
  type Hypothesis,
  type HypothesisStatus,
  type PublishGate,
} from "../../lib/api/client";
import {
  chosenVersion,
  explainBlock,
  explainFailure,
  versionLabel,
  words,
} from "../../lib/hypotheses";
import { STATES } from "../../lib/relationships";
import { routes } from "../../lib/routes";
import { useApi, useIdParam } from "../../lib/use-api";

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

function Dossier() {
  const id = useIdParam();
  const versionParam = useSearchParams().get("version");
  const [revision, setRevision] = useState(0);
  const [notice, setNotice] = useState<string | null>(null);
  const loaded = useApi(id === null ? null : `${id}#${revision}`, loadHypothesis);
  const changed = (message: string) => {
    setNotice(message);
    setRevision((each) => each + 1);
  };
  return (
    <>
      <p className="crumbs">
        <Link href={routes.hypotheses}>Hypotheses</Link>
      </p>
      {notice && (
        <p role="status" aria-live="polite">
          {notice}
        </p>
      )}
      <Load loaded={loaded} what="the Hypothesis">
        {(hypothesis) => (
          <Body
            hypothesis={hypothesis}
            versionParam={versionParam}
            revision={revision}
            onChanged={changed}
          />
        )}
      </Load>
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
  return (
    <>
      <h1>{version ? version.content.thesis_statement : "A Hypothesis being drafted"}</h1>
      <Summary hypothesis={hypothesis} />
      {version === undefined ? (
        <p>
          {hypothesis.draft_status === "failed"
            ? `The Editor's draft failed: ${hypothesis.draft_error ?? "no reason recorded"}.`
            : "The Editor's draft of version 1 is queued: nothing to read yet."}
        </p>
      ) : (
        <>
          <form aria-label="Choose a version" onSubmit={(event) => event.preventDefault()}>
            <div className="field">
              <label htmlFor="version">Version</label>
              <select
                id="version"
                value={version.version}
                onChange={(event) =>
                  router.push(routes.hypothesis(hypothesis.id, Number(event.target.value)))
                }
              >
                {hypothesis.versions.map((each) => (
                  <option key={each.version} value={each.version}>
                    {versionLabel(each)}
                  </option>
                ))}
              </select>
            </div>
          </form>
          <p>
            Export version {version.version}:{" "}
            <a href={api.exportUrl(hypothesis.id, "json", version.version)}>JSON</a>
            {" · "}
            <a href={api.exportUrl(hypothesis.id, "markdown", version.version)}>Markdown</a>{" "}
            <span className="muted-small">(with citations and run metadata)</span>
          </p>
          <VersionContent version={version} />
          <Findings hypothesisId={hypothesis.id} version={version} />
          <VersionDiff
            key={version.version}
            hypothesisId={hypothesis.id}
            versions={hypothesis.versions}
            chosen={version.version}
          />
          <Scenarios hypothesisId={hypothesis.id} version={version.version} />
        </>
      )}
      <Publish hypothesis={hypothesis} revision={revision} onChanged={onChanged} />
      <Snapshots hypothesisId={hypothesis.id} revision={revision} />
      <History hypothesis={hypothesis} />
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
          <Timestamp value={hypothesis.first_published_at} />
        </Row>
        <Row name="Next review">
          <Timestamp value={hypothesis.next_review_at} />
        </Row>
        <Row name="Investigation">
          <Code>{hypothesis.investigation_id}</Code>
        </Row>
      </tbody>
    </table>
  );
}

// --- the lifecycle and the publish gate ---------------------------------------

function Publish({
  hypothesis,
  revision,
  onChanged,
}: {
  hypothesis: Hypothesis;
  revision: number;
  onChanged: (message: string) => void;
}) {
  const gate = useApi(`${hypothesis.id}#${revision}`, loadGate);
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
        // Re-read the gate, which lists (and explains) each failed check.
        onChanged(
          `The publish gate refused: ${error.failures.length} check` +
            `${error.failures.length === 1 ? "" : "s"} failed (see the publish gate below).`,
        );
      } else {
        setRefusal(error instanceof Error ? error.message : String(error));
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <section aria-labelledby="publish">
      <h2 id="publish">Lifecycle and publication</h2>
      <p>
        Status: <strong>{words(hypothesis.status)}</strong>. Publishing freezes the latest version
        and its Research Snapshot; it needs at least one falsifier, one unresolved question, and the
        owner’s approval of every Relationship the findings depend on.
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
        {(gate) => (
          <>
            <GateChecks gate={gate} />
            {gate.version !== null && gate.blocked === null && (
              <button
                type="button"
                disabled={busy}
                onClick={() =>
                  void act(
                    () => api.publishVersion(hypothesis.id, gate.version ?? 0),
                    `Published version ${gate.version}.`,
                  )
                }
              >
                Publish version {gate.version}
              </button>
            )}
          </>
        )}
      </Load>
      {refusal && <p role="alert">{refusal}</p>}
    </section>
  );
}

function GateChecks({ gate }: { gate: PublishGate }) {
  const blocked = explainBlock(gate);
  return (
    <>
      <h3>The publish gate for version {gate.version ?? "–"}</h3>
      {blocked && <p>{blocked}</p>}
      {gate.failures.length === 0 ? (
        <p>Every check passes{blocked ? "" : ": the version can be published"}.</p>
      ) : (
        <ul aria-label="Failed checks">
          {gate.failures.map((failure) => (
            <FailedCheck key={failure.code} failure={failure} />
          ))}
        </ul>
      )}
    </>
  );
}

function FailedCheck({ failure }: { failure: GateFailure }) {
  return (
    <li>
      <Code>{failure.code}</Code>: {explainFailure(failure)}
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

// --- history ------------------------------------------------------------

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
                  <Timestamp value={each.at} />
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
