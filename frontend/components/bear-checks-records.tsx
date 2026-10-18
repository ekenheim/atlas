"use client";

// How each bear check was read, for the company's Records only (H3): the rule's own words with
// their ISO dates and concept names, verbatim, and the time the checks were run as of.
import { api } from "../lib/api/client";
import { bearConcepts, bearLabel, orderedChecks } from "../lib/bear-checks";
import { exactTime } from "../lib/format";
import { useApi } from "../lib/use-api";

export function BearChecksRecords({ companyId }: { companyId: string }) {
  const loaded = useApi(companyId, api.bearChecks);
  if (loaded.state !== "ready" || loaded.data === null) return null;
  return (
    <section aria-labelledby="bear-records">
      <h2 id="bear-records">Bear checks: how each was read</h2>
      <p className="muted-small">
        As of <time dateTime={loaded.data.as_of}>{exactTime(loaded.data.as_of)}</time>
      </p>
      <table>
        <caption>Bear checks: how each was read</caption>
        <thead>
          <tr>
            <th scope="col">Check</th>
            <th scope="col">How it was read</th>
            <th scope="col">Concepts</th>
          </tr>
        </thead>
        <tbody>
          {orderedChecks(loaded.data.checks).map((check) => (
            <tr key={check.key}>
              <th scope="row">{bearLabel(check)}</th>
              <td>{check.basis}</td>
              <td>{bearConcepts(check).join(", ")}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
