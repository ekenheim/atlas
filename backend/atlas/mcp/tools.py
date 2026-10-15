"""The Atlas MCP server's tools (atlas-beliefs ticket 15): typed inputs, each a call of the
existing `/api/v1` routes through `atlas.mcp.api.Api`.

What the tools add to the routes is exactly what a client used to do for itself
(`.claude/skills/atlas-research/atlas_tools.py`) and now does not, so the rules live in one
place:

- **The session's as-of time is the session's.** It is read from the `research_session` row
  (`Ctx.as_of`); no tool takes an as-of argument. `search` passes it to the archive search,
  `recall` as `available_by`; `read`, `locate`, `record_fact`, `get_fact`, `judge_statement`,
  `relate_facts`, `propose_belief` and `cite_belief` refuse a Source Version (or a Fact of one)
  that became public after it (`available_after_as_of`).
- **Quotes are located here** (`atlas.mcp.locate`: the typographic fold, one occurrence).
- **Slugs** name companies in every tool; the routes take ids.
- **`propose_belief` warns** (never refuses) when its supporting Facts come from documents more
  than 90 days apart and the statement does not name each year (`joins_dated_documents`).
- **Atlas judges what the session writes down** (ticket 23; `atlas.judging`, no tool of its own):
  `record_fact` refuses (`statement_beyond_quote`, with the judge's `beyond`, `kinds` and
  `reason`) a Fact whose statement says more than its quote, and returns the verdict it was
  recorded with (`judged`: `supported`, or `unjudged` when the judge could not be reached);
  `close_session` returns the verdict on the card's `thesis` (`thesis_judged`, flagged when
  misstated, never refused); `propose_belief` refuses a compound Belief (`belief_compound`) and
  one that says more than its load-bearing quotes (`belief_beyond_quotes`).

- **Atlas compounds across sessions** (ticket 26): `prior_work` (`atlas.mcp.agents`) is the
  session's starting state; `record_fact` returns a span an earlier Fact of the same step, status
  and alike statement already covers as `reused` instead of recording it again (a materially
  different statement is recorded and names the earlier Fact, `same_span_as`); `examine_belief`
  records that the session tested a Belief; a supporting Fact from a newer document shows on a
  proven Belief as a `belief_confirmed` notice, never as a change of its judgement.

A tool returns text only with the span it is in (`read`: the window and its offsets; `search`:
passages with theirs); Memory's `recall` is labelled an index, never Evidence.
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal, cast

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from atlas.facts.service import FactStatus, FactStep, Quantity
from atlas.mcp.api import Api, Refusal, obj, rows
from atlas.mcp.locate import Located, locate_quote

MAX_READ_CHARS = 20_000  # one `read` window; the skill asks for 2,000 to 6,000
JOINED_DAYS = 90  # the finding judge's `merged` rule: quotes this far apart need their dates

type BeliefStep = Literal[
    "constraint", "demand_vs_supply", "relief", "control", "capture", "invalidation"
]
type Weight = Literal["load_bearing", "context"]
Relation = Literal["contradicts", "limits", "dates", "qualifies", "supports"]
Valence = Annotated[float, Field(ge=-1, le=1)]


def iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class SessionRow:
    """The research session a call belongs to, as its row holds it."""

    id: uuid.UUID
    question: str
    theme: str
    as_of: datetime
    seed_company_ids: tuple[uuid.UUID, ...] = ()


@dataclass
class Ctx:
    """One tool call: the routes, the session and the per-call caches."""

    api: Api
    session: SessionRow | None = None
    _companies: list[dict[str, Any]] | None = None
    _versions: dict[str, dict[str, Any]] = field(default_factory=dict[str, dict[str, Any]])

    @property
    def bound(self) -> SessionRow:
        assert self.session is not None  # every tool that calls this requires a session
        return self.session

    @property
    def as_of(self) -> datetime:
        return self.bound.as_of

    @property
    def as_of_iso(self) -> str:
        """The session's as-of time as UTC with a `Z`, as the routes write times."""
        return iso(self.bound.as_of)

    async def companies(self, role: str = "researched") -> list[dict[str, Any]]:
        if role != "researched":
            return rows((await self.api.get("/companies", role=role, limit=500))["items"])
        if self._companies is None:
            self._companies = rows(
                (await self.api.get("/companies", role=role, limit=500))["items"]
            )
        return self._companies

    async def company_id(self, slug: str) -> str:
        for each in await self.companies():
            if each["slug"] == slug:
                return each["id"]
        raise Refusal("unknown_company", f"no researched company has the slug {slug!r}")

    async def company_ids(self, slugs: list[str]) -> list[str]:
        return [await self.company_id(slug) for slug in slugs]

    async def version(self, version_id: uuid.UUID | str) -> dict[str, Any]:
        key = str(version_id)
        if key not in self._versions:
            self._versions[key] = await self.api.get(f"/source-versions/{key}")
        return self._versions[key]

    async def visible_version(self, version_id: uuid.UUID | str) -> dict[str, Any]:
        """The Source Version, if it was public by the session's as-of time."""
        held = await self.version(version_id)
        available = datetime.fromisoformat(held["available_at"])
        if available > self.as_of:
            raise Refusal(
                "available_after_as_of",
                "that Source Version became public after the session's as-of time",
                version=str(version_id),
                available_at=held["available_at"],
                as_of=self.as_of_iso,
            )
        return held

    async def parsed(
        self, version_id: uuid.UUID | str, parser_version: str | None
    ) -> tuple[str, str]:
        """The parsed text (the current parse unless `parser_version` names another) and the
        parser version it is."""
        held = await self.visible_version(version_id)
        parser = parser_version or held.get("current_parser_version") or held.get("parser_version")
        text = await self.api.get_text(
            f"/source-versions/{version_id}/content", kind="parsed", parser_version=parser
        )
        return text, parser or ""

    async def visible_fact(self, fact_id: uuid.UUID | str) -> tuple[dict[str, Any], dict[str, Any]]:
        """A Fact and its Source Version, if that version was public by the as-of time."""
        fact = await self.api.get(f"/facts/{fact_id}")
        try:
            held = await self.visible_version(fact["assertion"]["source_version_id"])
        except Refusal as refusal:
            raise Refusal(
                "fact_available_after_as_of",
                "that Fact's document became public after the session's as-of time",
                fact=str(fact_id),
                **refusal.detail,
            ) from None
        return fact, held


type Handler[M: BaseModel] = Callable[[Ctx, M], Awaitable[dict[str, Any]]]
type SessionUse = Literal["required", "optional", "none"]


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Bound(Args):
    session_id: uuid.UUID = Field(
        description="the research session `open_session` returned; its as-of time rules every call"
    )


class Maybe(Args):
    session_id: uuid.UUID | None = Field(
        default=None,
        description="the research session, if one is open (the call is then counted on it)",
    )


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    model: type[Args]
    handler: Callable[[Ctx, Any], Awaitable[dict[str, Any]]]
    session: SessionUse


TOOLS: dict[str, Tool] = {}


def tool[M: Args](
    name: str, description: str, model: type[M], *, session: SessionUse = "required"
) -> Callable[[Handler[M]], Handler[M]]:
    def register(handler: Handler[M]) -> Handler[M]:
        TOOLS[name] = Tool(name, description, model, handler, session)
        return handler

    return register


# --- sessions ------------------------------------------------------------------------------


class OpenSessionArgs(Args):
    question: str = Field(min_length=1, description="the question, verbatim")
    as_of: AwareDatetime = Field(
        description="the time the research is as of (with an offset): nothing public after it"
        " is searched, read or recalled"
    )
    theme: str = "photonics"
    seeds: list[str] = Field(default_factory=list[str], description="seed company slugs")
    model: str | None = Field(default=None, description="the model doing the research")
    actor: str | None = None


@tool(
    "open_session",
    "Open a research session. Returns its id: pass it as `session_id` to every other tool."
    " The as-of time fixed here is the session's for good.",
    OpenSessionArgs,
    session="none",
)
async def open_session(ctx: Ctx, args: OpenSessionArgs) -> dict[str, Any]:
    opened = await ctx.api.post(
        "/sessions",
        {
            "question": args.question,
            "theme": args.theme,
            "seed_company_ids": await ctx.company_ids(args.seeds),
            "as_of": args.as_of.isoformat(),
            "kind": "claude",
            "model": args.model,
            "actor": args.actor,
        },
    )
    return {
        "opened": True,
        "session_id": opened["id"],
        "as_of": opened["as_of"],
        "theme": opened["theme"],
        "question": opened["question"],
    }


class CloseSessionArgs(Bound):
    usage: dict[str, Any] = Field(default_factory=dict[str, Any], description="your own usage")
    card: dict[str, Any] | None = Field(default=None, description="the research card (JSON)")
    card_markdown: str | None = None


@tool(
    "close_session",
    "Close the session with its card. Atlas counts the session's tool calls itself"
    " (`tool_calls` on the session read); `usage` is your own report. A card with a `thesis`"
    " (one sentence) has it judged against the Facts its statements cite: `thesis_judged` in"
    " the answer (`misstated` is flagged on the card, not refused: say so in your final message).",
    CloseSessionArgs,
)
async def close_session(ctx: Ctx, args: CloseSessionArgs) -> dict[str, Any]:
    closed = await ctx.api.post(
        f"/sessions/{args.session_id}/close",
        {"usage": args.usage, "card": args.card, "card_markdown": args.card_markdown},
    )
    result: dict[str, Any] = {"closed": True, "session_id": closed["id"], "facts": closed["facts"]}
    judged = obj(closed.get("card")).get("thesis_judged")
    if judged is not None:
        result["thesis_judged"] = judged
    return result


# --- reading -------------------------------------------------------------------------------


class CompaniesArgs(Maybe):
    role: Literal["researched", "counterparty"] = "researched"


@tool(
    "companies",
    "The companies of the universe: slug, id, name, supply-chain layer, country.",
    CompaniesArgs,
    session="optional",
)
async def companies(ctx: Ctx, args: CompaniesArgs) -> dict[str, Any]:
    return {
        "companies": [
            {key: each.get(key) for key in ("slug", "id", "display_name", "layer", "country")}
            for each in await ctx.companies(args.role)
        ]
    }


class SearchArgs(Bound):
    company: str = Field(description="a company slug")
    q: str = Field(min_length=1, description="the terms to search")
    top: int = Field(default=8, ge=1, le=50)
    per_document: int = Field(default=2, ge=1, le=10)


@tool(
    "search",
    "BM25 over the company's archived documents that were public by the session's as-of time."
    " Each hit is a passage with its Source Version, offsets in the named parse and the time it"
    " became public. Read the hit before recording from it.",
    SearchArgs,
)
async def search(ctx: Ctx, args: SearchArgs) -> dict[str, Any]:
    answer = await ctx.api.get(
        "/archive-search",
        q=args.q,
        company_id=await ctx.company_id(args.company),
        as_of=ctx.as_of_iso,
        top=args.top,
        per_document=args.per_document,
    )
    keys = (
        "source_version_id",
        "company",
        "title",
        "document_type",
        "form_type",
        "available_at",
        "parser_version",
        "char_start",
        "char_end",
        "score",
        "text",
    )
    return {
        "query": answer.get("query"),
        "terms": answer.get("terms"),
        "as_of": answer.get("as_of"),
        "documents_searched": answer.get("documents_searched"),
        "hits": [{key: hit.get(key) for key in keys} for hit in answer.get("hits", [])],
    }


class ReadArgs(Bound):
    version_id: uuid.UUID = Field(description="a Source Version id, from a search hit")
    start: int = Field(ge=0, description="first character (code point) of the window")
    end: int = Field(ge=0, description=f"end of the window; at most {MAX_READ_CHARS} characters")
    parser_version: str | None = None


@tool(
    "read",
    "The archived parsed text of a Source Version between two offsets. Refused for a version"
    " that became public after the session's as-of time. Read before you record.",
    ReadArgs,
)
async def read(ctx: Ctx, args: ReadArgs) -> dict[str, Any]:
    held = await ctx.visible_version(args.version_id)
    text, parser = await ctx.parsed(args.version_id, args.parser_version)
    start = min(args.start, len(text))
    end = min(len(text), args.end, start + MAX_READ_CHARS)
    return {
        "version_id": str(args.version_id),
        "title": held["source_document"].get("title"),
        "available_at": held["available_at"],
        "parser_version": parser,
        "length": len(text),
        "start": start,
        "end": end,
        "clamped": end < min(len(text), args.end),
        "text": text[start:end],
    }


class LocateArgs(Bound):
    version_id: uuid.UUID
    quote: str = Field(min_length=1, description="the verbatim text to find")
    parser_version: str | None = None


def located_answer(version_id: uuid.UUID, parser: str, quote: str, text: str) -> dict[str, Any]:
    placed = locate_quote(text, quote)
    if not isinstance(placed, Located):
        return {
            "located": False,
            "reason": placed.reason,
            "occurrences": placed.occurrences,
            "version_id": str(version_id),
        }
    return {
        "located": True,
        "version_id": str(version_id),
        "parser_version": parser,
        "span_start": placed.start,
        "span_end": placed.end,
        "offset_source": placed.source,
        "archived_quote": placed.archived_quote,
    }


@tool(
    "locate",
    "Where a verbatim quote is in the archived parse (code-point offsets), through the"
    " typographic fold if the exact text does not occur. A quote occurring more than once, or"
    " not at all, is not located.",
    LocateArgs,
)
async def locate(ctx: Ctx, args: LocateArgs) -> dict[str, Any]:
    text, parser = await ctx.parsed(args.version_id, args.parser_version)
    return located_answer(args.version_id, parser, args.quote, text)


# --- facts ---------------------------------------------------------------------------------


class RecordFactArgs(Bound):
    version_id: uuid.UUID
    quote: str = Field(min_length=1, description="the archived text, verbatim, one speaker's")
    step: FactStep
    status: FactStatus
    statement: str = Field(min_length=1, description="one sentence, in your words")
    epistemic_type: Literal["direct_source_statement", "third_party_report"] = (
        "direct_source_statement"
    )
    part: str | None = Field(default=None, description="the question's part it answers")
    period: str | None = Field(default=None, description="as the quote gives it")
    quantity: Quantity | None = None
    company: str | None = Field(
        default=None, description="slug of the company the Fact is about; default: the document's"
    )
    parser_version: str | None = None
    dry_run: bool = False


REUSED_NOTE = (
    "An earlier Fact of the same step, status and statement already covers this span, so nothing"
    " was recorded: use its fact_id (cite it, judge a statement on it). Record a new Fact for the"
    " span only with a materially different statement or another step."
)


@tool(
    "record_fact",
    "Record a Fact: a verbatim quote at an archived span, with the argument step and status."
    " The quote is located for you; Atlas then checks the span, the status wording and the"
    " period against the document's date, and refuses what fails; then the finding judge"
    " compares the statement with the quote: `statement_beyond_quote` (with `beyond`, `kinds`,"
    " `reason`) means rewrite the statement to what the quote says, or quote more. `judged` in"
    " the answer: `supported`, or `unjudged` (the judge was unreachable: judge it yourself)."
    " A span an earlier Fact of the same step already covers is not recorded again: with the same"
    " status and an alike statement the answer is `reused: true` and that Fact's id (nothing is"
    " recorded); a materially different statement is recorded and names the earlier one in"
    " `same_span_as`. Refused for a version that became public after the session's as-of time.",
    RecordFactArgs,
)
async def record_fact(ctx: Ctx, args: RecordFactArgs) -> dict[str, Any]:
    held = await ctx.visible_version(args.version_id)
    text, parser = await ctx.parsed(args.version_id, args.parser_version)
    placed = locate_quote(text, args.quote)
    if not isinstance(placed, Located):
        raise Refusal(
            placed.reason,
            "the quote is not located in the archived parse",
            occurrences=placed.occurrences,
        )
    subject = (
        await ctx.company_id(args.company)
        if args.company
        else held["source_document"].get("company_id")
    )
    body = {
        "subject_company_id": subject,
        "source_version_id": str(args.version_id),
        "quote": placed.archived_quote,
        "span_start": placed.start,
        "span_end": placed.end,
        "epistemic_type": args.epistemic_type,
        "parser_version": parser or None,
        "step": args.step,
        "statement": args.statement,
        "status": args.status,
        "period": args.period,
        "part": args.part,
        "session_id": str(args.session_id),
        "quantity": args.quantity.model_dump() if args.quantity else None,
    }
    if args.dry_run:
        return {"recorded": False, "dry_run": True, "body": body}
    answer = await ctx.api.post("/facts", body)
    if answer.get("reused"):
        return {
            "recorded": False,
            "reused": True,
            "fact_id": answer["fact"]["id"],
            "note": REUSED_NOTE,
            "fact": answer["fact"],
        }
    judgement = obj(answer["fact"].get("statement_judgement"))
    same_span_as = answer["fact"].get("same_span_as")
    return {
        "recorded": True,
        "fact_id": answer["fact"]["id"],
        "judged": judgement.get("verdict"),
        **({"judge_note": judgement["reason"]} if judgement.get("verdict") == "unjudged" else {}),
        **({"same_span_as": same_span_as} if same_span_as else {}),
        "fact": answer["fact"],
    }


class GetFactArgs(Bound):
    fact_id: uuid.UUID


@tool(
    "get_fact",
    "A Fact with its quote, span, status, period and document. Refused when its document"
    " became public after the session's as-of time.",
    GetFactArgs,
)
async def get_fact(ctx: Ctx, args: GetFactArgs) -> dict[str, Any]:
    fact, _ = await ctx.visible_fact(args.fact_id)
    return fact


# --- judging -------------------------------------------------------------------------------


class JudgeArgs(Bound):
    statement: str = Field(min_length=1, description="one statement, citing only these Facts")
    fact_ids: list[uuid.UUID] = Field(min_length=1, max_length=12)
    counter_fact_ids: list[uuid.UUID] = Field(default_factory=list[uuid.UUID], max_length=8)
    question: str | None = Field(default=None, description="default: the session's question")
    votes: int = Field(default=1, ge=1, le=3)
    run_id: uuid.UUID | None = Field(
        default=None, description="keeps a session's judge calls in one run"
    )


@tool(
    "judge_statement",
    "Atlas's finding judge compares a statement with the quotes of the Facts it cites:"
    " `supported`, or `misstated` with the words that go beyond the quotes. A quota or outage"
    " is an error: call again later. Never put on the card a statement not judged supported.",
    JudgeArgs,
)
async def judge_statement(ctx: Ctx, args: JudgeArgs) -> dict[str, Any]:
    for fact_id in dict.fromkeys([*args.fact_ids, *args.counter_fact_ids]):
        await ctx.visible_fact(fact_id)
    answer = await ctx.api.post(
        "/statements/judge",
        {
            "question": args.question or ctx.bound.question,
            "statement": args.statement,
            "fact_ids": [str(each) for each in args.fact_ids],
            "counter_fact_ids": [str(each) for each in args.counter_fact_ids],
            "votes": args.votes,
            "run_id": str(args.run_id) if args.run_id else None,
        },
    )
    keys = (
        "verdict",
        "reason",
        "beyond",
        "kinds",
        "unverified",
        "clauses",
        "refs",
        "counter_relations",
        "run_id",
    )
    return {key: answer[key] for key in keys}


class RelateArgs(Bound):
    fact_id: uuid.UUID = Field(description="the Fact challenged")
    counter_fact_id: uuid.UUID = Field(description="the counterevidence Fact")
    question: str | None = Field(default=None, description="default: the session's question")
    run_id: uuid.UUID | None = None


@tool(
    "relate_facts",
    "The counter-judge says what a counterevidence Fact does to a Fact: contradicts, limits,"
    " dates, qualifies, supports or unrelated. Only `contradicts` disputes a step.",
    RelateArgs,
)
async def relate_facts(ctx: Ctx, args: RelateArgs) -> dict[str, Any]:
    await ctx.visible_fact(args.fact_id)
    await ctx.visible_fact(args.counter_fact_id)
    return await ctx.api.post(
        "/statements/relate",
        {
            "question": args.question or ctx.bound.question,
            "fact_id": str(args.fact_id),
            "counter_fact_id": str(args.counter_fact_id),
            "run_id": str(args.run_id) if args.run_id else None,
        },
    )


# --- beliefs -------------------------------------------------------------------------------


class CitationArg(Args):
    fact_id: uuid.UUID
    how: Valence | Relation = Field(
        description="a valence in -1..1 (positive supports, negative counts against), or the"
        " counter-judge's relation (contradicts -1, limits/dates -0.5, qualifies -0.25,"
        " supports +0.5)"
    )
    weight: Weight = "context"
    note: str | None = None


def citation_body(citation: CitationArg, actor: str | None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "kind": "fact",
        "ref_id": str(citation.fact_id),
        "weight": citation.weight,
        "note": citation.note,
        "actor": actor,
    }
    if isinstance(citation.how, str):
        body["relation"] = citation.how
    else:
        body["valence"] = citation.how
    return body


def supporting(how: float | str) -> bool:
    return how == "supports" if isinstance(how, str) else how > 0


def belief_result(answer: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": answer["id"],
        "statement": answer["statement"],
        "judgement": answer["judgement"]["judgement"],
        "status": answer["status"],
        "citations": answer["citation_count"],
        "open_flags": answer["open_flags"],
        "open_notices": answer.get("open_notices", 0),
    }


def joined_documents(statement: str, dated: dict[str, str]) -> dict[str, Any] | None:
    """`dated`: the day each supporting Fact's document became public -> the Fact. The warning
    when the first and last day are more than 90 days apart and the statement does not name the
    year of each (the finding judge's `merged` rule), else None."""
    if len(dated) < 2:
        return None
    first, last = min(dated), max(dated)
    apart = (date.fromisoformat(last) - date.fromisoformat(first)).days
    if apart <= JOINED_DAYS or (
        first[:4] != last[:4] and first[:4] in statement and last[:4] in statement
    ):
        return None
    return {
        "warning": "joins_dated_documents",
        "documents": {first: dated[first], last: dated[last]},
        "days_apart": apart,
        "rule": "one proposition per Belief: split it, or name each document's date in the"
        " statement",
    }


class ProposeBeliefArgs(Bound):
    statement: str = Field(min_length=1, description="one falsifiable proposition, in your words")
    step: BeliefStep
    citations: list[CitationArg] = Field(min_length=1)
    companies: list[str] = Field(default_factory=list[str], description="company slugs")
    actor: str | None = None


@tool(
    "propose_belief",
    "Propose a Belief: one falsifiable proposition citing Facts. Atlas refuses one without a"
    " load-bearing citation of positive valence, one that is compound (`belief_compound`: more"
    " than one sentence, a semicolon, several periods) and one the judge finds says more than"
    " its load-bearing quotes (`belief_beyond_quotes`, with `beyond`, `kinds`, `reason`): split"
    " or rewrite it. A judge outage is an error result: call again later. It is born unproven;"
    " the session's theme and as-of time are used. A `joins_dated_documents` warning means the"
    " supporting Facts are from documents more than 90 days apart: split the proposition or"
    " name each year.",
    ProposeBeliefArgs,
)
async def propose_belief(ctx: Ctx, args: ProposeBeliefArgs) -> dict[str, Any]:
    dated: dict[str, str] = {}
    for citation in args.citations:
        fact, held = await ctx.visible_fact(citation.fact_id)
        if supporting(citation.how) and held["available_at"]:
            dated[held["available_at"][:10]] = fact["id"]
    session = ctx.bound
    answer = await ctx.api.post(
        "/beliefs",
        {
            "statement": args.statement,
            "theme": session.theme,
            "step": args.step,
            "company_ids": await ctx.company_ids(args.companies),
            "as_of": ctx.as_of_iso,
            "session_id": str(session.id),
            "actor": args.actor,
            "citations": [citation_body(each, args.actor) for each in args.citations],
        },
    )
    result = belief_result(answer)
    warning = joined_documents(args.statement, dated)
    if warning is not None:
        result["warnings"] = [warning]
    return result


class CiteBeliefArgs(Bound):
    belief_id: uuid.UUID
    citation: CitationArg
    actor: str | None = None


@tool(
    "cite_belief",
    "Add a Fact as a citation to a Belief, with a valence or a counter-judge relation.",
    CiteBeliefArgs,
)
async def cite_belief(ctx: Ctx, args: CiteBeliefArgs) -> dict[str, Any]:
    await ctx.visible_fact(args.citation.fact_id)
    answer = await ctx.api.post(
        f"/beliefs/{args.belief_id}/cite", citation_body(args.citation, args.actor)
    )
    return belief_result(answer)


class SupersedeBeliefArgs(Bound):
    belief_id: uuid.UUID
    by: list[uuid.UUID] = Field(min_length=1, description="the Beliefs that replace it")
    reason: str = Field(min_length=1)
    actor: str | None = None


@tool(
    "supersede_belief",
    "Replace a Belief by others. The old one keeps its citations and history.",
    SupersedeBeliefArgs,
)
async def supersede_belief(ctx: Ctx, args: SupersedeBeliefArgs) -> dict[str, Any]:
    answer = await ctx.api.post(
        f"/beliefs/{args.belief_id}/supersede",
        {"by": [str(each) for each in args.by], "reason": args.reason, "actor": args.actor},
    )
    return belief_result(answer)


# --- issues --------------------------------------------------------------------------------


class OpenIssueArgs(Bound):
    title: str = Field(min_length=1)
    body: str = ""
    kind: Literal["question", "step", "read"] = "read"
    priority: int = 0
    theme: str | None = Field(default=None, description="default: the session's theme")
    companies: list[str] = Field(default_factory=list[str], description="company slugs")
    narrows: uuid.UUID | None = Field(default=None, description="the Issue this one narrows")
    requires: list[uuid.UUID] = Field(default_factory=list[uuid.UUID])


def issue_result(issue: dict[str, Any]) -> dict[str, Any]:
    keys = ("id", "title", "kind", "status", "theme", "priority", "blocked", "parent_id")
    return {key: issue.get(key) for key in keys}


@tool(
    "open_issue",
    "Open an Issue on the research frontier (a question, a step or a read), optionally under"
    " the Issue it narrows. Produced by this session.",
    OpenIssueArgs,
)
async def open_issue(ctx: Ctx, args: OpenIssueArgs) -> dict[str, Any]:
    issue = await ctx.api.post(
        "/issues",
        {
            "title": args.title,
            "body": args.body,
            "theme": args.theme or ctx.bound.theme,
            "kind": args.kind,
            "priority": args.priority,
            "company_ids": await ctx.company_ids(args.companies),
            "produced_by": str(args.session_id),
            "narrows": str(args.narrows) if args.narrows else None,
            "requires": [str(each) for each in args.requires],
        },
    )
    return issue_result(issue)


class NarrowIssueArgs(Bound):
    issue_id: uuid.UUID
    parent_id: uuid.UUID
    requires: bool = Field(default=False, description="link as a prerequisite, not a narrowing")


@tool(
    "narrow_issue",
    "Link an Issue under a parent it narrows (or, with `requires`, behind one it requires).",
    NarrowIssueArgs,
)
async def narrow_issue(ctx: Ctx, args: NarrowIssueArgs) -> dict[str, Any]:
    issue = await ctx.api.post(
        f"/issues/{args.issue_id}/edges",
        {"kind": "requires" if args.requires else "narrows", "parent_id": str(args.parent_id)},
    )
    return {"linked": True, **issue_result(issue)}


class CompleteIssueArgs(Bound):
    issue_id: uuid.UUID
    fact_id: uuid.UUID | None = Field(default=None, description="a Fact it produced")
    belief_id: uuid.UUID | None = Field(default=None, description="a Belief it produced")
    abandon: bool = False


@tool(
    "complete_issue",
    "Record what an Issue produced (a Fact, a Belief), then complete it (or abandon it).",
    CompleteIssueArgs,
)
async def complete_issue(ctx: Ctx, args: CompleteIssueArgs) -> dict[str, Any]:
    for key, value in (("fact_id", args.fact_id), ("belief_id", args.belief_id)):
        if value is not None:
            await ctx.api.post(f"/issues/{args.issue_id}/produced", {key: str(value)})
    issue = await ctx.api.post(
        f"/issues/{args.issue_id}/{'abandon' if args.abandon else 'complete'}", {}
    )
    return {"closed": True, **issue_result(issue)}


class NextIssueArgs(Maybe):
    theme: str | None = Field(default=None, description="default: the session's theme")


@tool(
    "next_issue",
    "The next Issue by Atlas's rule: a step with no Belief, then flagged or disputed, then"
    " priority, then age. Its title is the question when a session has none.",
    NextIssueArgs,
    session="optional",
)
async def next_issue(ctx: Ctx, args: NextIssueArgs) -> dict[str, Any]:
    theme = args.theme or (ctx.session.theme if ctx.session else None)
    if theme is None:
        raise Refusal("theme_required", "name a theme, or pass the session_id of one that has it")
    return await ctx.api.get("/issues/next", theme=theme)


# --- memory --------------------------------------------------------------------------------

RECALL_NOTE = (
    "Memory is an index, never evidence: read a memory's section with `read` and record a Fact"
    " from the archived text. A memory with `beliefs` is Atlas's earlier conclusion, to be"
    " tested against Facts, not cited."
)


class RecallArgs(Bound):
    query: str = Field(min_length=1, max_length=4000)
    theme: str | None = Field(default=None, description="default: the session's theme")
    companies: list[str] = Field(default_factory=list[str], description="company slugs")
    max_tokens: int = Field(default=4096, ge=1, le=65536)
    bank: Literal["research", "beliefs"] = Field(
        default="research",
        description="`research`: the index of the archive's sections; `beliefs`: the"
        " conclusions bank",
    )


@tool(
    "recall",
    "What Memory holds for a question, each memory with the archived sections it resolves to"
    " (or the judged Belief it was retained from), only those public by the session's as-of"
    " time (`dropped_future` counts the rest). An index to find sections, never evidence.",
    RecallArgs,
)
async def recall(ctx: Ctx, args: RecallArgs) -> dict[str, Any]:
    scope: dict[str, Any] = {"theme_ids": [args.theme or ctx.bound.theme]}
    if args.companies:
        scope["company_ids"] = await ctx.company_ids(args.companies)
    stamp = ctx.as_of_iso
    answer = await ctx.api.post(
        "/memory/recall",
        {
            "query": args.query,
            "scope": scope,
            "max_tokens": args.max_tokens,
            "query_timestamp": stamp,
            "available_by": stamp,
            "include_source_facts": True,
            "bank": args.bank,
        },
    )
    section_keys = (
        "source_version_id",
        "company_id",
        "form_type",
        "section_anchor",
        "section_char_start",
        "section_char_end",
        "available_at",
    )
    by_memory: dict[str, list[dict[str, Any]]] = {}
    for section in rows(answer.get("evidence")):
        for memory_id in cast(list[str], section.get("memory_ids") or []):
            by_memory.setdefault(memory_id, []).append({k: section.get(k) for k in section_keys})
    memories: list[dict[str, Any]] = []
    for each in rows(answer.get("memories")):
        provenance = obj(each.get("provenance"))
        entry: dict[str, Any] = {
            "memory_id": each.get("memory_id"),
            "type": each.get("type"),
            "text": each.get("text"),
            "occurred": [each.get("occurred_start"), each.get("occurred_end")],
            "provenance_state": provenance.get("state"),
            "sections": by_memory.get(str(each.get("memory_id")), []),
        }
        beliefs = [
            {k: belief.get(k) for k in ("id", "statement", "judgement", "status", "as_of")}
            for belief in rows(provenance.get("beliefs"))
        ]
        if beliefs:
            entry["beliefs"] = beliefs
        memories.append(entry)
    return {
        "query": args.query,
        "as_of": stamp,
        "bank": args.bank,
        "counts": answer.get("counts"),
        "memories": memories,
        "dropped_future": answer.get("dropped_future", 0),
        "note": RECALL_NOTE,
    }
