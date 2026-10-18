"""The tools the Scout, Skeptic and Editor prompts need (atlas-beliefs ticket 16), on the same
pattern as `atlas.mcp.tools`: typed arguments that forbid extras, the session's `session_id`,
the as-of time taken from the session's row, each a projection of an existing route.

- `newest_documents`: `GET /archive-documents` (the documents `GET /archive-search` searches);
  `as_of` is the session's, so no document public after it is listed.
- `list_beliefs`: `GET /beliefs`; a Belief whose own `as_of` is after the session's is not listed.
  Stalest first by default (ticket 26): never tested, then the oldest `last_examined_as_of`; an
  examination by a session whose as-of time is after this one's is not seen.
- `prior_work`: `GET /research/prior-work` (ticket 26), the session's starting state: the Facts
  already recorded, the Beliefs of any judgement, the documents earlier sessions read and the open
  Issues, all bounded by the session's as-of time.
- `examine_belief`: `POST /beliefs/{id}/examine`: record that this session tested a Belief
  (`confirmed`, `qualified`, `contradicted`, `nothing_new`); sets no judgement.
- `list_beliefs`, `get_belief`, `examine_belief` and `list_issues` (and in `atlas.mcp.tools`
  `next_issue`, `open_issue`, `narrow_issue`, `complete_issue`) are refused in an **isolated**
  session (`isolated_session`, ticket 29a: `Ctx.refuse_isolated`), and `prior_work` is answered
  empty by the route.
- `get_belief`: `GET /beliefs/{id}`; a Belief after the session's time is refused
  (`belief_after_as_of`). What the later work added to it is left out: a citation of a document
  public after the session's time, a flag raised by such a citation, and a supersession link to a
  Belief whose own as-of time is after it (each counted: `hidden_citations`, `hidden_flags`,
  `hidden_links`).
- `list_issues`: `GET /issues` (an Issue is a question, not evidence: no time rule).
- `draft_hypothesis`: `POST /hypotheses` with `theme`; the cutoff is the session's, so only Beliefs
  with an as-of time at or before it are drafted from.
- `get_hypothesis`: `GET /hypotheses/{id}` and `.../publish-gate`; a Hypothesis with no cutoff, or
  one after the session's time, is refused.

Two rules differ from what a route's own `as_of` means. The beliefs route's `as_of` is the time
a *judgement* is read at, not a bound on the Belief's research time, so these tools never pass
it and filter on the Belief's `as_of` here. And there is no publish tool: publishing is the
owner's. Registered by importing this module (`atlas.mcp.server`).
"""

import uuid
from datetime import datetime
from typing import Any, Literal, cast

from pydantic import AwareDatetime, Field

from atlas.facts import FactStep
from atlas.mcp.api import Refusal, obj, rows
from atlas.mcp.tools import BeliefStep, Bound, Ctx, iso, issue_result, theme_company_ids, tool

AGENT_TOOLS = (
    "newest_documents",
    "list_beliefs",
    "get_belief",
    "list_issues",
    "draft_hypothesis",
    "get_hypothesis",
    "prior_work",
    "examine_belief",
)
SCAN_PAGE = 500  # the routes' largest page
SCAN_LIMIT = 2_000  # rows read through to find the visible ones: more is a refusal to guess

type Judgement = Literal["proven", "disproven", "unproven", "undecidable"]
type BeliefStatus = Literal["active", "superseded", "withdrawn"]


# --- documents -----------------------------------------------------------------------------


class NewestDocumentsArgs(Bound):
    theme: str | None = Field(
        default=None,
        description="a theme: its researched companies. Default, when no company is named: the"
        " session's theme",
    )
    companies: list[str] = Field(
        default_factory=list[str], description="company slugs (instead of the theme)"
    )
    since: AwareDatetime | None = Field(
        default=None, description="only documents public at or after this time (with an offset)"
    )
    kinds: list[str] = Field(
        default_factory=list[str],
        description="keep a form, document or source type: 10-K, 10-Q, 8-K, transcript..."
        " (case-insensitive; empty: all)",
    )
    limit: int = Field(default=50, ge=1, le=200)


@tool(
    "newest_documents",
    "The parsed English documents of a theme's companies (or the named ones) that were public by"
    " the session's as-of time, newest first, each with its Source Version id, title, form or"
    " type, company and the time it became public. Never a document after the as-of time."
    " Titles and dates only: `read` a version to see its text.",
    NewestDocumentsArgs,
)
async def newest_documents(ctx: Ctx, args: NewestDocumentsArgs) -> dict[str, Any]:
    theme = args.theme or (None if args.companies else ctx.bound.theme)
    if theme is not None and args.companies:
        raise Refusal("theme_or_companies", "name a theme or companies, not both")
    ids = await ctx.company_ids(args.companies) if args.companies else None
    if ids is None:
        assert theme is not None
        ids = await theme_company_ids(ctx, theme)
    if not ids:
        return {"as_of": ctx.as_of_iso, "total": 0, "documents": []}
    params: dict[str, Any] = {
        "company_id": ids,
        "as_of": ctx.as_of_iso,
        "since": iso(args.since) if args.since else None,
        "kind": args.kinds or None,
        "limit": args.limit,
    }
    answer = await ctx.api.get("/archive-documents", **params)
    keys = (
        "source_version_id",
        "company",
        "title",
        "form_type",
        "document_type",
        "source_type",
        "available_at",
        "parser_version",
    )
    return {
        "as_of": answer.get("as_of"),
        "since": answer.get("since"),
        "total": answer.get("total"),
        "documents": [{key: each.get(key) for key in keys} for each in rows(answer["documents"])],
    }


# --- beliefs -------------------------------------------------------------------------------


def belief_summary(each: dict[str, Any], as_of: datetime) -> dict[str, Any]:
    """A Belief as `list_beliefs` shows it. Its examination is seen only if its session's
    as-of time is not after `as_of` (a later one is future research: shown as never examined);
    `examined_through` is the as-of time it has been tested against, else its own."""
    examined_as_of = each.get("last_examined_as_of")
    seen = examined_as_of is not None and datetime.fromisoformat(examined_as_of) <= as_of
    return {
        "id": each["id"],
        "statement": each["statement"],
        "theme": each["theme"],
        "step": each["step"],
        "as_of": each["as_of"],
        "status": each["status"],
        "companies": [company["slug"] for company in rows(each.get("companies"))],
        "judgement": each["judgement"],
        "open_flags": each["open_flags"],
        "citation_count": each["citation_count"],
        "produced_by": each.get("produced_by"),
        "last_examined_at": each.get("last_examined_at") if seen else None,
        "last_examined_as_of": examined_as_of if seen else None,
        "last_examined_outcome": each.get("last_examined_outcome") if seen else None,
        "examined_through": examined_as_of if seen else each["as_of"],
    }


class ListBeliefsArgs(Bound):
    theme: str | None = Field(default=None, description="default: the session's theme")
    step: BeliefStep | None = None
    judgement: Judgement | None = None
    status: BeliefStatus | None = None
    company: str | None = Field(default=None, description="a company slug the Belief names")
    sort: Literal["stalest", "created"] = Field(
        default="stalest",
        description="stalest: never examined first, then the oldest `examined_through`;"
        " created: oldest first",
    )
    limit: int = Field(default=50, ge=1, le=200)


@tool(
    "list_beliefs",
    "The theme's Beliefs, stalest first (`sort: created`: oldest first), each with its current"
    " judgement (who judged it, when, with what confidence), step, companies, citation count and"
    " when a session last tested it (`last_examined_*`; `examined_through` is the as-of time it has"
    " been tested against, else its own: read documents public after it). A Belief whose own as-of"
    " time is after the session's is not listed (`hidden_after_as_of` counts them). Judgements are"
    " an author's: no tool sets one, and the judgement shown is the current one, whatever its"
    " time. `citation_count` and `open_flags` are the Belief's own, whatever their documents'"
    " dates: `get_belief` is the as-of bounded read (it alone counts the open notices, the"
    " confirmations that are no doubt).",
    ListBeliefsArgs,
)
async def list_beliefs(ctx: Ctx, args: ListBeliefsArgs) -> dict[str, Any]:
    ctx.refuse_isolated("list_beliefs")
    company = await ctx.company_id(args.company) if args.company else None
    visible: list[dict[str, Any]] = []
    hidden = scanned = 0
    while True:
        if scanned >= SCAN_LIMIT:
            raise Refusal(
                "too_many_beliefs",
                f"more than {SCAN_LIMIT} Beliefs match: narrow the call (step, judgement, company)",
                scanned=scanned,
            )
        page = await ctx.api.get(
            "/beliefs",
            theme=args.theme or ctx.bound.theme,
            step=args.step,
            judgement=args.judgement,
            status=args.status,
            company_id=company,
            sort=args.sort,
            limit=SCAN_PAGE,
            offset=scanned,
        )
        items = rows(page["items"])
        for each in items:
            if datetime.fromisoformat(each["as_of"]) > ctx.as_of:
                hidden += 1
            else:
                visible.append(belief_summary(each, ctx.as_of))
        scanned += len(items)
        if not items or scanned >= page["total"]:
            break
    if args.sort == "stalest":  # an unseen examination is not counted: sort what is shown
        visible.sort(
            key=lambda each: (
                each["last_examined_as_of"] is not None,
                datetime.fromisoformat(each["examined_through"]),
            )
        )
    return {
        "as_of": ctx.as_of_iso,
        "total": len(visible),
        "hidden_after_as_of": hidden,
        "beliefs": visible[: args.limit],
    }


class GetBeliefArgs(Bound):
    belief_id: uuid.UUID


@tool(
    "get_belief",
    "One Belief with its citations (Fact id, valence, weight, who cited it and when; the quote,"
    " span and the date its document became public), its counterevidence, open flags, judgement"
    " history, supersession and session, and its `notices` (what supports it, apart from the flags"
    " of doubt) and `examinations` (each session's test of it). Refused for a Belief after the"
    " session's as-of time; a citation of a document public after it, the flag it raised and a"
    " supersession link to a Belief after it are left out (`hidden_citations`, `hidden_flags`,"
    " `hidden_links`), and likewise a notice whose Fact and an examination by a later session"
    " (`hidden_notices`, `hidden_examinations`).",
    GetBeliefArgs,
)
async def get_belief(ctx: Ctx, args: GetBeliefArgs) -> dict[str, Any]:
    ctx.refuse_isolated("get_belief")
    found = await ctx.api.get(f"/beliefs/{args.belief_id}")
    if datetime.fromisoformat(found["as_of"]) > ctx.as_of:
        raise Refusal(
            "belief_after_as_of",
            "that Belief's as-of time is after the session's",
            belief=str(args.belief_id),
            belief_as_of=found["as_of"],
            as_of=ctx.as_of_iso,
        )
    citations = rows(found.get("citations"))
    kept = [each for each in citations if datetime.fromisoformat(each["available_at"]) <= ctx.as_of]
    shown = {each["id"] for each in kept}
    late_refs = {each["ref_id"] for each in citations if each["id"] not in shown}
    found["citations"] = kept
    found["counterevidence"] = [
        each for each in rows(found.get("counterevidence")) if each["id"] in shown
    ]
    found["hidden_citations"] = len(citations) - len(kept)
    # A flag raised by a citation the session cannot see would say what that citation said.
    flags = rows(found.get("flags"))
    found["flags"] = [each for each in flags if each["ref_id"] not in late_refs]
    found["hidden_flags"] = len(flags) - len(found["flags"])
    found["open_flags"] = sum(1 for each in found["flags"] if each["cleared_by"] is None)
    # A notice is raised by a Fact (a confirmation); one whose Fact is after the session's time
    # would say what that Fact said. Examinations by a later session are future research.
    notices = rows(found.get("notices"))
    seen_notices: list[dict[str, Any]] = []
    for each in notices:
        try:
            await ctx.visible_fact(each["ref_id"])
        except Refusal:
            continue
        seen_notices.append(each)
    found["notices"] = seen_notices
    found["hidden_notices"] = len(notices) - len(seen_notices)
    found["open_notices"] = sum(1 for each in seen_notices if each["cleared_by"] is None)
    examinations = rows(found.get("examinations"))
    kept_examinations = [
        each for each in examinations if datetime.fromisoformat(each["as_of"]) <= ctx.as_of
    ]
    found["examinations"] = kept_examinations
    found["hidden_examinations"] = len(examinations) - len(kept_examinations)
    latest = kept_examinations[-1] if kept_examinations else None
    found["last_examined_at"] = latest["at"] if latest else None
    found["last_examined_outcome"] = latest["outcome"] if latest else None
    found["last_examined_as_of"] = (
        max((each["as_of"] for each in kept_examinations), key=datetime.fromisoformat)
        if kept_examinations
        else None
    )
    # A supersession link carries the other Belief's statement: only one the session could read.
    hidden_links = 0
    for key in ("supersedes", "superseded_by"):
        linked: list[dict[str, Any]] = []
        for each in rows(found.get(key)):
            other = await ctx.api.get(f"/beliefs/{each['id']}")
            if datetime.fromisoformat(other["as_of"]) > ctx.as_of:
                hidden_links += 1
            else:
                linked.append(each)
        found[key] = linked
    found["hidden_links"] = hidden_links
    return found


class ExamineBeliefArgs(Bound):
    belief_id: uuid.UUID
    outcome: Literal["confirmed", "qualified", "contradicted", "nothing_new"] = Field(
        description="what reading the documents public since the Belief was last tested found:"
        " confirmed (newer evidence supports it), qualified (it limits, dates or narrows it),"
        " contradicted (it contradicts it), nothing_new (nothing bears on it)"
    )
    note: str | None = Field(default=None, description="what you read and found, in a line")


@tool(
    "examine_belief",
    "Record that this session tested a Belief against the documents public by its as-of time:"
    " `last_examined_at` and `last_examined_as_of` (this session's) are set on it, so the next"
    " session reads only what came after (`list_beliefs` sorts by it). It sets no judgement and"
    " clears no flag: only an author judges. Call it once, last, for each Belief you tested; a"
    " Belief whose own as-of time is after the session's is refused (`belief_after_as_of`).",
    ExamineBeliefArgs,
)
async def examine_belief(ctx: Ctx, args: ExamineBeliefArgs) -> dict[str, Any]:
    ctx.refuse_isolated("examine_belief")
    examined = await ctx.api.post(
        f"/beliefs/{args.belief_id}/examine",
        {"session_id": str(args.session_id), "outcome": args.outcome, "note": args.note},
    )
    return {
        "examined": True,
        "belief_id": examined["id"],
        "outcome": examined["last_examined_outcome"],
        "last_examined_at": examined["last_examined_at"],
        "last_examined_as_of": examined["last_examined_as_of"],
        "judgement": examined["judgement"]["judgement"],
        "open_flags": examined["open_flags"],
    }


# --- prior work ----------------------------------------------------------------------------

PRIOR_WORK_NOTE = (
    "What Atlas holds already, as of your session. Cite an existing Fact (its id) instead of"
    " recording the same span again: a repeat is returned as reused. Spend your calls on"
    " documents public after `latest_session_as_of` (a search hit says when it became public) and"
    " on the gaps: `sessions[].open_questions` and `issues`. A Belief's `examined_through` is the"
    " as-of time it has been tested against. Beliefs are Atlas's earlier conclusions: test them,"
    " never cite them as evidence."
)


ISOLATED_NOTE = (
    "This session is isolated (a replay of a past date): Atlas gives it no prior work, whatever it"
    " holds. Research from the archive: search, read, record_fact."
)


class PriorWorkArgs(Bound):
    companies: list[str] = Field(
        default_factory=list[str],
        description="company slugs; default: the session's seeds, else the theme's companies",
    )
    steps: list[FactStep] = Field(
        default_factory=list[FactStep], description="argument steps; default: all"
    )
    question: str | None = Field(default=None, description="default: the session's question")
    limit: int = Field(default=40, ge=1, le=200, description="the cap on each list")


@tool(
    "prior_work",
    "Call this right after open_session: what Atlas already holds for the question, bounded by the"
    " session's as-of time. Facts already recorded for the companies and steps (statement, status,"
    " period, document title and date, Fact id; newest document first, with the count beyond the"
    " cap), the Beliefs of any judgement that name them or their steps (stalest first, with who"
    " judged them and when they were last examined; the judgement is the current one, whatever"
    " its time, and the open flags and notices leave out those a document public after your"
    " as-of time raised), the documents read in earlier sessions with"
    " those sessions' as-of times (`latest_session_as_of`: what is public after it is new to"
    " Atlas), the earlier sessions with the open questions their cards named, and the open Issues"
    " that touch the companies or steps. Your own session's work is left out. An isolated session"
    " (`open_session` with `isolated: true`) is given nothing.",
    PriorWorkArgs,
)
async def prior_work(ctx: Ctx, args: PriorWorkArgs) -> dict[str, Any]:
    session = ctx.bound
    if args.companies:
        company_ids = await ctx.company_ids(args.companies)
    else:
        company_ids = [str(each) for each in session.seed_company_ids]
    answer = await ctx.api.get(
        "/research/prior-work",
        theme=session.theme,
        as_of=ctx.as_of_iso,
        company_ids=company_ids or None,
        steps=args.steps or None,
        question=args.question or session.question,
        exclude_session_id=str(session.id),
        limit=args.limit,
    )
    return {**answer, "note": ISOLATED_NOTE if answer.get("isolated") else PRIOR_WORK_NOTE}


# --- issues --------------------------------------------------------------------------------


class ListIssuesArgs(Bound):
    theme: str | None = Field(default=None, description="default: the session's theme")
    status: Literal["active", "complete", "abandoned", "invalid"] | None = "active"
    kind: Literal["question", "step", "read"] | None = None
    limit: int = Field(default=100, ge=1, le=500)


@tool(
    "list_issues",
    "The theme's Issues on the research frontier (default: the active ones), in the route's"
    " order: title, body, kind, priority, status, companies, what they narrow. Check it before"
    " `open_issue` so a question is not opened twice.",
    ListIssuesArgs,
)
async def list_issues(ctx: Ctx, args: ListIssuesArgs) -> dict[str, Any]:
    ctx.refuse_isolated("list_issues")
    found: list[dict[str, Any]] = []
    scanned = 0
    while True:
        if scanned >= SCAN_LIMIT:
            raise Refusal(
                "too_many_issues",
                f"more than {SCAN_LIMIT} Issues match: narrow the call (status, theme)",
                scanned=scanned,
            )
        page = await ctx.api.get(
            "/issues",
            theme=args.theme or ctx.bound.theme,
            status=args.status,
            limit=SCAN_PAGE,
            offset=scanned,
        )
        items = rows(page["items"])
        found += [each for each in items if args.kind is None or each["kind"] == args.kind]
        scanned += len(items)
        if not items or scanned >= page["total"]:
            break
    slugs: dict[str, str] = {each["id"]: each["slug"] for each in await ctx.companies()}
    items = [
        {
            **issue_result(each),
            "body": each.get("body"),
            "companies": [slugs.get(c, c) for c in cast(list[str], each.get("company_ids") or [])],
            "parent_title": each.get("parent_title"),
            "created_at": each.get("created_at"),
        }
        for each in found
    ]
    return {"total": len(items), "of_theme": scanned, "issues": items[: args.limit]}


# --- hypotheses ----------------------------------------------------------------------------


class DraftHypothesisArgs(Bound):
    theme: str | None = Field(default=None, description="default: the session's theme")
    question: str | None = Field(
        default=None,
        max_length=2000,
        description="the question it answers (default: the sessions')",
    )
    session_ids: list[uuid.UUID] = Field(
        default_factory=list[uuid.UUID],
        description="only the Beliefs these research sessions produced (empty: the theme's)",
    )


@tool(
    "draft_hypothesis",
    "Draft a Hypothesis from the theme's proven, active Beliefs whose as-of time is at or before"
    " the session's (the cutoff is the session's). The draft is a job: this returns the"
    " Hypothesis id at once with `draft_status: queued`; call `get_hypothesis` until it is"
    " `drafted` or `failed`. Refused when no proven Belief matches. It cannot publish.",
    DraftHypothesisArgs,
)
async def draft_hypothesis(ctx: Ctx, args: DraftHypothesisArgs) -> dict[str, Any]:
    ctx.refuse_isolated("draft_hypothesis")
    created = await ctx.api.post(
        "/hypotheses",
        {
            "theme": args.theme or ctx.bound.theme,
            "question": args.question,
            "session_ids": [str(each) for each in args.session_ids],
            "as_of": ctx.as_of_iso,
        },
    )
    return {
        "hypothesis_id": created["id"],
        "theme": created["theme_id"],
        "question": created["question"],
        "as_of": created["as_of"],
        "status": created["status"],
        "draft_status": created["draft_status"],
        "next": "call get_hypothesis until draft_status is drafted or failed",
    }


class GetHypothesisArgs(Bound):
    hypothesis_id: uuid.UUID


def step_view(step: dict[str, Any]) -> dict[str, Any]:
    return {
        "step": step["step"],
        "statements": [
            {key: each.get(key) for key in ("statement", "belief_ids", "judged")}
            for each in rows(step.get("statements"))
        ],
        "beliefs": [
            {
                key: each.get(key)
                for key in ("belief_id", "statement", "judgement", "confidence", "as_of")
            }
            for each in rows(step.get("beliefs"))
        ],
    }


@tool(
    "get_hypothesis",
    "A Hypothesis with its latest version's thesis (whether the judge found it supported, or why"
    " it is held as misstated), steps (each statement, whether the finding"
    " judge found it supported, the Beliefs it rests on as they were judged when drafted) and"
    " dropped statements, and its publish gate read now: `publishable`, what `blocked` it and"
    " each failure (a Belief no longer proven, a flag open, an edge unapproved) with the Belief"
    " ids. Refused for a Hypothesis with no cutoff or one after the session's as-of time.",
    GetHypothesisArgs,
)
async def get_hypothesis(ctx: Ctx, args: GetHypothesisArgs) -> dict[str, Any]:
    ctx.refuse_isolated("get_hypothesis")
    found = await ctx.api.get(f"/hypotheses/{args.hypothesis_id}")
    cutoff = found.get("as_of")
    if cutoff is None:
        raise Refusal(
            "hypothesis_without_cutoff",
            "that Hypothesis was saved from an investigation, not drafted from Beliefs: it has"
            " no as-of time to hold to the session's",
        )
    if datetime.fromisoformat(cutoff) > ctx.as_of:
        raise Refusal(
            "hypothesis_after_as_of",
            "that Hypothesis's cutoff is after the session's as-of time",
            hypothesis_as_of=cutoff,
            as_of=ctx.as_of_iso,
        )
    gate = await ctx.api.get(f"/hypotheses/{args.hypothesis_id}/publish-gate")
    latest = next(
        (
            each
            for each in rows(found.get("versions"))
            if each["version"] == found.get("latest_version")
        ),
        None,
    )
    version: dict[str, Any] | None = None
    if latest is not None:
        content = obj(latest["content"])
        steps = [step_view(each) for each in rows(content.get("steps"))]
        version = {
            "version": latest["version"],
            "origin": latest["origin"],
            "published": latest["published"],
            "thesis_statement": content.get("thesis_statement"),
            "thesis_belief_ids": content.get("thesis_belief_ids"),
            "thesis_judged": content.get("thesis_judged"),
            "thesis_misstated_reason": content.get("thesis_misstated_reason"),
            # The effective verdict (ticket 30), which the gate reads: a later judging of the
            # version, else the content's; none when no judge has seen the thesis.
            "thesis_judgement": latest.get("thesis_judgement"),
            "steps": steps,
            "steps_without_statement": [each["step"] for each in steps if not each["statements"]],
            "unsupported_findings": rows(content.get("unsupported_findings")),
            "falsifiers": content.get("falsifiers"),
            "unresolved_questions": content.get("unresolved_questions"),
        }
    return {
        "hypothesis_id": found["id"],
        "theme": found["theme_id"],
        "question": found["question"],
        "as_of": cutoff,
        "status": found["status"],
        "draft_status": found["draft_status"],
        "draft_error": found["draft_error"],
        "latest_version": found["latest_version"],
        "open_proposed_updates": found["open_proposed_updates"],
        "version": version,
        "publish_gate": {
            key: gate.get(key) for key in ("version", "status", "publishable", "blocked")
        }
        | {
            "failures": [
                {
                    key: each.get(key)
                    for key in (
                        "code",
                        "message",
                        "belief_ids",
                        "relationship_ids",
                        "assertion_ids",
                    )
                }
                for each in rows(gate.get("failures"))
            ]
        },
    }
