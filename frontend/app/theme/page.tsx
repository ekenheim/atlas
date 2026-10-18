"use client";

// One theme: what Atlas thinks about it and how sure it is, what changed, what is due, and the
// drill to a Belief and its quote. Everything raw (edges, Candidates, the per-layer tables,
// Hypotheses and their drafts) is in the Records, which render only when opened.
import Link from "next/link";
import { Suspense, useState } from "react";

import { ArgumentStrip } from "../../components/argument-strip";
import { DueList } from "../../components/due-list";
import { EdgeList } from "../../components/edge-list";
import { RecordsFold } from "../../components/records-fold";
import { StepRows, stepRowsOf } from "../../components/step-rows";
import { Status, ThesisCheck } from "../../components/status";
import { ChangedList, ThemeHypotheses } from "../../components/theme-feed";
import { Code, Load, Missing, Row, Timestamp } from "../../components/ui";
import {
  api,
  type Bottlenecks,
  type Candidate,
  type ThemeCompany,
  type ThemeMap,
} from "../../lib/api/client";
import { argumentOf, weakestText } from "../../lib/argument";
import { COMPANY_LAYERS } from "../../lib/relationships";
import { routes } from "../../lib/routes";
import { readMark } from "../../lib/seen";
import { layeredEdges, layerlessByCompany } from "../../lib/themes";
import { buildCard, startingStatus, themeBeliefs } from "../../lib/today";
import { useApi, useIdParam } from "../../lib/use-api";

export default function ThemePage() {
  return (
    <Suspense>
      <Theme />
    </Suspense>
  );
}

const GAPS: Record<ThemeCompany["gaps"][number], string> = {
  not_seeded: "not seeded",
  no_sources: "no sources",
};

const loadHypotheses = async () => (await api.hypotheses()).items;
const loadCalls = async (theme: string) => (await api.calls(theme)).items;
const loadPredictions = async () => (await api.predictions("open")).items;
const loadLeads = async () =>
  (await api.calendarLeads(new Date().toISOString().slice(0, 10))).items;

function Theme() {
  const id = useIdParam();
  const map = useApi(id, api.themeMap);
  return (
    <>
      <p className="crumbs">
        <Link href={routes.themes}>Themes</Link>
      </p>
      {map.state === "loading" ? (
        <div aria-busy="true">
          <span className="sk sk-h1" />
          <span className="sk sk-thesis" />
          <span className="sk sk-line" />
          <span className="sk sk-strip" />
        </div>
      ) : (
        <Load loaded={map} what="the theme">
          {(map) => <Body map={map} />}
        </Load>
      )}
    </>
  );
}

function Body({ map }: { map: ThemeMap }) {
  const { theme } = map;
  const hypotheses = useApi("hypotheses", loadHypotheses);
  const calls = useApi(theme.id, loadCalls);
  const predictions = useApi("predictions", loadPredictions);
  const leads = useApi("leads", loadLeads);
  const [mark] = useState<Date | null>(() => readMark());

  const active = themeBeliefs(map.beliefs, theme.id);
  const starting = active.length === 0;
  const steps = argumentOf(map.beliefs);
  const card = buildCard(theme, hypotheses.state === "ready" ? hypotheses.data : [], map.beliefs);
  const now = new Date();
  const callList = calls.state === "ready" ? calls.data : [];

  return (
    <div className="reader theme-page">
      <h1 className="page-title">{theme.title}</h1>

      {starting ? (
        <section className="starting-block" aria-label="Where the theme stands">
          <p className="card-starting">{startingStatus(theme)}</p>
          <p className="muted">Research begins when documents arrive.</p>
        </section>
      ) : (
        <>
          <section className="thesis-block" aria-label="Thesis">
            {card.hypothesis && card.proposition ? (
              <p className="thesis-line measure">
                <Link href={routes.hypothesis(card.hypothesis.id)}>{card.proposition}</Link>
              </p>
            ) : (
              <p className="thesis-line muted">
                {hypotheses.state === "error"
                  ? "The thesis is unavailable."
                  : `No thesis yet · ${card.provenCount} proven ${card.provenCount === 1 ? "Belief" : "Beliefs"}`}
              </p>
            )}
            <p className="thesis-status">
              {card.lifecycle ? <Status word={{ word: card.lifecycle.text, tone: card.lifecycle.tone }} /> : null}
              {card.version ? <span className="thesis-part">v{card.version.version}</span> : null}
              {card.version ? <ThesisCheck version={card.version} /> : null}
              {card.weakest ? <span className="thesis-part">{weakestText(card.weakest)}</span> : null}
              {card.otherDrafts > 0 ? (
                <a className="thesis-part" href="#records">
                  {card.otherDrafts} {card.otherDrafts === 1 ? "draft" : "drafts"}
                </a>
              ) : null}
            </p>
            <ArgumentStrip steps={steps} />
          </section>

          <section aria-labelledby="believed">
            <h2 className="reader-label" id="believed">
              What Atlas believes
            </h2>
            <StepRows steps={stepRowsOf(steps, now)} />
          </section>

          <div className="band band-2">
            <ChangedList theme={theme.id} mark={mark} />
            <section aria-labelledby="due">
              <h2 className="reader-label" id="due">
                Due
              </h2>
              {calls.state === "error" ? (
                <p className="muted">Due unavailable</p>
              ) : calls.state === "loading" || predictions.state === "loading" ? (
                <span className="sk sk-line" />
              ) : (
                <>
                  <DueList
                    calls={callList}
                    predictions={
                      predictions.state === "ready"
                        ? predictions.data.filter((each) => each.theme === theme.id)
                        : []
                    }
                    leads={leads.state === "ready" ? leads.data : undefined}
                    theme={theme.id}
                    limit={4}
                    now={now}
                  />
                  {callList.length > 0 ? (
                    <p className="card-more">
                      <Link href={routes.recordFor(theme.id)}>All {callList.length} calls →</Link>
                    </p>
                  ) : null}
                </>
              )}
            </section>
          </div>
        </>
      )}

      <section aria-labelledby="companies">
        <h2 className="reader-label" id="companies">
          Companies
        </h2>
        <LayerMatrix map={map} />
      </section>

      <RecordsFold
        counts={`${theme.relationship_count} relationships, ${theme.open_candidate_count} candidates`}
      >
        {theme.description ? <p className="measure">{theme.description}</p> : null}
        <ThemeHypotheses theme={theme.id} />

        <h2>Companies in detail</h2>
        {map.layers.map((layer) => (
          <section key={layer.layer} aria-labelledby={`layer-${layer.layer}`}>
            <h3 id={`layer-${layer.layer}`}>{COMPANY_LAYERS[layer.layer]}</h3>
            <p className="muted-small">{layer.covers}</p>
            {layer.companies.length === 0 ? (
              <p>
                <strong>Coverage gap:</strong> no company in this layer.
              </p>
            ) : (
              <Companies caption={`${COMPANY_LAYERS[layer.layer]} companies`} companies={layer.companies} />
            )}
          </section>
        ))}
        {map.unlayered.length > 0 && (
          <section aria-labelledby="layer-none">
            <h3 id="layer-none">No layer set</h3>
            <Companies caption="Companies with no layer" companies={map.unlayered} />
          </section>
        )}

        <h2>Relationships</h2>
        <p className="muted-small">
          Every edge is in the <Link href={routes.relationships()}>edge table</Link>.
        </p>
        {map.counterparties.length > 0 && (
          <p>
            Counterparties (the other end of an edge, not researched):{" "}
            {map.counterparties.map((company, index) => (
              <span key={company.id}>
                {index > 0 && ", "}
                <Link href={routes.company(company.id)}>{company.display_name}</Link>
              </span>
            ))}
          </p>
        )}
        {map.relationships.length === 0 && <p>No Relationships between the theme&apos;s companies yet.</p>}
        {layeredEdges(map.relationships).length > 0 && (
          <EdgeList
            edges={layeredEdges(map.relationships)}
            caption="Relationships between the theme's companies"
          />
        )}
        <LayerlessEdges map={map} />

        <h2>Candidates</h2>
        {map.candidates.length === 0 ? (
          <p>No Candidates proposed for this theme.</p>
        ) : (
          <Candidates candidates={map.candidates} />
        )}

        <h2>Memory&apos;s open gaps (not evidence)</h2>
        <OpenGaps bottlenecks={map.bottlenecks} />

        <table>
          <caption>The theme</caption>
          <tbody>
            <Row name="Companies">
              {theme.company_count}, {theme.companies_without_sources} without sources
            </Row>
            <Row name="Relationships">{theme.relationship_count}</Row>
            <Row name="Candidates awaiting a decision">{theme.open_candidate_count}</Row>
            <Row name="Universe config version">{theme.universe_version}</Row>
          </tbody>
        </table>
      </RecordsFold>
    </div>
  );
}

/** The layers, upstream to downstream, each with its companies; a filled dot is a company with
 * documents in the archive, a hollow one has none, and an empty layer says so. */
function LayerMatrix({ map }: { map: ThemeMap }) {
  return (
    <table aria-label="Companies by layer" className="layer-matrix">
      <tbody>
        {map.layers.map((layer) => (
          <tr key={layer.layer}>
            <th scope="row">{COMPANY_LAYERS[layer.layer]}</th>
            <td>
              {layer.companies.length === 0 ? (
                <span className="status status-warn">no company</span>
              ) : (
                <CompanyLinks companies={layer.companies} />
              )}
            </td>
          </tr>
        ))}
        {map.unlayered.length > 0 && (
          <tr>
            <th scope="row">No layer set</th>
            <td>
              <CompanyLinks companies={map.unlayered} />
            </td>
          </tr>
        )}
      </tbody>
    </table>
  );
}

function CompanyLinks({ companies }: { companies: ThemeCompany[] }) {
  return (
    <ul className="company-links">
      {companies.map((company) => {
        const covered = company.source_count > 0;
        return (
          <li key={company.id}>
            <span
              className={`cov-dot${covered ? " cov-dot-full" : ""}`}
              role="img"
              aria-label={`${company.display_name}, ${covered ? "documents in the archive" : "no documents yet"}`}
            />
            {company.seeded ? (
              <Link href={routes.company(company.id)}>{company.display_name}</Link>
            ) : (
              <span>{company.display_name}</span>
            )}
          </li>
        );
      })}
    </ul>
  );
}

/**
 * The edges with no layer, under each theme company they name (in the map's order: by layer,
 * then the companies with no layer set). They are never placed in a layer of the map.
 */
function LayerlessEdges({ map }: { map: ThemeMap }) {
  const companies = [...map.layers.flatMap((layer) => layer.companies), ...map.unlayered];
  const groups = layerlessByCompany(map.relationships, companies);
  if (groups.length === 0) return null;
  return (
    <>
      <p className="muted-small">
        Edges whose Evidence names no supply-chain layer are listed under their companies.
      </p>
      {groups.map((group) => (
        <EdgeList
          key={group.company.id}
          edges={group.edges}
          caption={`Relationships with no layer: ${group.company.display_name}`}
        />
      ))}
    </>
  );
}

function Companies({ caption, companies }: { caption: string; companies: ThemeCompany[] }) {
  return (
    <table>
      <caption>{caption}</caption>
      <thead>
        <tr>
          <th scope="col">Company</th>
          <th scope="col">Country</th>
          <th scope="col">Source path</th>
          <th scope="col">Sources</th>
          <th scope="col">Relationships</th>
          <th scope="col">Identity reviews</th>
          <th scope="col">Coverage gaps</th>
        </tr>
      </thead>
      <tbody>
        {companies.map((company) => (
          <tr key={company.id}>
            <th scope="row">
              {company.seeded ? (
                <Link href={routes.company(company.id)}>{company.display_name}</Link>
              ) : (
                company.display_name
              )}
            </th>
            <td>{company.country}</td>
            <td>
              <Code>{company.source_path}</Code>
            </td>
            <td>{company.source_count}</td>
            <td>{company.relationship_count}</td>
            <td>
              {company.pending_identity_reviews > 0 ? (
                `${company.pending_identity_reviews} pending`
              ) : (
                <Missing />
              )}
            </td>
            <td>
              {company.gaps.length === 0 ? <Missing /> : company.gaps.map((gap) => GAPS[gap]).join(", ")}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Candidates({ candidates }: { candidates: Candidate[] }) {
  return (
    <table>
      <caption>Candidates (companies outside the universe that leads named)</caption>
      <thead>
        <tr>
          <th scope="col">Name</th>
          <th scope="col">State</th>
          <th scope="col">Resolution tier</th>
          <th scope="col">Identifier</th>
          <th scope="col">Leads</th>
          <th scope="col">Proposed</th>
        </tr>
      </thead>
      <tbody>
        {candidates.map((candidate) => (
          <tr key={candidate.id}>
            <th scope="row">{candidate.name}</th>
            <td>
              {candidate.state}
              {candidate.reject_reason && (
                <>
                  <br />
                  <span className="muted-small">{candidate.reject_reason}</span>
                </>
              )}
            </td>
            <td>{candidate.tier}</td>
            <td>
              <Code>{candidate.identity_key}</Code>
            </td>
            <td>{candidate.leads.length}</td>
            <td>
              <Timestamp value={candidate.created_at} mode="exact" />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function OpenGaps({ bottlenecks }: { bottlenecks: Bottlenecks }) {
  const model = bottlenecks.model;
  if (bottlenecks.status !== "refreshed" || !model) {
    const why = {
      refreshed: "",
      not_refreshed: "Hindsight has not generated the Bottlenecks mental model yet.",
      not_in_bank: "The bank template (with the Bottlenecks mental model) is not applied yet.",
      not_configured: "Hindsight is not configured, so there is no Bottlenecks mental model.",
      unavailable: `Hindsight could not be read: ${bottlenecks.message ?? "unknown error"}.`,
    }[bottlenecks.status];
    return <p>{why}</p>;
  }
  const counts = model.counts;
  return (
    <>
      <p>
        <strong>Generated by Hindsight: Memory, not Evidence.</strong> Refreshed{" "}
        <Timestamp value={model.last_refreshed_at} mode="exact" />. Citations: {counts.resolved ?? 0}{" "}
        resolved, {counts.unverified ?? 0} unverified, {counts.broken ?? 0} broken.
        {model.evidence_missing && <strong> Unsupported: no citation resolves to a source.</strong>}
      </p>
      <blockquote className="quote">{model.content}</blockquote>
      {model.evidence.length > 0 && (
        <>
          <h3>Sources behind resolved citations</h3>
          <ul>
            {model.evidence.map((evidence) => (
              <li key={`${evidence.source_version_id}-${evidence.section_anchor}`}>
                <Link href={routes.version(evidence.source_version_id)}>
                  {evidence.form_type ?? "Source Version"}:{" "}
                  {evidence.section_heading ?? evidence.section_anchor}
                </Link>{" "}
                <span className="muted-small">
                  available <Timestamp value={evidence.available_at} mode="exact" />
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </>
  );
}
