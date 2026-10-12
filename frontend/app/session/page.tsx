"use client";

import Link from "next/link";
import { Suspense } from "react";

import { Load, Missing, Row, Timestamp } from "../../components/ui";
import { api, type ResearchSession } from "../../lib/api/client";
import { routes } from "../../lib/routes";
import {
  cardView,
  costText,
  factsById,
  KINDS,
  statusLabel,
  usageParts,
  type CardFactRef,
} from "../../lib/sessions";
import { useApi, useIdParam } from "../../lib/use-api";

export default function SessionPage() {
  return (
    <Suspense>
      <Session />
    </Suspense>
  );
}

type SessionFact = ResearchSession["fact_items"][number];

function Session() {
  const id = useIdParam();
  const session = useApi(id, api.session);
  const companies = useApi("companies", api.companies);
  return (
    <>
      <p className="crumbs">
        <Link href={routes.sessions}>Sessions</Link>
      </p>
      <Load loaded={session} what="the session">
        {(session) => (
          <>
            <h1>{session.question}</h1>
            <p>
              {KINDS[session.kind]} session{session.model ? ` on ${session.model}` : ""}, as of{" "}
              {session.as_of.slice(0, 10)}. {session.facts} Facts, {costText(session.usage)}.
              {session.finished_at ? "" : " Still open."}
            </p>
            <Card session={session} />
            <Facts facts={session.fact_items} />
            <Record
              session={session}
              seeds={
                companies.state === "ready"
                  ? new Map(companies.data.items.map((each) => [each.id, each.display_name]))
                  : new Map()
              }
            />
          </>
        )}
      </Load>
    </>
  );
}

function Cited({ refs, facts }: { refs: CardFactRef[]; facts: Map<string, SessionFact> }) {
  return (
    <ul>
      {refs.map((ref, index) => {
        const fact = ref.id ? facts.get(ref.id) : undefined;
        return (
          <li key={`${ref.id ?? "x"}-${index}`}>
            {ref.statement}
            {ref.detail && <span className="muted-small"> [{ref.detail}]</span>}
            {fact && (
              <>
                {" "}
                <Link href={routes.span(fact.assertion.source_version_id, fact.id)}>span</Link>
              </>
            )}
          </li>
        );
      })}
    </ul>
  );
}

function Card({ session }: { session: ResearchSession }) {
  const card = cardView(session.card);
  const facts = factsById(session.fact_items);
  if (card.steps.length === 0 && card.parts.length === 0 && card.openQuestions.length === 0) {
    return (
      <>
        <h2>Card</h2>
        <p>{session.finished_at ? "The session wrote no card." : "No card yet."}</p>
      </>
    );
  }
  return (
    <>
      <h2>Card</h2>
      {card.parts.length > 0 && (
        <ul aria-label="Question parts">
          {card.parts.map((part) => (
            <li key={part.key}>
              {part.text} <span className="muted-small">{statusLabel(part.status)}</span>
            </li>
          ))}
        </ul>
      )}
      {card.steps.map((step) => (
        <section key={step.key} aria-labelledby={`step-${step.key}`}>
          <h3 id={`step-${step.key}`}>
            {step.title} <span className="muted-small">{statusLabel(step.status)}</span>
          </h3>
          {step.statements.length === 0 ? (
            <p>
              <Missing>No statement.</Missing>
            </p>
          ) : (
            step.statements.map((statement, index) => (
              <div key={index}>
                <p>{statement.statement}</p>
                <Cited refs={statement.facts} facts={facts} />
                {statement.counterevidence.length > 0 && (
                  <>
                    <p className="muted-small">Against</p>
                    <Cited refs={statement.counterevidence} facts={facts} />
                  </>
                )}
              </div>
            ))
          )}
          {step.unchecked.length > 0 && (
            <p className="muted-small">Unchecked: {step.unchecked.join("; ")}</p>
          )}
        </section>
      ))}
      {card.openQuestions.length > 0 && (
        <>
          <h3>Open questions</h3>
          <ul>
            {card.openQuestions.map((question) => (
              <li key={question}>{question}</li>
            ))}
          </ul>
        </>
      )}
    </>
  );
}

function Facts({ facts }: { facts: SessionFact[] }) {
  return (
    <>
      <h2>Facts</h2>
      {facts.length === 0 ? (
        <p>None recorded.</p>
      ) : (
        <table>
          <caption>Facts recorded in the session</caption>
          <thead>
            <tr>
              <th scope="col">Fact</th>
              <th scope="col">Step</th>
              <th scope="col">Quote</th>
            </tr>
          </thead>
          <tbody>
            {facts.map((fact) => (
              <tr key={fact.id}>
                <td>{fact.statement}</td>
                <td>{fact.step.split("_").join(" ")}</td>
                <td>
                  <Link href={routes.span(fact.assertion.source_version_id, fact.id)}>
                    {fact.assertion.quote}
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}

function Record({ session, seeds }: { session: ResearchSession; seeds: Map<string, string> }) {
  const parts = usageParts(session.usage);
  return (
    <>
      <h2>Record</h2>
      <table>
        <tbody>
          <Row name="Theme">{session.theme}</Row>
          <Row name="Seeds">
            {session.seed_company_ids.length === 0 ? (
              <Missing />
            ) : (
              session.seed_company_ids.map((id) => seeds.get(id) ?? "a company").join(", ")
            )}
          </Row>
          <Row name="Researcher">{session.actor}</Row>
          <Row name="Started">
            <Timestamp value={session.started_at} />
          </Row>
          <Row name="Finished">
            <Timestamp value={session.finished_at} />
          </Row>
          <Row name="Usage">
            {costText(session.usage)}
            {parts.length > 0 && `; ${parts.join(", ")}`}
          </Row>
          {session.investigation_id && (
            <Row name="Investigation">
              <Link href={routes.investigation(session.investigation_id)}>Open</Link>
            </Row>
          )}
        </tbody>
      </table>
    </>
  );
}
