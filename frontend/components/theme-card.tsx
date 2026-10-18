"use client";

// A theme as a card, the same on Today and on Themes (spec §5.1, §5.2): the theme and where its
// thesis stands, the proposition, the weakest step, the argument strip. Today adds what changed
// and what is due (`extra`). A card shows what it has when a read fails, and a skeleton at its
// final height while they load, so nothing shifts.
import Link from "next/link";
import type { ReactNode } from "react";

import type { BeliefSummary, Hypothesis, ThemeSummary } from "../lib/api/client";
import { weakestText } from "../lib/argument";
import { routes } from "../lib/routes";
import { type CardModel, buildCard, coverageLine, startingLine } from "../lib/today";
import type { Loaded } from "../lib/use-api";
import { ArgumentStrip } from "./argument-strip";
import { Status } from "./status";

export function CardSkeleton({ label }: { label: string }) {
  return (
    <article className="theme-card theme-card-skeleton" aria-label={label} aria-busy="true">
      <span className="sk sk-title" />
      <span className="sk sk-thesis" />
      <span className="sk sk-line" />
      <span className="sk sk-strip" />
    </article>
  );
}

export function ThemeCard({
  theme,
  hypotheses,
  beliefs,
  coverage = false,
  unseen = 0,
  extra,
}: {
  theme: ThemeSummary;
  hypotheses: Loaded<Hypothesis[]>;
  beliefs: Loaded<BeliefSummary[]>;
  /** The Themes page's extra line: "12 companies · 11 with documents · 0 layers empty". */
  coverage?: boolean;
  /** Changes newer than the last visit (Today). */
  unseen?: number;
  /** Below the strip: what changed and what is due (Today). */
  extra?: ReactNode;
}) {
  const id = `card-${theme.id}`;
  if (beliefs.state === "loading" || hypotheses.state === "loading") {
    return <CardSkeleton label={theme.title} />;
  }
  const card: CardModel | null =
    beliefs.state === "ready"
      ? buildCard(theme, hypotheses.state === "ready" ? hypotheses.data : [], beliefs.data)
      : null;
  return (
    <article className="theme-card" aria-labelledby={id}>
      <div className="card-line card-head">
        <h2 className="card-title" id={id}>
          <Link href={routes.theme(theme.id)}>{theme.title}</Link>
        </h2>
        <span className="card-status">
          {card?.starting ? (
            <Status word={{ word: "Starting", tone: "muted" }} />
          ) : (
            <>
              {card?.lifecycle ? <Status word={{ word: card.lifecycle.text, tone: card.lifecycle.tone }} /> : null}
              {card?.check ? <Status word={card.check} /> : null}
            </>
          )}
          {unseen > 0 ? (
            <span className="card-new">
              <span className="nav-dot" aria-hidden="true" /> {unseen} new
            </span>
          ) : null}
        </span>
      </div>

      {card === null ? (
        <p className="muted">What Atlas believes is unavailable.</p>
      ) : card.starting ? (
        <p className="card-starting">{startingLine(theme)}</p>
      ) : (
        <>
          <p className="card-thesis measure">
            {card.hypothesis && card.proposition ? (
              <Link href={routes.hypothesis(card.hypothesis.id)}>{card.proposition}</Link>
            ) : hypotheses.state === "error" ? (
              <span className="muted">The thesis is unavailable.</span>
            ) : (
              <span className="muted">
                No thesis yet · {card.provenCount} proven {card.provenCount === 1 ? "Belief" : "Beliefs"}
              </span>
            )}
          </p>
          {card.weakest ? <p className="card-weakest">{weakestText(card.weakest)}</p> : null}
          {card.findings !== null ? (
            <p className="card-findings">
              {card.findings} {card.findings === 1 ? "finding" : "findings"}
            </p>
          ) : (
            <ArgumentStrip steps={card.steps} compact />
          )}
        </>
      )}

      {coverage ? <p className="card-meta">{coverageLine(theme)}</p> : null}
      {extra}
    </article>
  );
}

/** A theme that has no Belief yet but the Watch is on it (`Watching`, with its last watch and
 * board), or one with no company that the Watch has not reached (`Not started`). */
export function WatchCard({
  slug,
  title,
  watching,
  line,
}: {
  slug: string;
  title: string;
  watching: boolean;
  line: string;
}) {
  const id = `card-${slug}`;
  return (
    <article className="theme-card" aria-labelledby={id}>
      <div className="card-line card-head">
        <h2 className="card-title" id={id}>
          <Link href={routes.theme(slug)}>{title}</Link>
        </h2>
        <span className="card-status">
          <Status word={{ word: watching ? "Watching" : "Not started", tone: "muted" }} />
        </span>
      </div>
      <p className="card-starting">{line}</p>
    </article>
  );
}
