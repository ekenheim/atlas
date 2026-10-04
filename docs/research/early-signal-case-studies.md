# Early-signal case studies: AXT and SanDisk

**What this is.** Two hand-made timelines (2026-10-04) of what a company's management said, in order, before its bottleneck was priced, each overlaid with the share price. The owner asked for them to see whether "hints" were public early, and what Atlas would need to catch such a case. They are not system output and no evaluation result: two winners, chosen after the fact.

**How they were made.** AXT is one of Atlas's 12 companies: its call transcripts and 8-Ks were read from the production archive (`GET /api/v1/source-versions/{id}/content`). SanDisk (NASDAQ:SNDK) is outside Atlas (the memory theme): its catalog and six transcripts were read ad hoc through the cluster's TradingView proxy with Atlas's own client, on a port-forward, and nothing was stored in Atlas. Daily closes for both came from the proxy's `mcp-tv-get-ohlcv` tool (split-adjusted, delayed feed), a tool Atlas itself does not call. Quotes are kept short; the transcripts are TradingView content under the owner's override.

## AXT (InP substrates): a physical shortage behind an export-permit gate

| Date | Document | What was said | Close | Next day | +3 months | +6 months |
|---|---|---|---|---|---|---|
| 2025-05-01 | Q1 call | InP backlog outside China "ready to ship", blocked by China's export permits | $1.35 | +3.0% | 1.4× | 5.4× |
| 2025-07-09 | 8-K | Q2 revenue miss announced ($17.5–18M against $20–22M) | $2.54 | −11.0% | 2.1× | 9.5× |
| 2025-07-31 | Q2 call | Revenue $18.0M, InP $3.6M, gross margin 8%. In Q&A: "the market is just growing too fast to be adequately serviced by just two players"; about 40% of world InP substrate supply; backlog over $10M; "new orders on pretty much a daily basis" | $2.08 | −7.7% | 3.4× | 8.9× |
| 2025-10-30 | Q3 call | InP revenue $13.1M; InP backlog $49M, "the largest we've ever had"; customers "cannot get enough material"; a customer's word, "tsunami"; prices firm; capacity ~$20M a quarter, doubled in nine months for $10–15M | $7.32 | +8.6% | 2.9× | 14.5× |
| 2025-12-29 | 8-K | Offering of 7.1M shares at $12.25 to expand InP capacity | $14.59 | +8.3% | 3.9× | 4.5× |
| 2026-01-08 | 8-K | Q4 revenue cut: fewer permits issued | $25.83 | −11.0% | 2.5× | 2.0× |

Peak $143.16 (2026-05-26); $85.87 on 2026-10-02.

## SanDisk (NAND): a shortage by decision, announced in advance

| Date | Document | What was said | Close | Next day | +3 months | +6 months |
|---|---|---|---|---|---|---|
| 2025-02-11 | Investor Day | The industry cuts utilisation while still profitable, "evidence of this structural change"; forecast: "by Q2 we are into undersupply. And by Q3, Q4, that undersupply should be at least 5%" | $36.00 (first trading day, 02-13) | +1.8% | 1.1× | 1.2× |
| 2025-05-07 | Q3 FY25 call | $1.9B GAAP loss (goodwill); prices fell more than forecast; "we are extending our fab underutilization actions"; price increases begun; "We still see an undersupplied market through the end of next year" | $34.97 | +4.8% | 1.2× | 6.2× |
| 2025-06-11 | Mizuho conference | "You're seeing underutilization when you're still at a profitable level because I want to support pricing" | $40.23 | +2.7% | 2.1× | 5.8× |
| 2025-08-14 | Q4 FY25 call | Inventory days 150 to 135 "as demand exceeded supply in line with our strategy"; undersupplied "through the end of 2026" | $46.68 | −4.6% | 6.1× | 13.4× |
| 2025-09-04 | Trade press | Second 10% price increase | $62.50 | +9.7% | 3.1× | 8.4× |
| 2025-09-10 | Goldman conference | "We see an undersupplied market all the way through 2026"; "the market is tight" | $73.92 | +14.0% | 3.0× | 8.4× |
| 2025-11-06 | Q1 FY26 call | "Our products are currently on allocation across all end markets"; customers seek long-term commitments | $207.69 | +15.3% | 2.8× | 7.5× |

Peak $2,354.39 (2026-06-22); $1,719.99 on 2026-10-02.

## What the two cases show

1. **The angle was stated on a bad-headline day.** AXT's Q2 call followed a revenue miss and an 8% margin; SanDisk's Q3 call carried a $1.9B loss. A screen on financials would have passed over both. The text held the bottleneck test's parts: demand against capacity, few suppliers, pricing.
2. **The market took months to price it.** About three months for AXT (2025-07-31 to 2025-10-30), about seven for SanDisk (the Investor Day to September). The day after the hint was flat or down in both.
3. **Buying the explicit confirmation was still early.** AXT at the Q3 call was 14.5× six months later; SanDisk at the Goldman conference 8.4×. The owner's aim follows: a thesis on the shelf, and a notice when the confirmation comes, matter more than being first.
4. **Where it was said.** In call Q&A, at an investor day and at broker conferences; not in the 10-Q or 10-K. Three of SanDisk's six most useful documents were not earnings calls.
5. **Two kinds of bottleneck.** AXT: physical, with a stated gate (permits) that also became the January disappointment. SanDisk: a supplier's own decision, with a forecast that could be checked each quarter (undersupply by Q2, at least 5% by Q3–Q4).
6. **Nothing here says when it ends.** Both are well below their peaks (AXT −40%, SanDisk −27%).

## What Atlas would have done with these sentences

Atlas's `capacity_constrained` rule needs a constraint cue in the quote (`atlas.claims.directional_cue`). The fourteen key sentences were run through it:

| Sentence | Cue found |
|---|---|
| AXT 07-31 "growing too fast to be adequately serviced by just two players" | none |
| AXT 07-31 "new orders on pretty much a daily basis" | none |
| AXT 07-31 "a backlog of more than $10 million" | `backlog` |
| AXT 10-30 "they cannot get enough material" | none |
| AXT 10-30 "there's a tsunami coming" | none |
| AXT 10-30 "there are shortages" | `shortages` |
| SNDK 02-11 "by Q2 we are into undersupply" | none |
| SNDK 05-07 "extending our fab underutilization actions" | none |
| SNDK 05-07 "an undersupplied market through the end of next year" | none |
| SNDK 06-11 "underutilization … because I want to support pricing" | none |
| SNDK 08-14 "demand exceeded supply" | `demand exceeded` |
| SNDK 09-10 "an undersupplied market all the way through 2026" | none |
| SNDK 09-10 "the market is tight" | none |
| SNDK 11-06 "on allocation across all end markets" | `on allocation` |

Four of fourteen. The earliest sentence of each case fails. Two reasons, and only one is vocabulary: "undersupplied", "cannot get enough" and "the market is tight" are missing words; but "an undersupplied market" and "too fast for two players" are statements about a **market**, not about the speaker's own capacity, and the predicate's subject is a company. That is a modelling question, not a regex.

## What it asks of Atlas

Ranked by how directly the two cases depend on it. All are candidates for the effort after the verdict; none changes the version the verdict runs measure.

1. **Market-level supply statements as Claims** (the cue test above): a supplier saying its market is undersupplied, or served by two players. Decide the predicate and its subject; add the missing words with it.
2. **Supply discipline as a signal**: "reduce supply to match demand", underutilisation while profitable, price increases. Atlas has no predicate for a constraint that is chosen.
3. **A management forecast as a tracked falsifier**: SanDisk's "undersupply by Q2, at least 5% by Q3–Q4" was checkable each quarter. A Hypothesis has falsifiers; nothing tracks a company's own forecast against later documents.
4. **A notice when evidence confirms a Hypothesis**: proposed updates fire on contradiction only. The cases' value was in the confirmation (AXT 10-30, SanDisk 09-10).
5. **Investor days and conferences** are already ingested as event transcripts for the 12 companies; keep them in the document floor's view (today the floor is the periodic report and the results release; passage selection also keeps one passage of a results call).
6. **Speaker labels in TradingView transcripts** are wrong in two of the documents read (pilot-fix ticket 32). The own-speaker rule reads them.
7. **Price history through the proxy** makes "scored against what happened" cheap (`mcp-tv-get-ohlcv`), but it is a fourth tool under display-only terms: the owner's decision (map, "Parked (owner)").
8. **Slides and trade press**: SanDisk's April price letter reached the trade press five weeks before the call; slide decks are catalogued and unread. Lower: a lead already exists for news, and a slide parser is new work.

## Five more names, read blind (2026-10-04, later the same day)

The owner named IREN, ETOR, SNAP, POET and RPI (read as Raspberry Pi, LSE:RPI). Their transcripts and daily closes were fetched ad hoc through the proxy, as for SanDisk; nothing was stored in Atlas. Each company was read by a separate reader that saw only its transcripts, no prices, and was told to use no knowledge of what followed. The prices were overlaid afterwards. POET is a photonics company outside the 12: named by the owner, it no longer counts in the held-out answer key (pilot-review ticket 02). The dates and direction of the investor's own posts are not known here.

| Name | What the reader found in the text | Dates | Close on the date, and after |
|---|---|---|---|
| IREN (grid power for AI data centers) | A bottleneck from the first document: "the escalating power shortage", 2.3 GW of grid power held, new connections taking years; 2025-05-14: "That is the critical bottleneck"; contracts 2025-08-28; a $9.7bn Microsoft contract with a 20% prepayment 2025-11-06 | stated 2025-02-12; named 2025-05-14; first contracts 2025-08-28; headline contract 2025-11-06 | $13.01 (0.6× at 3 months, 1.5× at 6); $7.97 (next day −2.8%; 7.0× at 6 months); $23.04 (+14.9%; 2.1× at 3 months); $66.96 (−6.8%; 0.7× at 3 months). High $76.87 on 2025-11-05; $41.76 on 2026-10-02 |
| Raspberry Pi (squeezed by DRAM) | On the squeezed side: 2025-09-23, memory capacity moved to AI memory, "temporary"; 2026-03-31, memory about 7× dearer, prices raised, "substantial customer backlogs", revenue guided well above estimates | squeeze stated 2025-09-23; confirmed with pass-through 2026-03-31 | 416.6p (0.7× at 3 months); 429.8p (+13.6%; 2.0× at 3 months). High 1,082p on 2026-06-05; 716.5p now |
| POET (optical engines) | No bottleneck: near pre-revenue, the CEO says capacity meets demand, the production ramp slips three times, all financing by share issuance; a $50M order in 2026-05 (provider summaries, not the company's words, for all but the AGM) | promise 2024-11-14; order 2026-05-21 | $3.84 (1.2× at 6 months); $14.82 (0.6× at 3 months). High $20.81 on 2026-05-14; $7.79 now |
| eToro | No bottleneck: retail trading activity follows volatility; double-digit account growth forecast, 9% delivered | 2025-08-12 to 2026-02-17 | $50.74 (0.5× at 6 months); $25.42 now |
| Snap | The reverse of a bottleneck: ad inventory growing faster than demand, ad prices down 7%, 10%, 13% | 2025-02-04 to 2025-11-05 | $11.60 (0.7× at 6 months); $5.58 now |

What the seven names add to the two:

1. **The text separates them.** Readers without prices found a bottleneck in the three that ran (AXT, SanDisk, IREN), a squeeze in one (Raspberry Pi), and none in the three that fell or went nowhere (eToro, Snap, POET). Seven names are no hit rate, and who chose them is not neutral; but the test was not fitted to the outcome.
2. **"Confirmation" means the first numbers, not the headline deal.** IREN's first contracts (2025-08-28) were a good entry; the Microsoft contract ten weeks later was the top, with billions of debt and equity still to raise in the same call. The financing part of the test is what changes between the two dates.
3. **A stated thesis can halve first.** IREN closed at $13.01 on the day it described the power shortage and $5–6 two months later. AXT, SanDisk, IREN and POET all made their lows between 7 and 9 April 2025, a market-wide sell-off: the text had not changed.
4. **Being squeezed is not a thesis by itself.** Raspberry Pi fell while the squeeze was "temporary" and doubled when it showed backlog and price rises passed on: pricing power, shown in numbers.
5. **The same bottleneck is visible from both ends.** SanDisk forecast undersupply in February 2025; a memory buyer named the squeeze in September 2025. Joining them is the cross-company observation Memory does not yet form (pilot-review ticket 21).
6. **Speaker labels again**: Raspberry Pi's 2025-09-23 call labels the CEO's answers as the CFO's (pilot-fix ticket 32: three of the seven companies' transcripts so far).

## The investor's own dates on the five names

The owner supplied the dates (2026-10-04), compiled outside Atlas from the public tracker and the skill repository's analysis files; only names, dates and approximate prices are used here, and their confidence is the compiler's. Closes are TradingView's.

| Name | His call | Close that day | What the company's text had said by then | After his date |
|---|---|---|---|---|
| IREN | Bought 2025-09-26 on a ~13% drop (about $40); later reduced and turned bearish | $41.86 | The bottleneck since 2025-02-12, named 2025-05-14 ($7.97), first contracts 2025-08-28 ($23.04) | High $76.87 six weeks later (1.8×); 0.96× at 3 months; 1.0× now |
| eToro | Bullish from 2025-07-02 (about $63); averaged down; "Extremely Strong Buy" 2025-09-29 (about $39) | $63.42; $41.99 | No call before his first date (listed 2025-05). The 2025-08-12 call: no bottleneck | Low $24.74 (0.39× of the first date); 0.40× now |
| Snap | Thesis published 2025-12-12 ("100%+ upside"); no clear ownership; backed away over stock compensation | $7.31 | Four calls of ad inventory outgrowing demand; stock compensation of $268M a quarter stated on the 2025-11-05 call | Low $3.81 (0.52×); 0.76× now |
| POET | Discussed, repeatedly not long; "tiny positions" 2026-08-07 | $8.91 | No bottleneck; ramp slipped three times; financed by share issuance | 0.87× now |
| Raspberry Pi | "Long $RPI" 2026-02-16 on agentic-computing hardware demand (about 280–285p) | 305.0p | Nothing on that demand: the 2025-09-23 call has the memory squeeze and a backlog | +36.1% the next day; high 1,082p (3.5×); 2.35× now |

1. **On IREN the text was earlier than he was.** The company named the bottleneck at $7.97 and showed the first contracts at $23.04; he bought at about $40. His later turn to bearish fits the 2025-11-06 call, where the capital still to raise is spelled out.
2. **The test would have kept out of his two losers.** eToro and Snap show no bottleneck in any call, and the figure he backed away from Snap over is in the transcript. A use for Atlas follows: run the test on a name somebody flags, before acting on it.
3. **Raspberry Pi came from outside the documents.** His reason was a product trend, not anything the company had said; the price moved 36% the day after his call. On 2026-03-31 the CEO answered the question directly: "Did we see a significant increase in demand related to Agentic AI and OpenClaw? No, I don't think we saw a prompt increase in demand." The same call confirmed something else (backlog, price rises, revenue above estimates). Atlas could have held this only as a lead with no evidence until that call.
4. Five names, his calls: two rose from his date (one of them partly on the call itself), two fell, one was no position.

## Limits

- Two winners picked afterwards show the pattern exists, not its hit rate. Controls are needed: companies that used the same language in the same months and did not run, and calls of the same investor that failed.
- The quotes were chosen knowing the outcome.
- The SanDisk transcripts were read once and are not in the archive; the AXT ones are (Source Versions of provider `tradingview`).
- Replay is the real test: pilot question 2 (InP substrates) with the cutoff at 2025-08-01, to see whether Atlas surfaces AXT from what was public then.
