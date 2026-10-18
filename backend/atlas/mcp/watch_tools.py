"""The Atlas MCP server's Chokepoint Watch tools (Chokepoint Watch ticket W1): `board`,
`get_chokepoint`, `add_chokepoint`, `update_chokepoint` and `write_memo`.

Projections of `/api/v1/chokepoints` and `/api/v1/watch-runs`; every rule (what a step needs,
the thesis-ready gate, the Facts visible by the session's as-of time) is the routes', so the
tools add none. The board is the Watch's own state, so an **isolated** session (the early-call
scorecard's, ticket 29) is refused every one of them, before anything is called (the frozen
surface: the scorecard sees exactly what it saw in v0.6.14).

A chokepoint is a lead's home, not a finding: a `primary` step cites Facts the session read in
the archive, `crowding` is context and never evidence, and nothing here is a Belief.

Registered by importing this module (`atlas.mcp.server`).
"""

from datetime import UTC
from typing import Any, Literal

from pydantic import Field, JsonValue

from atlas.chokepoints.model import Holder, WriteKind
from atlas.mcp.api import obj, rows
from atlas.mcp.tools import Bound, Ctx, tool

BOARD_NOTE = (
    "The Watch's board: candidate bottlenecks and where each stands. A chokepoint is a lead's"
    " home, never a finding. A step is `primary` only with a Fact you read in the archive"
    " (`record_fact`), `lead` with a lead or an Issue; `crowding` is context, never evidence;"
    " `stale` means no field_set or step_set event for 56 days (a note does not count);"
    " `needs_review` marks a thesis_ready chokepoint whose gate no longer holds. The steps are"
    " a constraint, b demand_vs_supply, c relief, d control, e capture, f invalidation."
)


class BoardArgs(Bound):
    theme: str | None = None
    status: (
        Literal["lead", "candidate", "thesis_ready", "killed", "stale", "needs_review"] | None
    ) = None


def _line(item: dict[str, Any]) -> dict[str, Any]:
    """A chokepoint on the board: its state, the steps as their statuses only."""
    return {
        "id": item.get("id"),
        "constraint": item.get("constraint"),
        "layer": item.get("layer"),
        "holders": item.get("holders"),
        "status": item.get("status"),
        "status_reason": item.get("status_reason"),
        "stale": item.get("stale"),
        "needs_review": item.get("needs_review"),
        "thesis_gate": item.get("thesis_gate"),
        "steps": {step["step"]: step["status"] for step in rows(item.get("steps"))},
        "kill_criteria": item.get("kill_criteria"),
        "relief_horizon": item.get("relief_horizon"),
        "crowding": item.get("crowding"),
        "issue_ids": item.get("issue_ids"),
        "last_event_at": item.get("last_event_at"),
    }


@tool(
    "board",
    "The Watch's board for a theme (default: the session's): its chokepoints, latest event"
    " first, each with its status (and the reason given), the six steps' statuses (a constraint,"
    " b demand_vs_supply, c relief, d control, e capture, f invalidation), holders, kill"
    " criteria, relief horizon, crowding, linked Issues, whether `thesis_ready` would hold"
    " (`thesis_gate`) and whether it needs review, and the theme's last memo. `status` filters"
    " (`stale`, `needs_review` are derived). Load it first; then `get_chokepoint` for one's"
    " history.",
    BoardArgs,
)
async def board(ctx: Ctx, args: BoardArgs) -> dict[str, Any]:
    ctx.refuse_isolated("board")
    theme = args.theme or ctx.bound.theme
    session = str(args.session_id)
    listed = await ctx.api.get(
        "/chokepoints", theme=theme, status=args.status, limit=200, session_id=session
    )
    memos = rows(
        (await ctx.api.get("/watch-runs", theme=theme, limit=1, session_id=session)).get("items")
    )
    last = memos[0] if memos else None
    return {
        "theme": theme,
        "total": listed.get("total"),
        "chokepoints": [_line(each) for each in rows(listed.get("items"))],
        "last_memo": None
        if last is None
        else {
            "run_date": last.get("run_date"),
            "mode": last.get("mode"),
            "memo": last.get("memo"),
            "counts": last.get("counts"),
        },
        "note": BOARD_NOTE,
    }


class GetChokepointArgs(Bound):
    id: str


@tool(
    "get_chokepoint",
    "One chokepoint: its current state and the history of every event (what changed, why, the"
    " evidence, the session), oldest first.",
    GetChokepointArgs,
)
async def get_chokepoint(ctx: Ctx, args: GetChokepointArgs) -> dict[str, Any]:
    ctx.refuse_isolated("get_chokepoint")
    found = await ctx.api.get(f"/chokepoints/{args.id}", session_id=str(args.session_id))
    return {**found, "note": BOARD_NOTE}


class AddChokepointArgs(Bound):
    constraint: str
    layer: str
    holders: list[Holder] = Field(default_factory=list[Holder])


@tool(
    "add_chokepoint",
    "Add a candidate chokepoint to the session's theme: the scarce thing (`constraint`), the"
    " layer it sits in, and who holds it (`holders`: names, with a company slug and a CIK when"
    " known; a holder outside the universe is fine). Born `lead`, every step `unexamined`. Check"
    " `board` first: do not add the same constraint and layer twice. Refused in a session of"
    " another theme or whose as-of time is more than 36 hours old (the board is prospective).",
    AddChokepointArgs,
)
async def add_chokepoint(ctx: Ctx, args: AddChokepointArgs) -> dict[str, Any]:
    ctx.refuse_isolated("add_chokepoint")
    created = await ctx.api.post(
        "/chokepoints",
        {
            "theme": ctx.bound.theme,
            "constraint": args.constraint,
            "layer": args.layer,
            "holders": [each.model_dump(mode="json") for each in args.holders],
            "session_id": str(args.session_id),
        },
    )
    return {"created": True, **_line(created), "note": BOARD_NOTE}


class UpdateChokepointArgs(Bound):
    id: str
    kind: WriteKind
    payload: dict[str, JsonValue]
    reason: str | None = None


@tool(
    "update_chokepoint",
    "Append an event to a chokepoint (one event, one change). `kind` and its `payload`:"
    " `field_set` any of constraint, layer, holders, relief_horizon ({horizon, basis} or null),"
    " crowding (early | emerging | consensus | null), kill_criteria (observables), issue_ids (the"
    " Issues linked to it); **a list you give (holders, kill_criteria, issue_ids) replaces the"
    " whole list**, `add_issue_ids` appends instead; `step_set` {step, status: unexamined | lead"
    " | primary | contradicted, evidence: {fact_ids, lead_ids, issue_ids}} where the step is a"
    " constraint, b demand_vs_supply, c relief, d control, e capture or f invalidation (letter"
    " or name); **`evidence` replaces the step's whole evidence**, `add_evidence` (same shape)"
    " appends; primary and contradicted need a Fact, lead a lead or an Issue; `status_set`"
    " {status: lead | candidate | thesis_ready | killed} (killed needs a `reason`; thesis_ready"
    " needs steps a, b and d primary, a kill criterion and an open linked Issue; while it is"
    " thesis_ready, move the status down before you change a, b or d away from primary);"
    " `note` {text}. A Fact public after the session's as-of time, or recorded by an isolated"
    " session, is refused; so are an Issue of another theme and a lead or Issue opened after"
    " the as-of time (your own session's Issues are fine).",
    UpdateChokepointArgs,
)
async def update_chokepoint(ctx: Ctx, args: UpdateChokepointArgs) -> dict[str, Any]:
    ctx.refuse_isolated("update_chokepoint")
    updated = await ctx.api.post(
        f"/chokepoints/{args.id}/events",
        {
            "kind": args.kind,
            "payload": args.payload,
            "reason": args.reason,
            "session_id": str(args.session_id),
        },
    )
    return {"updated": True, **_line(updated), "events": updated.get("event_count")}


class WriteMemoArgs(Bound):
    mode: Literal["architect", "delta"]
    memo: str
    counts: dict[str, JsonValue] | None = None
    cost_usd: float | None = Field(default=None, ge=0, description="the run's cost, if known")
    tokens: int | None = Field(default=None, ge=0, description="the run's tokens, if known")


@tool(
    "write_memo",
    "Record the run's memo (markdown) for the session's theme, dated the session's as-of day:"
    " `architect` for the first run, which decomposes the industry, `delta` for a weekly one."
    " `counts` is a small object of the run's numbers (discoveries, rejections, changes);"
    " `cost_usd` and `tokens` the run's cost if you know it. The"
    " Today page shows the latest. Write it last; it is insert-only.",
    WriteMemoArgs,
)
async def write_memo(ctx: Ctx, args: WriteMemoArgs) -> dict[str, Any]:
    ctx.refuse_isolated("write_memo")
    written = await ctx.api.post(
        "/watch-runs",
        {
            "theme": ctx.bound.theme,
            "run_date": ctx.as_of.astimezone(UTC).date().isoformat(),
            "mode": args.mode,
            "memo": args.memo,
            "counts": obj(args.counts),
            "cost_usd": args.cost_usd,
            "tokens": args.tokens,
            "session_id": str(args.session_id),
        },
    )
    return {
        "recorded": True,
        "watch_run_id": written.get("id"),
        "run_date": written.get("run_date"),
        "tool_calls": written.get("tool_calls"),
    }
