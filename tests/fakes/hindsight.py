"""A transport-level fake Hindsight 0.10.1, replaying the spike's recorded interactions.

Every response it serves is a real recording from `spikes/hindsight/recordings/`. A request is
answered only when its method, path, query and JSON body match a recording exactly; anything
else raises `UnrecordedRequest`, so a gateway request that drifts from what the real server was
sent fails loudly instead of being answered by a guess. Extend the fake by recording new real
interactions, never by hand-writing responses.

Derived behaviours (each serves a recorded response with only the named fields changed):

- `hold_operation`: the spike recorded only the terminal state of each operation, so to
  exercise polling it serves a recorded operation-status response with nothing changed but
  its `status` field.
- `derive_retains` (off by default): the spike retained synthetic documents, so an Atlas
  retain of real sections (whose document IDs and content no recording can match) would be
  unanswerable. With it on, an *unrecorded* async batch retain is answered with the recorded
  `retain/04-batch` response, changing only `bank_id`, `items_count` and `operation_id` (a
  UUIDv5 of the request body, so an identical request gets the same operation). Polling that
  operation serves `retain/05-batch-final` with only `operation_id` changed, and reading one
  of its documents serves `upsert/09-get-document` with only `id`, `bank_id`, `tags` and
  `document_metadata` changed to the retained item's. Recorded requests still replay as
  recorded.
- `report_zero_facts` and `hold_retains` (need `derive_retains`): a zero-fact document and a
  failed or stuck retain were never recorded. `report_zero_facts` serves a derived document
  with its memory counts set to zero; `hold_retains` applies `hold_operation` to each derived
  retain operation whose batch matches.
"""

import copy
import functools
import json
import uuid
from collections import defaultdict, deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import httpx2
from pydantic import JsonValue

RECORDINGS_DIR = Path(__file__).resolve().parents[2] / "spikes" / "hindsight" / "recordings"

type QueryKey = tuple[tuple[str, str], ...]
type RequestKey = tuple[str, str, QueryKey, str]


class UnrecordedRequest(AssertionError):
    """The gateway sent a request no recording matches."""


@dataclass(frozen=True)
class Recording:
    name: str  # "<feature>/<NN-name>", e.g. "retain/04-batch"
    method: str
    path: str
    query: dict[str, JsonValue] | None
    body: JsonValue
    status: int
    response_body: JsonValue

    @property
    def bank_id(self) -> str:
        """The bank in the recorded path (`/v1/default/banks/<bank>/...`)."""
        parts = self.path.split("/")
        return parts[4] if len(parts) > 4 and parts[3] == "banks" else ""

    def response_object(self) -> dict[str, JsonValue]:
        assert isinstance(self.response_body, dict), self.name
        return self.response_body

    def request_object(self) -> dict[str, JsonValue]:
        assert isinstance(self.body, dict), self.name
        return self.body


def load_recordings(directory: Path = RECORDINGS_DIR) -> dict[str, Recording]:
    """All recordings by name. Read once per process; treat the bodies as read-only."""
    return dict(_load(directory))


@functools.cache
def _load(directory: Path) -> dict[str, Recording]:
    recordings: dict[str, Recording] = {}
    for file in sorted(directory.glob("*/*.json")):
        raw = cast(dict[str, dict[str, JsonValue]], json.loads(file.read_text(encoding="utf-8")))
        request, response = raw["request"], raw["response"]
        name = f"{file.parent.name}/{file.stem}"
        recordings[name] = Recording(
            name=name,
            method=str(request["method"]),
            path=str(request["path"]),
            query=cast(dict[str, JsonValue] | None, request.get("query")),
            body=request.get("body"),
            status=cast(int, response["status"]),
            response_body=response.get("body"),
        )
    return recordings


def _query_key(pairs: list[tuple[str, str]]) -> QueryKey:
    return tuple(sorted(pairs))


def _recorded_query(query: dict[str, JsonValue] | None) -> QueryKey:
    pairs: list[tuple[str, str]] = []
    for key, value in (query or {}).items():
        values = value if isinstance(value, list) else [value]
        pairs.extend((key, _query_value(v)) for v in values)
    return _query_key(pairs)


def _query_value(value: JsonValue) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _body_key(body: JsonValue) -> str:
    return json.dumps(body, sort_keys=True)


@dataclass
class _Hold:
    status: str
    polls: int | None  # None: hold forever


@dataclass
class _RetainHold:
    status: str
    polls: int | None
    where: Callable[[Sequence[str]], bool]


# The recordings derived responses are built from (see the module docstring).
DERIVED_RETAIN = "retain/04-batch"
DERIVED_RETAIN_FINAL = "retain/05-batch-final"
DERIVED_DOCUMENT = "upsert/09-get-document"
_DERIVED_NAMESPACE = uuid.UUID("0f4c9a53-7d1e-4b8e-9c3a-2e6f1d5b8a70")


def _never(_: str) -> bool:
    return False


@dataclass
class RecordedHindsight:
    """Serves the recordings through an `httpx2.MockTransport`; inspect `calls` and `served`."""

    recordings: dict[str, Recording] = field(default_factory=load_recordings)
    calls: list[httpx2.Request] = field(default_factory=list[httpx2.Request])
    served: list[str] = field(default_factory=list[str])
    _replies: dict[RequestKey, deque[Recording]] = field(init=False)
    _holds: dict[str, _Hold] = field(init=False, default_factory=dict[str, _Hold])
    _derive: bool = field(init=False, default=False)
    _derived_operations: set[str] = field(init=False, default_factory=set[str])
    _derived_documents: dict[str, dict[str, JsonValue]] = field(
        init=False, default_factory=dict[str, dict[str, JsonValue]]
    )
    _zero_facts: Callable[[str], bool] = field(init=False, default_factory=lambda: _never)
    _retain_holds: list[_RetainHold] = field(init=False, default_factory=list[_RetainHold])

    def __post_init__(self) -> None:
        self._replies = defaultdict(deque)
        for recording in self.recordings.values():
            key = (
                recording.method,
                recording.path,
                _recorded_query(recording.query),
                _body_key(recording.body),
            )
            self._replies[key].append(recording)

    @property
    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self._handle)

    def recording(self, name: str) -> Recording:
        return self.recordings[name]

    def hold_operation(self, operation_id: str, status: str, polls: int | None = None) -> None:
        """Report `status` for the next `polls` reads of a recorded operation (None: forever)."""
        self._holds[operation_id] = _Hold(status, polls)

    def derive_retains(self) -> None:
        """Answer unrecorded batch retains, their operations and documents (derived; see above)."""
        self._derive = True

    def report_zero_facts(self, document_ids: Callable[[str], bool]) -> None:
        """Serve derived documents whose ID matches with zero memories (derived)."""
        self._zero_facts = document_ids

    def hold_retains(
        self, status: str, *, where: Callable[[Sequence[str]], bool], polls: int | None = None
    ) -> None:
        """`hold_operation` for each later derived retain whose batch's document IDs match."""
        self._retain_holds.append(_RetainHold(status, polls, where))

    def retained(self) -> list[list[dict[str, Any]]]:
        """The items of every batch retain received, in order (recorded or derived)."""
        batches: list[list[dict[str, Any]]] = []
        for request in self.calls:
            if request.method == "POST" and request.url.path.endswith("/memories"):
                body = cast(dict[str, Any], json.loads(request.content))
                batches.append(cast(list[dict[str, Any]], body["items"]))
        return batches

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self.calls.append(request)
        content = request.content
        body: JsonValue = json.loads(content) if content else None
        key = (
            request.method,
            request.url.path,
            _query_key(list(request.url.params.multi_items())),
            _body_key(body),
        )
        queue = self._replies.get(key)
        if not queue and self._derive:
            derived = self._derived(request, body)
            if derived is not None:
                return derived
        if not queue:
            raise UnrecordedRequest(
                f"no recording for {request.method} {request.url.path} "
                f"query={dict(request.url.params)} body={body!r}"
            )
        recording = queue[0]
        if len(queue) > 1:  # replay identical requests in recorded order, then repeat the last
            queue.popleft()
        self.served.append(recording.name)
        return self._respond(recording)

    def _respond(self, recording: Recording) -> httpx2.Response:
        body = recording.response_body
        if isinstance(body, dict) and "_binary_bytes" in body:
            raise UnrecordedRequest(f"{recording.name}: the binary body was not recorded")
        if (
            isinstance(body, dict)
            and recording.method == "GET"
            and "/operations/" in recording.path
        ):
            body = self._apply_hold(body)
        if isinstance(body, str):
            return httpx2.Response(recording.status, text=body)
        return httpx2.Response(recording.status, json=body)

    def _apply_hold(self, body: dict[str, JsonValue]) -> dict[str, JsonValue]:
        hold = self._holds.get(str(body.get("operation_id")))
        if hold is None or hold.polls == 0:
            return body
        if hold.polls is not None:
            hold.polls -= 1
        derived = copy.deepcopy(body)
        derived["status"] = hold.status
        return derived

    # --- derived retains (see the module docstring) --------------------------------------------

    def _derived(self, request: httpx2.Request, body: JsonValue) -> httpx2.Response | None:
        parts = request.url.path.split("/")  # ["", "v1", "default", "banks", bank, ...]
        if len(parts) < 6 or parts[1:4] != ["v1", "default", "banks"]:
            return None
        bank, route = parts[4], parts[5:]
        if request.method == "POST" and route == ["memories"] and isinstance(body, dict):
            return self._derived_retain(bank, body)
        if request.method == "GET" and len(route) == 2 and route[0] == "operations":
            if route[1] in self._derived_operations:
                return self._derived_operation(route[1])
        if request.method == "GET" and len(route) == 2 and route[0] == "documents":
            if route[1] in self._derived_documents:
                return self._derived_document(bank, route[1])
        return None

    def _derived_retain(self, bank: str, body: dict[str, JsonValue]) -> httpx2.Response | None:
        items = body.get("items")
        if body.get("async") is not True or not isinstance(items, list) or not items:
            return None
        operation_id = str(uuid.uuid5(_DERIVED_NAMESPACE, _body_key(body)))
        document_ids: list[str] = []
        for item in cast(list[dict[str, JsonValue]], items):
            document_id = str(item["document_id"])
            document_ids.append(document_id)
            self._derived_documents[document_id] = item
        self._derived_operations.add(operation_id)
        for hold in self._retain_holds:
            if hold.where(document_ids):
                self.hold_operation(operation_id, hold.status, hold.polls)
        recording = self.recording(DERIVED_RETAIN)
        response = copy.deepcopy(recording.response_object())
        response |= {"bank_id": bank, "items_count": len(items), "operation_id": operation_id}
        self.served.append(f"{DERIVED_RETAIN} (derived)")
        return httpx2.Response(recording.status, json=response)

    def _derived_operation(self, operation_id: str) -> httpx2.Response:
        recording = self.recording(DERIVED_RETAIN_FINAL)
        response = copy.deepcopy(recording.response_object())
        response["operation_id"] = operation_id
        self.served.append(f"{DERIVED_RETAIN_FINAL} (derived)")
        return httpx2.Response(recording.status, json=self._apply_hold(response))

    def _derived_document(self, bank: str, document_id: str) -> httpx2.Response:
        item = self._derived_documents[document_id]
        recording = self.recording(DERIVED_DOCUMENT)
        response = copy.deepcopy(recording.response_object())
        response |= {
            "id": document_id,
            "bank_id": bank,
            "tags": item.get("tags", []),
            "document_metadata": item.get("metadata", {}),
        }
        if self._zero_facts(document_id):
            counts = cast(dict[str, JsonValue], response["nodes_by_fact_type"])
            response["memory_unit_count"] = 0
            response["nodes_by_fact_type"] = dict.fromkeys(counts, 0)
        self.served.append(f"{DERIVED_DOCUMENT} (derived)")
        return httpx2.Response(recording.status, json=response)
