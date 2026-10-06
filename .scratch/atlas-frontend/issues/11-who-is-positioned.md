# Who is positioned: the Exposures on the reader page

Type: prototype (HITL)
Status: resolved
Blocked by: 08

## Question

After the argument, how does the reader page show the companies positioned to capture the Bottleneck (their **Exposures**, `CONTEXT.md`), per the Serenity method's company test (the alignment note on `research/serenity-skills-alignment`: sole or near-sole qualified source, customer qualification and the customer path, pricing power rather than volume, share of the bill of materials, financing quality with dilution as a disqualifier), without a rating or a recommendation (product spec §1.4, §8.3)? Prototyped on the InP thesis's real Evidence (investigation `452c3b9d`) as a section of ticket 08's variant A; the answer goes to the bottleneck-argument spec (its item 4, economic capture).

## Answer

**A "Who is positioned" section after the argument** (the owner, 2026-10-06), captured on `prototype/thesis-reader` (commit `8adda0d`, `exposures.ts` and the `Positioned` section of variant A):
- One row per Exposure (company, with its role in the bottleneck: "merchant InP substrate supplier"), one column per test of the Serenity method's company test: holds scarce capacity · few second sources · qualified with customers · pricing power · small share of BOM · clean financing. Each cell is evidence for (green ●), against (red ✕) or unknown (grey ○); a cell opens its question, a plain note and the quote with its source.
- Rows ordered by how many tests have evidence for them, with "For n / 6"; the page says it is "a count, not a rating". Atlas never names a pick (product spec §1.4, §8.3); dilution shows as evidence against financing.
- A computed closing line names the tests no company has evidence for: on the InP thesis, "pricing power, small share of BOM. Until it is, the thesis says who holds the scarcity, not who profits from it."
- Company names link to the reader's dossier.

On the real data (hand-judged cells, verbatim quotes): Coherent 3/6; AXT, Lumentum and Applied Optoelectronics 2/6 (AXT against on financing, $600.1M of new shares); IQE 1/6 (it adds InP capacity, and its share count rose ~36%). No price, ASP or margin evidence for any company: the research's largest gap for an investable call.

What Atlas must produce for it (to the spec): the Exposures of a Hypothesis, each test's verdict with its Evidence (or "not found"), and the role line. `CONTEXT.md` gains **Exposure**.
