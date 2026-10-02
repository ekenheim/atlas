# Investigation 1 on the memory-directed reading release

Type: task
Status: resolved
Blocked by: 14

## Question

Run pilot investigation 1 a fourth time (the same question; seeds Coherent and Lumentum) on the release of ticket 14, and review it with the `pilot-review` skill against the verdict criteria and the baseline.

Against the 0.2.5 run (`ead2b86e-3556-42ba-9f3e-08660a938f98`): does the reading reach AXT (the 6-inch InP supply agreement with Coherent, the export-permit backlog), the allocation statement, the NVIDIA purchase commitments and the slides' capacity figures; which selection found each accepted Claim (pointer, search, entity, lead); what did recall cost (calls, memories, pointers); and is "contradicted" on the card now true?

The answer points at the results section and lists new defect tickets.

## Answer

Resolved by the lead on 2026-10-02. Results: `.scratch/pilot/results.md`, "Investigation 1, fourth and fifth runs". The run on 0.3.0 ended with no card (the comment below); the run on 0.3.1, `452c3b9d-2e2f-4cc6-bc54-5130155b9aac`, is the one reviewed.

**It does not meet the bar.** Two measures fail: the trust gate's second half (nine of eleven findings state something no cited Claim says; five misstate one) and latency (34 minutes 45 seconds against 20). The others hold: 182 of 182 quotes verbatim; Claim precision 154 of 182 (84.6%) strict, 161 of 182 (88.5%) lenient; nine findings with a correct on-question core; baseline coverage 5 of 10 strict, 10 of 10 lenient; the roles ran; 1,586,388 tokens.

**The ticket's questions:**
- *Does the reading reach AXT?* Yes. AXT was added from 159 pointers; its Investigator read its 10-Q of 2026-08-13, its 8-K of 2026-07-29, a results call and a conference, and 36 Claims were accepted: the Master Development and Supply Agreement with Coherent for 6-inch InP substrates, the Capacity Reservation Agreement with Lumentum, demand outpacing a tripling capacity. The export-permit backlog is not on the card: the Skeptic proposed its sentence and it was rejected on an offset (pilot-fix ticket 28).
- *The allocation statement?* Not as the 10-K writes it: no filing of either seed was read (pilot-fix ticket 24). The calls say it more bluntly, and that is on the card: Lumentum "very much sold out in our high-powered laser fab"; its "indium phosphide wafer fab capacity remains at a premium, fully allocated" is the sentence before an accepted quote.
- *The NVIDIA purchase commitments?* In part: Coherent's multi-year supply agreement with NVIDIA covering "multiple CPO-related products, including our high-power CW laser" and NVIDIA's $2 billion equity investment are accepted Claims, from the call. The commitments in the 8-Ks were not read.
- *The slides' capacity figures?* No: the figures the baseline finds in slides and filings (the "3X InP capacity increase", 250 million InP lasers shipped) are covered only in substance.
- *Which selection found each accepted Claim?* It cannot be told: the `search` tag is on every passage of every reading task (pointer 236 tags, search 182, entity 58 over 182 Claims). Pilot-fix ticket 28.
- *What did recall cost?* No LLM token. 47 recalls (Scout 11, Skeptic 36), 2,089 memories, 4,121 pointers, about 5 minutes of the 35.
- *Is "contradicted" on the card now true?* Yes, as far as it goes: the Skeptic accepted no contradiction and the card claims none. But it read documents of AXT and IQE only, so for the other four companies the card's silence means "not checked" (pilot-fix ticket 25).

**New defect tickets** (`.scratch/atlas-pilot-fixes/issues/`): 21 a finding says more than its Claims (the trust gate; a blocker); 22 an analyst's words accepted as the company's; 23 plans, ramps and objects outside the quote; 24 a seed's filings go unread; 25 the Skeptic checks two of six companies; 26 the Investigator's answers carry extra fields (28.5% of the tokens are repairs); 27 role calls run one after another; 28 smaller ones.

**How the review was done and how the reviewers held up:** fifteen Opus reviewers on files cut from the saved run; every Claim judged twice, blind (174 of 182 agree, kappa 0.81; the lead adjudicated the eight, confirmed the 21 both called wrong, and checked a sample of 18 both called right: all hold); the card, the baseline and the run by one reviewer each. One judge mistyped two Claim IDs, which the lead's audit caught and matched. The run reviewer said plainly what its file did not contain rather than inferring it.

## Comments

**2026-10-02, the lead: the first run on 0.3.0 ended with no card (a blocker); run again on 0.3.1.**

- **ID:** `fcb1ef32-50fd-4788-84c3-e2397a92dd97`, seeds Lumentum and Coherent, 2,000,000 token budget in the request. Started 07:34:24 UTC, stopped 08:04:57 (30.5 minutes, with a pod restart at 07:54 when the owner merged the settings PR #7194; no budget pause). 1,243,309 tokens in, 111,002 out, 77 role calls (three MiniMax 529 "overloaded" errors among them, each retried).
- **What worked:** the Scout made 11 recalls and stored 1,074 pointers; the plan grew from the two seeds to six Investigators (AXT 128 pointers, IQE 37, Applied Optoelectronics 5, Soitec 2; Fabrinet had no room). 89 Claims were accepted (AXT 35, Lumentum 21, Coherent 18, Applied Optoelectronics 8, IQE 7, Soitec 0), and every quote is verbatim at its span (`.scratch/tools/pilot_audit.py gate 1`). The Skeptic made 36 recalls (2,876 pointers), read 12 documents its pointers led to and accepted 41 items, all bear context, no contradiction.
- **The blocker:** the Editor's answer was cut off at its 4,096-token output cap on all six attempts, so the investigation stopped `needs_review` with no research card. Memory-quality ticket 16 fixes it (`.scratch/atlas-memory-quality/issues/16-the-editors-card-fits-a-multi-hop-investigation.md`); it is released as 0.3.1.
- **Not reviewed:** the 89 Claims of this run are not judged one by one; the run on 0.3.1 is the one reviewed, since its Claims will differ. The saved run is in `.scratch/live-runs/pilot-0.3.0/inv-1/` (not in git).
