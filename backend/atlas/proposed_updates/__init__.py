"""Proposed updates (spec §5.6, §5.7 "Contradiction flow"; ticket 21): a later Source Version
or Assertion that contradicts what a published Hypothesis version depends on flags the
Hypothesis (and the Candidates it concerns) with a proposed update listing the contradicting
Evidence. The published version and its Research Snapshot never change.

- `triggers`: the version's dependencies, recorded when it is published, and the hooks that
  enqueue the `check_contradictions` job where each contradicting event is recorded.
- `detection`: that job (deterministic, no LLM).
- `model`: the read side; `service`: the owner's accept (a correction) or dismiss.

Only `triggers` is imported here: the ledger, the Assertions and the Relationships call its
hooks, and must not import the Hypotheses through this package.
"""

from atlas.proposed_updates.triggers import (
    CHECK_CONTRADICTIONS_KIND,
    on_assertion_reviewed,
    on_counterevidence,
    on_relationship_rejected,
    on_source_revised,
    record_dependencies,
)

__all__ = [
    "CHECK_CONTRADICTIONS_KIND",
    "on_assertion_reviewed",
    "on_counterevidence",
    "on_relationship_rejected",
    "on_source_revised",
    "record_dependencies",
]
