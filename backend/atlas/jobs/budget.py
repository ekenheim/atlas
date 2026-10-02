"""Rolling-window budgets: LLM-backed work paced against the owner's subscription quotas.

The owner's ChatGPT/Codex subscription (spent by the shared Hindsight's retain,
consolidation and mental models) and MiniMax subscription (spent by Atlas's research roles
through LiteLLM) each renew in rolling windows (5 h by default). Each **provider** gets a
budget per window, and the queue holds a provider's job kinds while its window is spent:

- `codex`, counted in **Hindsight operations submitted** (retain and reprocess batches, and a
  replay's retain batches and consolidation, one unit each; and since memory-quality ticket
  10 each reflect and each mental-model refresh Atlas submits, one unit each: a research
  answer's reflect, every attempt; a refresh Atlas's `refresh_mental_model` job submitted; a
  replay's reflect; and since memory-quality ticket 19 each consolidation of the research
  bank the `consolidate` job requests, one unit): Atlas can't see Codex tokens, only what it
  asked Hindsight to do.
- `hindsight_minimax`, counted in **Hindsight operations submitted** too: the retain and
  reprocess batches whose items asked the shared Hindsight for its MiniMax extractor
  (`ATLAS_RETAIN_EXTRACTOR=minimax`; Hindsight's metadata routing, docs/decisions.md,
  "Atlas's retains on MiniMax by metadata routing"). It exists only while that setting is on:
  `retain`, `poll_operation` and `reprocess` are then its kinds and leave `codex`, which
  keeps `reflect`, `refresh_mental_model` and `replay`. Each operation records the extractor
  it asked for (`hindsight_operation.extractor`) and counts against that extractor's budget
  whatever the setting is later, so switching the setting never counts an operation twice.
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

`poll_operation` is a retain kind (`codex`, or `hindsight_minimax` when routed) but never
held: it only watches an operation already submitted (and counted) and spends nothing new.
The 429/outage pause (`atlas.jobs.pacing`) stays the backstop for whatever the budgets don't
foresee.
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

Provider = Literal["codex", "hindsight_minimax", "minimax", "tradingview"]
PROVIDERS: tuple[Provider, ...] = ("codex", "hindsight_minimax", "minimax", "tradingview")
BudgetUnit = Literal["operations", "tokens", "requests"]
UNITS: dict[Provider, BudgetUnit] = {
    "codex": "operations",
    "hindsight_minimax": "operations",
    "minimax": "tokens",
    "tradingview": "requests",
}
# The extractor Atlas's retain items may ask Hindsight for (`ATLAS_RETAIN_EXTRACTOR`), and
# the provider whose budget the retains routed to it spend.
RetainExtractor = Literal["minimax"]
EXTRACTOR_PROVIDERS: dict[RetainExtractor, Provider] = {"minimax": "hindsight_minimax"}
# The kinds that follow the extractor: they submit, watch or resubmit a retain batch.
RETAIN_KINDS = frozenset({"retain", "poll_operation", "reprocess"})

# Which provider's quota each LLM-backed job kind spends while no extractor is asked for
# (`provider_kinds` gives the mapping in force). Kinds not listed (ingest, noop) spend
# neither and are never held by a budget.
PROVIDER_KINDS: dict[str, Provider] = {
    "retain": "codex",
    "poll_operation": "codex",
    "reprocess": "codex",
    "refresh_mental_model": "codex",
    "reflect": "codex",
    "replay": "codex",
    # The research bank's consolidation, asked for by Atlas (memory-quality ticket 19); it
    # runs on Hindsight's primary LLM whatever extractor the retains ask for.
    "consolidate": "codex",
    "discover": "minimax",
    "extract_claims": "minimax",
    "review_relationships": "minimax",
    "investigation_task": "minimax",
    "triage": "minimax",
    "triage_audit": "minimax",
    "tradingview_catalog": "tradingview",
    "tradingview_transcripts": "tradingview",
}
# Watches an operation already submitted and counted; holding it would only delay the result.
BUDGET_EXEMPT_KINDS = frozenset({"poll_operation"})

# Where each provider's usage is recorded: (source rows not yet counted, their units).
_SWEEPS: dict[Provider, str] = {
    "codex": (
        # The operations that asked for no extractor: the primary (Codex) extracted them.
        "SELECT h.id AS source_id, 1 AS units FROM hindsight_operation h"
        " WHERE h.extractor IS NULL AND NOT EXISTS (SELECT FROM provider_usage u"
        "   WHERE u.provider = 'codex' AND u.source_id = h.id)"
        # A replay's retain batches and consolidation (atlas.replay), in its own bank.
        " UNION ALL SELECT r.operation_id, 1 FROM replay_operation r"
        " WHERE NOT EXISTS (SELECT FROM provider_usage u"
        "   WHERE u.provider = 'codex' AND u.source_id = r.operation_id)"
        # Each reflect and each mental-model refresh Atlas submits (memory-quality ticket 10):
        # a research answer's reflect, a refresh Atlas's job submitted, a replay's reflect.
        " UNION ALL SELECT 'reflect_submission:' || s.id::text, 1 FROM reflect_submission s"
        " WHERE NOT EXISTS (SELECT FROM provider_usage u WHERE u.provider = 'codex'"
        "   AND u.source_id = 'reflect_submission:' || s.id::text)"
        " UNION ALL SELECT 'mental_model_refresh:' || m.id::text, 1 FROM mental_model_refresh m"
        " WHERE m.operation_id IS NOT NULL AND NOT EXISTS (SELECT FROM provider_usage u"
        "   WHERE u.provider = 'codex' AND u.source_id = 'mental_model_refresh:' || m.id::text)"
        " UNION ALL SELECT 'replay_answer:' || a.replay_job_id::text || ':' || a.position::text,"
        " 1 FROM replay_answer a WHERE NOT EXISTS (SELECT FROM provider_usage u"
        "   WHERE u.provider = 'codex' AND u.source_id = 'replay_answer:'"
        "     || a.replay_job_id::text || ':' || a.position::text)"
        # Each consolidation request Atlas submitted to the research bank (ticket 19).
        " UNION ALL SELECT 'consolidation:' || c.id::text, 1 FROM memory_consolidation c"
        " WHERE c.operation_id IS NOT NULL AND NOT EXISTS (SELECT FROM provider_usage u"
        "   WHERE u.provider = 'codex' AND u.source_id = 'consolidation:' || c.id::text)"
    ),
    "hindsight_minimax": (
        "SELECT h.id AS source_id, 1 AS units FROM hindsight_operation h"
        " WHERE h.extractor = 'minimax' AND NOT EXISTS (SELECT FROM provider_usage u"
        "   WHERE u.provider = 'hindsight_minimax' AND u.source_id = h.id)"
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


def provider_kinds(retain_extractor: RetainExtractor | None = None) -> dict[str, Provider]:
    """Which provider's quota each LLM-backed kind spends: `PROVIDER_KINDS`, with the retain
    kinds moved to the routed extractor's provider when Atlas's retains ask for one."""
    if retain_extractor is None:
        return dict(PROVIDER_KINDS)
    routed = EXTRACTOR_PROVIDERS[retain_extractor]
    return {
        kind: routed if kind in RETAIN_KINDS else provider
        for kind, provider in PROVIDER_KINDS.items()
    }


def provider_of(kind: str, retain_extractor: RetainExtractor | None = None) -> Provider | None:
    return provider_kinds(retain_extractor).get(kind)


def budgeted_kinds(
    provider: Provider, retain_extractor: RetainExtractor | None = None
) -> list[str]:
    """The kinds a spent `provider` window holds back."""
    return sorted(
        kind
        for kind, owner in provider_kinds(retain_extractor).items()
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
    # The extractor Atlas's retains ask for (None: the primary, and the retain kinds are
    # `codex` kinds), and the routed retains' own budget, in force only with an extractor.
    retain_extractor: RetainExtractor | None = None
    retain_operations: int = 200

    def __post_init__(self) -> None:
        if self.window <= timedelta(0):
            raise ValueError("the budget window must be positive")
        budgets = (
            self.codex_operations,
            self.minimax_tokens,
            self.tradingview_requests,
            self.retain_operations,
        )
        if min(budgets) < 1:
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
            retain_extractor=settings.retain_extractor,
            retain_operations=settings.retain_budget_operations,
        )

    def providers(self) -> tuple[Provider, ...]:
        """The providers that have a budget now: a routed extractor's only while Atlas's
        retains ask for it (without it, the view is what it was before the setting)."""
        asked = EXTRACTOR_PROVIDERS[self.retain_extractor] if self.retain_extractor else None
        routed = set(EXTRACTOR_PROVIDERS.values())
        return tuple(p for p in PROVIDERS if p not in routed or p == asked)

    def provider_of(self, kind: str) -> Provider | None:
        """The provider whose budget holds `kind` now (None: no budget holds it)."""
        return provider_of(kind, self.retain_extractor)

    def kinds(self, provider: Provider) -> list[str]:
        """The kinds `provider`'s spent window holds back now."""
        return budgeted_kinds(provider, self.retain_extractor)

    def budget(self, provider: Provider) -> int:
        return {
            "codex": self.codex_operations,
            "hindsight_minimax": self.retain_operations,
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
    """Count each provider's usage rows the queue hasn't seen yet, as spent at `now` (every
    provider's, whether or not it has a budget now)."""
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
    """The window now of each provider that has a budget; usage not swept yet counts as
    spent now."""
    usage: dict[Provider, ProviderBudget] = {}
    for provider in budgets.providers():
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
        kinds=budgets.kinds(provider),
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
