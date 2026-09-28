"use client";

import Link from "next/link";
import { Suspense } from "react";

import { Code, Load, Missing, Timestamp } from "../../components/ui";
import { api } from "../../lib/api/client";
import { routes } from "../../lib/routes";
import { useApi, useIdParam } from "../../lib/use-api";

export default function CompanyPage() {
  return (
    <Suspense>
      <Company />
    </Suspense>
  );
}

function Company() {
  const id = useIdParam();
  const company = useApi(id, api.company);
  const sources = useApi(id, api.companySources);
  return (
    <>
      <p className="crumbs">
        <Link href={routes.companies}>Companies</Link>
      </p>
      <Load loaded={company} what="the company">
        {(company) => (
          <>
            <h1>{company.display_name}</h1>
            <p>
              {company.legal_name}
              {company.cik && (
                <>
                  , CIK <Code>{company.cik}</Code>
                </>
              )}
            </p>
          </>
        )}
      </Load>
      <h2>Source Documents</h2>
      <Load loaded={sources} what="Source Documents">
        {(page) =>
          page.items.length === 0 ? (
            <p>No Source Documents collected yet.</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th scope="col">Title</th>
                  <th scope="col">Form</th>
                  <th scope="col">Accession</th>
                  <th scope="col">Source type</th>
                  <th scope="col">First seen</th>
                  <th scope="col">Versions</th>
                </tr>
              </thead>
              <tbody>
                {page.items.map((document) => (
                  <tr key={document.id}>
                    <td>
                      <Link href={routes.source(document.id)}>{document.title}</Link>
                    </td>
                    <td>{document.form_type ?? <Missing />}</td>
                    <td>{document.accession ? <Code>{document.accession}</Code> : <Missing />}</td>
                    <td>{document.source_type}</td>
                    <td>
                      <Timestamp value={document.first_seen_at} />
                    </td>
                    <td>{document.version_count}</td>
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
