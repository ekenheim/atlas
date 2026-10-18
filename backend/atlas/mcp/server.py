"""The Atlas MCP server over streamable HTTP, mounted at `/mcp` (atlas-beliefs ticket 15).

The transport is the MCP specification's (2025-06-18, "Transports: Streamable HTTP") reduced to
what a tool server needs, the mirror of `atlas.tradingview.mcp`'s client: every JSON-RPC message
is one POST; a request is answered with one `application/json` object, a notification or a
response with 202 and no body; `GET` and `DELETE` are 405 (no server-initiated stream, no
transport session: the server is stateless, so no `Mcp-Session-Id` is issued). `initialize`,
`ping`, `tools/list` and `tools/call` are the methods. A request with an `Origin` header must
name an origin in `ATLAS_MCP_ALLOWED_ORIGINS` (DNS-rebinding protection); a client such as
Claude Code sends none. Like the rest of `/api/v1` it carries no authentication of its own:
Atlas sits behind the internal gateway.

Two kinds of session, kept apart: the transport's (none here) and the **research session**,
the `session_id` argument of the tools. Which tools take it:

- every tool but three requires it: it names an open `claude` session, whose row gives the
  as-of time, the theme and the question (an unknown one is `unknown_session`, a closed or
  pipeline one `session_closed`; neither is recorded: no session to record it on);
- `companies` and `next_issue` take it optionally (a lookup before any session exists; if
  given it is checked and the call is counted);
- `open_session` takes none and is counted on the session it opened.

Every call on a session is recorded after its outcome is known in `session_tool_call`
(insert-only): `ok`, `refused` (an argument that does not fit the tool's schema, a rule of
`atlas.mcp.tools`, a route's 4xx) or `error` (a 5xx, an unexpected exception: logged, its
detail not returned). The session read's `tool_calls` is that count.
"""

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any, cast

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError
from sqlalchemy import Engine, text

from atlas import __version__
from atlas.mcp.agents import AGENT_TOOLS
from atlas.mcp.api import Api, Failed, Refusal, obj
from atlas.mcp.tools import TOOLS, Ctx, SessionRow
from atlas.settings import Settings

log = logging.getLogger(__name__)

PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
INSTRUCTIONS = (
    "Atlas research tools. Call open_session first (question, as_of) and pass the session_id it"
    " returns to every other tool: the session's as-of time rules what you can search, read,"
    " recall and cite, and Atlas counts your calls on it. Then call prior_work: what Atlas"
    " already holds for the question, so you build on it instead of restarting. Record Facts"
    " only from text you read in the archive; Memory (recall) is an index, never evidence."
    " Close the session last."
)

assert set(AGENT_TOOLS) <= set(TOOLS)  # importing `agents` registered them

PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS = -32700, -32600, -32601, -32602


@dataclass(frozen=True)
class Outcome:
    value: dict[str, Any]
    outcome: str  # ok | refused | error
    reason: str | None = None  # the refusal's or error's code
    session_id: uuid.UUID | None = None  # the session to count the call on


def _session_row(engine: Engine, session_id: uuid.UUID) -> tuple[SessionRow, bool] | None:
    """The session and whether it is open (a `claude` session not yet closed)."""
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT id, question, theme, as_of, kind, finished_at, seed_company_ids, isolated"
                " FROM research_session WHERE id = :id"
            ),
            {"id": session_id},
        ).one_or_none()
    if row is None:
        return None
    session = SessionRow(
        id=row.id,
        question=row.question,
        theme=row.theme,
        as_of=row.as_of,
        seed_company_ids=tuple(row.seed_company_ids),
        isolated=row.isolated,
    )
    return session, row.kind == "claude" and row.finished_at is None


def _record(
    engine: Engine,
    session_id: uuid.UUID,
    tool: str,
    arguments: Any,
    outcome: str,
    reason: str | None,
) -> None:
    payload: dict[str, Any] = (
        cast(dict[str, Any], arguments) if isinstance(arguments, dict) else {"arguments": arguments}
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO session_tool_call (id, session_id, tool, arguments, outcome, reason)"
                " VALUES (:id, :session, :tool, CAST(:arguments AS jsonb), :outcome, :reason)"
            ),
            {
                "id": uuid.uuid4(),
                "session": session_id,
                "tool": tool,
                "arguments": json.dumps(payload, default=str),
                "outcome": outcome,
                "reason": reason,
            },
        )


class McpServer:
    """Tool dispatch, independent of the transport."""

    def __init__(self, app: FastAPI, engine: Engine) -> None:
        self._app = app
        self._engine = engine

    async def handle(self, message: Any) -> dict[str, Any] | None:
        """The JSON-RPC response to `message`, or None for a notification or a response."""
        if not isinstance(message, dict):
            return _error(None, INVALID_REQUEST, "a JSON-RPC message is an object")
        message = cast(dict[str, Any], message)
        method, request_id = message.get("method"), message.get("id")
        if not isinstance(method, str):
            return None  # a response to a request of ours (we make none)
        if "id" not in message:
            return None  # a notification
        params = obj(message.get("params")) if isinstance(message.get("params"), dict) else {}
        if method == "initialize":
            requested = params.get("protocolVersion")
            return _result(
                request_id,
                {
                    "protocolVersion": requested if requested in PROTOCOLS else PROTOCOLS[0],
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "atlas-research", "version": __version__},
                    "instructions": INSTRUCTIONS,
                },
            )
        if method == "ping":
            return _result(request_id, {})
        if method == "tools/list":
            return _result(request_id, {"tools": self.tool_list()})
        if method == "tools/call":
            name = params.get("name")
            if not isinstance(name, str) or name not in TOOLS:
                return _error(request_id, INVALID_PARAMS, f"unknown tool: {name!r}")
            return _result(request_id, _tool_result(await self.call(name, params.get("arguments"))))
        return _error(request_id, METHOD_NOT_FOUND, f"unsupported method: {method}")

    @staticmethod
    def tool_list() -> list[dict[str, Any]]:
        return [
            {
                "name": each.name,
                "description": each.description,
                "inputSchema": each.model.model_json_schema(),
            }
            for each in TOOLS.values()
        ]

    async def call(self, name: str, raw: Any) -> Outcome:
        """One tool call: check the arguments and the session, run the tool, count the call.

        `raw` is the request's `arguments` as received: a JSON object (missing or null: empty),
        else `invalid_arguments`, with no session to count it on.
        """
        tool = TOOLS[name]
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            return _refused("invalid_arguments", "arguments must be a JSON object")
        raw = cast(dict[str, Any], raw)
        try:
            args = tool.model.model_validate(raw)
        except ValidationError as invalid:
            problems = [
                f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
                for error in invalid.errors()
            ]
            outcome = _refused("invalid_arguments", "; ".join(problems))
            return await self._counted(name, raw, outcome, await self._given_session(raw))
        session: SessionRow | None = None
        given: uuid.UUID | None = getattr(args, "session_id", None)
        if given is not None:
            found = await asyncio.to_thread(_session_row, self._engine, given)
            if found is None:
                return _refused("unknown_session", "no such research session")
            session, is_open = found
            if not is_open:
                return _refused("session_closed", "the session is closed (or is not a claude one)")
        try:
            async with Api(self._app) as api:
                value = await tool.handler(Ctx(api, session), args)
            outcome = Outcome(value, "ok")
        except Refusal as refusal:
            outcome = _refused(refusal.code, refusal.message, **refusal.detail)
        except Failed as failure:
            outcome = Outcome(
                {"error": failure.code, "message": failure.message, **failure.detail},
                "error",
                failure.code,
            )
        except Exception:
            log.exception("MCP tool %s failed", name)
            outcome = Outcome(
                {"error": "internal_error", "message": "the tool failed; it was logged"},
                "error",
                "internal_error",
            )
        if name == "open_session" and outcome.outcome == "ok":
            outcome = Outcome(
                outcome.value, "ok", None, uuid.UUID(str(outcome.value["session_id"]))
            )
        return await self._counted(
            name, raw, outcome, session.id if session else outcome.session_id
        )

    async def _given_session(self, raw: Any) -> uuid.UUID | None:
        """The open session an invalid call names, if it names one, so it is counted too."""
        if not isinstance(raw, dict):
            return None
        try:
            given = uuid.UUID(str(cast(dict[str, Any], raw).get("session_id")))
        except ValueError:
            return None
        found = await asyncio.to_thread(_session_row, self._engine, given)
        return given if found is not None and found[1] else None

    async def _counted(
        self, name: str, raw: Any, outcome: Outcome, session_id: uuid.UUID | None
    ) -> Outcome:
        if session_id is not None:
            await asyncio.to_thread(
                _record, self._engine, session_id, name, raw, outcome.outcome, outcome.reason
            )
        return outcome


def _refused(code: str, message: str, **detail: Any) -> Outcome:
    return Outcome({"refused": code, "message": message, **detail}, "refused", code)


def _result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _tool_result(outcome: Outcome) -> dict[str, Any]:
    return {
        "content": [
            {"type": "text", "text": json.dumps(outcome.value, ensure_ascii=False, default=str)}
        ],
        "structuredContent": json.loads(json.dumps(outcome.value, default=str)),
        "isError": outcome.outcome != "ok",
    }


def mcp_router(app: FastAPI, engine: Engine, settings: Settings) -> APIRouter:
    """`POST /mcp` (see the module). Not part of the OpenAPI schema."""
    router = APIRouter(include_in_schema=False)
    server = McpServer(app, engine)
    allowed = {
        origin.strip() for origin in settings.mcp_allowed_origins.split(",") if origin.strip()
    }

    @router.post("/mcp")
    async def post(request: Request) -> Response:  # pyright: ignore[reportUnusedFunction]
        origin = request.headers.get("origin")
        if origin is not None and origin not in allowed:
            return JSONResponse(
                _error(None, INVALID_REQUEST, "this origin may not call the MCP server"),
                status_code=403,
            )
        try:
            body = json.loads(await request.body())
        except ValueError:
            return JSONResponse(_error(None, PARSE_ERROR, "the body is not JSON"), status_code=400)
        if isinstance(body, list):
            answers = [
                answer
                for answer in [await server.handle(each) for each in body]  # pyright: ignore[reportUnknownVariableType]
                if answer is not None
            ]
            return JSONResponse(answers) if answers else Response(status_code=202)
        answer = await server.handle(body)
        return JSONResponse(answer) if answer is not None else Response(status_code=202)

    @router.api_route("/mcp", methods=["GET", "DELETE"])
    async def unsupported() -> Response:  # pyright: ignore[reportUnusedFunction]
        return Response(status_code=405, headers={"Allow": "POST"})

    return router
