# Study Hindsight and specify the memory-quality effort

Type: research
Status: resolved
Blocked by: none

## Question

The owner asked (2026-10-02) for a close reading of how Hindsight 0.10.1 works, so that Atlas makes the best possible use of its memory, and then for a set of tickets that addresses what the reading shows.

- Read the pinned docs (`.agents/skills/hindsight-docs/`), the feature matrix and Atlas's own use of Hindsight (the gateway, retention, recall, the reading pointers, the mental models, the bank template). The lead reads the concept pages; six Opus readers take the configuration reference, the API surface, reflect and mental models, the changelog and model guidance, and Atlas's code. Every finding carries a verbatim quote the lead checks against the file.
- Check the findings against production with read-only calls where one call settles it.
- Write the verified findings to `docs/research/` and the spec with `to-spec`, then the tickets with `to-tickets`.

The answer points at the findings file, the spec and the tickets, and says how each reader's artifact held up against its brief.

## Answer

Resolved by the lead on 2026-10-02; the owner approved the ticket breakdown the same day.

- **Findings:** `docs/research/hindsight-memory-use.md`. Seven findings, each marked observed, documented or open. The largest is not a missing feature: production records 695 retained sections as completed and 1,907 as failed. Then: observations never cross a company, a form or a source; recall is asked with the query, the budget and the tags only; Atlas passes Hindsight neither the companies it knows nor a usable context; reflect runs at its shallowest setting and cannot see Atlas's mental models; the shared server embeds without the model's query instruction and with thresholds calibrated for another model.
- **Spec:** `.scratch/atlas-memory-quality/spec.md`. **Tickets:** `.scratch/atlas-memory-quality/issues/` 01 to 15. Two came from the owner's reply: 14, a conformance check that says behaviour by behaviour whether Memory works as advertised, and 15, the embedding model measured and decided (the owner offered a different model).
- **The readers:** six Opus readers, 110 findings, every quote found verbatim in the file it cites (`.scratch/tools/study_audit.py`; notes in `.scratch/hindsight-study/`). The lead confirmed on production or in the cluster's manifests what they marked unverified. One over-reach: the API reader took "10 to 14 memories per recall" from the synthetic recordings; production returned 45. Three findings came back from three or four readers working apart.
- **Order:** ticket 20 builds and releases the effort; investigations 2 to 5 wait for it.

## Comments

**2026-10-02, the lead: the order of work.** Investigation 1 on 0.3.0 (ticket 15) is run and reviewed as planned: it is the before-measure and separates Memory's defects from the roles'. Investigations 2 to 5 (tickets 05 to 08) wait for the release of this effort, so the five verdict runs are on one version. Recall-side changes act at once; intake-side changes (observation scopes, context, entities, labels) need the corpus re-extracted or re-consolidated, so the spec carries a backfill and its budget.

First finding, confirmed on production by one read-only recall (`.scratch/live-runs/hindsight-probe/probe-recall.json`, not in git): every observation carries its source facts' full tag set (company, theme, source, document type, form), because Atlas sends no `observation_scopes` and the default is `combined`. Nothing consolidates across companies, or across a company's forms.
