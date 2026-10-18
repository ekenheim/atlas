"use client";

// One Issue: what is still to find out, and what it produced. Built from the Issue itself
// (`GET /issues/{id}`: its parent, its products) and the list for the Issues under it.
import Link from "next/link";
import { Suspense } from "react";

import { Quote } from "../../components/quote";
import { RecordsFold } from "../../components/records-fold";
import { Status } from "../../components/status";
import { BeliefRow, beliefRowOf } from "../../components/step-rows";
import { Load, Row, Timestamp } from "../../components/ui";
import { api, type Company, type IssueDetail, type IssueEdge, type IssueProduct } from "../../lib/api/client";
import { activity } from "../../lib/format";
import { KINDS, STATUSES, statusWord, subQuestionsText } from "../../lib/issues";
import { routes } from "../../lib/routes";
import { useApi, useIdParam } from "../../lib/use-api";

export default function IssuePage() {
  return (
    <Suspense>
      <IssueDetail />
    </Suspense>
  );
}

const loadCompanies = () => api.companies();

function IssueDetail() {
  const id = useIdParam();
  const issue = useApi(id, api.issue);
  return (
    <>
      <p className="crumbs">
        <Link href={routes.issues()}>Issues</Link>
      </p>
      <Load loaded={issue} what="the Issue">
        {(issue) => <Body issue={issue} />}
      </Load>
    </>
  );
}

function Body({ issue }: { issue: IssueDetail }) {
  const companies = useApi("companies", loadCompanies);
  const names = new Map<string, string>(
    companies.state === "ready"
      ? companies.data.items.map((company: Company) => [company.id, company.display_name])
      : [],
  );
  const named = issue.company_ids.map((id) => names.get(id) ?? "").filter(Boolean);
  const parents = issue.edges.filter((edge) => edge.direction === "parent");
  const children = issue.edges.filter((edge) => edge.direction === "child");
  const meta = [KINDS[issue.kind], named.join(", "), subQuestionsText(issue)].filter(
    (part) => part !== "",
  );
  return (
    <div className="reader">
      <header>
        <p className="reader-meta">
          <Status word={statusWord(issue)} />
          <span>{meta.join(" · ")}</span>
          <span>opened {activity(issue.created_at)}</span>
        </p>
        <h1 className="reader-headline measure">{issue.title}</h1>
        {issue.body ? <p className="measure issue-body">{issue.body}</p> : null}
      </header>

      {parents.length > 0 ? (
        <section aria-labelledby="under">
          <h2 className="reader-label" id="under">
            Under
          </h2>
          <ul className="reader-rows" aria-label="Under">
            {parents.map((edge) => (
              <EdgeRow key={edge.issue_id} edge={edge} />
            ))}
          </ul>
        </section>
      ) : null}

      {children.length > 0 ? (
        <section aria-labelledby="sub">
          <h2 className="reader-label" id="sub">
            Sub-questions
          </h2>
          <ul className="reader-rows" aria-label="Sub-questions">
            {children.map((edge) => (
              <EdgeRow key={edge.issue_id} edge={edge} />
            ))}
          </ul>
        </section>
      ) : null}

      <section aria-labelledby="produced">
        <h2 className="reader-label" id="produced">
          What it produced
        </h2>
        {issue.products.length === 0 ? (
          <p className="muted">Nothing yet.</p>
        ) : (
          issue.products.map((product) => (
            <Produced key={`${product.belief_id ?? ""}${product.fact_id ?? ""}`} product={product} />
          ))
        )}
      </section>

      <RecordsFold>
        <table>
          <caption>The Issue</caption>
          <tbody>
            <Row name="Producing session">
              {issue.produced_by ? (
                <Link href={routes.session(issue.produced_by)}>The session that opened it</Link>
              ) : (
                <span className="muted">none</span>
              )}
            </Row>
            <Row name="Opened">
              <Timestamp value={issue.created_at} mode="exact" />
            </Row>
            <Row name="Closed">
              <Timestamp value={issue.closed_at} mode="exact" />
            </Row>
            <Row name="By">{issue.created_by}</Row>
          </tbody>
        </table>
      </RecordsFold>
    </div>
  );
}

/** A Fact it produced is a quote; a Belief is a row. Each is read when the page shows it. */
function Produced({ product }: { product: IssueProduct }) {
  if (product.belief_id) return <ProducedBelief id={product.belief_id} />;
  if (product.fact_id) return <ProducedFact id={product.fact_id} />;
  return null;
}

function ProducedBelief({ id }: { id: string }) {
  const belief = useApi(id, api.belief);
  if (belief.state !== "ready") return <p className="muted">A Belief it produced…</p>;
  return (
    <ul className="reader-rows">
      <BeliefRow belief={beliefRowOf(belief.data)} />
    </ul>
  );
}

function ProducedFact({ id }: { id: string }) {
  const fact = useApi(id, api.fact);
  if (fact.state !== "ready") return <p className="muted">A Fact it produced…</p>;
  const { assertion } = fact.data;
  return (
    <Quote
      statement={fact.data.statement}
      quote={assertion.quote}
      href={routes.span(assertion.source_version_id, assertion.id)}
    />
  );
}

/** An Issue it narrows or waits on, or that narrows it: a row that opens that Issue. */
function EdgeRow({ edge }: { edge: IssueEdge }) {
  return (
    <li className="reader-row">
      <div>
        <div className="row-title">
          <Link href={routes.issue(edge.issue_id)}>{edge.title}</Link>
        </div>
        <div className="reader-row-sub">
          {STATUSES[edge.status]} · {edge.kind === "requires" ? "needed first" : "narrows"} ·{" "}
          {activity(edge.created_at)}
        </div>
      </div>
    </li>
  );
}
