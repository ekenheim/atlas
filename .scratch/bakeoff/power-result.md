# Bake-off round 2, power equipment, as of 2026-10-19: result

- **Atlas:** the architect Watch run on 0.6.19 (no reach fix), 53 calls, 5 min 50 s. 8 refusals: 5 `created_after_as_of` on its own leads, 2 `statement_beyond_quote`, 1 `fetch_page` `unknown_company`.
- **Serenity arm:** the brief in the chat of 2026-10-19 (power equipment, the robotics brief with copies counted as leads and the as-of bound stated), about 61 calls. The skill was identified by folder hash, since the copy had no git metadata.

| | Atlas | Serenity arm |
|---|---|---|
| Gas-turbine output (GW/yr) | Context only | Chokepoint 1, primary: GEV's release and 10-K, MHI's Q&A |
| Hot-section castings | Its strongest lead | Chokepoint 3, named, lead-level |
| HV transformers and substation gear | One primary step: IREN's 10-K lead times, the same ranges as a year earlier (Atlas said so) | Chokepoint 2, primary on demand against supply: GEV, Hitachi Energy, the DPA determination |
| Grain-oriented electrical steel | Lead | Rejected: concentration shown, scarcity not |
| Dry-type transformers (the skill's own thesis) | Not examined | Rejected on Hammond's filing (backlog falling, lead times shorter), contradicting the skill |
| Primary sources on steps | 1 | 11 |

**Convergent:** castings, transformers and substation gear, the turbine slot book. **Divergent:** electrical steel. **Independent of the skill:** both arms. The arm's two deep-dives are its own research, and it overturned the skill's power thesis on a primary filing.

**Quotes checked by the lead** (sources downloaded): 30 of 31 verbatim, across GEV's release and 10-K, MHI, Howmet, the Federal Register, Hammond, Hitachi Energy, Hitachi Energy India and NKT. The miss is "Scheduled for completion in FY28." (P9), possibly worded otherwise.

**Same cause as round 1:** reach. Ticket W9 (the in-run lead rule, `fetch_page` beyond the universe and for publishers, EDGAR filings by URL) and W9b (site register entries) are in progress.
