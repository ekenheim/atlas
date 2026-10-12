# 21: The Hypothesis page as the product

Type: build
Status: open
Blocked by: 14

## What to build

`frontend/app/hypothesis/`, `components/hypothesis.tsx`, `lib/hypotheses.ts`: the thesis first; the six steps with each Belief's judgement, confidence and as-of; each citation's quote opening the source viewer at its span; counterevidence and falsifiers; open Issues; predictions and settlements (19, when it exists); the owner's rules (dark, terse, no commands, the assessment first). `app/theme/`: the theme's Hypotheses, then the Beliefs by step; a "what changed" feed (`GET /api/v1/themes/{id}/changes`: Belief flags, new judgements, new Facts, newest first).

## Acceptance criteria

- [ ] Playwright on the seeded Hypothesis and theme; the owner reads one real page and says what is missing (recorded on the ticket).
