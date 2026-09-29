"use client";

import Link from "next/link";

import { Load, Missing } from "../../components/ui";
import { api } from "../../lib/api/client";
import { LAYERS } from "../../lib/relationships";
import { routes } from "../../lib/routes";
import { useApi } from "../../lib/use-api";

export default function ThemesPage() {
  const themes = useApi("themes", api.themes);
  return (
    <>
      <h1>Themes</h1>
      <p>
        Each theme the universe config defines, with its coverage. Open a theme to see its
        companies by supply-chain layer, the Relationships between them, its Candidates and its
        open gaps.
      </p>
      <Load loaded={themes} what="themes">
        {(themes) =>
          themes.length === 0 ? (
            <p>No themes: the universe config defines none.</p>
          ) : (
            <table>
              <caption>Themes and their coverage</caption>
              <thead>
                <tr>
                  <th scope="col">Theme</th>
                  <th scope="col">Companies</th>
                  <th scope="col">Without sources</th>
                  <th scope="col">Empty layers</th>
                  <th scope="col">Relationships</th>
                  <th scope="col">Open Candidates</th>
                </tr>
              </thead>
              <tbody>
                {themes.map((theme) => (
                  <tr key={theme.id}>
                    <td>
                      <Link href={routes.theme(theme.id)}>{theme.title}</Link>
                      {theme.description && (
                        <>
                          <br />
                          <span className="muted-small">{theme.description}</span>
                        </>
                      )}
                    </td>
                    <td>{theme.company_count}</td>
                    <td>{theme.companies_without_sources}</td>
                    <td>
                      {theme.empty_layers.length === 0 ? (
                        <Missing />
                      ) : (
                        theme.empty_layers.map((layer) => LAYERS[layer]).join(", ")
                      )}
                    </td>
                    <td>{theme.relationship_count}</td>
                    <td>{theme.open_candidate_count}</td>
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
