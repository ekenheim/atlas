"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { Status } from "../../components/status";
import { Load } from "../../components/ui";
import { api, type Company, type Issue } from "../../lib/api/client";
import { activity } from "../../lib/format";
import {
  applyFilters,
  filterSearch,
  KINDS,
  nextAction,
  orderIssues,
  parseFilters,
  producedText,
  ROWS_SHOWN,
  STATUSES,
  statusWord,
  subQuestionsText,
  TIER_WORDS,
  tier,
  type IssueFilters,
} from "../../lib/issues";
import { routes } from "../../lib/routes";
import { useApi } from "../../lib/use-api";

export default function IssuesPage() {
  return (
    <Suspense>
      <Issues />
    </Suspense>
  );
}

const loadIssues = () => api.issues();
const loadCompanies = () => api.companies();

function Issues() {
  const router = useRouter();
  const filters = parseFilters(useSearchParams());
  const issues = useApi("issues", loadIssues);
  const companies = useApi("companies", loadCompanies);
  const [all, setAll] = useState(false);
  const names = new Map<string, string>(
    companies.state === "ready"
      ? companies.data.items.map((company: Company) => [company.id, company.display_name])
      : [],
  );
  const show = (next: IssueFilters) => router.replace(routes.issues(filterSearch(next)));

  return (
    <>
      <h1>Issues</h1>
      <Load loaded={issues} what="issues">
        {(page) => {
          const themes = [...new Set(page.items.map((issue) => issue.theme))].sort();
          const shown = orderIssues(applyFilters(page.items, filters));
          const next = nextAction(shown);
          const rows = all ? shown : shown.slice(0, ROWS_SHOWN);
          return (
            <>
              <form aria-label="Filters" className="filters">
                <label>
                  Theme{" "}
                  <select
                    value={filters.theme}
                    onChange={(event) => show({ ...filters, theme: event.target.value })}
                  >
                    <option value="">All</option>
                    {themes.map((theme) => (
                      <option key={theme} value={theme}>
                        {theme}
                      </option>
                    ))}
                  </select>
                </label>{" "}
                <label>
                  Status{" "}
                  <select
                    value={filters.status}
                    onChange={(event) =>
                      show({ ...filters, status: event.target.value as IssueFilters["status"] })
                    }
                  >
                    {Object.entries(STATUSES).map(([status, words]) => (
                      <option key={status} value={status}>
                        {words}
                      </option>
                    ))}
                    <option value="all">All</option>
                  </select>
                </label>
              </form>
              {next ? (
                <section aria-label="Next action">
                  <h2 className="reader-label">Next</h2>
                  <p className="measure">
                    <strong>{next.title}</strong> ({TIER_WORDS[tier(next)]})
                  </p>
                  {next.parent_title ? <p className="muted-small measure">Under: {next.parent_title}</p> : null}
                </section>
              ) : null}
              {shown.length === 0 ? (
                <p>No issues match.</p>
              ) : (
                <>
                  <ul
                    className="reader-rows issue-rows"
                    aria-label="Research frontier, next action first"
                  >
                    {rows.map((issue) => (
                      <IssueRow
                        key={issue.id}
                        issue={issue}
                        names={names}
                        isNext={next?.id === issue.id}
                      />
                    ))}
                  </ul>
                  {!all && shown.length > ROWS_SHOWN ? (
                    <button type="button" className="show-all" onClick={() => setAll(true)}>
                      Show all {shown.length}
                    </button>
                  ) : null}
                </>
              )}
            </>
          );
        }}
      </Load>
    </>
  );
}

function IssueRow({
  issue,
  names,
  isNext,
}: {
  issue: Issue;
  names: Map<string, string>;
  isNext: boolean;
}) {
  const companies = issue.company_ids.map((id) => names.get(id) ?? "").filter(Boolean);
  const produced = producedText(issue);
  const meta = [
    KINDS[issue.kind],
    companies.join(", "),
    subQuestionsText(issue),
    produced,
    activity(issue.created_at),
  ].filter((part) => part !== "");
  return (
    <li className="reader-row issue-row" aria-current={isNext ? "true" : undefined}>
      <div>
        <div className="row-title">
          <Link href={routes.issue(issue.id)}>{issue.title}</Link>
        </div>
        <div className="reader-row-sub row-secondary">
          <Status word={statusWord(issue)} />
          {meta.join(" · ")}
          {issue.produced_by ? (
            <>
              {" · "}
              <Link href={routes.session(issue.produced_by)}>Session</Link>
            </>
          ) : null}
        </div>
        {issue.parent_title ? (
          <div className="reader-row-sub issue-parent">under {issue.parent_title}</div>
        ) : null}
      </div>
    </li>
  );
}
