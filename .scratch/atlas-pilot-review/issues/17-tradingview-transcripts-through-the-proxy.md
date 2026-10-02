# TradingView transcripts for the universe through the cluster proxy

Type: task
Status: claimed
Blocked by: none

## Question

The owner put TradingView's MCP server in the cluster behind a read-only proxy and asked the lead to use it (2026-10-01). Atlas 0.2.5's TradingView source works against it with configuration alone (`docs/decisions.md`, "TradingView through the cluster's MCP proxy"). Get the universe's earnings-call and conference transcripts into the archive and into Memory before the reviewed pilot runs:

- home-ops PR #7178 (the three settings; the nightly `tradingview_catalog` job per universe company) is merged by the owner;
- the first catalog jobs succeed in the cluster (the pods reach the proxy; no authorization error);
- for each seed company of the five investigations: transcripts in the ledger (provider `tradingview`, Tier B), parsed, and retained;
- what it costs: tool calls against the `tradingview` budget and Codex operations for the retains.

This also does the live check that build tickets 26 and 31 were paused for. The answer records the counts per company and anything the first jobs show (transcript parsing, speaker turns, the party check on spoken "we").

Open decision to record when the first transcript Claims exist: a management statement in a transcript is Tier B, and today only Tier A Evidence can make a `machine_reviewed` edge, so every transcript edge goes to the owner's queue.

## Comments

**2026-10-02 (08:50 UTC), the lead: the transcripts are in the ledger for every company but Innolight; Memory has them for five companies so far.** Read from production (`.scratch/tools/transcript_counts.py`, read-only). Home-ops #7178 is merged, the nightly catalog jobs ran (catalog rows last seen 2026-10-02 01:39 UTC), and 149 of the catalog's 151 call and event transcripts are Source Versions, all parsed (Marvell's last two wait for the next nightly job: 20 calls a job).

| Company | Catalog transcripts | In the ledger | Parsed | Sections completed | cancelled or failed | pending | zero-fact | Facts |
|---|---|---|---|---|---|---|---|---|
| AXT | 10 | 10 | 10 | 36 | 0 | 0 | 0 | 680 |
| Applied Optoelectronics | 13 | 13 | 13 | 59 | 0 | 0 | 0 | 1389 |
| Ciena | 13 | 13 | 13 | 0 | 0 | 0 | 0 | 0 |
| Coherent | 13 | 13 | 13 | 65 | 0 | 0 | 0 | 1240 |
| Fabrinet | 14 | 14 | 14 | 9 | 0 | 4 | 0 | 211 |
| IQE | 4 | 4 | 4 | 0 | 0 | 0 | 0 | 0 |
| Lumentum | 25 | 25 | 25 | 106 | 0 | 0 | 0 | 1909 |
| MACOM | 8 | 8 | 8 | 0 | 0 | 0 | 0 | 0 |
| Marvell | 22 | 20 | 20 | 0 | 0 | 0 | 0 | 0 |
| STMicroelectronics | 20 | 20 | 20 | 0 | 0 | 0 | 0 | 0 |
| Soitec | 9 | 9 | 9 | 0 | 0 | 0 | 0 | 0 |
| Zhongji Innolight | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| **All** | 151 | 149 | 149 | 275 | 0 | 4 | 0 | 5429 |

- The six companies with no section yet (Ciena, IQE, MACOM, Marvell, STMicroelectronics, Soitec) are in the retain queue, which was held by the Codex budget until the owner merged home-ops #7194 at 07:54 UTC; it is draining under the `hindsight_minimax` budget (93 retains queued at 08:26 UTC). Three of them are seeds of investigations 4 and 5.
- Soitec's nine transcripts are in English, so Memory will hold Soitec through them although its AMF filings are French.
- Innolight has no transcript on TradingView (its catalog holds eight interim and annual reports, which are not retrievable). News through TradingView was considered and dropped with the owner (memory-quality tickets 17 and 18, `wontfix`), so Innolight stays uncovered until the owner imports documents or holds a licence.
- These retains carry the old context (for a transcript, "Q4 2026: chunk-004"); the backfill (memory-quality ticket 12) re-extracts them under the new profile.
- Open decision from the question, still open: a management statement in a transcript is Tier B, and only Tier A Evidence makes a `machine_reviewed` edge, so every transcript edge goes to the owner's queue.

Resolved when every seed company of the five investigations has its transcripts in Memory; the lead checks again when the queue has drained.
