# Investigation 1 on the memory-directed reading release

Type: task
Status: claimed
Blocked by: 14

## Question

Run pilot investigation 1 a fourth time (the same question; seeds Coherent and Lumentum) on the release of ticket 14, and review it with the `pilot-review` skill against the verdict criteria and the baseline.

Against the 0.2.5 run (`ead2b86e-3556-42ba-9f3e-08660a938f98`): does the reading reach AXT (the 6-inch InP supply agreement with Coherent, the export-permit backlog), the allocation statement, the NVIDIA purchase commitments and the slides' capacity figures; which selection found each accepted Claim (pointer, search, entity, lead); what did recall cost (calls, memories, pointers); and is "contradicted" on the card now true?

The answer points at the results section and lists new defect tickets.

## Comments

**2026-10-02, the lead: the first run on 0.3.0 ended with no card (a blocker); run again on 0.3.1.**

- **ID:** `fcb1ef32-50fd-4788-84c3-e2397a92dd97`, seeds Lumentum and Coherent, 2,000,000 token budget in the request. Started 07:34:24 UTC, stopped 08:04:57 (30.5 minutes, with a pod restart at 07:54 when the owner merged the settings PR #7194; no budget pause). 1,243,309 tokens in, 111,002 out, 77 role calls (three MiniMax 529 "overloaded" errors among them, each retried).
- **What worked:** the Scout made 11 recalls and stored 1,074 pointers; the plan grew from the two seeds to six Investigators (AXT 128 pointers, IQE 37, Applied Optoelectronics 5, Soitec 2; Fabrinet had no room). 89 Claims were accepted (AXT 35, Lumentum 21, Coherent 18, Applied Optoelectronics 8, IQE 7, Soitec 0), and every quote is verbatim at its span (`.scratch/tools/pilot_audit.py gate 1`). The Skeptic made 36 recalls (2,876 pointers), read 12 documents its pointers led to and accepted 41 items, all bear context, no contradiction.
- **The blocker:** the Editor's answer was cut off at its 4,096-token output cap on all six attempts, so the investigation stopped `needs_review` with no research card. Memory-quality ticket 16 fixes it (`.scratch/atlas-memory-quality/issues/16-the-editors-card-fits-a-multi-hop-investigation.md`); it is released as 0.3.1.
- **Not reviewed:** the 89 Claims of this run are not judged one by one; the run on 0.3.1 is the one reviewed, since its Claims will differ. The saved run is in `.scratch/live-runs/pilot-0.3.0/inv-1/` (not in git).
