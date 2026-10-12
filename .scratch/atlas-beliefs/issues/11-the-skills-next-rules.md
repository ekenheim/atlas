# 11: The skill's next rules, from the closing measure

Type: build
Status: ready-for-agent
Blocked by: none

## What to build

In `.claude/skills/atlas-research/SKILL.md` and `atlas_tools.py` (the lead's): a Fact's statement is held to its quote as a card statement is (no clause from the context, no hedge dropped); a quote long enough to carry the clause the statement needs; one proposition per Belief; a call bound of about 150 when the judge loop is on; a statement the judge rejects twice becomes an Issue (`issue open --kind question`), not a drop.

## Acceptance criteria

- [ ] The rules are in SKILL.md; `belief propose` warns on a statement that joins two dated documents.
- [ ] Question 2 once more by hand, scored by the pilot's procedure: precision at or above 95%, the trust gate at or below 10% (`.scratch/pilot/results.md`).
