"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { Load, Missing } from "../../components/ui";
import { api, type Company, type Issue } from "../../lib/api/client";
import {
  applyFilters,
  filterSearch,
  KINDS,
  nextAction,
  onFrontier,
  orderIssues,
  parseFilters,
  producedText,
  STATUSES,
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
  const names = new Map<string, string>(
    companies.state === "ready"
      ? companies.data.items.map((company: Company) => [company.id, company.display_name])
      : [],
  );
  const show = (next: IssueFilters) => router.replace(routes.issues(filterSearch(next)));

  return (
    <>
      <h1>Issues</h1>
      <p>What is still to find out, the next thing to read first.</p>
      <Load loaded={issues} what="issues">
        {(page) => {
          const themes = [...new Set(page.items.map((issue) => issue.theme))].sort();
          const shown = orderIssues(applyFilters(page.items, filters));
          const next = nextAction(shown);
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
                  <h2>Next</h2>
                  <p>
                    <strong>{next.title}</strong> ({TIER_WORDS[tier(next)]})
                  </p>
                  {next.parent_title ? <p>Under: {next.parent_title}</p> : null}
                </section>
              ) : null}
              {shown.length === 0 ? (
                <p>No issues match.</p>
              ) : (
                <table>
                  <caption>Research frontier, next action first</caption>
                  <thead>
                    <tr>
                      <th scope="col">Issue</th>
                      <th scope="col">Question</th>
                      <th scope="col">Kind</th>
                      <th scope="col">Companies</th>
                      <th scope="col">Status</th>
                      <th scope="col">Produced</th>
                      <th scope="col">Session</th>
                    </tr>
                  </thead>
                  <tbody>
                    {shown.map((issue) => (
                      <IssueRow
                        key={issue.id}
                        issue={issue}
                        names={names}
                        isNext={next?.id === issue.id}
                      />
                    ))}
                  </tbody>
                </table>
              )}
            </>
          );
        }}
      </Load>
    </>
  );
}

function status(issue: Issue): string {
  if (issue.status !== "active") return STATUSES[issue.status].toLowerCase();
  if (issue.blocked) return "waiting";
  return onFrontier(issue) ? "open" : "narrowed";
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
  return (
    <tr aria-current={isNext ? "true" : undefined}>
      <th scope="row">{issue.title}</th>
      <td>{issue.parent_title ?? <Missing />}</td>
      <td>{KINDS[issue.kind]}</td>
      <td>{companies.length > 0 ? companies.join(", ") : <Missing />}</td>
      <td>{status(issue)}</td>
      <td>{produced || <Missing />}</td>
      <td>
        {issue.produced_by ? (
          <Link href={routes.session(issue.produced_by)}>Session</Link>
        ) : (
          <Missing />
        )}
      </td>
    </tr>
  );
}
