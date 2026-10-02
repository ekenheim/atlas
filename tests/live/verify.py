"""The live verification harness's parts: call caps, the report, and the rehearsal's model.

Used by `tests/live/test_live_verify.py` (ticket 32; `scripts/live-verify.sh`, see
`docs/runbooks.md`, "Live verification"):

- `CappedProxy`: a forwarding HTTP proxy on localhost between Atlas and LiteLLM (or
  Hindsight). It counts the requests that spend quota (chat completions; retain batches) per
  part and in total, and refuses any beyond the part's or the run's cap with HTTP 400, so a
  part can't spend more than its budget whatever the code under test does. Atlas talks to
  the real services only through it; everything else is forwarded unchanged.
- `PART_BUDGETS`: each part's caps. Their sums are the run's hard caps (at most 40 MiniMax
  chat completions and 25 Hindsight retain operations).
- `VerifyReport`: every part's result, budget, usage (the proxies' counts and what the
  database recorded) and numbers, written as `results.json` and `summary.md`.
- `RehearsalModel`: the scripted answers each research role gets in a rehearsal (every part
  against the fakes on localhost). They are written here, so they check the harness's
  wiring, never a model.
"""

import json
import threading
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

import httpx2
import pytest
from pydantic import JsonValue

type Mode = Literal["live", "rehearse"]

PARTS = (
    "sec",
    "exchanges",
    "tradingview",
    "discovery",
    "relationships",
    "investigation",
    "identity",
)
RUN_CHAT_CAP = 40  # MiniMax chat completions per full run (Atlas's role calls)
RUN_RETAIN_CAP = 25  # Hindsight retain operations per full run


@dataclass(frozen=True)
class Budget:
    """A part's caps: chat completions through LiteLLM and retain batches to Hindsight."""

    chat_calls: int
    retain_operations: int


PART_BUDGETS: dict[str, Budget] = {
    # Triage: one call per retained version (30 sections a call), at most 12 versions.
    "sec": Budget(chat_calls=12, retain_operations=RUN_RETAIN_CAP),
    "exchanges": Budget(chat_calls=0, retain_operations=0),  # retention off
    "tradingview": Budget(chat_calls=0, retain_operations=0),
    # The Scout (3 queries) and the mention extractor (10 leads a call), repairs included.
    "discovery": Budget(chat_calls=8, retain_operations=0),
    # One Investigator call (8 passages) and the Reviewer, repairs included.
    "relationships": Budget(chat_calls=6, retain_operations=0),
    # Scout, 2 Investigators, Skeptic, Financial Analyst, Editor, the chained Reviewer and
    # the Hypothesis Editor: 8 calls, with room for repairs.
    "investigation": Budget(chat_calls=14, retain_operations=0),
    "identity": Budget(chat_calls=0, retain_operations=0),
}
assert sum(b.chat_calls for b in PART_BUDGETS.values()) <= RUN_CHAT_CAP
assert sum(b.retain_operations for b in PART_BUDGETS.values()) <= RUN_RETAIN_CAP


def as_dict(value: Any) -> dict[str, Any]:
    """A JSON object read from the API (or {} for null)."""
    return cast(dict[str, Any], value) if value else {}


def as_list(value: Any) -> list[Any]:
    """A JSON array read from the API (or [] for null)."""
    return cast(list[Any], value) if value else []


class CapExceeded(Exception):
    """A part asked for more than its budget: the proxy refused and the part is aborted."""


# --- the capped proxy ----------------------------------------------------------------------------

_HOP_HEADERS = {
    "host",
    "content-length",
    "transfer-encoding",
    "connection",
    "accept-encoding",
    "content-encoding",
    "keep-alive",
}


@dataclass
class CappedProxy:
    """Forwards every request to `upstream`; counts those `counted` selects and refuses any
    beyond the part's cap or `run_cap` with HTTP 400 (an error body both LiteLLM's and
    Hindsight's clients read as a permanent failure)."""

    name: str
    upstream: str
    counted: Callable[[httpx2.Request], bool]
    run_cap: int
    timeout_seconds: float = 900
    part: str = ""
    part_cap: int = 0
    part_count: int = 0
    total: int = 0
    refusals: list[str] = field(default_factory=list[str])
    routes: dict[str, int] = field(default_factory=dict[str, int])
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _client: httpx2.Client | None = None

    def begin_part(self, part: str, cap: int) -> None:
        with self._lock:
            self.part, self.part_cap, self.part_count = part, cap, 0
            self.refusals = []
            self.routes = {}

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        route = f"{request.method} {_route(request.url.path)}"
        with self._lock:
            self.routes[route] = self.routes.get(route, 0) + 1
            if self.counted(request):
                if self.part_count >= self.part_cap or self.total >= self.run_cap:
                    message = (
                        f"live-verify: {self.name} cap reached in part {self.part!r}"
                        f" ({self.part_count}/{self.part_cap} this part, {self.total}/"
                        f"{self.run_cap} this run); request refused"
                    )
                    self.refusals.append(route)
                    error: dict[str, JsonValue] = {
                        "message": message,
                        "type": "live_verify_cap",
                        "param": None,
                        "code": "400",
                    }
                    return httpx2.Response(400, json={"error": error, "detail": message})
                self.part_count += 1
                self.total += 1
        if self._client is None:
            self._client = httpx2.Client(timeout=self.timeout_seconds)
        forwarded = httpx2.Request(
            request.method,
            self.upstream.rstrip("/") + request.url.raw_path.decode("ascii"),
            headers=[(k, v) for k, v in request.headers.items() if k.lower() not in _HOP_HEADERS],
            content=request.content,
        )
        response = self._client.send(forwarded)
        return httpx2.Response(
            response.status_code,
            headers=[(k, v) for k, v in response.headers.items() if k.lower() not in _HOP_HEADERS],
            content=response.content,
        )

    def close(self) -> None:
        if self._client is not None:
            self._client.close()


def _route(path: str) -> str:
    """The path with bank IDs, UUIDs and long IDs folded, for the per-route counts."""
    parts = path.split("/")
    folded = [
        "{id}" if (len(p) >= 20 or p.startswith("atlas-") or p.startswith("srcv:")) else p
        for p in parts
    ]
    return "/".join(folded)


def is_chat_completion(request: httpx2.Request) -> bool:
    return request.method == "POST" and request.url.path.endswith("/chat/completions")


def is_retain(request: httpx2.Request) -> bool:
    """A retain batch (`POST /v1/default/banks/{bank}/memories`): one Hindsight operation."""
    return request.method == "POST" and request.url.path.endswith("/memories")


# --- the report ----------------------------------------------------------------------------------


@dataclass
class VerifyReport:
    """What a verification run saw: written as results.json and summary.md."""

    mode: Mode
    selected: list[str]
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    stack: dict[str, Any] = field(default_factory=dict[str, Any])
    parts: dict[str, dict[str, Any]] = field(default_factory=dict[str, dict[str, Any]])
    extra: dict[str, Any] = field(default_factory=dict[str, Any])
    refused: str | None = None
    chat_cap: int = RUN_CHAT_CAP  # the run's cap (--max-chat-calls may lower it)

    @contextmanager
    def part(self, name: str, usage: Callable[[], dict[str, Any]]) -> Generator[dict[str, Any]]:
        """Record one part: its status (passed, failed, aborted over budget, skipped), the
        reason, its numbers (the caller fills `record["numbers"]`), usage and duration."""
        budget = PART_BUDGETS[name]
        record: dict[str, Any] = {
            "status": "running",
            "reason": None,
            "budget": {
                "chat_calls": budget.chat_calls,
                "retain_operations": budget.retain_operations,
            },
            "numbers": {},
        }
        self.parts[name] = record
        started = time.monotonic()
        try:
            yield record
            record["status"] = "passed"
        except pytest.skip.Exception as skipped:
            record["status"], record["reason"] = "skipped", str(skipped.msg)
            raise
        except CapExceeded as error:
            record["status"], record["reason"] = "aborted", str(error)
            raise
        except BaseException as error:
            record["status"] = "failed"
            record["reason"] = f"{type(error).__name__}: {error}"[:600]
            raise
        finally:
            record["seconds"] = round(time.monotonic() - started, 1)
            if record["status"] != "skipped" or record["reason"] != NOT_SELECTED:
                try:
                    record["usage"] = usage()
                except Exception as error:  # the report must be written whatever happened
                    record["usage"] = {"error": f"{type(error).__name__}: {error}"}

    def totals(self) -> dict[str, int]:
        usages = [as_dict(p.get("usage")) for p in self.parts.values()]
        return {
            "chat_calls": sum(int(u.get("chat_calls", 0)) for u in usages),
            "retain_operations": sum(int(u.get("retain_operations", 0)) for u in usages),
            "llm_calls_recorded": sum(int(u.get("llm_calls_recorded", 0)) for u in usages),
            "tokens_in": sum(int(u.get("tokens_in", 0)) for u in usages),
            "tokens_out": sum(int(u.get("tokens_out", 0)) for u in usages),
        }

    def write(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        results = {
            "mode": self.mode,
            "selected": self.selected,
            "started_at": self.started_at,
            "finished_at": datetime.now(UTC).isoformat(),
            "caps": {"chat_calls": self.chat_cap, "retain_operations": RUN_RETAIN_CAP},
            "totals": self.totals(),
            "refused": self.refused,
            "stack": self.stack,
            "parts": self.parts,
            **self.extra,
        }
        (directory / "results.json").write_text(
            json.dumps(results, indent=2, default=str) + "\n", encoding="utf-8"
        )
        (directory / "summary.md").write_text(self.summary(results), encoding="utf-8")

    def summary(self, results: dict[str, Any]) -> str:
        """A Markdown digest (a table per part, then each part's numbers) for the log."""
        kind = {
            "live": "LIVE (real services; MiniMax via LiteLLM)",
            "rehearse": "REHEARSAL (fakes on localhost; nothing was live)",
        }
        totals = results["totals"]
        lines = [
            f"# Live verification run: {kind[self.mode]}",
            "",
            f"- started {results['started_at']}, finished {results['finished_at']}",
            f"- parts selected: {', '.join(self.selected)}",
            f"- chat completions {totals['chat_calls']}/{self.chat_cap}, retain operations"
            f" {totals['retain_operations']}/{RUN_RETAIN_CAP}, tokens"
            f" {totals['tokens_in']} in / {totals['tokens_out']} out",
        ]
        if self.refused:
            lines.append(f"- **refused by the preflight**: {self.refused}")
        for key in ("hindsight_url", "hindsight_version", "bank_id", "role_model", "database"):
            if key in self.stack:
                lines.append(f"- {key}: `{self.stack[key]}`")
        lines += [
            "",
            "| Part | Result | Chat calls (cap) | Retain ops (cap) | LLM calls recorded"
            " | Tokens in/out | Seconds | Reason |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for name in PARTS:
            record = self.parts.get(name)
            if record is None:
                continue
            usage = as_dict(record.get("usage"))
            budget = record["budget"]
            reason = (record.get("reason") or "").replace("|", "\\|").replace("\n", " ")
            lines.append(
                f"| {name} | **{record['status']}** "
                f"| {usage.get('chat_calls', 0)} ({budget['chat_calls']}) "
                f"| {usage.get('retain_operations', 0)} ({budget['retain_operations']}) "
                f"| {usage.get('llm_calls_recorded', 0)} "
                f"| {usage.get('tokens_in', 0)}/{usage.get('tokens_out', 0)} "
                f"| {record.get('seconds', 0)} | {reason[:200]} |"
            )
        for name in PARTS:
            record = self.parts.get(name)
            if record is None or not record.get("numbers"):
                continue
            lines += ["", f"## {name}", "", "```json"]
            lines.append(json.dumps(record["numbers"], indent=2, default=str))
            lines.append("```")
        for key, value in self.extra.items():
            lines += ["", f"## {key}", "", "```json", json.dumps(value, indent=2, default=str)]
            lines.append("```")
        return "\n".join(lines) + "\n"


NOT_SELECTED = "not selected (--only)"


# --- the rehearsal's model -----------------------------------------------------------------------

# The recorded fixtures the rehearsal's answers are written against (tests/fixtures/searxng and
# the Coherent FY2026 10-K in tests/fixtures/edgar).
DISCOVERY_QUERY = "EML laser suppliers AI transceivers capacity"
INVESTIGATION_QUERY = "indium phosphide substrate capacity expansion 2026"
SUPPLY_QUOTE = (
    "we announced the expansion of our Sherman, Texas, manufacturing facility, entered into a"
    " strategic multi-year supply agreement with NVIDIA for advanced lasers and optical"
    " networking products"
)
# What the mention extractor names in each lead of `unseeded-companies` (by the lead's URL).
MENTIONS: dict[str, list[JsonValue]] = {
    "https://photonics-news.test/2026/09/lumentum-ramps-200g-eml-lasers": [
        {"name": "Lumentum Holdings Inc.", "ticker": "LITE", "exchange": "Nasdaq"}
    ],
    "https://optics-trade.test/articles/soitec-photonics-soi-demand": [
        {"name": "Soitec SA", "ticker": None, "exchange": None},
        {"name": "Coherent Corp.", "ticker": None, "exchange": None},
    ],
    "https://blog.photonics.test/who-makes-eml-lasers": [
        {"name": "Acme Photonics", "ticker": None, "exchange": None}
    ],
}
# Sections the Triage stand-in retains: Item 1 (the business, or a 10-Q's statements), an
# 8-K's results item and a press release's first chunk.
TRIAGE_RETAINS = {"part-i-item-1", "item-2-02", "chunk-001"}


@dataclass
class RehearsalModel:
    """The rehearsal's stand-in for every role, answering from what each request carries."""

    scout_queries: list[str] = field(default_factory=list[str])

    def answer(self, body: dict[str, Any]) -> JsonValue:
        role = body["metadata"]["role"]
        asked = json.loads(body["messages"][1]["content"])
        request: dict[str, Any] = asked["request"]
        retrieved: list[dict[str, Any]] = as_list(asked.get("retrieved_data"))
        if role == "triage":
            return {
                "decisions": [
                    {
                        "anchor": s["anchor"],
                        "decision": "retain" if s["anchor"] in TRIAGE_RETAINS else "skip",
                        "category": "supplier_customer"
                        if s["anchor"] in TRIAGE_RETAINS
                        else "other",
                        "reason": f"rehearsal decision for {s['anchor']}",
                    }
                    for s in request["sections"]
                ]
            }
        if role == "scout":
            return {"queries": [{"query": q, "purpose": None} for q in self.scout_queries]}
        if role == "mention_extractor":
            return {
                "leads": [
                    {"lead": item["id"], "companies": MENTIONS.get(item["source"], [])}
                    for item in retrieved
                ]
            }
        if role == "investigator":
            return {"claims": _supply_claims(request, retrieved)}
        if role == "reviewer":
            return {
                "reviews": [
                    {
                        "item_id": item["item_id"],
                        "hedge": "none",
                        "direction": "as_proposed",
                        "layer": "correct",
                        "suggested_layer": None,
                        "reasoning": "the quote states it",
                    }
                    for item in request["items"]
                ]
            }
        if role == "skeptic" and "passages" not in request:
            # It plans no search; it reads where Memory points (or what code's fallback
            # chooses for a company with no pointer).
            return {"queries": []}
        if role == "skeptic":
            return {"counterevidence": []}  # its reading of them finds none
        if role == "financial_analyst":
            return {"scenarios": []}  # the scenario then comes from the researcher's table
        if role == "editor":
            statement = "Coherent supplies NVIDIA with advanced lasers."
            if "card_findings" in request:
                # The Hypothesis draft cites Claims by ID; the research card by reference.
                claim_ids: list[JsonValue] = [c["claim_id"] for c in request["claims"]]
                finding: dict[str, JsonValue] = {
                    "statement": statement,
                    "claim_ids": claim_ids,
                    "limitations": ["A company's own statement."],
                    "open_questions": [],
                }
                return {
                    "thesis_statement": "Demand for advanced lasers may outgrow capacity.",
                    "mechanism": {
                        "demand_driver": "AI data-center optical interconnects",
                        "possible_constraint": "Qualified advanced-laser capacity",
                        "economic_capture_question": None,
                    },
                    "measurable_predictions": ["Laser lead times stay elevated in 2027"],
                    "catalysts": ["New multi-year supply agreements"],
                    "falsifiers": ["Verified laser capacity exceeds plausible demand"],
                    "required_evidence": ["An original document naming a second source"],
                    "alternative_explanations": ["Inventory build-up mimics demand"],
                    "unresolved_questions": ["Does NVIDIA qualify a second laser source?"],
                    "findings": [finding],
                }
            claim_refs: list[JsonValue] = [c["ref"] for c in request["claims"]]
            card_finding: dict[str, JsonValue] = {
                "statement": statement,
                "claim_refs": claim_refs,
                "limitations": ["A company's own statement."],
                "open_questions": [],
            }
            return {
                "findings": [card_finding],
                "open_questions": ["Is InP substrate capacity a constraint for 2027?"],
                "verdict": "answered",
            }
        raise AssertionError(f"the rehearsal has no answer for role {role!r}")


def _supply_claims(request: dict[str, Any], passages: list[dict[str, Any]]) -> list[JsonValue]:
    """The Coherent 10-K's NVIDIA supply agreement, from the passage holding it (if sent)."""
    ids = {str(c["names"][-1]): str(c["company_id"]) for c in request["companies"]}
    coherent = next((i for name, i in ids.items() if "Coherent" in name), None)
    nvidia = next((i for name, i in ids.items() if "NVIDIA" in name), None)
    claims: list[JsonValue] = []
    for passage in passages:
        if coherent and nvidia and SUPPLY_QUOTE in passage["text"]:
            start = str(passage["text"]).index(SUPPLY_QUOTE)
            claims.append(
                {
                    "passage_id": passage["id"],
                    "subject_company_id": coherent,
                    "predicate": "supplies",
                    "object_company_id": nvidia,
                    "object_name": None,
                    "object_text": None,
                    "product": "advanced lasers",
                    "layer": "chip-laser",
                    "epistemic_type": "company_claim",
                    "quote": SUPPLY_QUOTE,
                    "quote_start": start,
                    "quote_end": start + len(SUPPLY_QUOTE),
                }
            )
            break
    return claims
