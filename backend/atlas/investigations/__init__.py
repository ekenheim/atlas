"""Investigations (spec Phase 4, "Research workflow"; §7.2-§7.4): a theme question run as a
fixed plan of role tasks on the job queue, Scout -> Investigator -> (Skeptic || Financial
Analyst) -> Editor, within per-run budgets, with every stop's reason recorded.

`model` is what the API shows (the §7.2 request, budgets, plan, research card, events);
`service` the state machine (plan, advance, stop, premises, resume); `tasks` runs one task's
role; `handlers` registers the `investigation_task` job.
"""

from atlas.investigations.handlers import register_investigation_handlers
from atlas.investigations.model import (
    INVESTIGATION_TASK_KIND,
    RUN_KIND,
    STOP_REASONS,
    Budgets,
    Investigation,
    InvestigationEvent,
    ResearchCard,
    StopReason,
    get_investigation,
    list_events,
)
from atlas.investigations.service import (
    InvestigationConflict,
    InvestigationError,
    InvestigationNotFound,
    Investigations,
)

__all__ = [
    "INVESTIGATION_TASK_KIND",
    "RUN_KIND",
    "STOP_REASONS",
    "Budgets",
    "Investigation",
    "InvestigationConflict",
    "InvestigationError",
    "InvestigationEvent",
    "InvestigationNotFound",
    "Investigations",
    "ResearchCard",
    "StopReason",
    "get_investigation",
    "list_events",
    "register_investigation_handlers",
]
