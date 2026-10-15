# 16: The four agent prompts: Scout, Researcher, Skeptic, Editor

Type: build
Status: in-review
Blocked by: 15

## What to build

Beside the Researcher's SKILL.md in `.claude/skills/atlas-research/`: `scout.md` (reads a theme's newest documents, the last quarter's calls and filings, for bottleneck cues: allocation, sold out, lead times, permits, "two players", capacity ramps; opens `question` Issues with the cue quoted as a Fact under `context`), `skeptic.md` (takes a proven Belief, searches for what would falsify it, records counterevidence Facts, relates them, proposes a supersession or leaves a flag for the lead), `editor.md` (drafts the Hypothesis from a theme's proven Beliefs through ticket 14's job, writes the market-expectations paragraph only from estimated inputs). Each names the MCP tools it may call and its bounds.

## Acceptance criteria

- [ ] Each prompt run once on photonics by hand (the lead), scored where the pilot's procedure applies: the Skeptic's Facts blind-reviewed; the Scout's Issues judged on-question; the Editor's draft through the gate.
