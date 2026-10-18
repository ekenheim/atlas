# UI follow-ups after 0.6.14 (backend tickets 30 and 31)

Adopt once 0.6.14 is live, on the rebased UI branch with the client regenerated:

1. **Thesis check, effective verdict only.** `thesisCheck` reads only `version.thesis_judgement` (`{verdict: supported|misstated|unjudged, reason, at, by, source: draft|correction|rejudge} | null`): the backend resolves the effective verdict, so drop the fallback to `content.thesis_judged`. Status words: supported → "Checked", misstated → "Overreaches" (gap), unjudged or null → "Not checked" (warn).
2. **"Check the thesis" action** where the gate shows `thesis_unchecked` (the dossier's gate banner and the Decide item): `POST /api/v1/hypotheses/{id}/versions/{n}/judge-thesis` (no body, or `{note?}`). 201 answers with the whole Hypothesis (re-render from it). 409 `not_belief_backed` or `thesis_misstated_stands` (a misstated verdict on the same text changes only by a correction: say so and point to the correction). 503 `judge_unavailable` (retry later). `GATE_EXPLANATIONS.thesis_unchecked` must name the button, not an action no page offers.
3. **Agents:** session items' `agent` (scout|researcher|skeptic|editor|lead), `beliefs_proposed`, `beliefs_examined` {confirmed, qualified, contradicted, nothing_new}, `issues_opened` (older sessions read `lead` unless their question opens with "Scout:", "Skeptic:" or "Editor:").
4. **Hypotheses by theme:** `GET /api/v1/hypotheses?theme=<slug>` (`theme` wins over `theme_id`) in place of the client-side filter.
5. **Freshness:** Beliefs' `newest_evidence_at` for the theme-level "newest evidence" line (spec §5.3).
6. **Conflicts to expect on the rebase:** tickets 30 and 31 edit `frontend/lib/hypotheses.ts`, `lib/hypothesis-steps.ts`, `unit/hypothesis-page.test.ts`, `unit/beliefs.test.ts` and regenerate `lib/api/*`. Keep their effective-verdict logic and the `thesis_unchecked` gate text.
