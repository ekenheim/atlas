# 04: EDGAR filing phrases are specific, and a filer needs a kept hit to become a Candidate

**What to build:** A discovery proposes Candidates that belong to the theme. Evidence: discovery `ca235cf4-e60c-408e-a8a8-83fc6f43dd43` proposed 16 Candidates, about 5 on the theme; the phrases `"VCSEL"`, `"CW laser"`, `"MOCVD"` and `"export controls"` brought lidar makers, medical lasers and others (pilot-fix ticket 20, which this supersedes).

Spec: `.scratch/atlas-memory-directed-reading/spec.md` ("Filing phrases").

- A filing phrase is searched in EDGAR only when it has at least two words or is a product or layer term of the lead-ranking config; otherwise the query's EDGAR search is skipped and recorded as skipped with the reason. The Scout's and the Skeptic's prompts ask for a specific phrase and show the difference.
- A filer outside the universe becomes a Candidate only when at least one of its filing leads scores at or above the ranking's keep threshold, where a filing lead is scored against the query and its purpose as a web lead is, not against the phrase alone.
- A filer that is already a counterparty company is proposed as a Candidate once, linked to the counterparty (the promotion path of the counterparty decision); record that in the decision entry.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] At the discovery seam with the EDGAR fake: a one-word phrase that is not a theme term makes no EDGAR search and no Candidate; `"InP substrates"` still proposes Aeluma; a filer whose only hit scores under the threshold is not proposed.
- [ ] Unit tests of the phrase rule and of filing-lead scoring.
- [ ] Decision entry with the pilot discovery's phrases and filers; prompt versions bumped; no migration unless the skipped search needs a column (use the revision the lead names).
