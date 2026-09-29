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
  UUIDv5 of the request body; a repeat of an identical request, such as a resubmission after a
  failed operation, is a new operation, keyed also by how many times the body was sent before).
  Polling that
  operation serves `retain/05-batch-final` with only `operation_id` changed, and reading one
  of its documents serves `upsert/09-get-document` with only `id`, `bank_id`, `tags` and
  `document_metadata` changed to the retained item's. Recorded requests still replay as
  recorded.
- `report_zero_facts` and `hold_retains` (need `derive_retains`): a zero-fact document and a
  failed or stuck retain were never recorded. `report_zero_facts` serves a derived document
  with its memory counts set to zero; `hold_retains` applies `hold_operation` to each derived
  retain operation whose batch matches.
- `hold_operation(..., error_message=...)` and `hold_retains(..., error_message=..., times=...)`:
  a failed operation's error was never recorded either (the spike saw no 429 or outage), so a
  held status can also change only the response's `error_message`. The message text is the
  OpenAI-style error LiteLLM returns for a 429 or 503, as quoted in Atlas's tests; it has not
  been checked against a real Hindsight failure. `times` limits a retain hold to the first
  matching batches, so a resubmitted batch is served as recorded.
- `derive_memories` (implies `derive_retains`): the recorded memories belong to the synthetic
  documents, so none can point at an Atlas section. With it on, each derived document (except
  zero-fact ones) holds one **world fact**, `derived_fact(document_id)`. Reading it serves
  `reflect/06-resolve-source-memory` with only `id` (a UUIDv5 of the document ID), `text`
  (the section's first 200 characters, whitespace collapsed), `context`, `document_id`,
  `chunk_id`, `tags`, `metadata` and `mentioned_at` changed to the retained item's.
  `derive_observation(document_ids)` adds an **observation** consolidated from those
  documents' facts; reading it serves `reflect/02-resolve-memory` with only `id`, `text` (its
  first source fact's), `tags` (the union of its sources'), `source_memory_ids` and
  `source_memories` changed (each embedded source is the recorded first one, with only `id`,
  `text`, `context` and `mentioned_at` changed).
  An unrecorded strict-tag recall (`any_strict`/`all_strict`) serves `tags/02-tags-any_strict`
  with its `results` replaced by the derived observations, then facts, whose tags match the
  scope the way the recorded strict modes did (untagged and non-matching memories excluded).
  Each result is the recorded result of the same type (its first observation, its first world
  fact) with only the fields above changed; the scores stay as recorded.
- `forget(memory_id)` (a deleted memory; never recorded): reading it answers HTTP 404 with a
  **hand-written** body `{"detail": "Memory not found"}` (only the status is relied on). It
  drops out of derived recalls; an observation keeps its ID in `source_memory_ids` but drops
  it from `source_memories`.
- `script_reflect(text, cited, ...)` (a reflect answer is LLM output, and no recorded one can
  cite an Atlas section): the next unrecorded reflect serves `reflect/01-provenance` with only
  `text`, `based_on.memories`, `structured_output` and `structured_output_error` changed.
  Each cited memory is the recorded first `based_on` entry with only `id`, `text`, `type` and
  `context` changed; a `ChunkContent(document_id)` entry is content without memory identity
  (`id: null`, `type: null`), its `text` the retained section's first 400 characters
  (whitespace collapsed). **The answer text is written by the test**, so the quotes in it are
  the test's choice.
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
    error_message: str | None = None  # None: as recorded


@dataclass(frozen=True)
class ChunkContent:
    """A reflect citation drawn from a retained document's raw chunk, with no memory ID."""

    document_id: str


@dataclass
class _ScriptedReflect:
    text: str
    cited: "Sequence[str | ChunkContent]"
    structured_output: dict[str, JsonValue] | None
    structured_output_error: str | None


@dataclass
class _RetainHold:
    status: str
    polls: int | None
    where: Callable[[Sequence[str]], bool]
    error_message: str | None = None
    times: int | None = None  # None: every matching batch


# The recordings derived responses are built from (see the module docstring).
DERIVED_RETAIN = "retain/04-batch"
DERIVED_RETAIN_FINAL = "retain/05-batch-final"
DERIVED_DOCUMENT = "upsert/09-get-document"
DERIVED_FACT = "reflect/06-resolve-source-memory"
DERIVED_OBSERVATION = "reflect/02-resolve-memory"
DERIVED_RECALL = "tags/02-tags-any_strict"
DERIVED_REFLECT = "reflect/01-provenance"
FACT_TEXT_CHARS = 200
CHUNK_TEXT_CHARS = 400
_DERIVED_NAMESPACE = uuid.UUID("0f4c9a53-7d1e-4b8e-9c3a-2e6f1d5b8a70")
_EMBEDDED_SOURCE_FIELDS = ("id", "text", "context", "mentioned_at")


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
    _submissions: dict[str, int] = field(init=False, default_factory=dict[str, int])
    _derive_memories: bool = field(init=False, default=False)
    _observations: dict[str, list[str]] = field(init=False, default_factory=dict[str, list[str]])
    _forgotten: set[str] = field(init=False, default_factory=set[str])
    _reflects: deque[_ScriptedReflect] = field(init=False, default_factory=deque[_ScriptedReflect])

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

    def hold_operation(
        self,
        operation_id: str,
        status: str,
        polls: int | None = None,
        error_message: str | None = None,
    ) -> None:
        """Report `status` (and `error_message`, if given) for the next `polls` reads of a
        recorded operation (None: forever)."""
        self._holds[operation_id] = _Hold(status, polls, error_message)

    def derive_retains(self) -> None:
        """Answer unrecorded batch retains, their operations and documents (derived; see above)."""
        self._derive = True

    def report_zero_facts(self, document_ids: Callable[[str], bool]) -> None:
        """Serve derived documents whose ID matches with zero memories (derived)."""
        self._zero_facts = document_ids

    def hold_retains(
        self,
        status: str,
        *,
        where: Callable[[Sequence[str]], bool],
        polls: int | None = None,
        error_message: str | None = None,
        times: int | None = None,
    ) -> None:
        """`hold_operation` for each later derived retain whose batch's document IDs match
        (only the first `times` such batches, if given)."""
        self._retain_holds.append(_RetainHold(status, polls, where, error_message, times))

    def derive_memories(self) -> None:
        """One world fact per derived document, observations, and strict recalls (derived)."""
        self._derive = True
        self._derive_memories = True

    def derived_fact(self, document_id: str) -> str:
        """The ID of the derived world fact extracted from a retained document."""
        if document_id not in self._derived_documents:
            raise KeyError(f"{document_id} was not retained through the fake")
        return _fact_id(document_id)

    def derive_observation(self, document_ids: Sequence[str]) -> str:
        """An observation consolidated from these documents' facts; returns its ID."""
        sources = [self.derived_fact(document_id) for document_id in document_ids]
        observation_id = str(uuid.uuid5(_DERIVED_NAMESPACE, "observation:" + "|".join(sources)))
        self._observations[observation_id] = sources
        return observation_id

    def forget(self, memory_id: str) -> None:
        """The memory is gone: reading it answers 404 (derived; see the module docstring)."""
        self._forgotten.add(memory_id)

    def script_reflect(
        self,
        text: str,
        cited: "Sequence[str | ChunkContent]",
        *,
        structured_output: dict[str, JsonValue] | None = None,
        structured_output_error: str | None = None,
    ) -> None:
        """Answer the next unrecorded reflect with this text and these citations (derived)."""
        self._reflects.append(
            _ScriptedReflect(text, cited, structured_output, structured_output_error)
        )

    def requests(self, method: str, route: str) -> list[dict[str, Any]]:
        """The JSON bodies of the bank requests received for `route` (e.g. `memories/recall`)."""
        return [
            cast(dict[str, Any], json.loads(request.content))
            for request in self.calls
            if request.method == method and request.url.path.endswith(f"/{route}")
        ]

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
        if hold.error_message is not None:
            derived["error_message"] = hold.error_message
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
        if not self._derive_memories:
            return None
        if request.method == "GET" and len(route) == 2 and route[0] == "memories":
            return self._derived_memory(bank, route[1])
        if request.method == "POST" and route == ["memories", "recall"] and isinstance(body, dict):
            return self._derived_recall(bank, body)
        if request.method == "POST" and route == ["reflect"] and self._reflects:
            return self._derived_reflect(bank)
        return None

    def _derived_retain(self, bank: str, body: dict[str, JsonValue]) -> httpx2.Response | None:
        items = body.get("items")
        if body.get("async") is not True or not isinstance(items, list) or not items:
            return None
        key = _body_key(body)
        repeat = self._submissions.get(key, 0)
        self._submissions[key] = repeat + 1
        operation_id = str(uuid.uuid5(_DERIVED_NAMESPACE, key if not repeat else f"{key}#{repeat}"))
        document_ids: list[str] = []
        for item in cast(list[dict[str, JsonValue]], items):
            document_id = str(item["document_id"])
            document_ids.append(document_id)
            self._derived_documents[document_id] = item
        self._derived_operations.add(operation_id)
        for hold in self._retain_holds:
            if hold.times != 0 and hold.where(document_ids):
                self.hold_operation(operation_id, hold.status, hold.polls, hold.error_message)
                if hold.times is not None:
                    hold.times -= 1
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

    # --- derived memories, recall and reflect (see the module docstring) -----------------------

    def _facts(self, bank: str) -> dict[str, dict[str, JsonValue]]:
        """The derived world facts that exist now, by ID, in retain order."""
        facts: dict[str, dict[str, JsonValue]] = {}
        for document_id, item in self._derived_documents.items():
            fact_id = _fact_id(document_id)
            if self._zero_facts(document_id) or fact_id in self._forgotten:
                continue
            facts[fact_id] = {
                "id": fact_id,
                "text": _collapsed(item["content"])[:FACT_TEXT_CHARS],
                "context": item.get("context"),
                "document_id": document_id,
                "chunk_id": f"{bank}_{document_id}_0",
                "tags": item.get("tags", []),
                "metadata": item.get("metadata", {}),
                "mentioned_at": item.get("timestamp"),
            }
        return facts

    def _observation(self, observation_id: str, bank: str) -> dict[str, JsonValue]:
        facts = self._facts(bank)
        present = [facts[s] for s in self._observations[observation_id] if s in facts]
        tags: list[JsonValue] = []
        for fact in present:
            tags.extend(t for t in cast(list[JsonValue], fact["tags"]) if t not in tags)
        return {
            "id": observation_id,
            "text": present[0]["text"] if present else "",
            "tags": tags,
        }

    def _derived_memory(self, bank: str, memory_id: str) -> httpx2.Response | None:
        if memory_id in self._forgotten:
            self.served.append("memories/<id> 404 (derived, hand-written body)")
            return httpx2.Response(404, json={"detail": "Memory not found"})
        facts = self._facts(bank)
        if memory_id in facts:
            recording = self.recording(DERIVED_FACT)
            response = copy.deepcopy(recording.response_object()) | facts[memory_id]
            self.served.append(f"{DERIVED_FACT} (derived)")
            return httpx2.Response(recording.status, json=response)
        if memory_id in self._observations:
            recording = self.recording(DERIVED_OBSERVATION)
            response = copy.deepcopy(recording.response_object())
            embedded = cast(list[dict[str, JsonValue]], response["source_memories"])[0]
            sources = self._observations[memory_id]
            response |= self._observation(memory_id, bank)
            response["source_memory_ids"] = list[JsonValue](sources)
            response["source_memories"] = [
                copy.deepcopy(embedded) | {k: facts[s][k] for k in _EMBEDDED_SOURCE_FIELDS}
                for s in sources
                if s in facts
            ]
            self.served.append(f"{DERIVED_OBSERVATION} (derived)")
            return httpx2.Response(recording.status, json=response)
        return None

    def _derived_recall(self, bank: str, body: dict[str, JsonValue]) -> httpx2.Response | None:
        match, tags = body.get("tags_match"), body.get("tags")
        if match not in ("any_strict", "all_strict") or not isinstance(tags, list) or not tags:
            return None
        scope = {str(tag) for tag in tags}

        def in_scope(memory_tags: JsonValue) -> bool:
            have = {str(tag) for tag in cast(list[JsonValue], memory_tags)}
            return bool(have & scope) if match == "any_strict" else scope <= have

        recording = self.recording(DERIVED_RECALL)
        response = copy.deepcopy(recording.response_object())
        recorded = cast(list[dict[str, JsonValue]], response["results"])
        observation = next(r for r in recorded if r["type"] == "observation")
        world = next(r for r in recorded if r["type"] == "world")
        results: list[JsonValue] = []
        for observation_id in self._observations:
            fields = self._observation(observation_id, bank)
            if observation_id not in self._forgotten and in_scope(fields["tags"]):
                results.append(copy.deepcopy(observation) | fields)
        results.extend(
            copy.deepcopy(world) | fact
            for fact in self._facts(bank).values()
            if in_scope(fact["tags"])
        )
        response["results"] = results
        self.served.append(f"{DERIVED_RECALL} (derived)")
        return httpx2.Response(recording.status, json=response)

    def _derived_reflect(self, bank: str) -> httpx2.Response:
        scripted = self._reflects.popleft()
        recording = self.recording(DERIVED_REFLECT)
        response = copy.deepcopy(recording.response_object())
        based_on = cast(dict[str, JsonValue], response["based_on"])
        entry = cast(list[dict[str, JsonValue]], based_on["memories"])[0]
        facts = self._facts(bank)
        memories: list[JsonValue] = []
        for cited in scripted.cited:
            fields: dict[str, JsonValue]
            if isinstance(cited, ChunkContent):
                content = self._derived_documents[cited.document_id]["content"]
                text = _collapsed(content)[:CHUNK_TEXT_CHARS]
                fields = {"id": None, "text": text, "type": None, "context": None}
            elif cited in self._observations:
                text = self._observation(cited, bank)["text"]
                fields = {"id": cited, "text": text, "type": "observation", "context": None}
            elif cited in facts:
                fact = facts[cited]
                fields = {"id": cited, "text": fact["text"], "type": "world"}
                fields["context"] = fact["context"]
            else:  # cited, then deleted: the answer still carries the text it was given
                fields = {"id": cited, "text": "(deleted)", "type": "world", "context": None}
            memories.append(copy.deepcopy(entry) | fields)
        based_on["memories"] = memories
        response |= {
            "text": scripted.text,
            "structured_output": scripted.structured_output,
            "structured_output_error": scripted.structured_output_error,
        }
        self.served.append(f"{DERIVED_REFLECT} (derived)")
        return httpx2.Response(recording.status, json=response)


def _fact_id(document_id: str) -> str:
    return str(uuid.uuid5(_DERIVED_NAMESPACE, f"world:{document_id}"))


def _collapsed(content: JsonValue) -> str:
    return " ".join(str(content).split())
