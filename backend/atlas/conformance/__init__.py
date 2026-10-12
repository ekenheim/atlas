"""The memory conformance check (memory-quality ticket 14): Memory works as Hindsight's
documentation and Atlas's spec promise, before anything is benchmarked.

- `known_answers`: the known-answers file, resolving each answer against a running Atlas and
  recalling the pilot's questions on the live bank (read-only, no LLM call).
- `beliefs_bank`: the conclusions bank exists and carries the repository's template version
  (beliefs ticket 12; read-only).
- `behaviours`: the ten behaviour checks on a throwaway bank, each pending until its ticket
  is on the branch.
- `report`: the report (`results.json`, `summary.md`) and the exit rule.
- `api`: reading Atlas through `/api/v1`.

`scripts/memory-conformance.sh` runs it; `docs/runbooks.md`, "Memory conformance".
"""

from atlas.conformance.api import AtlasApi, AtlasApiError
from atlas.conformance.behaviours import CHECKS, BehaviourBank, Check, CheckResult, run_checks
from atlas.conformance.beliefs_bank import BeliefsBankReport, check_beliefs_bank
from atlas.conformance.known_answers import (
    DEFAULT_RECALL_MAX_TOKENS,
    HOPS,
    TEST_PARTS,
    KnownAnswersError,
    KnownAnswerSet,
    KnownAnswersReport,
    find_sentence,
    load_known_answers,
    ranked_sections,
    run_known_answers,
)
from atlas.conformance.report import ConformanceReport, Usage

__all__ = [
    "CHECKS",
    "DEFAULT_RECALL_MAX_TOKENS",
    "HOPS",
    "TEST_PARTS",
    "AtlasApi",
    "AtlasApiError",
    "BehaviourBank",
    "BeliefsBankReport",
    "Check",
    "CheckResult",
    "ConformanceReport",
    "KnownAnswerSet",
    "KnownAnswersError",
    "KnownAnswersReport",
    "Usage",
    "check_beliefs_bank",
    "find_sentence",
    "load_known_answers",
    "ranked_sections",
    "run_checks",
    "run_known_answers",
]
