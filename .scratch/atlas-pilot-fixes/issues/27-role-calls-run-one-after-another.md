# 27: Six Investigators take 23 minutes because role calls run one after another

**What to build:** An investigation's wall time fits the pilot's bar (20 minutes) when it reads six companies.

Evidence: production 0.3.1, investigation `452c3b9d-2e2f-4cc6-bc54-5130155b9aac` (pilot investigation 1, fifth run; reviewed in `.scratch/pilot/results.md`, "Investigation 1, fourth and fifth runs"): 34 minutes 45 seconds; 85 role calls with no two overlapping; 1,748 seconds inside role calls; the six Investigators ran from 10:09:02 to 10:32:30; the recalls took about 5 minutes (the Skeptic's 36 took 233 seconds, the Scout's 11 took 78). The worker runs one job at a time, and an Investigator makes its 12 calls in sequence.

Decide:
- Whether Investigator tasks of one round run concurrently (several workers, or one task making its calls concurrently), within the MiniMax plan's 3 to 4 concurrent agents, of which Hindsight's extraction may use 2.
- Whether the Skeptic's 36 recalls run concurrently (they make no LLM call).
- What ticket 26 (repairs) alone gives back: 28.5% of the tokens, and their time.
- Or whether the latency bar moves with the multi-hop plan as the cost bar did, with the reason.

**Blocked by:** 26

**Status:** needs-triage

- [ ] The decision in `docs/decisions.md` with the measured times of this run and of the first run after ticket 26.
