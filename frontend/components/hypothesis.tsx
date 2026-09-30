"use client";

// The Hypothesis dossier's sections (app/hypothesis): a version's content, its findings with
// numbered citations, the Skeptic's contradictions, the diff between two versions, the
// version's scenarios, and the Research Snapshots.
import Link from "next/link";
import { useState } from "react";

import {
  ApiError,
  api,
  type CardContradiction,
  type Citation,
  type DiffClaim,
  type HypothesisExport,
  type HypothesisVersion,
  type ResearchSnapshot,
  type Scenario,
  type ScenarioInput,
  type SnapshotRecord,
} from "../lib/api/client";
import { groupDigits } from "../lib/format";
import {
  CASES,
  CHANGES,
  LINES,
  groupClaims,
  inputProvenance,
  summarizeSnapshot,
  words,
} from "../lib/hypotheses";
import { routes } from "../lib/routes";
import { useApi } from "../lib/use-api";
import { Code, Load, Missing, Row, Timestamp } from "./ui";

// --- the version's content ------------------------------------------------------------

const LISTS = [
  ["measurable_predictions", "Measurable predictions"],
  ["catalysts", "Catalysts"],
  ["falsifiers", "Falsifiers"],
  ["required_evidence", "Required evidence"],
  ["alternative_explanations", "Alternative explanations"],
  ["unresolved_questions", "Unresolved questions"],
] as const;

/** The version's record (hash, origin, publication) and its thesis content. */
export function VersionContent({ version }: { version: HypothesisVersion }) {
  const content = version.content;
  const mechanism = content.mechanism;
  return (
    <section aria-labelledby="thesis">
      <h2 id="thesis">Thesis, version {version.version}</h2>
      <table>
        <caption>Version {version.version}</caption>
        <tbody>
          <Row name="Origin">
            {version.origin === "editor_draft" ? "The Editor's draft" : "A correction"}
            {version.based_on_version !== null && <> of version {version.based_on_version}</>}
          </Row>
          {version.note && <Row name="Note">{version.note}</Row>}
          <Row name="Written">
            by {version.created_by} at <Timestamp value={version.created_at} />
          </Row>
          <Row name="Published">
            {version.published ? (
              <>
                by {version.published_by} at <Timestamp value={version.published_at} />
              </>
            ) : (
              <Missing>not published: a draft, which can still be superseded</Missing>
            )}
          </Row>
          <Row name="Content SHA-256">
            <Code>{version.content_sha256}</Code>
          </Row>
        </tbody>
      </table>
      <h3>Thesis statement</h3>
      <p>{content.thesis_statement}</p>
      <h3>Mechanism</h3>
      <dl>
        <dt>Demand driver</dt>
        <dd>{mechanism.demand_driver ?? <Missing>not established</Missing>}</dd>
        <dt>Possible constraint</dt>
        <dd>{mechanism.possible_constraint ?? <Missing>not established</Missing>}</dd>
        <dt>Economic capture question</dt>
        <dd>{mechanism.economic_capture_question ?? <Missing>not established</Missing>}</dd>
      </dl>
      {LISTS.map(([field, title]) => (
        <div key={field}>
          <h3>{title}</h3>
          {content[field].length === 0 ? (
            <p>
              <Missing />
            </p>
          ) : (
            <ul aria-label={title}>
              {content[field].map((item, index) => (
                <li key={index}>{item}</li>
              ))}
            </ul>
          )}
        </div>
      ))}
    </section>
  );
}

// --- findings, citations and contradictions -----------------------------------

const loadExport = (key: string) => {
  const [id = "", version = ""] = key.split("@");
  return api.hypothesisExport(id, Number(version));
};

/** The findings with their numbered citations (each opens its highlighted source span),
 * what was not promoted, and the Skeptic's contradictions. */
export function Findings({
  hypothesisId,
  version,
}: {
  hypothesisId: string;
  version: HypothesisVersion;
}) {
  const dossier = useApi(`${hypothesisId}@${version.version}`, loadExport);
  return (
    <>
      <section aria-labelledby="findings">
        <h2 id="findings">Findings</h2>
        <p>
          Only findings state facts, and each cites accepted Claims: the exact quote of a Source
          Version. A citation opens that span, highlighted in the source.
        </p>
        <Load loaded={dossier} what="the findings">
          {(dossier) => <FindingList dossier={dossier} />}
        </Load>
        {version.content.unsupported_findings.length > 0 && (
          <>
            <h3>Unsupported (not promoted)</h3>
            <p>What the Editor wrote without citing an accepted Claim: never a finding.</p>
            <ul aria-label="Unsupported statements">
              {version.content.unsupported_findings.map((each, index) => (
                <li key={index}>
                  <strong>Unsupported:</strong> {each.statement}{" "}
                  <span className="muted-small">({each.reason})</span>
                </li>
              ))}
            </ul>
          </>
        )}
      </section>
      <Contradictions contradictions={version.content.contradictions ?? []} />
    </>
  );
}

function FindingList({ dossier }: { dossier: HypothesisExport }) {
  const byNumber = new Map(dossier.citations.map((each) => [each.number, each]));
  if (dossier.findings.length === 0) return <p>No finding cites accepted Evidence.</p>;
  return (
    <>
      <ol aria-label="Findings">
        {dossier.findings.map((finding, index) => (
          <li key={index}>
            {finding.claim_text}{" "}
            {finding.citations.map((number) => {
              const citation = byNumber.get(number);
              return citation ? (
                <CitationLink key={number} citation={citation} />
              ) : (
                <span key={number}>[{number}]</span>
              );
            })}
            <br />
            <span className="muted-small">
              {finding.needs_review ? <strong>Needs review</strong> : "Corroborated"};{" "}
              {finding.independent_evidence_families.length} independent Evidence Famil
              {finding.independent_evidence_families.length === 1 ? "y" : "ies"}; known from{" "}
              <Timestamp value={finding.evidence_available_at} />
            </span>
            {finding.limitations.length > 0 && (
              <>
                <br />
                <span className="muted-small">Limitations: {finding.limitations.join("; ")}</span>
              </>
            )}
            {finding.open_questions.length > 0 && (
              <>
                <br />
                <span className="muted-small">
                  Open questions: {finding.open_questions.join("; ")}
                </span>
              </>
            )}
            {finding.counterevidence_ids.length > 0 && (
              <>
                <br />
                <span className="muted-small">
                  Contradicted by independent counterevidence:{" "}
                  {finding.counterevidence_ids.map((each, n) => (
                    <span key={each}>
                      {n > 0 && ", "}
                      <a href={`#contradiction-${each}`}>{each.slice(0, 8)}</a>
                    </span>
                  ))}
                </span>
              </>
            )}
          </li>
        ))}
      </ol>
      <table>
        <caption>Citations, numbered in order of first use</caption>
        <thead>
          <tr>
            <th scope="col">#</th>
            <th scope="col">Quote</th>
            <th scope="col">Source</th>
            <th scope="col">Assertion</th>
          </tr>
        </thead>
        <tbody>
          {dossier.citations.map((citation) => (
            <tr key={citation.number} id={`citation-${citation.number}`}>
              <th scope="row">{citation.number}</th>
              <td>
                <blockquote className="quote">{citation.quote}</blockquote>
                <Link
                  href={routes.span(citation.source_version_id, citation.assertion_id)}
                  aria-label={`Open the span of citation ${citation.number}`}
                >
                  Open source span
                </Link>{" "}
                <span className="muted-small">
                  characters {citation.span_start}–{citation.span_end}
                </span>
              </td>
              <td>
                <Link href={routes.source(citation.source_document_id)}>{citation.title}</Link>
                <br />
                <span className="muted-small">
                  {citation.publisher}, Tier {citation.source_tier}
                  {citation.accession && <>, {citation.accession}</>}; available{" "}
                  <Timestamp value={citation.available_at} />
                </span>
              </td>
              <td>
                <strong>{citation.verification_status_now}</strong>
                {citation.verification_status_now !== citation.verification_status && (
                  <span className="muted-small">
                    {" "}
                    (was {citation.verification_status} when the version was written)
                  </span>
                )}
                <br />
                <Code>{citation.assertion_id.slice(0, 8)}</Code>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function CitationLink({ citation }: { citation: Citation }) {
  return (
    <Link
      href={routes.span(citation.source_version_id, citation.assertion_id)}
      aria-label={`Citation ${citation.number}: ${citation.title}`}
    >
      [{citation.number}]
    </Link>
  );
}

function Contradictions({ contradictions }: { contradictions: CardContradiction[] }) {
  return (
    <section aria-labelledby="contradictions">
      <h2 id="contradictions">Contradictions</h2>
      {contradictions.length === 0 ? (
        <p>The Skeptic’s accepted counterevidence: none against this version.</p>
      ) : (
        <>
          <p>The Skeptic’s accepted counterevidence against the findings’ Claims.</p>
          <ul aria-label="Contradictions">
            {contradictions.map((each) => (
              <li key={each.counterevidence_id} id={`contradiction-${each.counterevidence_id}`}>
                {each.statement}{" "}
                <span className="muted-small">
                  ({words(each.checklist_item)};{" "}
                  {each.independent ? "an independent witness" : "not independent"}:{" "}
                  {each.independence_detail})
                </span>
                <blockquote className="quote">{each.source_span.quote}</blockquote>
                <Link
                  href={routes.span(
                    each.source_span.source_version_id,
                    each.source_span.assertion_id,
                  )}
                >
                  Open the counterevidence’s source span
                </Link>
                {each.disproves_premise && (
                  <span className="muted-small">
                    {" "}
                    Disproves the premise “{each.disproves_premise}”.
                  </span>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

// --- the diff ------------------------------------------------------------

const loadDiff = (key: string) => {
  const [id = "", from = "", to = ""] = key.split(":");
  return api.hypothesisDiff(id, Number(from), Number(to));
};

/** The claims new, contradicted, unchanged or removed between two versions (default: the
 * chosen version and the one before it, or version 1 and 2). Key it by the chosen version,
 * so choosing another resets the range. */
export function VersionDiff({
  hypothesisId,
  versions,
  chosen,
}: {
  hypothesisId: string;
  versions: HypothesisVersion[];
  chosen: number;
}) {
  const numbers = versions.map((each) => each.version);
  const initialTo = chosen > 1 ? chosen : Math.min(2, Math.max(...numbers));
  const [current, setRange] = useState({ from: initialTo - 1, to: initialTo });
  const valid = current.from < current.to;
  const diff = useApi(
    valid && numbers.length > 1 ? `${hypothesisId}:${current.from}:${current.to}` : null,
    loadDiff,
  );
  return (
    <section aria-labelledby="diff">
      <h2 id="diff">Changes between versions</h2>
      {numbers.length < 2 ? (
        <p>Only one version so far: nothing to compare.</p>
      ) : (
        <>
          <form
            className="filters"
            aria-label="Compare versions"
            onSubmit={(e) => e.preventDefault()}
          >
            {(["from", "to"] as const).map((end) => (
              <div className="field" key={end}>
                <label htmlFor={`diff-${end}`}>
                  {end === "from" ? "From version" : "To version"}
                </label>
                <select
                  id={`diff-${end}`}
                  value={current[end]}
                  onChange={(event) => setRange({ ...current, [end]: Number(event.target.value) })}
                >
                  {numbers.map((number) => (
                    <option key={number} value={number}>
                      {number}
                    </option>
                  ))}
                </select>
              </div>
            ))}
          </form>
          {!valid ? (
            <p role="alert">Choose an earlier “from” version than “to” version.</p>
          ) : (
            <Load loaded={diff} what="the diff">
              {(diff) => (
                <>
                  <p role="status">
                    Version {diff.from_version} → {diff.to_version}: {diff.counts.new} new,{" "}
                    {diff.counts.contradicted} contradicted, {diff.counts.unchanged} unchanged,{" "}
                    {diff.counts.removed} removed.
                    {diff.fields_changed.length > 0 && (
                      <> Also changed: {diff.fields_changed.map(words).join(", ")}.</>
                    )}
                  </p>
                  {groupClaims(diff.claims).map((group) => {
                    const described = CHANGES.find((c) => c.change === group.change);
                    return (
                      <div key={group.change}>
                        <h3>
                          {described?.title} ({group.claims.length})
                        </h3>
                        <p className="muted-small">{described?.meaning}</p>
                        <ul aria-label={`${described?.title} claims`}>
                          {group.claims.map((claim, index) => (
                            <DiffClaimItem key={index} claim={claim} />
                          ))}
                        </ul>
                      </div>
                    );
                  })}
                </>
              )}
            </Load>
          )}
        </>
      )}
    </section>
  );
}

function DiffClaimItem({ claim }: { claim: DiffClaim }) {
  return (
    <li>
      {claim.claim_text}
      {claim.contradictions.length > 0 && (
        <>
          <br />
          <span className="muted-small">
            Contradicted by:{" "}
            {claim.contradictions
              .map((each) =>
                each.counterevidence_id
                  ? `counterevidence ${each.counterevidence_id.slice(0, 8)}`
                  : `Assertion ${each.assertion_id?.slice(0, 8)} now ${each.verification_status}`,
              )
              .join("; ")}
          </span>
        </>
      )}
    </li>
  );
}

// --- scenarios ------------------------------------------------------------

const loadScenarios = async (key: string) => {
  const [id = "", version = ""] = key.split("@");
  return (await api.scenarios(id, Number(version))).items;
};

/** The version's scenarios: inputs with their provenance, low/base/high lines, ±20% sensitivity. */
export function Scenarios({ hypothesisId, version }: { hypothesisId: string; version: number }) {
  const scenarios = useApi(`${hypothesisId}@${version}`, loadScenarios);
  return (
    <section aria-labelledby="scenarios">
      <h2 id="scenarios">Scenarios</h2>
      <Load loaded={scenarios} what="the scenarios">
        {(scenarios) =>
          scenarios.length === 0 ? (
            <p>No scenario is attached to version {version}.</p>
          ) : (
            scenarios.map((scenario, index) => (
              <ScenarioTables key={scenario.id} scenario={scenario} number={index + 1} />
            ))
          )
        }
      </Load>
    </section>
  );
}

function amount(value: string | null | undefined): string {
  return value === null || value === undefined ? "" : groupDigits(value);
}

function ScenarioTables({ scenario, number }: { scenario: Scenario; number: number }) {
  const name = `Scenario ${number}: ${scenario.product}`;
  return (
    <div>
      <h3>{name}</h3>
      <p>
        {scenario.origin === "researcher" ? "The researcher's" : "The Financial Analyst's"}{" "}
        assumptions in {scenario.currency}, as of <Timestamp value={scenario.as_of} />; model{" "}
        <Code>{scenario.model_version}</Code>.{" "}
        {scenario.recomputes_identically ? (
          <>Recomputing it gives the same outputs, byte for byte.</>
        ) : (
          <strong>Recomputing it gives different outputs.</strong>
        )}
        {scenario.note && <> Note: {scenario.note}</>}
        <br />
        <span className="muted-small">
          Assumptions SHA-256 <Code>{scenario.assumptions_sha256}</Code>; outputs SHA-256{" "}
          <Code>{scenario.outputs_sha256}</Code>
        </span>
      </p>
      <table>
        <caption>{name}: inputs, sourced or estimated</caption>
        <thead>
          <tr>
            <th scope="col">Input</th>
            {CASES.map((each) => (
              <th scope="col" key={each}>
                {words(each)}
              </th>
            ))}
            <th scope="col">Provenance</th>
          </tr>
        </thead>
        <tbody>
          {scenario.inputs.map((input) => (
            <InputRow key={input.name} input={input} />
          ))}
        </tbody>
      </table>
      <table>
        <caption>{name}: outputs by case</caption>
        <thead>
          <tr>
            <th scope="col">Line</th>
            {CASES.map((each) => (
              <th scope="col" key={each}>
                {words(each)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {LINES.map((line) => (
            <tr key={line}>
              <th scope="row">{words(line)}</th>
              {CASES.map((each) => {
                const result = scenario.outputs.cases[each]?.[line];
                return (
                  <td key={each}>
                    {result?.value != null ? (
                      amount(result.value)
                    ) : (
                      <Missing>
                        blocked
                        {result?.missing.length ? `: needs ${result.missing.join(", ")}` : ""}
                      </Missing>
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <div style={{ overflowX: "auto" }}>
        <table>
          <caption>{name}: sensitivity, one input ±20% from the base case</caption>
          <thead>
            <tr>
              <th scope="col">Input</th>
              <th scope="col">Change</th>
              <th scope="col">Input value</th>
              {LINES.map((line) => (
                <th scope="col" key={line}>
                  {words(line)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {scenario.outputs.sensitivity.map((row) => (
              <tr key={`${row.input}${row.change}`}>
                <th scope="row">{words(row.input)}</th>
                <td>{row.change}</td>
                <td>
                  {amount(row.input_value)}
                  {row.capped && <span className="muted-small"> (capped at its bound)</span>}
                </td>
                {LINES.map((line) => (
                  <td key={line}>
                    {row.lines[line] != null ? amount(row.lines[line]) : <Missing>blocked</Missing>}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function InputRow({ input }: { input: ScenarioInput }) {
  const source = input.source;
  return (
    <tr>
      <th scope="row">
        {words(input.name)}
        <br />
        <span className="muted-small">{input.meaning}</span>
      </th>
      {CASES.map((each) => (
        <td key={each}>{input[each] === null ? <Missing /> : amount(input[each])}</td>
      ))}
      <td>
        <strong>{words(input.kind)}</strong>
        <br />
        <span className="muted-small">{inputProvenance(input)}</span>
        {source?.type === "assertion" && (
          <>
            <blockquote className="quote">{source.quote}</blockquote>
            <Link href={routes.span(source.source_version_id, source.assertion_id)}>
              Open the source span of {words(input.name).toLowerCase()}
            </Link>
          </>
        )}
        {source?.type === "xbrl_observation" && (
          <>
            <br />
            <Link href={routes.version(source.observation.source_version_id)}>
              Open the XBRL source of {words(input.name).toLowerCase()}
            </Link>{" "}
            <span className="muted-small">
              available <Timestamp value={source.observation.available_at} />
            </span>
          </>
        )}
      </td>
    </tr>
  );
}

// --- Research Snapshots ------------------------------------------------------------

const loadSnapshots = async (key: string) => (await api.snapshots(key.split("#")[0] ?? "")).items;

/** The Research Snapshots frozen at each publication, each verified when it is read. */
export function Snapshots({ hypothesisId, revision }: { hypothesisId: string; revision: number }) {
  const snapshots = useApi(`${hypothesisId}#${revision}`, loadSnapshots);
  return (
    <section aria-labelledby="snapshots">
      <h2 id="snapshots">Research Snapshots</h2>
      <p>
        What each published version was built from, frozen when it was published. Each read
        re-hashes the archived snapshot against its recorded SHA-256.
      </p>
      <Load loaded={snapshots} what="the Research Snapshots">
        {(snapshots) =>
          snapshots.length === 0 ? (
            <p>No version has been published: there is no snapshot yet.</p>
          ) : (
            snapshots.map((record) => <SnapshotPanel key={record.id} record={record} />)
          )
        }
      </Load>
    </section>
  );
}

type Verified = { ok: true; snapshot: ResearchSnapshot } | { ok: false; message: string };

const verify = async (id: string): Promise<Verified> => {
  try {
    return { ok: true, snapshot: await api.snapshot(id) };
  } catch (error) {
    if (error instanceof ApiError && error.code === "snapshot_integrity_failed") {
      return { ok: false, message: error.message };
    }
    throw error;
  }
};

function SnapshotPanel({ record }: { record: SnapshotRecord }) {
  const verified = useApi(record.id, verify);
  const name = `Snapshot of version ${record.hypothesis_version}`;
  return (
    <table>
      <caption>{name}</caption>
      <tbody>
        <Row name="Integrity">
          <Load loaded={verified} what="the snapshot">
            {(verified) =>
              verified.ok ? (
                <>
                  <strong>Verified</strong>: the archived snapshot hashes to its recorded SHA-256.
                </>
              ) : (
                <strong role="alert">Integrity check failed: {verified.message}</strong>
              )
            }
          </Load>
        </Row>
        <Row name="SHA-256">
          <Code>{record.sha256}</Code>
        </Row>
        <Row name="Archived at">
          <Code>{record.object_uri}</Code> ({groupDigits(String(record.byte_size))} bytes)
        </Row>
        <Row name="Evidence cutoff">
          <Timestamp value={record.as_of} />
        </Row>
        <Row name="Frozen">
          by {record.created_by} at <Timestamp value={record.created_at} />
        </Row>
        <Row name="Contents">
          {verified.state === "ready" && verified.data.ok ? (
            <SnapshotContents snapshot={verified.data.snapshot} />
          ) : (
            <Missing>shown once verified</Missing>
          )}
        </Row>
      </tbody>
    </table>
  );
}

function SnapshotContents({ snapshot }: { snapshot: ResearchSnapshot }) {
  const summary = summarizeSnapshot(snapshot.content);
  const counted: [number, string, string][] = [
    [summary.sourceVersions, "Source Version", "Source Versions"],
    [summary.assertions, "Assertion", "Assertions"],
    [summary.relationships, "Relationship", "Relationships"],
    [summary.scenarios, "scenario", "scenarios"],
    [summary.observations, "XBRL observation", "XBRL observations"],
    [summary.runs, "run", "runs"],
    [summary.roleCalls, "role call", "role calls"],
  ];
  return (
    <>
      {counted.map(([n, one, many]) => `${n} ${n === 1 ? one : many}`).join(", ")};{" "}
      {summary.memoryUsed ? "Hindsight Memory reached the run" : "no Hindsight Memory used"}.
      {summary.question && (
        <>
          <br />
          <span className="muted-small">Question: {summary.question}</span>
        </>
      )}
    </>
  );
}
