"use client";

import Link from "next/link";

import { Code, Load, Missing } from "../components/ui";
import { api } from "../lib/api/client";
import { routes } from "../lib/routes";
import { useApi } from "../lib/use-api";

export default function CompaniesPage() {
  const companies = useApi("companies", api.companies);
  return (
    <>
      <h1>Companies</h1>
      <Load loaded={companies} what="companies">
        {(page) =>
          page.items.length === 0 ? (
            <p>No companies yet. Seed them with <code>atlas companies seed</code> or run an ingest.</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th scope="col">Company</th>
                  <th scope="col">Legal name</th>
                  <th scope="col">CIK</th>
                  <th scope="col">Listings</th>
                </tr>
              </thead>
              <tbody>
                {page.items.map((company) => (
                  <tr key={company.id}>
                    <td>
                      <Link href={routes.company(company.id)}>{company.display_name}</Link>
                    </td>
                    <td>{company.legal_name}</td>
                    <td>{company.cik ? <Code>{company.cik}</Code> : <Missing />}</td>
                    <td>
                      {company.securities.length === 0 ? (
                        <Missing />
                      ) : (
                        company.securities.map((s) => `${s.ticker} (${s.exchange_mic})`).join(", ")
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )
        }
      </Load>
    </>
  );
}
