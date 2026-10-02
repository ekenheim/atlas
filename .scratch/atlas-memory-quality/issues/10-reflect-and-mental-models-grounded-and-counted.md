# 10: Reflect and the mental models: grounded, and counted

**What to build:** A reflect answer searches at a real depth and cites memories that resolve to sections. The two mental models rest on the theme's memories and never on each other. Every reflect and every refresh shows in the budget.

Spec: `.scratch/atlas-memory-quality/spec.md` ("Reflect and the mental models", and the trigger and reflect settings under "The bank template"). Study: finding 6. Recordings: ticket 01 (reflect's `budget` and `exclude_mental_models`, a tagged model and a tag-scoped reflect, the template schema's trigger fields).

- Reflect requests carry `budget` (request field on `POST /api/v1/memory/reflect`, default `mid`) and `exclude_mental_models` (default true: an answer's citations must resolve).
- The template's bank section: reflect's own recall returns no raw chunks and includes the facts behind observations (the per-bank fields the recorded schema names). Each model's trigger gains `exclude_mental_models: true` and `keep_trace: true`.
- The two models are tagged with their theme. A refresh then reads the theme's memories; whether a theme-scoped reflect that does not exclude models sees them is shown by the recording and stated in the decision entry.
- A citation of a mental model in a reflect answer is reported as such (kind `mental_model`, never resolved to a section) instead of being dropped.
- Every reflect and every refresh Atlas submits adds one unit to the `codex` budget. Atlas's daily job is the only scheduler: the template keeps its rule that no model may run away, and Hindsight's own cron is kept from firing in the way the recorded schema allows; the refresh records show who refreshed.
- `docs/decisions.md`: "Reflect and the models: grounded and counted"; `docs/runbooks.md`: the budget's new units.

Migration revision `0066` (down: main's head), only if a record needs it.

**From ticket 01 (the matrix's answer (d); recordings `reflect_options/`, `tagged_mental_model/`):** on 0.10.2 a reflect's cited world fact carries `document_id`, `chunk_id`, `metadata` and `tags`, so it resolves to its section in one hop; a cited observation still needs the hop through its sources. A mental-model trigger takes `budget`. Build to the recordings, and simplify the resolver's reflect path where the new fields allow it.

**Blocked by:** 01

**Status:** done

- [x] Integration test at the API seam: a reflect is sent with `budget` and `exclude_mental_models`; the answer's citations are labelled; a model citation is reported with its kind.
- [x] A reflect job and a refresh job each add one `codex` unit (the queue read shows it); a spent window holds them as today.
- [x] The template validates and imports through the fake with the new trigger and bank fields and the theme tags; a template whose model could run away is still invalid.
- [x] The refresh record says Atlas's job refreshed; a model already refreshed inside its interval is still skipped.
- [x] API client regenerated; decision and runbook entries; `AGENTS.md` line.
