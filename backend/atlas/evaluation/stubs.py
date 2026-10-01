"""The services an evaluation case runs against, served on localhost for its job handlers.

- **Scripted LiteLLM** (fake mode only): `GET /model/info` names one scripted deployment per
  alias, and `POST /chat/completions` answers from the case's `script`, per role, in order
  (the last answer repeats). An answer is written in the case's terms (entity and source
  keys, exact quotes) and turned into the role's JSON against the request actually sent:
  the Investigator proposes a Claim only when a passage it was sent holds its quote (a model
  can only quote what it reads, so a document Atlas never sent yields nothing); the Reviewer
  answers the items matching its entries; the Skeptic reads the passages of the sources it
  names; the Editor writes one finding citing every Claim it is sent. A call with no answer
  scripted is an error of the case, except the Financial Analyst's: its scenario proposals
  aren't scored by these cases (no metric reads them), so unless a case scripts its answers
  it proposes no scenario (`UNSCRIPTED_DEFAULTS`), as the SearXNG stub finds no leads; and
  the Skeptic's reading: a case whose Skeptic plan chooses no document now has code's
  fallback choose the seed companies' documents (pilot fix 06), and unless the case scripts
  `skeptic` answers, that reading proposes no counterevidence.
- **Hindsight stub**: `/version` (reported as `evaluation-stub`, so a run's record shows it),
  the bank template import (so runs can start) and an empty recall. Memory isn't evaluated
  here: retention and recall have their own recorded contract tests.
- **SearXNG stub**: every search returns no results (leads aren't scored by these cases).

Any other request is recorded in `errors` and answered 404, and fails the case.
"""

import json
import threading
import uuid
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast

import httpx2
from pydantic import JsonValue

STUB_API_KEY = "sk-atlas-evaluation"  # not a real key: the scripted LiteLLM's only key
STUB_MODEL = "evaluation/scripted"
HINDSIGHT_STUB_VERSION = "evaluation-stub"

type Handler = Callable[[httpx2.Request], httpx2.Response]

# The answer of a role no metric scores when the case scripts none for it.
UNSCRIPTED_DEFAULTS: dict[str, dict[str, JsonValue]] = {
    "financial_analyst": {"scenarios": []},
    "skeptic": {"counterevidence": []},
}


class StubError(Exception):
    """A request the stub can't answer: the case is broken or the pipeline went off-script."""


@dataclass
class Served:
    url: str
    errors: list[str] = field(default_factory=list[str])


@contextmanager
def serve(handler: Handler) -> Generator[Served]:
    """Serve `handler` on an ephemeral localhost port; its exceptions are kept in `errors`."""
    served = Served(url="")

    class _RequestHandler(BaseHTTPRequestHandler):
        def _dispatch(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            request = httpx2.Request(
                self.command,
                f"{served.url}{self.path}",
                headers=[(k, v) for k, v in self.headers.items() if k.lower() != "host"],
                content=body,
            )
            try:
                response = handler(request)
                response.read()
                status, headers, content = response.status_code, response.headers, response.content
            except StubError as error:
                served.errors.append(str(error))
                message = {"error": {"message": str(error), "type": "evaluation_stub"}}
                status, headers = 404, httpx2.Headers({"content-type": "application/json"})
                content = json.dumps(message).encode()
            self.send_response(status)
            for key, value in headers.items():
                if key.lower() not in {"content-length", "transfer-encoding", "connection"}:
                    self.send_header(key, value)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _dispatch

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), _RequestHandler)
    served.url = f"http://127.0.0.1:{server.server_address[1]}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield served
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@dataclass
class ScriptContext:
    """What the scripted answers' keys stand for in the case's database."""

    companies: dict[str, uuid.UUID] = field(default_factory=dict[str, uuid.UUID])
    versions: dict[str, uuid.UUID] = field(default_factory=dict[str, uuid.UUID])

    def company(self, key: str) -> str:
        if key not in self.companies:
            raise StubError(f"the script names entity {key!r}, which wasn't seeded")
        return str(self.companies[key])

    def version(self, key: str) -> str:
        if key not in self.versions:
            raise StubError(f"the script names source {key!r}, which wasn't recorded")
        return str(self.versions[key])

    def entity_key(self, company_id: str | None) -> str | None:
        return next((k for k, v in self.companies.items() if str(v) == company_id), None)


# --- Hindsight and SearXNG ---------------------------------------------------------------------


def hindsight_stub(request: httpx2.Request) -> httpx2.Response:
    path = request.url.path
    if (request.method, path) == ("GET", "/version"):
        return httpx2.Response(200, json={"api_version": HINDSIGHT_STUB_VERSION, "features": {}})
    if path.startswith("/v1/default/banks/"):
        bank = path.split("/")[4]
        if request.method == "POST" and path.endswith("/import"):
            dry = request.url.params.get("dry_run") == "true"
            return httpx2.Response(
                200, json={"bank_id": bank, "config_applied": not dry, "dry_run": dry}
            )
        if request.method == "POST" and path.endswith("/memories/recall"):
            return httpx2.Response(200, json={"results": []})
        if request.method == "GET" and "/mental-models/" in path:
            return httpx2.Response(404, json={"detail": "no mental models in an evaluation"})
    raise StubError(f"Hindsight stub: unexpected {request.method} {path}")


def searxng_stub(request: httpx2.Request) -> httpx2.Response:
    if (request.method, request.url.path) != ("GET", "/search"):
        raise StubError(f"SearXNG stub: unexpected {request.method} {request.url.path}")
    query = request.url.params.get("q", "")
    return httpx2.Response(
        200,
        json={
            "query": query,
            "number_of_results": 0,
            "results": [],
            "answers": [],
            "corrections": [],
            "infoboxes": [],
            "suggestions": [],
            "unresponsive_engines": [],
        },
    )


# --- scripted LiteLLM --------------------------------------------------------------------------


@dataclass
class ScriptedLiteLLM:
    script: dict[str, list[dict[str, JsonValue]]]
    context: ScriptContext
    aliases: list[str]
    calls: dict[str, int] = field(default_factory=dict[str, int])

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        if request.headers.get("Authorization") != f"Bearer {STUB_API_KEY}":
            return httpx2.Response(401, json={"error": {"message": "Authentication Error"}})
        route = (request.method, request.url.path)
        if route == ("GET", "/model/info"):
            data = [
                {
                    "model_name": alias,
                    "litellm_params": {"model": STUB_MODEL},
                    "model_info": {"id": "evaluation-scripted"},
                }
                for alias in self.aliases
            ]
            return httpx2.Response(200, json={"data": data})
        if route != ("POST", "/chat/completions"):
            raise StubError(f"LiteLLM stub: unexpected {request.method} {request.url.path}")
        body = cast(dict[str, Any], json.loads(request.content))
        role = str(body["metadata"]["role"])
        sent = cast(dict[str, Any], json.loads(body["messages"][1]["content"]))
        if role == "skeptic" and "catalog" in sent["request"]:
            role = "skeptic_plan"
        content = json.dumps(self._answer(role, sent))
        completion = {
            "id": f"chatcmpl-evaluation-{sum(self.calls.values())}",
            "object": "chat.completion",
            "created": 1790000000,
            "model": body["model"],
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
        }
        return httpx2.Response(200, json=completion)

    def _answer(self, role: str, sent: dict[str, Any]) -> Any:
        replies = self.script.get(role) or []
        if not replies and role in UNSCRIPTED_DEFAULTS:
            self.calls[role] = self.calls.get(role, 0) + 1
            return UNSCRIPTED_DEFAULTS[role]
        if not replies:
            raise StubError(f"the {role} was called, but the case scripts no {role} answer")
        count = self.calls.get(role, 0)
        self.calls[role] = count + 1
        reply = cast(dict[str, Any], replies[min(count, len(replies) - 1)])
        answer = _ANSWERS.get(role)
        return reply if answer is None else answer(self.context, reply, sent)


def _passages(sent: dict[str, Any]) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], sent["retrieved_data"])


def _holding(passages: list[dict[str, Any]], quote: str, version: str | None = None):
    return [
        p
        for p in passages
        if quote in p["text"] and (version is None or str(p["source"]).startswith(version))
    ]


def _investigator(
    context: ScriptContext, reply: dict[str, Any], sent: dict[str, Any]
) -> dict[str, Any]:
    passages = _passages(sent)
    claims: list[Any] = []
    for claim in reply.get("claims", []):
        holding = _holding(passages, claim["quote"])
        if not holding:
            continue  # never sent: a model can only quote what it reads
        start = holding[0]["text"].index(claim["quote"])
        claims.append(
            {
                "passage_id": holding[0]["id"],
                "subject_company_id": context.company(claim["subject"]),
                "predicate": claim["predicate"],
                "object_company_id": context.company(claim["object"])
                if claim.get("object")
                else None,
                "object_name": None,
                "object_text": claim.get("object_text"),
                "product": claim.get("product"),
                "layer": claim["layer"],
                "quote": claim["quote"],
                "quote_start": start,
                "quote_end": start + len(claim["quote"]),
                "epistemic_type": claim.get("epistemic_type", "company_claim"),
            }
        )
    return {"claims": claims}


def _reviewer(
    context: ScriptContext, reply: dict[str, Any], sent: dict[str, Any]
) -> dict[str, Any]:
    reviews: list[Any] = []
    for item in sent["request"]["items"]:
        subject = context.entity_key(item["subject"]["company_id"])
        target = item["object_company"]
        obj = context.entity_key(target["company_id"]) if target else None
        matching = [
            entry
            for entry in reply.get("reviews", [])
            if entry["subject"] == subject
            and entry["predicate"] == item["predicate"]
            and entry.get("object") == obj
            and entry.get("layer", item["layer"]) == item["layer"]
        ]
        entry = matching[0] if matching else reply.get("otherwise")
        if entry is None:
            continue  # left out: the item gets no answer
        reviews.append(
            {
                "item_id": item["item_id"],
                "verdict": entry["verdict"],
                "direction": entry["direction"],
                "layer": entry["layer_verdict"],
                "suggested_layer": entry.get("suggested_layer"),
                "reasoning": entry.get("reasoning", "scripted"),
            }
        )
    return {"reviews": reviews}


def _skeptic_plan(
    context: ScriptContext, reply: dict[str, Any], sent: dict[str, Any]
) -> dict[str, Any]:
    return {
        "queries": reply.get("queries", []),
        "documents": [
            {
                "source_version_id": context.version(d["source"]),
                "checklist_item": d["checklist_item"],
            }
            for d in reply.get("documents", [])
        ],
    }


def _skeptic(context: ScriptContext, reply: dict[str, Any], sent: dict[str, Any]) -> dict[str, Any]:
    supporting: list[Any] = [c["claim_id"] for c in sent["request"]["supporting_claims"]]
    passages = _passages(sent)
    found: list[Any] = []
    for item in reply.get("counterevidence", []):
        holding = _holding(passages, item["quote"], context.version(item["source"]))
        if not holding:
            continue
        start = holding[0]["text"].index(item["quote"])
        contradicts = item.get("contradicts", True)
        found.append(
            {
                "passage_id": holding[0]["id"],
                # A case's item is a contradiction of every supporting Claim (how: `limits`
                # unless it says), or bear context when it `contradicts` nothing.
                "kind": "contradiction" if contradicts else "bear_context",
                "checklist_item": item["checklist_item"],
                "subject_company_id": context.company(item["subject"]),
                "statement": item["statement"],
                "quote": item["quote"],
                "quote_start": start,
                "quote_end": start + len(item["quote"]),
                "epistemic_type": item.get("epistemic_type", "company_claim"),
                "contradicts_claim_ids": supporting if contradicts else [],
                "how": item.get("how", "limits") if contradicts else None,
                "figure_name": item.get("figure_name"),
                "figure_period": item.get("figure_period"),
                "disproves_premise": item.get("disproves"),
            }
        )
    return {"counterevidence": found}


def _editor(context: ScriptContext, reply: dict[str, Any], sent: dict[str, Any]) -> dict[str, Any]:
    claims: list[Any] = [c["claim_id"] for c in sent["request"]["claims"]]
    findings: list[Any] = []
    if claims:
        findings.append(
            {
                "statement": reply["statement"],
                "claim_ids": claims,
                "limitations": reply.get("limitations", []),
                "open_questions": reply.get("finding_open_questions", []),
            }
        )
    return {
        "findings": findings,
        "open_questions": reply.get("open_questions", []),
        "verdict": reply.get("verdict", "answered"),
    }


type _Answer = Callable[[ScriptContext, dict[str, Any], dict[str, Any]], Any]
_ANSWERS: dict[str, _Answer] = {
    "investigator": _investigator,
    "reviewer": _reviewer,
    "skeptic_plan": _skeptic_plan,
    "skeptic": _skeptic,
    "editor": _editor,
}
