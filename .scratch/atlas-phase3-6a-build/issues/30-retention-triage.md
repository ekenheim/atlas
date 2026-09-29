# 30: Retention triage (read first, retain what adds durable value)

**What to build:** Nothing goes into Hindsight just because it was ingested. Each new English Source Version is archived and parsed as today. A cheap **Triage** role (MiniMax via LiteLLM, under ticket 27's pacing) then reads it section by section and decides what is worth retaining for the theme's bottleneck questions. Only the sections it selects are retained. The rest stay archived and citable, and can be retained on demand later. This is the Serenity method's promotion rule (keep a post only when it adds something durable, otherwise record it as data only; `docs/research/serenity-skills-alignment.md` V11) applied to Atlas's sources, with Atlas's evidence rules intact.

Owner direction (2026-09-29): "everything seems like token bloat. We should be able to read and figure out its value?"

**Blocked by:** None (can start immediately). Coordinate with 27, which adds pacing to the same job kinds.

**Status:** ready-for-agent

- [ ] A Triage role with a strict schema. For each section it gets the heading, the first ~1,500 characters and the document's metadata, and returns `retain` or `skip`, a value category and a one-line reason. The rubric is versioned in the repo and targets durable, bottleneck-relevant content:
  - named suppliers or customers
  - capacity additions or constraints
  - qualifications and design wins
  - input shortages and lead times, and pricing power
  - substitutes and second sources
  - dilution and financing (S-3/424B/ATM)
  - segment guidance on the theme
  - material risk changes

  Boilerplate (forward-looking-statement legends, signatures, exhibit indexes, generic risk text unchanged from the prior version) is `skip`.
- [ ] Deterministic pre-filter before any LLM call: sections identical (by content hash) to the previous version's retained or skipped section inherit that decision. Known boilerplate headings skip.
- [ ] Retention retains only the `retain` sections. A `triage_decision` record per section is kept (insert-only, audited), with its reason, the rubric version and the role call.
- [ ] Retain on demand: an investigation or the owner can retain a skipped section (`POST /api/v1/source-versions/{id}/sections/{anchor}/retain`), recorded with who asked and why.
- [ ] Owner visibility: `GET /api/v1/triage` lists decisions with filters. Metrics: sections retained or skipped by category, and estimated Hindsight operations saved.
- [ ] Setting `ATLAS_RETENTION_TRIAGE` (`on` by default when LiteLLM is configured; `off` retains every section as before).
- [ ] Tests at the worker-pass seam with the scripted LiteLLM fake: boilerplate is skipped without a call, a supplier-naming section is retained, an unchanged section inherits, and retain on demand works.
