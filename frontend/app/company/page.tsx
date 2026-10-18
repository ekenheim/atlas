"use client";

import Link from "next/link";
import { Suspense, useState } from "react";

import { DueList } from "../../components/due-list";
import { EdgeList } from "../../components/edge-list";
import { QuestionRows } from "../../components/question-rows";
import { Quote } from "../../components/quote";
import { RecordsFold } from "../../components/records-fold";
import { StepRows, stepRowsOf } from "../../components/step-rows";
import { Code, Load, Missing, Row, Timestamp } from "../../components/ui";
import { VersionBar, VersionLegend } from "../../components/version-bar";
import {
  api,
  type CompanyDossier,
  type FinancialFigure,
  type SourceDocument,
} from "../../lib/api/client";
import { companyFindings, firstQuote, type Finding as FindingRow } from "../../lib/company-findings";
import type { Exposure } from "../../lib/beliefs";
import { argumentOf } from "../../lib/argument";
import { SOURCE_ROWS, filterByType, typeChips, typeName } from "../../lib/company-sources";
import { evidenceDay, groupDigits, period } from "../../lib/format";
import { companyRows, formatCount, plural } from "../../lib/memory";
import { COMPANY_LAYERS } from "../../lib/relationships";
import { companyQuestions, hypothesisByInvestigation } from "../../lib/research-index";
import { routes } from "../../lib/routes";
import { useApi, useIdParam } from "../../lib/use-api";

/** The runs, and the Hypotheses a question's thesis comes from; a failed Hypotheses call costs only the theses. */
async function loadResearch() {
  const [runs, hypotheses] = await Promise.all([
    api.investigations(),
    api.hypotheses().catch(() => ({ items: [] })),
  ]);
  return { runs: runs.items, hypotheses: hypothesisByInvestigation(hypotheses.items) };
}
const loadHealth = () => api.memoryHealth();

export default function CompanyPage() {
  return (
    <Suspense>
      <Company />
    </Suspense>
  );
}

function Company() {
  const id = useIdParam();
  const dossier = useApi(id, api.dossier);
  return (
    <>
      <Load loaded={dossier} what="the company dossier">
        {(dossier) => <Dossier dossier={dossier} />}
      </Load>
    </>
  );
}

function Dossier({ dossier }: { dossier: CompanyDossier }) {
  const { company } = dossier;
  const listing = company.securities[0];
  const kicker = [
    company.layer ? COMPANY_LAYERS[company.layer] : null,
    listing?.ticker ?? null,
  ].filter((part) => part !== null);
  const facts = [company.country, listing?.exchange_mic].filter((part) => part);
  const findings = companyFindings(dossier.relationships_out, dossier.relationships_in);
  const edgeCount = dossier.relationships_out.length + dossier.relationships_in.length;
  const theme = dossier.themes[0];
  const now = new Date();
  return (
    <div className="reader company-page">
      {theme ? (
        <p className="crumbs">
          <Link href={routes.theme(theme.id)}>{theme.title}</Link>
        </p>
      ) : null}
      <header>
        {kicker.length > 0 && <div className="reader-kicker">{kicker.join(" · ")}</div>}
        <h1 className="reader-headline">{company.display_name}</h1>
        {facts.length > 0 && <p className="reader-meta">{facts.join(" · ")}</p>}
      </header>

      <section aria-labelledby="believed">
        <h2 className="reader-label" id="believed">
          What Atlas believes
        </h2>
        {dossier.beliefs.length === 0 ? (
          <p className="muted">Nothing believed about {company.display_name} yet.</p>
        ) : (
          GROUPS.map((group) => {
            const mine = dossier.beliefs.filter((each) => each.exposure === group.exposure);
            if (mine.length === 0) return null;
            return (
              <section key={group.exposure} aria-label={`${group.title} (${mine.length})`} className="exposure-group">
                <h3 className="exposure-title">
                  {group.title} ({mine.length})
                </h3>
                <StepRows steps={stepRowsOf(argumentOf(mine), now).filter((row) => row.beliefs.length > 0)} />
              </section>
            );
          })
        )}
      </section>

      <OnThisCompany companyId={company.id} now={now} />
      <LatestDocuments sources={dossier.sources} total={dossier.source_total} />

      <RecordsFold counts={`${plural(edgeCount, "relationship")}, ${plural(dossier.source_total, "source")}`}>
        <InTheResearch companyId={company.id} />
        <section aria-labelledby="found">
          <h2 id="found">What Atlas found</h2>
          {findings.groups.length === 0 ? (
            <p className="muted">Nothing found about {company.display_name} yet.</p>
          ) : (
            <>
              <p className="muted-small">
                {findings.tally.approved} approved · {findings.tally.machine_reviewed} machine-checked only ·{" "}
                {findings.tally.needs_human_review} not yet verified
              </p>
              {findings.groups.map((group) => (
                <div key={group.key} className="finding-group">
                  <h3>{group.title}</h3>
                  <ul className="reader-rows">
                    {group.findings.map((finding) => (
                      <Finding key={finding.id} finding={finding} />
                    ))}
                  </ul>
                </div>
              ))}
            </>
          )}
        </section>
        <div>
          <MemoryStrip companyId={company.id} />

          <h3>Identity</h3>
          <table>
            <caption>Identity</caption>
            <tbody>
              <Row name="Legal name">{company.legal_name}</Row>
              <Row name="Role">
                {company.role === "counterparty"
                  ? "Counterparty: known only as the other end of Relationships, not researched"
                  : "Researched"}
              </Row>
              <Row name="CIK">{company.cik ? <Code>{company.cik}</Code> : <Missing />}</Row>
              <Row name="LEI">{company.lei ? <Code>{company.lei}</Code> : <Missing />}</Row>
              <Row name="Country">{company.country ?? <Missing />}</Row>
              <Row name="Website">
                {company.website ? (
                  <a href={company.website} rel="noreferrer noopener">
                    {company.website}
                  </a>
                ) : (
                  <Missing />
                )}
              </Row>
              <Row name="Layer">{company.layer ? COMPANY_LAYERS[company.layer] : <Missing />}</Row>
              <Row name="Source path">
                {company.source_path ? <Code>{company.source_path}</Code> : <Missing />}
              </Row>
              <Row name="Themes">
                {dossier.themes.length === 0 ? (
                  <Missing />
                ) : (
                  dossier.themes.map((theme, index) => (
                    <span key={theme.id}>
                      {index > 0 && ", "}
                      <Link href={routes.theme(theme.id)}>{theme.title}</Link>
                    </span>
                  ))
                )}
              </Row>
            </tbody>
          </table>

          <h3>Listings</h3>
          {company.securities.length === 0 ? (
            <p>No listings recorded.</p>
          ) : (
            <table>
              <caption>Listings (securities)</caption>
              <thead>
                <tr>
                  <th scope="col">Ticker</th>
                  <th scope="col">Exchange (MIC)</th>
                  <th scope="col">Instrument</th>
                  <th scope="col">Currency</th>
                  <th scope="col">ISIN</th>
                  <th scope="col">FIGI</th>
                  <th scope="col">Review state</th>
                  <th scope="col">Valid</th>
                </tr>
              </thead>
              <tbody>
                {company.securities.map((security) => (
                  <tr key={security.id}>
                    <th scope="row">{security.ticker}</th>
                    <td>
                      <Code>{security.exchange_mic}</Code>
                      {security.segment_mic && (
                        <>
                          {" "}
                          (segment <Code>{security.segment_mic}</Code>)
                        </>
                      )}
                    </td>
                    <td>{security.instrument_type}</td>
                    <td>{security.currency}</td>
                    <td>{security.isin ? <Code>{security.isin}</Code> : <Missing />}</td>
                    <td>{security.figi ? <Code>{security.figi}</Code> : <Missing />}</td>
                    <td>{security.review_state}</td>
                    <td>
                      from {security.valid_from}
                      {security.valid_to && <> to {security.valid_to}</>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <h3>Pending identity reviews</h3>
          {dossier.pending_identity_reviews.length === 0 ? (
            <p>No identity mapping awaits review.</p>
          ) : (
            <table>
              <caption>Identity mappings awaiting the owner</caption>
              <thead>
                <tr>
                  <th scope="col">Kind</th>
                  <th scope="col">Value</th>
                  <th scope="col">Tier</th>
                  <th scope="col">Source</th>
                  <th scope="col">Observed</th>
                  <th scope="col">Reasons</th>
                </tr>
              </thead>
              <tbody>
                {dossier.pending_identity_reviews.map((mapping) => (
                  <tr key={mapping.id}>
                    <th scope="row">{mapping.kind}</th>
                    <td>
                      <Code>{mapping.value}</Code>
                    </td>
                    <td>{mapping.tier}</td>
                    <td>
                      <a href={mapping.source_url} rel="noreferrer noopener">
                        {mapping.source}
                      </a>
                    </td>
                    <td>
                      <Timestamp value={mapping.observed_at} />
                    </td>
                    <td>
                      {mapping.reasons.length === 0 ? <Missing /> : mapping.reasons.join(", ")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <h3>Relationships</h3>
          {dossier.relationships_out.length === 0 ? (
            <p>No Relationships with {company.display_name} as subject.</p>
          ) : (
            <EdgeList
              edges={dossier.relationships_out}
              caption={`Relationships out (${company.display_name} as subject)`}
            />
          )}
          {dossier.relationships_in.length === 0 ? (
            <p>No Relationships with {company.display_name} as object.</p>
          ) : (
            <EdgeList
              edges={dossier.relationships_in}
              caption={`Relationships in (${company.display_name} as object)`}
            />
          )}

          <h3>Financials</h3>
          <Financials figures={dossier.financials.figures} asOf={dossier.financials.as_of} />

          <SourceDocuments sources={dossier.sources} total={dossier.source_total} />

          <h3>Fetch-gate blocks</h3>
          {dossier.fetch_gate_blocks.length === 0 ? (
            <p>No request for this company was blocked by the fetch gate.</p>
          ) : (
            <table>
              <caption>Requests the fetch gate blocked ({dossier.fetch_gate_block_total})</caption>
              <thead>
                <tr>
                  <th scope="col">Decided</th>
                  <th scope="col">Provider</th>
                  <th scope="col">URL</th>
                  <th scope="col">Blocked by</th>
                  <th scope="col">Reason</th>
                </tr>
              </thead>
              <tbody>
                {dossier.fetch_gate_blocks.map((block) => (
                  <tr key={block.id}>
                    <td>
                      <Timestamp value={block.decided_at} />
                    </td>
                    <td>{block.provider}</td>
                    <td>
                      <Code>{block.url}</Code>
                    </td>
                    <td>{block.blocked_by}</td>
                    <td>{block.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </RecordsFold>
    </div>
  );
}

const GROUPS: { exposure: Exposure; title: string }[] = [
  { exposure: "holder", title: "Holds the position" },
  { exposure: "dependent", title: "Depends on it" },
  { exposure: "supplier", title: "Supplies" },
];

const loadCalls = async () => (await api.allCalls()).items;
const loadPredictions = async () => (await api.predictions("open")).items;
const loadLeads = async () =>
  (await api.calendarLeads(new Date().toISOString().slice(0, 10))).items;

/** Its calls and open predictions, and when it next reports (the calendar, when it has one). */
function OnThisCompany({ companyId, now }: { companyId: string; now: Date }) {
  const calls = useApi("calls", loadCalls);
  const predictions = useApi("predictions", loadPredictions);
  const leads = useApi("leads", loadLeads);
  if (calls.state !== "ready" || predictions.state !== "ready") return null;
  const mine = calls.data.filter((call) => call.companies.some((each) => each.company_id === companyId));
  const bets = predictions.data.filter((each) => each.company_id === companyId);
  const reports =
    leads.state === "ready" ? leads.data.filter((lead) => lead.calendar?.company_id === companyId) : [];
  if (mine.length === 0 && bets.length === 0 && reports.length === 0) return null;
  return (
    <section aria-labelledby="on-company">
      <h2 className="reader-label" id="on-company">
        On this company
      </h2>
      <DueList calls={mine} predictions={bets} leads={reports} limit={4} now={now} label="Due on this company" />
    </section>
  );
}

/** The newest documents, five of them and then all the page holds. */
function LatestDocuments({ sources }: { sources: SourceDocument[]; total?: number }) {
  const [all, setAll] = useState(false);
  if (sources.length === 0) return null;
  const newest = [...sources].sort((a, b) => b.first_seen_at.localeCompare(a.first_seen_at));
  const shown = all ? newest : newest.slice(0, 5);
  return (
    <section aria-labelledby="latest">
      <h2 className="reader-label" id="latest">
        Latest documents
      </h2>
      <ul className="reader-rows" aria-label="Latest documents">
        {shown.map((document) => (
          <li className="reader-row" key={document.id}>
            <div>
              <div className="row-title one-line">
                <Link href={routes.source(document.id)} title={document.title}>
                  {document.title}
                </Link>
              </div>
              <div className="reader-row-sub">
                {[typeName(document.source_type), document.form_type, evidenceDay(document.first_seen_at)]
                  .filter(Boolean)
                  .join(" · ")}
              </div>
            </div>
          </li>
        ))}
      </ul>
      {!all && newest.length > 5 ? (
        <button type="button" className="show-all show-all-flush" onClick={() => setAll(true)}>
          All {newest.length}
        </button>
      ) : null}
    </section>
  );
}

/** The questions this company seeded: hidden until they load, and when there are none. */
function InTheResearch({ companyId }: { companyId: string }) {
  const loaded = useApi("company-research", loadResearch);
  if (loaded.state === "loading") {
    return <p className="muted">Loading the investigations…</p>;
  }
  if (loaded.state !== "ready") return null;
  const rows = companyQuestions(loaded.data.runs, companyId);
  if (rows.length === 0) return null;
  return (
    <section aria-labelledby="research">
      <h2 id="research">Investigations</h2>
      <QuestionRows rows={rows} hypotheses={loaded.data.hypotheses} />
    </section>
  );
}

/** One finding: a sentence and its review state; its first quote is fetched on opening. */
function Finding({ finding }: { finding: FindingRow }) {
  const [open, setOpen] = useState(false);
  const detail = useApi(open ? finding.id : null, api.relationship);
  const first = detail.state === "ready" ? firstQuote(detail.data.evidence) : null;
  return (
    <li>
      <button
        type="button"
        className="finding-line"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        <span>{finding.sentence}</span>
        <span className={`reader-pill ${finding.tone}`}>{finding.review}</span>
      </button>
      {open && (
        <div className="finding-quote">
          {detail.state === "loading" && <p className="muted">Loading the quote…</p>}
          {detail.state === "error" && (
            <p role="alert">Could not load the quote: {detail.message}</p>
          )}
          {detail.state === "ready" && !first && <p className="muted">No quote recorded.</p>}
          {first && (
            <Quote
              quote={first.assertion.quote}
              company={first.publisher}
              document={first.source_title}
              href={routes.span(first.assertion.source_version_id, first.assertion.id)}
              note={finding.evidenceCount > 1 ? `${finding.evidenceCount} quotes in all` : undefined}
            />
          )}
        </div>
      )}
    </li>
  );
}

/**
 * The company's row from the whole bank's memory health, so "thin" is measured against the
 * others; its own request, shown when it lands.
 */
function MemoryStrip({ companyId }: { companyId: string }) {
  const health = useApi("memory-health", loadHealth);
  if (health.state === "loading") return <p className="muted">Loading memory…</p>;
  if (health.state === "error") {
    return <p className="muted">Memory unavailable: {health.message}</p>;
  }
  const row = companyRows(health.data).find((r) => r.key === companyId);
  if (!row) return <p className="muted">Not in the research bank.</p>;
  return (
    <>
      <section className="mem-strip" aria-label="Memory">
        <VersionBar counts={row.versions} />
        <span>
          {formatCount(row.versions.in_memory)} of {formatCount(row.versions.total)} versions in
          memory
        </span>
        <span>{formatCount(row.sections.fact_count)} facts</span>
        {row.versions.retired > 0 && <span>{formatCount(row.versions.retired)} retired</span>}
        {row.versions.all_skipped > 0 && <span>{formatCount(row.versions.all_skipped)} skipped</span>}
        <span className={`mem-tag ${row.status.severity}`}>{row.status.label}</span>
        <Link href={routes.memory}>Memory</Link>
      </section>
      <VersionLegend />
    </>
  );
}

/** Source Documents with type chips: 25 rows, then "Show all". */
function SourceDocuments({ sources, total }: { sources: SourceDocument[]; total: number }) {
  const [type, setType] = useState<string | null>(null);
  const [all, setAll] = useState(false);
  const chosen = filterByType(sources, type);
  const shown = all ? chosen : chosen.slice(0, SOURCE_ROWS);
  return (
    <>
      <h3>Source Documents</h3>
      {sources.length === 0 ? (
        <p>No Source Documents collected yet.</p>
      ) : (
        <>
          <div className="chips" role="group" aria-label="Source type">
            {typeChips(sources).map((chip) => (
              <button
                key={chip.type ?? "all"}
                type="button"
                aria-pressed={type === chip.type}
                onClick={() => {
                  setType(chip.type);
                  setAll(false);
                }}
              >
                {chip.name} <span>{chip.count}</span>
              </button>
            ))}
          </div>
          <table>
            <caption>
              Source Documents ({total}
              {total > sources.length && `, showing the first ${sources.length}`})
            </caption>
            <thead>
              <tr>
                <th scope="col">Title</th>
                <th scope="col">Type</th>
                <th scope="col">Form</th>
                <th scope="col">Accession</th>
                <th scope="col">First seen</th>
                <th scope="col">Versions</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((sourceDocument) => (
                <tr key={sourceDocument.id}>
                  <td>
                    <Link href={routes.source(sourceDocument.id)}>{sourceDocument.title}</Link>
                  </td>
                  <td>{typeName(sourceDocument.source_type)}</td>
                  <td>{sourceDocument.form_type ?? <Missing />}</td>
                  <td>
                    {sourceDocument.accession ? (
                      <Code>{sourceDocument.accession}</Code>
                    ) : (
                      <Missing />
                    )}
                  </td>
                  <td>
                    <Timestamp value={sourceDocument.first_seen_at} />
                  </td>
                  <td>{sourceDocument.version_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {chosen.length > shown.length && (
            <button type="button" onClick={() => setAll(true)}>
              Show all {chosen.length}
            </button>
          )}
        </>
      )}
    </>
  );
}

/** Each figure with its period, unit and currency, FX basis, availability and filings. */
function Financials({ figures, asOf }: { figures: FinancialFigure[]; asOf: string }) {
  if (figures.length === 0) {
    return (
      <p>
        No financial figures available as of <Timestamp value={asOf} />.
      </p>
    );
  }
  return (
    <table>
      <caption>
        Financials as of <Timestamp value={asOf} /> (XBRL, each value from the latest filing
        available then)
      </caption>
      <thead>
        <tr>
          <th scope="col">Metric</th>
          <th scope="col">Period</th>
          <th scope="col">Value</th>
          <th scope="col">Unit</th>
          <th scope="col">FX basis</th>
          <th scope="col">Available at</th>
          <th scope="col">Source</th>
          <th scope="col">Flags</th>
        </tr>
      </thead>
      <tbody>
        {figures.map((figure) => (
          <tr
            key={`${figure.metric}-${figure.unit}-${figure.period_start ?? ""}-${figure.period_end}`}
          >
            <th scope="row">{figure.label}</th>
            <td>
              {period(figure.period_start, figure.period_end)}
              <br />
              <span className="muted-small">{figure.period_type.replace("_", " ")}</span>
            </td>
            <td>{groupDigits(figure.value)}</td>
            <td>{figure.unit}</td>
            <td>
              {figure.fx_basis ? (
                `${figure.fx_basis.from_currency} at ${figure.fx_basis.rate_date} (${figure.fx_basis.rate_source})`
              ) : (
                <Missing>as filed</Missing>
              )}
            </td>
            <td>
              <Timestamp value={figure.available_at} />
            </td>
            <td>
              {figure.derived && <>derived from </>}
              {figure.sources.map((source, index) => (
                <span key={source.id}>
                  {index > 0 && " and "}
                  {source.form} <Code>{source.accession}</Code> (<Code>{source.concept}</Code>)
                </span>
              ))}
            </td>
            <td>{figure.flags.length === 0 ? <Missing /> : figure.flags.join(", ")}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
