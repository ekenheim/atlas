# 16: The Editor's card fits a multi-hop investigation

**What to build:** An investigation with many accepted Claims ends with a research card. Today the Editor's answer is cut off at its output cap and the investigation ends with no card at all.

A blocker under the pilot-review map's focus rule (no card), found on production 0.3.0. It is released by itself as a patch (0.3.1) so investigation 1 can be run again; it does not wait for the rest of this effort.

Evidence: investigation `fcb1ef32-50fd-4788-84c3-e2397a92dd97` (2026-10-02, six Investigators, 89 accepted Claims). The Editor task failed after 3 attempts, role calls `a6313db9-0ce9-4dd8-8dfb-f63a053b6ae2`, `60b0c792-f6d5-4f5a-b5ae-cc71fd0b9e77` and `4e76a562-790a-4944-b1df-0d0ed8fc04c0`: each of the six model answers used exactly 4,096 output tokens and ended in the middle of a list of Claim IDs ("Invalid JSON: EOF while parsing a string"); the repair call was sent with the same cap and was cut the same way. The Editor's request was about 38,000 tokens. Investigations before 0.3.0 had 10 to 31 accepted Claims and two or three Investigators.

- **A cut-off answer is its own outcome.** When the model stops at the output cap (the completion's finish reason, or the tokens used equal to the cap), the role call is recorded as truncated, not as a schema failure, and no repair is sent with the same cap.
- **The Editor's cap follows the work.** The cap for the research card is a setting (`ATLAS_EDITOR_MAX_OUTPUT_TOKENS`, default 16,384, the role's bound); a truncated answer is retried once with the cap doubled up to that bound, within the run's token budget.
- **Claims are cited by a short reference.** The Editor is sent each Claim with a short reference (`c1`, `c2`, …) and cites those; code maps them back to Claim IDs and rejects an unknown reference as today's unknown ID. A 36-character ID per citation is most of what overflowed. This is a new prompt version (`editor.v6`); the Hypothesis draft's prompt is left alone unless it shares the request.
- **An investigation never ends card-less.** If the Editor still fails, the investigation stops `needs_review` with a card that has no finding and says so: the accepted Claims by company, the contradictions and bear context, what was searched and read, and the reason the Editor failed. The Evidence tray is unchanged.
- The other roles keep their caps; the truncated outcome applies to every role's calls and is shown in `GET /api/v1/runs/{id}/role-calls`.
- `docs/decisions.md`: "A cut-off answer is not a schema failure; the card never goes missing".

No migration is expected (the role call's status is a string; if a constraint lists the statuses, use revision `0061` and say so).

**Blocked by:** None (can start immediately)

**Status:** done

- [x] Integration test at the investigation seam with the scripted LiteLLM fake: 90 accepted Claims and an Editor answer cut at the cap; the call is recorded truncated, retried with the larger cap, and the card has its findings with Claim IDs mapped back from the short references.
- [x] An Editor answer that cites an unknown reference is rejected as an unknown Claim is today.
- [ ] An Editor that is cut off at the bound too, or quarantined, leaves the investigation `needs_review` with the fallback card (no finding; Claims by company; the reason); the read returns it and the investigation page shows it.
- [x] A truncated answer of another role is recorded truncated and handled by that role's existing failure path (no behaviour change beyond the status).
- [x] The evaluation cases and the e2e seeds that script Editor answers are moved to the short references; `atlas evaluate` (fake mode) passes.
- [x] Decision entry; `AGENTS.md` line; API client regenerated if the read changes.

The third box is left open only for its last clause: the read returns the fallback card (tested), and the investigation page renders it (`EditorFailed`), but no test renders the page with it (the e2e was not run and has no such scenario); see the implementation log.
