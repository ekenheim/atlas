# Study Hindsight and specify the memory-quality effort

Type: research
Status: claimed
Blocked by: none

## Question

The owner asked (2026-10-02) for a close reading of how Hindsight 0.10.1 works, so that Atlas makes the best possible use of its memory, and then for a set of tickets that addresses what the reading shows.

- Read the pinned docs (`.agents/skills/hindsight-docs/`), the feature matrix and Atlas's own use of Hindsight (the gateway, retention, recall, the reading pointers, the mental models, the bank template). The lead reads the concept pages; six Opus readers take the configuration reference, the API surface, reflect and mental models, the changelog and model guidance, and Atlas's code. Every finding carries a verbatim quote the lead checks against the file.
- Check the findings against production with read-only calls where one call settles it.
- Write the verified findings to `docs/research/` and the spec with `to-spec`, then the tickets with `to-tickets`.

The answer points at the findings file, the spec and the tickets, and says how each reader's artifact held up against its brief.

## Comments

**2026-10-02, the lead: the order of work.** Investigation 1 on 0.3.0 (ticket 15) is run and reviewed as planned: it is the before-measure and separates Memory's defects from the roles'. Investigations 2 to 5 (tickets 05 to 08) wait for the release of this effort, so the five verdict runs are on one version. Recall-side changes act at once; intake-side changes (observation scopes, context, entities, labels) need the corpus re-extracted or re-consolidated, so the spec carries a backfill and its budget.

First finding, confirmed on production by one read-only recall (`.scratch/live-runs/hindsight-probe/probe-recall.json`, not in git): every observation carries its source facts' full tag set (company, theme, source, document type, form), because Atlas sends no `observation_scopes` and the default is `combined`. Nothing consolidates across companies, or across a company's forms.
