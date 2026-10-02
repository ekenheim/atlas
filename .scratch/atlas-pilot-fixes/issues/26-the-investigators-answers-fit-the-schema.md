# 26: The Investigator's answers fit the schema the first time

**What to build:** An Investigator call that answers with a field the schema does not have is not sent back for a whole new answer. In the fifth run 28.5% of all tokens were repairs.

Evidence: production 0.3.1, investigation `452c3b9d-2e2f-4cc6-bc54-5130155b9aac` (pilot investigation 1, fifth run; reviewed in `.scratch/pilot/results.md`, "Investigation 1, fourth and fifth runs"); `GET /runs/{run_id}/role-calls`: 29 of 72 Investigator calls needed the repair (33 failed attempts in the run, 407,409 tokens in and 45,170 out). The validation errors: an extra `subject_name` in 20 answers, an extra `claim_id` in 10, a missing `object_text` in 5. The repair resends the conversation and asks for the full answer again.

- Find why the model adds those two fields (the request carries `subject_name`-like fields for the universe's companies and the passages; `claim_id` is nowhere in the Investigator's contract) and remove the cause in the prompt or the request (`investigator.v9`).
- An extra field the response model does not name is dropped by code and recorded on the attempt (`ignored_fields`), not a validation error: the roles' answers are checked by what they must contain; an unknown extra key carries nothing code would use. This is for every role (the Financial Analyst's quarantined call in the same run was an extra `data_gaps`). A missing required field stays an error.
- A missing `object_text` where the Claim has an `object_name` or is company-level is not an error (check what the schema requires against what the checks need).
- The run's read shows repairs per role (`GET /runs/{id}/role-calls` already has attempts; add a count to the investigation's usage).

**Blocked by:** None

**Status:** ready-for-agent

- [ ] Integration test at the role-call seam: an answer with an unknown extra field is accepted, the field recorded as ignored, no second request made; an answer missing a required field is repaired as today.
- [ ] The strict JSON schema sent to the model is unchanged in what it requires (a test compares it), or the change is stated in the decision entry.
- [ ] `investigator.v9` and its prompt tests; the scripted evaluation cases pass.
- [ ] Decision entry ("Roles: an unknown field is ignored, a missing one repaired"); `AGENTS.md` line.
