# The `atlas-research` skill: a strong agent researches with Atlas's tools

Type: prototype
Status: resolved
Blocked by: none (run before 02 and 04 with the card as a file)

Spec §3. A repo skill whose tools wrap the public API (archive-search as-of, facts, recall, beliefs, issues) and whose text holds the method (six steps, bottleneck test, what counts as evidence; the researcher's-hour rules). First test: pilot question 2 and the AXT replay question (pilot-review 26) with a Fable or Opus session, scored exactly as the pilot scores a card (Facts blind-reviewed, trust gate on the proposed Beliefs' statements, researcher's facts held, cost). Memory as a tool only in this ticket; the store of conclusions is ticket 06.

## Done when

- [x] Two sessions scored beside the pipeline's rows in `.scratch/pilot/results.md`, "The proof sessions"; the decision in the map: the session is the method, the pipeline the bulk mode.

## Answer

Built as `.claude/skills/atlas-research/` (SKILL.md and `atlas_tools.py`: companies, search, read, locate, record, recall with an as-of filter on the resolved sections, fact) and run on question 2 and the AXT replay with Opus sessions (`.scratch/live-runs/proof-claude/`). Facts 100% and 93% right; 19 of the researcher's 32 facts on the card; the trust gate 25 of 35 and 24 of 26; about 170k tokens a session. Decision: taken. What the skill still lacks is in ticket 07.
