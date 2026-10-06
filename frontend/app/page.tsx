"use client";

import Link from "next/link";

import { Load } from "../components/ui";
import { api } from "../lib/api/client";
import { dayOf, researchIndex, runsLabel, statusWords } from "../lib/research-index";
import { routes } from "../lib/routes";
import { useApi } from "../lib/use-api";

/** Every call at once: the list is light, and a theme with no run still shows. */
async function loadIndex() {
  const [themes, runs, companies] = await Promise.all([
    api.themes(),
    api.investigations(),
    api.companies(),
  ]);
  return { themes, runs: runs.items, companies: companies.items };
}

export default function ResearchPage() {
  const loaded = useApi("index", loadIndex);
  return (
    <div className="reader">
      <h1 className="reader-headline">Research</h1>
      <Load loaded={loaded} what="research">
        {(data) => <Index data={data} />}
      </Load>
    </div>
  );
}

function Index({ data }: { data: Awaited<ReturnType<typeof loadIndex>> }) {
  const names = new Map(data.companies.map((c) => [c.id, c.display_name]));
  const themes = new Map(data.themes.map((t) => [t.id, t]));
  const index = researchIndex(
    data.runs,
    data.themes.map((t) => t.id),
  );
  if (index.length === 0) return <p>No research yet.</p>;
  return (
    <>
      {index.map(({ theme, rows }) => (
        <section key={theme} aria-labelledby={`theme-${theme}`}>
          <h2 className="reader-label" id={`theme-${theme}`}>
            {themes.get(theme)?.title ?? theme}
          </h2>
          {themes.get(theme)?.description ? (
            <p className="muted">{themes.get(theme)?.description}</p>
          ) : null}
          {rows.length === 0 ? (
            <p className="muted">No research questions yet.</p>
          ) : (
            <ul className="reader-rows">
              {rows.map((row) => (
                <li key={row.latest.id}>
                  <div className="reader-row">
                    <div>
                      <Link className="reader-row-title" href={routes.investigation(row.latest.id)}>
                        {row.question}
                      </Link>
                      <div className="reader-row-sub">
                        {dayOf(row.latest.created_at)}
                        {runsLabel(row.runs) ? ` · ${runsLabel(row.runs)}` : ""}
                        {row.latest.seed_company_ids.length > 0 ? " · " : ""}
                        {row.latest.seed_company_ids.map((id, i) => (
                          <span key={id}>
                            {i > 0 ? ", " : ""}
                            <Link href={routes.company(id)}>{names.get(id) ?? "Company"}</Link>
                          </span>
                        ))}
                      </div>
                    </div>
                    <span
                      className={`reader-pill ${
                        row.latest.stop_reason === "answered" ? "reader-supported" : "reader-review"
                      }`}
                    >
                      {statusWords(row.latest)}
                    </span>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      ))}
    </>
  );
}
