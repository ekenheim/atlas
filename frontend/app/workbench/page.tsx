"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { Load, Missing, Timestamp } from "../../components/ui";
import {
  ApiError,
  api,
  type InvestigationSummary,
  type ThemeCompany,
  type ThemeSummary,
} from "../../lib/api/client";
import { routes } from "../../lib/routes";
import { useApi } from "../../lib/use-api";
import { STOP_REASONS } from "../../lib/workbench";

export default function WorkbenchPage() {
  const themes = useApi("themes", api.themes);
  const investigations = useApi("investigations", api.investigations);
  return (
    <>
      <h1>Research workbench</h1>
      <p>
        An investigation runs a theme question through a fixed plan: Scout, then one
        Investigator per seed company, then the Skeptic beside the Financial Analyst, then the
        Editor, within its budgets. Follow it here, launch one follow-up round on an open
        question, and save its research card as a Hypothesis.
      </p>
      <section aria-labelledby="start">
        <h2 id="start">Start an investigation</h2>
        <Load loaded={themes} what="the themes">
          {(themes) =>
            themes.length === 0 ? (
              <p>No theme is configured.</p>
            ) : (
              <StartForm themes={themes} />
            )
          }
        </Load>
      </section>
      <section aria-labelledby="investigations">
        <h2 id="investigations">Investigations</h2>
        <Load loaded={investigations} what="the investigations">
          {(page) =>
            page.items.length === 0 ? (
              <p>No investigation yet.</p>
            ) : (
              <Investigations items={page.items} total={page.total} />
            )
          }
        </Load>
      </section>
    </>
  );
}

function StartForm({ themes }: { themes: ThemeSummary[] }) {
  const router = useRouter();
  const [themeId, setThemeId] = useState(themes[0]?.id ?? "");
  const [question, setQuestion] = useState("");
  const [seeds, setSeeds] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const map = useApi(themeId || null, api.themeMap);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const started = await api.startInvestigation({
        theme: themeId,
        question,
        ...(seeds.length > 0 ? { seed_company_ids: seeds } : {}),
      });
      router.push(routes.investigation(started.id));
    } catch (failure) {
      setError(
        failure instanceof ApiError ? `${failure.code}: ${failure.message}` : String(failure),
      );
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} aria-describedby="start-hint">
      <p id="start-hint" className="muted-small">
        Budgets take the configured defaults (at most 2 rounds, 10 leads, 25 documents and the
        run&apos;s token budget).
      </p>
      <div className="field">
        <label htmlFor="theme">Theme</label>
        <select
          id="theme"
          value={themeId}
          onChange={(event) => {
            setThemeId(event.target.value);
            setSeeds([]);
          }}
        >
          {themes.map((theme) => (
            <option key={theme.id} value={theme.id}>
              {theme.title}
            </option>
          ))}
        </select>
      </div>
      <div className="field">
        <label htmlFor="question">Question</label>
        <textarea
          id="question"
          required
          rows={3}
          cols={60}
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
        />
      </div>
      <fieldset>
        <legend>Seed companies (none checked: every company of the theme)</legend>
        <Load loaded={map} what="the theme's companies">
          {(map) => {
            const companies: ThemeCompany[] = [
              ...map.layers.flatMap((layer) => layer.companies),
              ...map.unlayered,
            ].filter((company) => company.seeded);
            if (companies.length === 0) return <p>No company of the theme is seeded.</p>;
            return (
              <ul className="choices">
                {companies.map((company) => (
                  <li key={company.id}>
                    <label>
                      <input
                        type="checkbox"
                        checked={seeds.includes(company.id)}
                        onChange={(event) =>
                          setSeeds((current) =>
                            event.target.checked
                              ? [...current, company.id]
                              : current.filter((id) => id !== company.id),
                          )
                        }
                      />{" "}
                      {company.display_name}
                    </label>
                  </li>
                ))}
              </ul>
            );
          }}
        </Load>
      </fieldset>
      {error && <p role="alert">Could not start the investigation: {error}</p>}
      <button type="submit" disabled={busy || !question.trim()}>
        Start the investigation
      </button>
    </form>
  );
}

function Investigations({ items, total }: { items: InvestigationSummary[]; total: number }) {
  return (
    <table>
      <caption>
        Investigations, newest first{total > items.length && ` (the latest ${items.length})`}
      </caption>
      <thead>
        <tr>
          <th scope="col">Question</th>
          <th scope="col">Theme</th>
          <th scope="col">Round</th>
          <th scope="col">Status</th>
          <th scope="col">Started</th>
        </tr>
      </thead>
      <tbody>
        {items.map((item) => (
          <tr key={item.id}>
            <td>
              <Link href={routes.investigation(item.id)}>{item.question}</Link>
            </td>
            <td>{item.theme}</td>
            <td>{item.round}</td>
            <td>
              {item.status === "running"
                ? "running"
                : `stopped: ${item.stop_reason ? STOP_REASONS[item.stop_reason] : "unknown"}`}
            </td>
            <td>
              <Timestamp value={item.created_at} />
              <br />
              <span className="muted-small">by {item.created_by || <Missing />}</span>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
