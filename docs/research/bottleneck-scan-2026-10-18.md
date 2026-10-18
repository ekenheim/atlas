# Bottleneck scan, 2026-10-18 (ticket 33)

A market-wide search of SEC filings for supply-constraint language: the first scan of Atlas's own find step. This "Method" section was committed before the scan ran. The results below it were added after.

## Method (fixed before the run)

**Source.** The EDGAR full-text search API (`efts.sec.gov/LATEST/search-index`), every filer.
- **Forms:** 10-Q, 10-K, 8-K, 6-K, 20-F and 40-F, exhibits included (an 8-K's EX-99 press release or call transcript is searched too).
- **Filed:** 2026-06-20 to 2026-10-18 (120 days).
- **Requests:** Atlas's SEC user agent, at most 5 a second.

**Phrases.** Each one is an exact-phrase query. "Strong" phrases state a constraint in progress, "medium" ones its usual signs, and "weak" ones are often boilerplate.

- **Strong (1.0):**
  - "demand exceeds supply", "demand exceeded supply", "demand continues to exceed supply";
  - "demand outpaces supply", "demand outpaced supply", "demand outstrips supply";
  - "undersupplied", "supply shortage", "supply shortages";
  - "capacity constrained", "capacity-constrained", "sold out", "fully booked", "on allocation";
  - "unable to meet demand", "unable to keep up with demand", "cannot get enough";
  - "supply remains tight", "tight supply".
- **Medium (0.5):** "extended lead times", "lead times have extended", "lead times have increased", "longer lead times", "record backlog", "pricing power", "raised prices".
- **Weak (0.25):** "sole source", "single source", "limited number of suppliers", "shortage of".

**Exclusions.**
- **The universe:** every `cik:` in `configs/themes/ai-infrastructure.yaml`, scorecard cases included.
- **Finance, insurance and real estate:** SIC 6000–6799, where "tight" and "shortage" usually mean liquidity or housing. Blank-check companies (6770) are in this range.
- **Funds and trusts:** filers with no SIC.

**Score and shortlist.**
- **Score:** a filer's score is the sum of the weights of the distinct phrases its filings matched. Several filings matching the same phrase count it once.
- **Ranking:** by score, ties by the most recent matching filing. The top 40 go to the analyst.
- **Passages:** for each shortlisted filer, up to six passages of about 800 characters around a matched phrase, strongest phrase first and newest filing first, taken from the filing documents themselves.

**The analyst's reading.**
- **Who reads:** one Opus reader, who sees the passages, the filer's name, SIC and form, and no prices. It classes each filer:
  - **holder:** the company controls the scarce thing: its own capacity sold out, its product on allocation, its prices rising on demand;
  - **squeezed:** it buys a scarce input;
  - **noise:** risk-factor boilerplate, a hypothetical, a past episode, a company-specific failure, or a shortage of labour or housing unrelated to supply;
  - **unclear.**

  Each class comes with the quote that decides it, what is scarce, and whether other shortlisted filers point at the same scarce thing (a cluster).
- **A second, blind reader** classes the same 40 for the precision@20 measure. Where the two disagree, the lead decides.

**Known limits, stated before the run.**
- Filings miss calls and conferences.
- Exact phrases miss paraphrase.
- Large filers write the same risk language every quarter, so the weak phrases are boilerplate-prone. That is why they weigh a quarter.
- The full-text search covers filings from 2001 on, but only the 120-day window is read here.

## Results (added 2026-10-18 after the run)

**The run.**
- **Hits:** 2,699 matches (532 strong, 379 medium, 1,788 weak) over 166 requests.
- **Filers:** 1,282 ranked after the exclusions (15 universe CIKs, 173 with SIC 6000–6799, 20 with no SIC).
- **Deviation, decided before any passage was read:** the lead counts "capacity constrained" and "capacity-constrained" once, because EDGAR returns identical hits for both.
- **Where the data is:** the raw output in `.scratch/live-runs/20261018-bottleneck-scan/` (local): the ranking, the shortlist with passages, and both readings.

**Precision@20: 5 of 20 (25%), from both blind readers alike.**
- **Holders (2):** Forgent Power Solutions and INNIO.
- **Squeezed (3):** ImmunityBio, Microchip and Extreme Networks.

**The rest of the top 20.** Fifteen are noise or unclear:
- an LLC agreement's "limitation on allocation";
- medical-device and biotech risk factors;
- a hyperscale networking vendor's demand language with no constraint;
- three pre-production miners (scandium, tungsten, boric acid), classed unclear.

**Where the readers split (ranks 21–40), and the lead's call:**
- **Brady: squeezed.** It names memory and semiconductor components.
- **Key Tronic: unclear.** Its input is "not named further", and the method requires a named input.
- **Interactive Strength: noise.** No input is named.

**Clusters (both readers):**

1. **Memory and trailing-edge semiconductors pulled toward AI.** Squeezed buyers in five unrelated industries say so in their own filings. No holder is among the 40: the holders are the memory makers.
   - The buyers: a networking vendor (Extreme Networks), a sequencing-instrument maker (PacBio), a security-hardware maker (Napco), a drone maker (AeroVironment), an industrial-labels maker (Brady), and Microchip on trailing-edge foundry and assembly capacity.
   - This is independent corroboration, from the buy side, of the DRAM and HBM question the Researcher takes on 2026-10-20. A Researcher session should cite these buyers' own filings as Facts once they are in the archive.
2. **Medium-voltage switchgear, transformers and gas-engine generators for data-centre power.** Two holders, Forgent Power Solutions (CIK 0002080126, P2) and INNIO (CIK 0002109150, P3), and a squeezed buyer, Fervo Energy, short of transformers and grid interconnection equipment.
   - Likely already consensus (crowding to be recorded, never evidence).
   - Both holders are candidates for admission (ticket 33, step 3), into a power-equipment theme when the Watch takes one up.
3. **Minor metals under Chinese export controls.** Germanium: LightPath, squeezed, P2. The would-be non-Chinese holders (tungsten, scandium, boric acid) are pre-production miners, which is a financing question before it is a supply one.
4. **TICE BCG for a bladder-cancer combination.** ImmunityBio, squeezed. A single-manufacturer drug input, outside Atlas's themes. Recorded, not pursued.

**What it says about the method.**
- **A quarter of the top 20 is signal.** The weak phrases and medical risk factors carry most of the noise. Next scan:
  - drop the weak tier from scoring;
  - exclude SIC 2833–2836 and 3841–3845 from the ranking, or rank them apart.
- **The strongest finding is a cluster of buyers, not a holder.** Squeezed buyers in unrelated industries, saying one thing in their own filings, are hard evidence that the input is short. The Watch should treat a buyer cluster as a first-class lead toward the holder layer.
