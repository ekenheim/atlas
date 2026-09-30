"use client";

import Link from "next/link";

import { Load, Missing, Timestamp } from "../../components/ui";
import { api, type Hypothesis } from "../../lib/api/client";
import { words } from "../../lib/hypotheses";
import { routes } from "../../lib/routes";
import { useApi } from "../../lib/use-api";

const loadHypotheses = async () => (await api.hypotheses()).items;

export default function HypothesesPage() {
  const hypotheses = useApi("hypotheses", loadHypotheses);
  return (
    <>
      <h1>Hypotheses</h1>
      <p>
        Investigations saved as versioned, falsifiable research objects, newest first. Open one for
        its dossier: every version with its findings and citations, the differences between
        versions, its scenarios, the publish gate and its Research Snapshots.
      </p>
      <Load loaded={hypotheses} what="Hypotheses">
        {(hypotheses) =>
          hypotheses.length === 0 ? (
            <p>No Hypotheses yet: save a stopped investigation as one.</p>
          ) : (
            <table>
              <caption>Hypotheses, newest first</caption>
              <thead>
                <tr>
                  <th scope="col">Thesis (latest version)</th>
                  <th scope="col">Status</th>
                  <th scope="col">Theme</th>
                  <th scope="col">Versions</th>
                  <th scope="col">Published</th>
                  <th scope="col">Updated</th>
                </tr>
              </thead>
              <tbody>
                {hypotheses.map((hypothesis) => (
                  <HypothesisRow key={hypothesis.id} hypothesis={hypothesis} />
                ))}
              </tbody>
            </table>
          )
        }
      </Load>
    </>
  );
}

function HypothesisRow({ hypothesis }: { hypothesis: Hypothesis }) {
  const latest = hypothesis.versions.at(-1);
  const published = hypothesis.versions.filter((each) => each.published);
  return (
    <tr>
      <td>
        <Link href={routes.hypothesis(hypothesis.id)}>
          {latest ? latest.content.thesis_statement : `Hypothesis ${hypothesis.id.slice(0, 8)}`}
        </Link>
        {!latest && (
          <>
            <br />
            <span className="muted-small">
              {hypothesis.draft_status === "failed"
                ? `The Editor's draft failed: ${hypothesis.draft_error ?? "no reason recorded"}`
                : "The Editor's draft is queued."}
            </span>
          </>
        )}
      </td>
      <td>{words(hypothesis.status)}</td>
      <td>
        <Link href={routes.theme(hypothesis.theme_id)}>{hypothesis.theme_id}</Link>
      </td>
      <td>{hypothesis.versions.length}</td>
      <td>
        {published.length === 0 ? (
          <Missing>never</Missing>
        ) : (
          `version${published.length === 1 ? "" : "s"} ` +
          published.map((each) => each.version).join(", ")
        )}
      </td>
      <td>
        <Timestamp value={hypothesis.updated_at} />
      </td>
    </tr>
  );
}
