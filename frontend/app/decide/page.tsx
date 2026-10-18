"use client";

// Everything that waits on the owner, in one counted queue: a version at the publish gate, an
// open proposed update, a Belief to judge. Each row opens the object's page, where the controls
// are. Edge exceptions, Candidates and identity reviews are the lead's delegated work: counts.
import Link from "next/link";
import { useState } from "react";

import { CheckThesisButton } from "../../components/check-thesis";
import { StatStrip } from "../../components/stat-strip";
import { api, type Hypothesis, type PublishGate } from "../../lib/api/client";
import { beliefsToJudge, forgetDecideCount, whyToJudge } from "../../lib/decide";
import { activity } from "../../lib/format";
import { needsThesisCheck } from "../../lib/hypotheses";
import { gateFailureText } from "../../lib/status";
import { proposition, draftedProposition } from "../../lib/thesis";
import { routes } from "../../lib/routes";
import { useApi } from "../../lib/use-api";

const loadBeliefs = async () => (await api.beliefs({ status: "active" })).items;
const loadUpdates = async () => (await api.proposedUpdates("open")).items;

interface GateRow {
  hypothesis: Hypothesis;
  gate: PublishGate;
  title: string;
}

/** The latest version of each Hypothesis that is not published and not closed, with its gate.
 * One that could not be checked is counted, never silently dropped. */
async function loadGates(): Promise<{ rows: GateRow[]; failed: number }> {
  const all = (await api.hypotheses()).items;
  const candidates = all.filter((each) => {
    const latest = each.versions.at(-1);
    return (
      latest !== undefined &&
      !latest.published &&
      each.status !== "closed" &&
      each.status !== "rejected"
    );
  });
  const checked = await Promise.allSettled(candidates.map((each) => api.publishGate(each.id)));
  const rows: GateRow[] = [];
  let failed = 0;
  checked.forEach((result, index) => {
    const hypothesis = candidates[index] as Hypothesis;
    if (result.status === "rejected") {
      failed += 1;
      return;
    }
    // A version the status does not let anyone publish yet (a draft) waits on the work, not the owner.
    if (result.value.blocked !== null) return;
    const version = hypothesis.versions.at(-1);
    rows.push({
      hypothesis,
      gate: result.value,
      title: version
        ? proposition(version.content.thesis_statement, draftedProposition(version.content))
        : "A Hypothesis being drafted",
    });
  });
  return { rows, failed };
}

export default function DecidePage() {
  const [revision, setRevision] = useState(0);
  const [notice, setNotice] = useState<string | null>(null);
  const gates = useApi(`gates#${revision}`, loadGates);
  const updates = useApi("updates", loadUpdates);
  const beliefs = useApi("beliefs", loadBeliefs);
  const exceptions = useApi("exceptions", api.exceptionsTotal);
  const candidates = useApi("candidates", api.candidatesTotal);
  const identity = useApi("identity", api.identityPendingTotal);

  const toJudge = beliefs.state === "ready" ? beliefsToJudge(beliefs.data) : [];
  const gateRows = gates.state === "ready" ? gates.data.rows : [];
  const updateRows = updates.state === "ready" ? updates.data : [];
  const waiting = gateRows.length + updateRows.length + toJudge.length;
  const loading = [gates, updates, beliefs].some((each) => each.state === "loading");
  const blocking =
    gates.state === "ready"
      ? gates.data.rows.reduce(
          (sum, row) =>
            sum + row.gate.failures.reduce((n, failure) => n + failure.relationship_ids.length, 0),
          0,
        )
      : 0;

  return (
    <div className="decide-page">
      <h1>Decide</h1>
      {notice ? (
        <p role="status" aria-live="polite">
          {notice}
        </p>
      ) : null}
      <StatStrip
        stats={[
          {
            label: "Waiting on you",
            value: loading ? "…" : waiting,
            tone: waiting > 0 ? "warn" : "muted",
          },
        ]}
      />

      {gates.state === "error" || (gates.state === "ready" && gates.data.failed > 0) ? (
        <p className="muted">Could not check publish gates</p>
      ) : null}

      {!loading && waiting === 0 ? <p className="measure">Nothing waits on you.</p> : null}

      {gateRows.length > 0 || updateRows.length > 0 || toJudge.length > 0 ? (
        <ul className="reader-rows decide-rows" aria-label="Waiting on you">
          {gateRows.map((row) => (
            <li className="reader-row" key={`gate-${row.hypothesis.id}`}>
              <div>
                <div className="row-title">
                  <Link href={routes.hypothesis(row.hypothesis.id)}>{row.title}</Link>
                </div>
                <div className="reader-row-sub">
                  Version {row.gate.version} ·{" "}
                  {row.gate.failures.length === 0
                    ? "ready to publish"
                    : row.gate.failures.map((failure) => gateFailureText(failure)).join(" · ")}
                </div>
                {needsThesisCheck(row.gate) && row.gate.version !== null ? (
                  <div className="row-secondary">
                    <CheckThesisButton
                      hypothesisId={row.hypothesis.id}
                      version={row.gate.version}
                      onChecked={(message) => {
                        setNotice(message);
                        forgetDecideCount();
                        setRevision((each) => each + 1);
                      }}
                    />
                  </div>
                ) : null}
              </div>
              <span className="reader-pill reader-disputed">Publish</span>
            </li>
          ))}
          {updateRows.map((update) => (
            <li className="reader-row" key={`update-${update.id}`}>
              <div>
                <div className="row-title">
                  <Link href={routes.hypothesis(update.hypothesis_id, update.hypothesis_version)}>
                    {update.summary}
                  </Link>
                </div>
                <div className="reader-row-sub">
                  Proposed update to version {update.hypothesis_version} ·{" "}
                  {activity(update.created_at)}
                </div>
              </div>
              <span className="reader-pill reader-disputed">Review</span>
            </li>
          ))}
          {toJudge.map((belief) => (
            <li className="reader-row" key={`belief-${belief.id}`}>
              <div>
                <div className="row-title">
                  <Link href={routes.belief(belief.id)}>{belief.statement}</Link>
                </div>
                <div className="reader-row-sub">
                  {whyToJudge(belief)} · {belief.companies.map((each) => each.display_name).join(", ")}
                </div>
              </div>
              <span className="reader-pill reader-disputed">Judge</span>
            </li>
          ))}
        </ul>
      ) : null}

      <section aria-labelledby="lead">
        <h2 className="reader-label" id="lead">
          With the lead
        </h2>
        <ul className="reader-rows decide-rows" aria-label="With the lead">
          <li className="reader-row">
            <div className="row-title">
              {exceptions.state === "ready" ? (
                <Link href={routes.exceptions}>
                  {exceptions.data.toLocaleString("en")} links in the exceptions queue ·{" "}
                  {blocking === 0 ? "none blocks a publish" : `${blocking} block a publish`}
                </Link>
              ) : (
                <Link href={routes.exceptions}>Exceptions queue</Link>
              )}
            </div>
          </li>
          <li className="reader-row">
            <div className="row-title">
              {candidates.state === "ready" ? (
                <Link href={routes.themes}>{candidates.data.toLocaleString("en")} candidates</Link>
              ) : (
                <Link href={routes.themes}>Candidates</Link>
              )}
            </div>
          </li>
          <li className="reader-row">
            <div className="row-title">
              {identity.state === "ready" ? (
                <Link href={routes.companies}>
                  {identity.data.toLocaleString("en")} identity reviews
                </Link>
              ) : (
                <Link href={routes.companies}>Identity reviews</Link>
              )}
            </div>
          </li>
        </ul>
      </section>
    </div>
  );
}
