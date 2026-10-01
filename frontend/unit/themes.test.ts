import { expect, test } from "@playwright/test";

import type { Relationship } from "../lib/api/client";
import { layeredEdges, layerlessByCompany } from "../lib/themes";

const LUMENTUM = { id: "c-lumentum", display_name: "Lumentum" };
const COHERENT = { id: "c-coherent", display_name: "Coherent" };
const FABRINET = { id: "c-fabrinet", display_name: "Fabrinet" };
const NVIDIA = "c-nvidia"; // a counterparty: at the end of an edge, not a theme company

function edge(
  id: string,
  subject: string,
  object: string | null,
  layer: Relationship["layer"],
): Relationship {
  return {
    id,
    subject_company_id: subject,
    object_company_id: object,
    object_text: object ? null : "optical products",
    layer,
  } as unknown as Relationship;
}

const sole = edge("e-sole", LUMENTUM.id, FABRINET.id, "contract-manufacturing");
const competes = edge("e-competes", LUMENTUM.id, COHERENT.id, null);
const makes = edge("e-makes", LUMENTUM.id, null, null);
const owns = edge("e-owns", NVIDIA, COHERENT.id, null);
const edges = [competes, makes, owns, sole];

test("only edges with a layer are listed by layer", () => {
  expect(layeredEdges(edges)).toEqual([sole]);
  expect(layeredEdges([competes, makes])).toEqual([]);
});

test("an edge with no layer is listed under each theme company it names", () => {
  // Companies in the map's order; an edge between two of them shows under both, and one
  // from a counterparty under the theme company at its other end.
  expect(layerlessByCompany(edges, [COHERENT, LUMENTUM, FABRINET])).toEqual([
    { company: COHERENT, edges: [competes, owns] },
    { company: LUMENTUM, edges: [competes, makes] },
  ]);
});

test("a company-level edge has no object: it is listed under its own company only", () => {
  // Lumentum's own constraint names no product: no object company, no object text, no layer.
  const constrained = {
    ...edge("e-constrained", LUMENTUM.id, null, null),
    object_text: null,
    company_level: true,
  } as Relationship;
  expect(layeredEdges([constrained, sole])).toEqual([sole]);
  expect(layerlessByCompany([constrained, sole], [COHERENT, LUMENTUM, FABRINET])).toEqual([
    { company: LUMENTUM, edges: [constrained] },
  ]);
});

test("a company with no layerless edge is left out, and layered edges never show there", () => {
  expect(layerlessByCompany([sole], [LUMENTUM, FABRINET])).toEqual([]);
  expect(layerlessByCompany(edges, [FABRINET])).toEqual([]);
});
