import type { Relationship } from "../lib/api/client";
import { EdgeLink, EdgeObject, LayerName, ReviewState, edgeLabel } from "./relationships";
import { Code } from "./ui";

/**
 * A plain table of edges (the Theme explorer's and the Company dossier's), each row named by
 * the edge read in its direction and opening its page (Evidence and source spans). The full,
 * sortable table is the edge table page.
 */
export function EdgeList({ edges, caption }: { edges: readonly Relationship[]; caption: string }) {
  return (
    <table>
      <caption>{caption}</caption>
      <thead>
        <tr>
          <th scope="col">Subject</th>
          <th scope="col">Predicate</th>
          <th scope="col">Object</th>
          <th scope="col">Layer</th>
          <th scope="col">Review state</th>
          <th scope="col">Evidence</th>
          <th scope="col">Families</th>
          <th scope="col">Edge</th>
        </tr>
      </thead>
      <tbody>
        {edges.map((edge) => (
          <tr key={edge.id} aria-label={edgeLabel(edge)}>
            <td>{edge.subject_name}</td>
            <td>
              <Code>{edge.predicate}</Code>
            </td>
            <td>
              <EdgeObject relationship={edge} />
            </td>
            <td>
              <LayerName layer={edge.layer} />
            </td>
            <td>
              <ReviewState relationship={edge} />
            </td>
            <td>{edge.evidence_count}</td>
            <td>{edge.family_count}</td>
            <td>
              <EdgeLink relationship={edge} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
