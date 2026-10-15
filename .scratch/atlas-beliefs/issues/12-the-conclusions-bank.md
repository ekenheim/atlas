# 12: The conclusions bank: judged Beliefs in a Hindsight bank of their own

Type: build
Status: done
Blocked by: none

## What to build

A second Hindsight bank, `atlas-beliefs` (`Settings.hindsight_beliefs_bank_id`), with its own versioned template `configs/hindsight/bank-template-beliefs.json` (a `retain_mission` for propositions and the evidence they cite; the built-in observations rules; `entity_labels` as the research bank's; one observation scope per theme tag; `enable_auto_consolidation: false`; `audit_log_enabled: true`; the same pinned server defaults the research template pins), applied by `atlas hindsight apply-template --bank beliefs` (dry-run then import, the version recorded as for the research bank). `retain_belief` (`atlas.retention.beliefs`) writes to this bank; `POST /api/v1/memory/recall` takes `bank: "beliefs" | "research"` (default `research` for existing callers; the skill's `recall` defaults to `beliefs` and takes `--bank research` for the legacy index); the provenance resolver resolves a `belief:` memory of either bank; `GET /api/v1/memory/health` reports both banks (`beliefs.bank`). `uv run atlas memory beliefs re-retain` enqueues `retain_belief` for every judged Belief (the two on production move to the new bank; their old documents deleted from the research bank, recorded as replacements). The conformance check (`scripts/memory-conformance.sh`) gains the beliefs bank's existence and template version as a known answer.

## Acceptance criteria

- [x] Worker tests with the Hindsight fake: retain into the beliefs bank, recall by bank, health per bank, the re-retain command; settings tests.
- [x] `docs/decisions.md` ("Memory holds what was found" extended: two banks, what each holds), `docs/runbooks.md` (applying the beliefs template; re-retain), `AGENTS.md`.
- [ ] On production after the release (the lead): the template applied, the two Beliefs re-retained, a session's `recall --bank beliefs` returns one (ticket 06's probe, recorded in `docs/experiments.md`).
