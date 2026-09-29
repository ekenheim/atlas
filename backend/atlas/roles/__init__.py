"""Research roles' LLM calls: one way for every role (Scout, Investigator, Reviewer, Skeptic,
Financial Analyst, Editor) to call the LLM through LiteLLM, validated, budgeted and recorded.

`contract` defines a role (versioned prompt, request and strict response models, the fixed
directives); `caller` makes the call (strict schema, one repair, then quarantine; budget;
queue pause on quota or outage); `records` reads what was asked, answered and spent.
"""

from atlas.roles.caller import (
    MAX_ATTEMPTS,
    RoleCaller,
    RoleCallFailed,
    RoleOutputQuarantined,
    TokenBudgetExhausted,
)
from atlas.roles.contract import (
    DIRECTIVES,
    PROMPTS_DIR,
    REPAIR_DIRECTIVE,
    NotStrict,
    Prompt,
    QuotedText,
    Role,
    RoleOutput,
)
from atlas.roles.records import (
    LLMAttempt,
    RoleCallRecord,
    RoleCallStatus,
    RunRoleCalls,
    RunUsage,
    run_role_calls,
    run_usage,
)

__all__ = [
    "DIRECTIVES",
    "MAX_ATTEMPTS",
    "PROMPTS_DIR",
    "REPAIR_DIRECTIVE",
    "LLMAttempt",
    "NotStrict",
    "Prompt",
    "QuotedText",
    "Role",
    "RoleCallFailed",
    "RoleCallRecord",
    "RoleCallStatus",
    "RoleCaller",
    "RoleOutput",
    "RoleOutputQuarantined",
    "RunRoleCalls",
    "RunUsage",
    "TokenBudgetExhausted",
    "run_role_calls",
    "run_usage",
]
