"""Rolling-window budgets: LLM-backed work paced against the owner's subscription quotas.

The owner's ChatGPT/Codex subscription (spent by the shared Hindsight's retain,
consolidation and mental models) and MiniMax subscription (spent by Atlas's research roles
through LiteLLM) each renew in rolling windows (5 h by default). Each **provider** gets a
budget per window, and the queue holds a provider's job kinds while its window is spent:

- `codex`, counted in **Hindsight operations submitted** (retain and reprocess batches, and a
  replay's retain batches and consolidation, one unit each): Atlas can't see Codex tokens,
  only what it asked Hindsight to do.
- `minimax`, counted in **LLM tokens** (in + out) of the role calls' recorded `llm_call`
  rows.
- `tradingview`, counted in **MCP tool calls** Atlas made to TradingView (recorded
  `tradingview_request` rows; ticket 31, an owner override that is off by default). Not an
  LLM quota, but TradingView's fair-use limit (~100 requests/min) is paced the same way.

A unit counts from when the queue first sees its row (the pacing clock; `provider_usage`)
until one window later. A job of a provider's kind is claimed only while the window's usage
is below the limit for its class: the whole budget for `interactive` jobs (the owner's own
work), and the budget less the **interactive reserve** (default 30%) for `backfill` jobs,
so backfill never uses the last share of a window. A job may overshoot by what it spends
itself (one retain batch; at most one run's token ceiling), since its cost is known only
afterwards.

`poll_operation` is a `codex` kind but never held: it only watches an operation already
submitted (and counted) and spends nothing new. The 429/outage pause (`atlas.jobs.pacing`)
stays the backstop for whatever the budgets don't foresee.
"""

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Connection, text

if TYPE_CHECKING:
    from atlas.jobs.pacing import JobClass
    from atlas.settings import Settings

Provider = Literal["codex", "minimax", "tradingview"]
PROVIDERS: tuple[Provider, ...] = ("codex", "minimax", "tradingview")
BudgetUnit = Literal["operations", "tokens", "requests"]
UNITS: dict[Provider, BudgetUnit] = {
    "codex": "operations",
    "minimax": "tokens",
    "tradingview": "requests",
}

# Which provider's quota each LLM-backed job kind spends. Kinds not listed (ingest, noop)
# spend neither and are never held by a budget.
PROVIDER_KINDS: dict[str, Provider] = {
    "retain": "codex",
    "poll_operation": "codex",
    "reprocess": "codex",
    "refresh_mental_model": "codex",
    "reflect": "codex",
    "replay": "codex",
    "discover": "minimax",
    "extract_claims": "minimax",
    "review_relationships": "minimax",
    "investigation_task": "minimax",
    "triage": "minimax",
    "tradingview_catalog": "tradingview",
    "tradingview_transcripts": "tradingview",
}
# Watches an operation already submitted and counted; holding it would only delay the result.
BUDGET_EXEMPT_KINDS = frozenset({"poll_operation"})

# Where each provider's usage is recorded: (source rows not yet counted, their units).
_SWEEPS: dict[Provider, str] = {
    "codex": (
        "SELECT h.id AS source_id, 1 AS units FROM hindsight_operation h"
        " WHERE NOT EXISTS (SELECT FROM provider_usage u"
        "   WHERE u.provider = 'codex' AND u.source_id = h.id)"
        # A replay's retain batches and consolidation (atlas.replay), in its own bank.
        " UNION ALL SELECT r.operation_id, 1 FROM replay_operation r"
        " WHERE NOT EXISTS (SELECT FROM provider_usage u"
        "   WHERE u.provider = 'codex' AND u.source_id = r.operation_id)"
    ),
    "minimax": (
        "SELECT c.id::text AS source_id, c.tokens_in + c.tokens_out AS units FROM llm_call c"
        " WHERE NOT EXISTS (SELECT FROM provider_usage u"
        "   WHERE u.provider = 'minimax' AND u.source_id = c.id::text)"
    ),
    "tradingview": (
        "SELECT r.id::text AS source_id, 1 AS units FROM tradingview_request r"
        " WHERE NOT EXISTS (SELECT FROM provider_usage u"
        "   WHERE u.provider = 'tradingview' AND u.source_id = r.id::text)"
    ),
}


def provider_of(kind: str) -> Provider | None:
    return PROVIDER_KINDS.get(kind)


def budgeted_kinds(provider: Provider) -> list[str]:
    """The kinds a spent `provider` window holds back."""
    return sorted(
        kind
        for kind, owner in PROVIDER_KINDS.items()
        if owner == provider and kind not in BUDGET_EXEMPT_KINDS
    )


@dataclass(frozen=True)
class Budgets:
    """The rolling window and each provider's budget in it."""

    window: timedelta = timedelta(hours=5)
    codex_operations: int = 40
    minimax_tokens: int = 400_000
    tradingview_requests: int = 200
    interactive_reserve: float = 0.3  # the share of each budget backfill may not use

    def __post_init__(self) -> None:
        if self.window <= timedelta(0):
            raise ValueError("the budget window must be positive")
        if min(self.codex_operations, self.minimax_tokens, self.tradingview_requests) < 1:
            raise ValueError("each provider's budget must be at least 1")
        if not 0 <= self.interactive_reserve < 1:
            raise ValueError("the interactive reserve must be in [0, 1)")

    @classmethod
    def from_settings(cls, settings: "Settings") -> "Budgets":
        return cls(
            window=timedelta(hours=settings.budget_window_hours),
            codex_operations=settings.codex_budget_operations,
            minimax_tokens=settings.minimax_budget_tokens,
            tradingview_requests=settings.tradingview_budget_requests,
            interactive_reserve=settings.budget_interactive_reserve,
        )

    def budget(self, provider: Provider) -> int:
        return {
            "codex": self.codex_operations,
            "minimax": self.minimax_tokens,
            "tradingview": self.tradingview_requests,
        }[provider]

    def limit(self, provider: Provider, job_class: "JobClass") -> int:
        """Usage at or above which `job_class` jobs of `provider` are held."""
        budget = self.budget(provider)
        if job_class == "interactive":
            return budget
        # Rounded first, so 10 x 0.7 is 7 and not 6.
        return math.floor(round(budget * (1 - self.interactive_reserve), 6))


class ProviderBudget(BaseModel):
    """One provider's rolling window as the queue sees it now."""

    model_config = ConfigDict(frozen=True)

    provider: Provider
    unit: BudgetUnit
    window_seconds: float
    used: int  # units counted in the window (now - window, now]
    budget: int  # the interactive limit
    backfill_limit: int  # budget less the interactive reserve
    interactive_held: bool  # used >= budget: every budgeted kind of this provider waits
    backfill_held: bool  # used >= backfill_limit: backfill jobs of those kinds wait
    # When usage next drops below the limit, while held (None when not held, or never:
    # a limit of 0).
    interactive_resumes_at: datetime | None
    backfill_resumes_at: datetime | None
    kinds: list[str]  # the kinds this budget holds


@dataclass(frozen=True)
class Holds:
    """The kinds the budgets hold now: for every job, and for backfill jobs only."""

    all_classes: list[str]
    backfill: list[str]


def sweep(connection: Connection, now: datetime) -> None:
    """Count each provider's usage rows the queue hasn't seen yet, as spent at `now`."""
    for provider, source in _SWEEPS.items():
        connection.execute(
            text(
                "INSERT INTO provider_usage (provider, source_id, units, recorded_at)"  # noqa: S608 (constant fragments)
                f" SELECT :provider, source_id, units, :now FROM ({source}) AS unseen"
                " ON CONFLICT DO NOTHING"
            ),
            {"provider": provider, "now": now},
        )


def window_usage(
    connection: Connection, budgets: Budgets, now: datetime
) -> dict[Provider, ProviderBudget]:
    """Each provider's window now; usage not swept yet counts as spent now."""
    usage: dict[Provider, ProviderBudget] = {}
    for provider in PROVIDERS:
        rows = connection.execute(
            text(
                "SELECT recorded_at, units FROM provider_usage"  # noqa: S608 (constant fragments)
                " WHERE provider = :provider AND recorded_at > :start AND recorded_at <= :now"
                " UNION ALL SELECT CAST(:now AS timestamptz), units"
                f" FROM ({_SWEEPS[provider]}) AS unseen ORDER BY 1"
            ),
            {"provider": provider, "start": now - budgets.window, "now": now},
        ).all()
        usage[provider] = _provider_budget(
            provider, budgets, [(row[0], int(row[1])) for row in rows]
        )
    return usage


def holds(usage: Iterable[ProviderBudget]) -> Holds:
    all_classes: list[str] = []
    backfill: list[str] = []
    for window in usage:
        if window.interactive_held:
            all_classes += window.kinds
        elif window.backfill_held:
            backfill += window.kinds
    return Holds(sorted(all_classes), sorted(backfill))


def _provider_budget(
    provider: Provider, budgets: Budgets, spent: Sequence[tuple[datetime, int]]
) -> ProviderBudget:
    used = sum(units for _, units in spent)
    budget = budgets.limit(provider, "interactive")
    backfill = budgets.limit(provider, "backfill")
    return ProviderBudget(
        provider=provider,
        unit=UNITS[provider],
        window_seconds=budgets.window.total_seconds(),
        used=used,
        budget=budget,
        backfill_limit=backfill,
        interactive_held=used >= budget,
        backfill_held=used >= backfill,
        interactive_resumes_at=_resumes_at(spent, used, budget, budgets.window),
        backfill_resumes_at=_resumes_at(spent, used, backfill, budgets.window),
        kinds=budgeted_kinds(provider),
    )


def _resumes_at(
    spent: Sequence[tuple[datetime, int]], used: int, limit: int, window: timedelta
) -> datetime | None:
    """When enough of the oldest usage leaves the window for `used` to drop below `limit`."""
    if used < limit or limit <= 0:
        return None
    freed = 0
    for at, units in spent:  # oldest first
        freed += units
        if used - freed < limit:
            return at + window
    return None  # unreachable: freeing everything leaves 0 < limit
