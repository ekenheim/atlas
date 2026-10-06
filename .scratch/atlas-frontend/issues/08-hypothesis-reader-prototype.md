# What a reader sees when opening a Hypothesis

Type: prototype (HITL)
Status: resolved
Blocked by: none

## Question

The page on which a reader understands and consumes a Hypothesis as a bottleneck argument (the next effort's spec, `.scratch/atlas-bottleneck-argument/spec.md`: the Thesis Statement; the six steps (what is constrained, demand over qualified supply, relief, who controls it, economic capture, what would invalidate it), each with status (supported, disputed, unknown), evidence quotes and counterevidence; how sure Atlas is; open questions; falsifiers; records one click deeper). Production has no Hypothesis yet, so the prototype is fed by a real research card (the best of the 10 investigations on production, read with `GET /api/v1/investigations/{id}`) mapped by hand onto the steps, marked as such. Layouts genuinely different (for example: a one-screen argument with steps as rows; a story read top to bottom; a claim-and-evidence two-column view). The answer is the chosen layout, captured on a throwaway branch and linked from the spec as its design input; nothing ships.

## Answer

**Variant A, the argument as rows** (the owner, 2026-10-06). Captured with B (a story, top to bottom) and C (outline and evidence) on the throwaway branch `prototype/thesis-reader` (commit `553b6aa`; build the export, open `/prototype-thesis/?variant=A|B|C`). Fed by investigation `452c3b9d` (2026-10-02, laser chips for 800G/1.6T), whose card is saved in `.scratch/atlas-frontend/samples/cards/`; the six-step mapping, statuses, thesis wording and confidence were the lead's, by hand; every quote is verbatim from its Evidence.

The reader page, top to bottom:
1. **Head:** the theme and layer; the **Thesis Statement** as the page's headline (large, balanced); confidence (a word, coloured when not high) with one line on why; the tally of steps (supported · disputed · unknown); "n quotes from m documents · as of <date>".
2. **The argument:** the six steps as rows on one screen (what is constrained; demand exceeds qualified supply; how fast relief comes; who controls the scarce capacity; how the holders capture it; what would prove it wrong), each with a one-line summary, a status pill (supported green, disputed amber, unknown grey) and "n for · n against". A row expands to evidence for beside evidence against or not settled: quotes as cards (who, source, date, a Source link to the version), plain-language notes for bear context and gaps.
3. **Still open:** the open questions.
4. **Records:** one line linking the investigation and naming the companies.

What the data needs that Atlas does not produce yet (for the spec): a step-by-step argument with a status per step; a confidence with its reason; a one-line summary per step; bear context and gaps phrased for a reader; the thesis wording itself. Today's card gives findings, bear context and open questions, which a person had to map.
