"""The evaluation set: gold cases, `atlas evaluate`, and the stored results (ticket 25)."""

from atlas.evaluation.gold import GoldError, GoldSet, open_gold, validate_gold
from atlas.evaluation.runner import LIVE_OPT_IN, EvaluationRefused, RunOutcome, evaluate
from atlas.evaluation.store import (
    CaseResult,
    Check,
    EvaluationRun,
    EvaluationRunSummary,
    get_run,
    list_runs,
)

__all__ = [
    "LIVE_OPT_IN",
    "CaseResult",
    "Check",
    "EvaluationRefused",
    "EvaluationRun",
    "EvaluationRunSummary",
    "GoldError",
    "GoldSet",
    "RunOutcome",
    "evaluate",
    "get_run",
    "list_runs",
    "open_gold",
    "validate_gold",
]
