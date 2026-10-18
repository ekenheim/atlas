"use client";

// Everything that waits on the owner, in one counted queue, with the action in its row: judge a
// Belief, accept or dismiss a proposed update, publish a version that passes its gate, check a
// thesis nobody has. An item leaves the queue when its action succeeds. Edge exceptions,
// Candidates and identity reviews are the lead's delegated work: counts.
import Link from "next/link";
import { useState, type ReactNode } from "react";

import { CitationQuote } from "../../components/beliefs";
import { CheckThesisButton } from "../../components/check-thesis";
import { JudgeBelief, PublishVersion, UpdateActions } from "../../components/decide-actions";
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

/** A Belief's load-bearing quote, shown with the row so the judgement is made on the words. */
function BeliefQuote({ id }: { id: string }) {
  const belief = useApi(id, api.belief);
  if (belief.state !== "ready") return <span className="sk sk-line" />;
  const quote = belief.data.citations.find(
    (citation) => citation.weight === "load_bearing" && citation.valence > 0,
  );
  return quote ? <CitationQuote citation={quote} /> : <p className="muted-small">No quote cites it yet.</p>;
}

/** One waiting item: the title opens the object, the actions sit under it and above the link. */
function Item({
  title,
  href,
  sub,
  pill,
  children,
}: {
  title: string;
  href: string;
  sub: ReactNode;
  pill: string;
  children?: ReactNode;
}) {
  return (
    <li className="reader-row">
      <div>
        <div className="row-title">
          <Link href={href}>{title}</Link>
        </div>
        <div className="reader-row-sub">{sub}</div>
      </div>
      <span className="reader-pill reader-disputed">{pill}</span>
      {children ? <div className="row-actions">{children}</div> : null}
    </li>
  );
}

export default function DecidePage() {
  const [revision, setRevision] = useState(0);
  const [notice, setNotice] = useState<string | null>(null);
  // What the owner has dealt with this visit leaves the queue at once, whatever the next read says.
  const [handled, setHandled] = useState<ReadonlySet<string>>(new Set());
  const gates = useApi(`gates#${revision}`, loadGates);
  const updates = useApi(`updates#${revision}`, loadUpdates);
  const beliefs = useApi(`beliefs#${revision}`, loadBeliefs);
  const exceptions = useApi("exceptions", api.exceptionsTotal);
  const candidates = useApi("candidates", api.candidatesTotal);
  const identity = useApi("identity", api.identityPendingTotal);

  const done = (key: string) => (message: string) => {
    setNotice(message);
    setHandled((each) => new Set([...each, key]));
    forgetDecideCount();
    setRevision((each) => each + 1);
  };

  const toJudge =
    beliefs.state === "ready"
      ? beliefsToJudge(beliefs.data).filter((each) => !handled.has(`belief:${each.id}`))
      : [];
  const gateRows =
    gates.state === "ready"
      ? gates.data.rows.filter((each) => !handled.has(`gate:${each.hypothesis.id}`))
      : [];
  const updateRows =
    updates.state === "ready"
      ? updates.data.filter((each) => !handled.has(`update:${each.id}`))
      : [];
  const waiting = gateRows.length + updateRows.length + toJudge.length;
  const loading = [gates, updates, beliefs].some((each) => each.state === "loading") && waiting === 0;
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
      <p role="status" aria-live="polite" className={notice ? "decide-notice" : "sr-only"}>
        {notice ?? ""}
      </p>
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

      {waiting > 0 ? (
        <ul className="reader-rows decide-rows" aria-label="Waiting on you">
          {gateRows.map((row) => {
            const passes = row.gate.failures.length === 0;
            const version = row.gate.version;
            return (
              <Item
                key={`gate-${row.hypothesis.id}`}
                title={row.title}
                href={routes.hypothesis(row.hypothesis.id)}
                pill="Publish"
                sub={
                  <>
                    Version {version} ·{" "}
                    {passes
                      ? "ready to publish"
                      : row.gate.failures.map((failure) => gateFailureText(failure)).join(" · ")}
                  </>
                }
              >
                {version !== null && passes ? (
                  <PublishVersion
                    hypothesisId={row.hypothesis.id}
                    version={version}
                    onDone={done(`gate:${row.hypothesis.id}`)}
                  />
                ) : null}
                {version !== null && needsThesisCheck(row.gate) ? (
                  <CheckThesisButton
                    hypothesisId={row.hypothesis.id}
                    version={version}
                    onChecked={(message) => {
                      setNotice(message);
                      forgetDecideCount();
                      setRevision((each) => each + 1);
                    }}
                  />
                ) : null}
              </Item>
            );
          })}
          {updateRows.map((update) => (
            <Item
              key={`update-${update.id}`}
              title={update.summary}
              href={routes.hypothesis(update.hypothesis_id, update.hypothesis_version)}
              pill="Review"
              sub={
                <>
                  Proposed update to version {update.hypothesis_version} · {activity(update.created_at)}
                </>
              }
            >
              <UpdateActions id={update.id} summary={update.summary} onDone={done(`update:${update.id}`)} />
            </Item>
          ))}
          {toJudge.map((belief) => (
            <Item
              key={`belief-${belief.id}`}
              title={belief.statement}
              href={routes.belief(belief.id)}
              pill="Judge"
              sub={
                <>
                  {whyToJudge(belief)} · {belief.companies.map((each) => each.display_name).join(", ")}
                </>
              }
            >
              <BeliefQuote id={belief.id} />
              <JudgeBelief
                id={belief.id}
                statement={belief.statement}
                current={belief.judgement}
                onDone={done(`belief:${belief.id}`)}
              />
            </Item>
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
