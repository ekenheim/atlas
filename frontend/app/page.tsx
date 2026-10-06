"use client";

import Link from "next/link";

import { QuestionRows } from "../components/question-rows";
import { Load } from "../components/ui";
import { api } from "../lib/api/client";
import { hypothesisByInvestigation, researchIndex } from "../lib/research-index";
import { routes } from "../lib/routes";
import { useApi } from "../lib/use-api";

/** Every call at once: the list is light, and a theme with no run still shows. */
async function loadIndex() {
  const [themes, runs, hypotheses, companies] = await Promise.all([
    api.themes(),
    api.investigations(),
    api.hypotheses(),
    // Only the names come from here: a failure costs the names, not the page.
    api.companies().catch(() => ({ items: [] })),
  ]);
  return {
    themes,
    runs: runs.items,
    hypotheses: hypothesisByInvestigation(hypotheses.items),
    companies: companies.items,
  };
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
  const { hypotheses } = data;
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
            <QuestionRows
              rows={rows}
              hypotheses={hypotheses}
              seeds={(row) => {
                const ids = row.latest.seed_company_ids.filter((id) => names.has(id));
                return ids.length === 0 ? null : (
                  <>
                    {" · "}
                    {ids.map((id, i) => (
                      <span key={id}>
                        {i > 0 ? ", " : ""}
                        <Link href={routes.company(id)}>{names.get(id)}</Link>
                      </span>
                    ))}
                  </>
                );
              }}
            />
          )}
        </section>
      ))}
    </>
  );
}
