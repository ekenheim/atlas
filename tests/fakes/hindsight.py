"""A transport-level fake Hindsight, replaying the spike's recorded interactions.

The recordings are 0.10.1's (the Phase 2 contract) and 0.10.2's memory-quality features
(observation scopes, recall options and scores, entities, entity labels, the entity listing,
dry-run extraction, reflect options, a tagged mental model, chunks, reprocess; memory-quality
ticket 01). The 0.10.2 ones are served exactly as recorded; no derivation was added for them.

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
  `document_metadata` changed to the retained item's. Listing a derived document's memories
  (`GET .../memories/list?document_id=<id>&limit=N[&offset=M]`) serves
  `observations/04-list-via-memories` with only `items` (the document's one derived world
  fact, none for a zero-fact document; each item the recorded first one with only `id`,
  `text`, `context`, `fact_type`, `document_id`, `chunk_id`, `tags`, `metadata`,
  `mentioned_at` and `source_memory_ids` changed), `total`, `limit` and `offset` changed.
  Recorded requests still replay as recorded.
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
- **Per-document states after a failed or cancelled retain** (memory-quality ticket 03; what
  a real failed or cancelled operation leaves stored was never recorded): a batch held
  `failed` or `cancelled` stores only the documents `hold_retains(..., stored=...)` matches
  (default none). A document it did not store, and no earlier batch stored, is absent:
  reading it answers HTTP 404 with a **hand-written** body `{"detail": "Document not found"}`
  (only the status is relied on), and it has no fact. A document an earlier batch stored
  stays as it was. A `cancelled` hold serves the recorded final status with only `status`
  changed to `cancelled` (and `error_message` if given), as any held status.
- `report_extraction_errors(count, where=..., times=...)` (an extraction error was never
  recorded): a matching derived retain operation's final status serves
  `retain/05-batch-final` with only `result_metadata.extraction_errors_count` (recorded `0`)
  also changed, to `count`. Its documents are stored as usual.
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
  `derive_observation(document_ids, scope=tags)` (memory-quality ticket 06) is the observation
  consolidated in that explicit observation scope instead: its `tags` are the scope's tags
  alone, as `observation_scopes/05` to `08` showed (one observation per scope, carrying only that
  scope's tags), and every source document's retained item must have sent that scope in its
  `observation_scopes` (the fake raises otherwise, so a test can't derive an observation the
  item's scopes wouldn't produce). Without `scope`, the tags stay the union of its sources'
  (the `combined` default of an item sent without scopes).
  With `derive_memories` on and no scopes scripted, `GET .../observations/scopes` serves
  `observation_scopes/09-list-scopes` with only `scopes` (each derived observation's tag set
  in the bank with its count, most populous first, then in first-derived order), `total`,
  `limit` and `offset` changed.
  An unrecorded strict-tag recall (`any_strict`/`all_strict`) serves `tags/02-tags-any_strict`
  with its `results` replaced by the derived observations, then facts, whose tags match the
  scope the way the recorded strict modes did (untagged and non-matching memories excluded).
  Each result is the recorded result of the same type (its first observation, its first world
  fact) with only the fields above changed; the scores stay as recorded.
- **`include.source_facts` on a derived recall** (memory-quality ticket 07): when the recall's
  body asks for source facts, each derived observation in the results has `source_fact_ids`
  set to all its source facts (a deleted one too: the docs say the list always names every
  source), and the response's `source_facts` map holds each source fact that exists, keyed by
  its ID, deduplicated, in result order. Each entry is the first entry of
  `recall_options/06-include-source-facts`'s map with only `id`, `text`, `context`,
  `document_id`, `chunk_id`, `tags`, `metadata` and `mentioned_at` changed (the derived
  fact's). `source_facts_truncated` is false, or true after `truncate_source_facts(keep)`
  when the map was cut to its first `keep` facts (the budget's doing, by the docs). The other
  0.10.2 recall fields (`max_tokens`, `types`, `prefer_observations`, `query_timestamp`) are
  accepted and change nothing in a derived recall; its `scores` and `entities` stay as
  recorded.
- `script_fact_text(document_id, text)` (needs `derive_memories`; Hindsight writes a fact in
  its own words, and no recorded fact is about an Atlas section): that document's derived
  world fact has `text`, **written by the test** (a paraphrase of a sentence of the section),
  instead of the section's first 200 characters, wherever the fact is served (read, listed,
  recalled, embedded in an observation). Nothing else about the fact changes.
- `script_fact_labels(document_id, labels)` (memory-quality ticket 05; needs `derive_memories`;
  which layer a fact concerns is the extractor's call): the `key:value` labels of the
  document's derived world fact. A label of a group the bank's last derived template import
  defines with `tag: true`, and with its value among the group's, is appended to the fact's
  `tags` after the item's own, wherever the fact is served, so a strict recall by that tag
  returns it; any other label is dropped, as the docs say of a value outside an enum group.
  `entity_labels/04` and `05` recorded both (the item's tags, then `layer:<value>`; a recall
  by `layer:chip-laser`, `any_strict`, returned only facts carrying it). The labels are not
  added to the fact's entities.
- `fail_recalls(where, status=..., times=...)` (needs `derive_memories`; a failed recall was
  never recorded): an unrecorded recall whose `query` matches answers HTTP `status` with a
  **hand-written** body `{"detail": "recall failed (scripted by the test)"}` (only the status
  is relied on), for the first `times` such recalls (None: every one).
- `forget(memory_id)` (a deleted memory; never recorded): reading it answers HTTP 404 with a
  **hand-written** body `{"detail": "Memory not found"}` (only the status is relied on). It
  drops out of derived recalls; an observation keeps its ID in `source_memory_ids` but drops
  it from `source_memories`.
- **Banks are separate** (ticket 22, replay banks): derived documents, their facts and
  observations belong to the bank they were retained into, so a recall, memory read or
  document read in one bank never sees another bank's. A fact's ID is a UUIDv5 of its bank and
  document ID (`derived_fact(document_id, bank=None)`: None means the one bank holding it).
  Reading a derived memory from a bank that doesn't hold it (another bank's, or a deleted
  bank's) answers HTTP 404 with the same hand-written body as `forget`.
- **Bank deletion** (`DELETE /v1/default/banks/<bank>`; never recorded, feature matrix "Not
  verified here"): answers 200 with a **hand-written** body in the documented `DeleteResponse`
  shape (`{"success": true, "message": null, "deleted_count": <documents dropped>}`; only the
  status is relied on), drops the bank's derived documents and observations, and appends the
  bank to `deleted_banks`.
- **Consolidation in any bank** (on by default): an unrecorded `POST .../consolidate` with
  body `{}` serves `observations/01-consolidate` with only `operation_id` changed; polling that
  operation serves `observations/02-consolidate-final` with only `operation_id` changed (and
  any `hold_operation`, or `hold_consolidations(status, polls)` for every later one, applied).
  It derives no observations.
- `script_reflect(text, cited, ..., mental_models=())` (a reflect answer is LLM output, and no
  recorded one can cite an Atlas section): the next unrecorded reflect serves 0.10.2's
  `reflect_options/02-exclude-mental-models` (memory-quality ticket 10; before it,
  `reflect/01-provenance`) with only `text`, `based_on.memories`, `based_on.mental_models`,
  `structured_output` and `structured_output_error` changed. Each cited memory is the
  recorded first `based_on` entry of its type (`world` or `observation`) with only `id`,
  `text`, `type`, `context`, `document_id`, `chunk_id`, `tags`, `metadata` and `mentioned_at`
  changed: a derived fact's own (as a 0.10.2 answer cites a world fact, with its document);
  an observation's ID, text and tags, the rest null or empty (as recorded for one); a fact
  deleted since, its ID and `(deleted)`, the rest null or empty. A `ChunkContent(document_id)`
  entry is content without memory identity (`id: null`, `type: null`, the rest null or
  empty), its `text` the retained section's first 400 characters (whitespace collapsed); a
  `BankFacts()` entry stands for every derived fact the answering bank holds when the answer
  is served, in retain order. Each of `mental_models` (models imported through the fake) is
  `reflect_options/01-budget-mid-tag-scoped`'s cited model with only `id` and `text`
  (`"<name>: <content>"`, as recorded) changed. **The answer text is written by the test**,
  so the quotes in it are the test's choice.

Derived by default (each is anchored to a request the real server was sent):

- **the template import** (the research template gained mental models in version 1.1.0, and
  importing mental models live queues their refreshes, i.e. LLM calls, so it wasn't
  re-recorded): an unrecorded `POST .../import` whose body differs from the recorded
  research-template request (`research_template/01-import-dry-run`, `02-import`) only in its
  `mental_models` and its `bank` config (memory-quality ticket 05: the missions and
  `entity_labels`; ticket 10: two reflect fields of the bank, and the models' tags and
  trigger fields), and which the bank-template schema 0.10.2 served
  (`rerun-0.10.2/bank_templates/01-schema.json`) takes with every `bank` field one it names,
  is served that recording's response with only `bank_id`,
  `mental_models_created` (the request's mental-model IDs, as `bank_templates/03-import-dry-run`
  and `04-import` list the models they created) and, for the real import, `operation_ids` (one
  derived refresh operation per model, as `bank_templates/04-import` queued) changed. A real
  import also defines each mental model in the fake (below); re-importing keeps a model's
  content and history. A re-import is still reported as creating the models (how 0.10.1
  reports a re-import of existing models was never recorded).
- **mental models defined by a derived import**: `GET .../mental-models/<id>` serves
  `mental_models/03-get` with only `id`, `bank_id`, `name`, `source_query`, `max_tokens`,
  `tags`, the trigger's `refresh_after_consolidation`/`refresh_cron`/
  `min_refresh_interval_seconds`/`exclude_mental_models`/`keep_trace` (the template's; 0.10.2
  stores a trigger as sent, `tagged_mental_model/03-get`), `content`, `reflect_response`,
  `last_refreshed_at` and `is_stale` changed. Until its first refresh a model holds the
  placeholder content `mental_models/06-history` recorded before the first refresh
  (`"Generating content...\n"`), no `reflect_response` and no `last_refreshed_at` (the
  refreshes an import queues never run in the fake). `reflect_response` is the recorded one
  with only `text` and `based_on` changed: each cited memory is the recorded first entry of its
  type (`world` or `observation`) with only `id`, `text`, `type` and `context` changed, as in
  `script_reflect`. `is_stale` follows Hindsight's documented rule: true until the first
  refresh, then whenever a document was retained or an observation derived after it.
  `GET .../history` serves `mental_models/06-history`'s first entry once per earlier content,
  newest first, with only `previous_content`, `previous_reflect_response` and `changed_at`
  changed.
- `script_refresh(model_id, content, cited, refreshed_at=...)` (a refresh is LLM output): the
  next `POST .../mental-models/<id>/refresh` serves `mental_models/04-refresh` with only
  `operation_id` changed; polling that operation serves `mental_models/05-refresh-final` with
  only `operation_id` and its `result_metadata`'s `mental_model_id`, `name`, `content_len` and
  `based_on_counts` changed (and any `hold_operation` applied). The first time it is served
  `completed`, the model's content becomes the scripted one, the old content moves into its
  history (`changed_at` = `refreshed_at`), and `last_refreshed_at` becomes `refreshed_at`. A
  refresh nobody scripted is unrecorded. With `hold=` (and `error_message=`), its operation is
  held at that status for good (`hold_operation`; a failed refresh's error was never
  recorded, see `hold_retains`), so it never applies. `apply_refresh(...)` applies a refresh
  the same way without a request: one Hindsight ran by itself (its `refresh_cron`).

Hand-written, not recorded (memory-quality ticket 02; to be replaced by ticket 01's recordings
on 0.10.2): the two listings the memory-health read makes were never recorded, so their
responses are built from the documented examples in the pinned OpenAPI schema, kept in
`tests/fixtures/hindsight-handwritten/`:

- `script_observation_scopes(scopes)`: `GET .../observations/scopes?limit=N[&offset=M]` (any
  bank) serves `observation-scopes.json` with only `scopes` (the scripted tag sets and counts,
  in the order given), `total`, `limit` and `offset` changed.
- `script_entities(entities)`: `GET .../entities?limit=N[&offset=M]` (any bank) serves
  `entities.json` with only `items` (each the example item with `id` (a UUIDv5 of the name),
  `canonical_name` and `mention_count` changed), `total`, `limit` and `offset` changed.
- `fail_listings(status)`: both listings answer HTTP `status` with the hand-written body
  `{"detail": "listing failed (scripted by the test)"}` (only the status is relied on).
"""

import copy
import functools
import json
import uuid
from collections import defaultdict, deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import httpx2
from jsonschema.validators import validator_for
from pydantic import JsonValue

RECORDINGS_DIR = Path(__file__).resolve().parents[2] / "spikes" / "hindsight" / "recordings"
# The bank-template schema 0.10.2 served (memory-quality ticket 01; kept out of `recordings/`).
TEMPLATE_SCHEMA_0102 = RECORDINGS_DIR.parent / "rerun-0.10.2" / "bank_templates" / "01-schema.json"
HANDWRITTEN_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "hindsight-handwritten"

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


@dataclass(frozen=True)
class BankFacts:
    """Every derived world fact the answering bank holds when the reflect is answered, in
    retain order (for a bank whose fact IDs the test can't know when it scripts the answer)."""


@dataclass
class _ScriptedReflect:
    text: str
    cited: "Sequence[str | ChunkContent | BankFacts]"
    structured_output: dict[str, JsonValue] | None
    structured_output_error: str | None
    mental_models: Sequence[str] = ()


@dataclass
class _ScriptedRefresh:
    content: str
    cited: Sequence[str]
    refreshed_at: str | None  # None: as recorded
    hold: str | None = None  # hold_operation its operation with this status (e.g. failed)
    error_message: str | None = None


@dataclass
class _Revision:
    content: str
    cited: list[str] | None  # None: the placeholder before the first refresh
    changed_at: str


@dataclass
class _MentalModel:
    definition: dict[str, JsonValue]
    content: str
    cited: list[str] | None = None  # None: never refreshed
    refreshed_at: str | None = None
    seen_writes: int = 0
    history: list[_Revision] = field(default_factory=list[_Revision])  # newest first


@dataclass
class _RefreshOperation:
    mental_model_id: str
    refresh: _ScriptedRefresh
    applied: bool = False


@dataclass
class _RetainHold:
    status: str
    polls: int | None
    where: Callable[[Sequence[str]], bool]
    error_message: str | None = None
    times: int | None = None  # None: every matching batch
    # For a batch held `failed` or `cancelled`: the documents it stored anyway (None: none).
    stored: Callable[[str], bool] | None = None


@dataclass
class _ExtractionErrors:
    count: int
    where: Callable[[Sequence[str]], bool]
    times: int | None = None  # None: every matching batch


# Held statuses under which a derived batch stores only the documents its hold names.
_UNSTORED_STATUSES = frozenset({"failed", "cancelled"})


@dataclass
class _RecallFailure:
    where: Callable[[str], bool]  # by the recall's query
    status: int
    times: int | None = None  # None: every matching recall


# The recordings derived responses are built from (see the module docstring).
DERIVED_RETAIN = "retain/04-batch"
DERIVED_RETAIN_FINAL = "retain/05-batch-final"
DERIVED_DOCUMENT = "upsert/09-get-document"
DERIVED_FACT = "reflect/06-resolve-source-memory"
DERIVED_OBSERVATION = "reflect/02-resolve-memory"
DERIVED_RECALL = "tags/02-tags-any_strict"
DERIVED_SOURCE_FACTS = "recall_options/06-include-source-facts"
DERIVED_MEMORY_LIST = "observations/04-list-via-memories"
DERIVED_REFLECT = "reflect_options/02-exclude-mental-models"  # 0.10.2 (memory-quality 10)
DERIVED_REFLECT_MENTAL_MODEL = "reflect_options/01-budget-mid-tag-scoped"
DERIVED_TEMPLATE_DRY_RUN = "research_template/01-import-dry-run"
DERIVED_TEMPLATE_IMPORT = "research_template/02-import"
DERIVED_MENTAL_MODEL = "mental_models/03-get"
DERIVED_MENTAL_MODEL_REFRESH = "mental_models/04-refresh"
DERIVED_MENTAL_MODEL_REFRESH_FINAL = "mental_models/05-refresh-final"
DERIVED_MENTAL_MODEL_HISTORY = "mental_models/06-history"
DERIVED_CONSOLIDATE = "observations/01-consolidate"
DERIVED_CONSOLIDATE_FINAL = "observations/02-consolidate-final"
DERIVED_SCOPES = "observation_scopes/09-list-scopes"
_TEMPLATE_TRIGGER_FIELDS = (
    "refresh_after_consolidation",
    "refresh_cron",
    "min_refresh_interval_seconds",
    "exclude_mental_models",
    "keep_trace",
)
# The fields of a cited memory a derived reflect answer changes (see `script_reflect`).
_CITED_FIELDS = (
    "id",
    "text",
    "type",
    "context",
    "document_id",
    "chunk_id",
    "tags",
    "metadata",
    "mentioned_at",
)
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
    # bank -> document ID -> the retained item
    _derived_documents: dict[str, dict[str, dict[str, JsonValue]]] = field(
        init=False, default_factory=dict[str, dict[str, dict[str, JsonValue]]]
    )
    _zero_facts: Callable[[str], bool] = field(init=False, default_factory=lambda: _never)
    _retain_holds: list[_RetainHold] = field(init=False, default_factory=list[_RetainHold])
    # bank -> the derived documents a failed or cancelled batch did not store (they answer 404)
    _absent: dict[str, set[str]] = field(init=False, default_factory=dict[str, set[str]])
    _extraction_errors: list[_ExtractionErrors] = field(
        init=False, default_factory=list[_ExtractionErrors]
    )
    # derived operation ID -> its extraction_errors_count
    _operation_errors: dict[str, int] = field(init=False, default_factory=dict[str, int])
    _submissions: dict[str, int] = field(init=False, default_factory=dict[str, int])
    _derive_memories: bool = field(init=False, default=False)
    # observation ID -> (its bank, its source fact IDs)
    _observations: dict[str, tuple[str, list[str]]] = field(
        init=False, default_factory=dict[str, tuple[str, list[str]]]
    )
    # observation ID -> the explicit observation scope it was consolidated in (ticket 06)
    _observation_scopes: dict[str, list[str]] = field(
        init=False, default_factory=dict[str, list[str]]
    )
    _known_memories: set[str] = field(init=False, default_factory=set[str])
    _consolidations: set[str] = field(init=False, default_factory=set[str])
    _consolidation_holds: list[_Hold] = field(init=False, default_factory=list[_Hold])
    deleted_banks: list[str] = field(init=False, default_factory=list[str])
    _forgotten: set[str] = field(init=False, default_factory=set[str])
    _fact_texts: dict[str, str] = field(init=False, default_factory=dict[str, str])
    # document ID -> the `key:value` labels scripted for its fact; bank -> its imported groups
    _fact_labels: dict[str, list[str]] = field(init=False, default_factory=dict[str, list[str]])
    _entity_labels: dict[str, list[dict[str, JsonValue]]] = field(
        init=False, default_factory=dict[str, list[dict[str, JsonValue]]]
    )
    _recall_failures: list[_RecallFailure] = field(init=False, default_factory=list[_RecallFailure])
    # How many source facts a derived recall's `source_facts` map keeps (None: every one).
    _source_facts_kept: int | None = field(init=False, default=None)
    _reflects: deque[_ScriptedReflect] = field(init=False, default_factory=deque[_ScriptedReflect])
    _mental_models: dict[str, _MentalModel] = field(
        init=False, default_factory=dict[str, _MentalModel]
    )
    _scripted_refreshes: dict[str, deque[_ScriptedRefresh]] = field(
        init=False, default_factory=dict[str, deque[_ScriptedRefresh]]
    )
    _memory_writes: int = field(init=False, default=0)  # derived documents and observations
    _refresh_operations: dict[str, _RefreshOperation] = field(
        init=False, default_factory=dict[str, _RefreshOperation]
    )
    # Hand-written listings (see the module docstring): None until scripted.
    _scopes: list[dict[str, JsonValue]] | None = field(init=False, default=None)
    _entities: list[tuple[str, int]] | None = field(init=False, default=None)
    _listing_failure: int | None = field(init=False, default=None)

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
        stored: Callable[[str], bool] | None = None,
    ) -> None:
        """`hold_operation` for each later derived retain whose batch's document IDs match
        (only the first `times` such batches, if given). A batch held `failed` or `cancelled`
        stores only the documents `stored` matches (None: none); the others answer 404."""
        self._retain_holds.append(_RetainHold(status, polls, where, error_message, times, stored))

    def report_extraction_errors(
        self, count: int, *, where: Callable[[Sequence[str]], bool], times: int | None = None
    ) -> None:
        """Each later derived retain operation whose batch's document IDs match (only the first
        `times`, if given) reports `extraction_errors_count` = `count` (derived)."""
        self._extraction_errors.append(_ExtractionErrors(count, where, times))

    def derive_memories(self) -> None:
        """One world fact per derived document, observations, and strict recalls (derived)."""
        self._derive = True
        self._derive_memories = True

    def derived_fact(self, document_id: str, bank: str | None = None) -> str:
        """The ID of the derived world fact extracted from a retained document (in `bank`;
        None: the one bank that holds the document)."""
        return _fact_id(self._holding_bank(document_id, bank), document_id)

    def derive_observation(
        self,
        document_ids: Sequence[str],
        bank: str | None = None,
        scope: Sequence[str] | None = None,
    ) -> str:
        """An observation consolidated from these documents' facts (in `bank`; None: the one
        bank that holds the first document); returns its ID. With `scope`, it is the
        observation of that explicit observation scope, which each document must have sent."""
        bank = self._holding_bank(document_ids[0], bank)
        sources = [self.derived_fact(document_id, bank) for document_id in document_ids]
        key = "observation:" + "|".join(sources)
        if scope is not None:
            for document_id in document_ids:
                item = self._derived_documents[bank][document_id]
                sent = cast(list[list[str]], item.get("observation_scopes") or [])
                if not any(set(s) == set(scope) for s in sent):
                    raise AssertionError(
                        f"{document_id} was retained with observation_scopes {sent}, "
                        f"not with {list(scope)}"
                    )
            key += "#scope:" + "|".join(scope)
        observation_id = str(uuid.uuid5(_DERIVED_NAMESPACE, key))
        self._observations[observation_id] = (bank, sources)
        if scope is not None:
            self._observation_scopes[observation_id] = list(scope)
        self._known_memories.add(observation_id)
        self._memory_writes += 1
        return observation_id

    def bank_documents(self, bank: str) -> list[str]:
        """The document IDs retained into `bank` through the fake (none once it's deleted)."""
        absent = self._absent.get(bank, set())
        return [d for d in self._derived_documents.get(bank, {}) if d not in absent]

    def bank_facts(self, bank: str) -> list[str]:
        """The IDs of the derived world facts that exist in `bank` now, in retain order."""
        return list(self._facts(bank))

    def hold_consolidations(self, status: str, polls: int | None = None) -> None:
        """`hold_operation` for each later derived consolidation operation."""
        self._consolidation_holds.append(_Hold(status, polls))

    def _holding_bank(self, document_id: str, bank: str | None) -> str:
        holders = [b for b, docs in self._derived_documents.items() if document_id in docs]
        if bank is not None:
            if bank not in holders:
                raise KeyError(f"{document_id} was not retained into {bank} through the fake")
            return bank
        if len(holders) != 1:
            raise KeyError(f"{document_id} is held by {len(holders)} banks; name the bank")
        return holders[0]

    def forget(self, memory_id: str) -> None:
        """The memory is gone: reading it answers 404 (derived; see the module docstring)."""
        self._forgotten.add(memory_id)

    def script_fact_text(self, document_id: str, text: str) -> None:
        """The document's derived world fact reads `text` (the test's paraphrase) instead of
        the section's first characters (derived; see the module docstring)."""
        self._fact_texts[document_id] = text

    def script_fact_labels(self, document_id: str, labels: Sequence[str]) -> None:
        """The extractor labelled the document's derived world fact with these `key:value`
        entity labels; those of a group the bank's imported template defines with `tag: true`
        and the value among the group's are added to the fact's tags (derived; see above)."""
        self._fact_labels[document_id] = list(labels)

    def fail_recalls(
        self, where: Callable[[str], bool], *, status: int, times: int | None = None
    ) -> None:
        """Answer HTTP `status` to each later unrecorded recall whose query matches (only the
        first `times`, if given), with a hand-written body (derived; see the module
        docstring)."""
        self._recall_failures.append(_RecallFailure(where, status, times))

    def truncate_source_facts(self, keep: int) -> None:
        """Derived recalls asked for source facts keep only the first `keep` of them in their
        `source_facts` map and say `source_facts_truncated: true` (derived; see above)."""
        self._source_facts_kept = keep

    def script_reflect(
        self,
        text: str,
        cited: "Sequence[str | ChunkContent | BankFacts]",
        *,
        structured_output: dict[str, JsonValue] | None = None,
        structured_output_error: str | None = None,
        mental_models: Sequence[str] = (),
    ) -> None:
        """Answer the next unrecorded reflect with this text and these citations (derived);
        `mental_models` are the IDs of imported models the answer read."""
        for mental_model_id in mental_models:
            self._mental_model(mental_model_id)
        self._reflects.append(
            _ScriptedReflect(text, cited, structured_output, structured_output_error, mental_models)
        )

    def script_refresh(
        self,
        mental_model_id: str,
        content: str,
        cited: Sequence[str],
        *,
        refreshed_at: datetime | None = None,
        hold: str | None = None,
        error_message: str | None = None,
    ) -> None:
        """Answer the next refresh of this mental model with this content (derived); with
        `hold`, its operation is held at that status (and `error_message`) and never applies."""
        self._mental_model(mental_model_id)
        scripted = _ScriptedRefresh(content, cited, _iso(refreshed_at), hold, error_message)
        self._scripted_refreshes.setdefault(mental_model_id, deque()).append(scripted)

    def apply_refresh(
        self,
        mental_model_id: str,
        content: str,
        cited: Sequence[str],
        *,
        refreshed_at: datetime | None = None,
    ) -> None:
        """A refresh Hindsight ran by itself (its `refresh_cron`), with no request (derived)."""
        self._apply(mental_model_id, _ScriptedRefresh(content, cited, _iso(refreshed_at)))

    def script_observation_scopes(self, scopes: Sequence[tuple[Sequence[str], int]]) -> None:
        """Serve these observation scopes (tag set, count) from the scopes listing
        (hand-written; see the module docstring)."""
        self._scopes = [{"tags": list(tags), "count": count} for tags, count in scopes]

    def script_entities(self, entities: Sequence[tuple[str, int]]) -> None:
        """Serve these entities (canonical name, mention count) from the entity listing, in
        the order given (hand-written; see the module docstring)."""
        self._entities = list(entities)

    def fail_listings(self, status: int) -> None:
        """Answer HTTP `status` to the scopes and entity listings (hand-written)."""
        self._listing_failure = status

    def refreshes_requested(self) -> list[str]:
        """The mental-model IDs of every refresh request received, in order."""
        return [
            request.url.path.split("/")[-2]
            for request in self.calls
            if request.method == "POST"
            and "/mental-models/" in request.url.path
            and request.url.path.endswith("/refresh")
        ]

    def requests(self, method: str, route: str) -> list[dict[str, Any]]:
        """The JSON bodies of the bank requests received for `route` (e.g. `memories/recall`)."""
        return [
            cast(dict[str, Any], json.loads(request.content))
            for request in self.calls
            if request.method == method and request.url.path.endswith(f"/{route}")
        ]

    def retained(self, bank: str | None = None) -> list[list[dict[str, Any]]]:
        """The items of every batch retain received (into `bank`, if given), in order
        (recorded or derived)."""
        batches: list[list[dict[str, Any]]] = []
        for request in self.calls:
            if bank is not None and request.url.path.split("/")[4:5] != [bank]:
                continue
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
        if not queue:
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
        if len(parts) == 5 and parts[1:4] == ["v1", "default", "banks"]:
            return self._deleted_bank(parts[4]) if request.method == "DELETE" else None
        if len(parts) < 6 or parts[1:4] != ["v1", "default", "banks"]:
            return None
        bank, route = parts[4], parts[5:]
        derived = self._derived_by_default(request, bank, route, body)
        if derived is not None or not self._derive:
            return derived
        if request.method == "POST" and route == ["memories"] and isinstance(body, dict):
            return self._derived_retain(bank, body)
        if request.method == "GET" and len(route) == 2 and route[0] == "operations":
            if route[1] in self._derived_operations:
                return self._derived_operation(route[1])
        if request.method == "GET" and len(route) == 2 and route[0] == "documents":
            if route[1] in self._derived_documents.get(bank, {}):
                return self._derived_document(bank, route[1])
        if request.method == "GET" and route == ["memories", "list"]:
            listed = self._derived_memory_list(bank, request)
            if listed is not None:
                return listed
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
        batch = cast(list[dict[str, JsonValue]], items)
        document_ids = [str(item["document_id"]) for item in batch]
        held: _RetainHold | None = None
        for hold in self._retain_holds:
            if hold.times != 0 and hold.where(document_ids):
                self.hold_operation(operation_id, hold.status, hold.polls, hold.error_message)
                held = hold
                if hold.times is not None:
                    hold.times -= 1
        for errors in self._extraction_errors:
            if errors.times != 0 and errors.where(document_ids):
                self._operation_errors[operation_id] = errors.count
                if errors.times is not None:
                    errors.times -= 1
        documents = self._derived_documents.setdefault(bank, {})
        absent = self._absent.setdefault(bank, set())
        for document_id, item in zip(document_ids, batch, strict=True):
            unstored = (
                held is not None
                and held.status in _UNSTORED_STATUSES
                and not (held.stored is not None and held.stored(document_id))
            )
            if unstored:
                # A failed or cancelled batch leaves a document an earlier batch stored as it
                # was; one it never stored is absent.
                if document_id not in documents or document_id in absent:
                    documents[document_id] = item
                    absent.add(document_id)
                continue
            documents[document_id] = item
            absent.discard(document_id)
            self._known_memories.add(_fact_id(bank, document_id))
            self._memory_writes += 1
        self._derived_operations.add(operation_id)
        recording = self.recording(DERIVED_RETAIN)
        response = copy.deepcopy(recording.response_object())
        response |= {"bank_id": bank, "items_count": len(items), "operation_id": operation_id}
        self.served.append(f"{DERIVED_RETAIN} (derived)")
        return httpx2.Response(recording.status, json=response)

    def _derived_operation(self, operation_id: str) -> httpx2.Response:
        recording = self.recording(DERIVED_RETAIN_FINAL)
        response = copy.deepcopy(recording.response_object())
        response["operation_id"] = operation_id
        if operation_id in self._operation_errors:
            metadata = cast(dict[str, JsonValue], response["result_metadata"])
            metadata["extraction_errors_count"] = self._operation_errors[operation_id]
        self.served.append(f"{DERIVED_RETAIN_FINAL} (derived)")
        return httpx2.Response(recording.status, json=self._apply_hold(response))

    def _derived_document(self, bank: str, document_id: str) -> httpx2.Response:
        if document_id in self._absent.get(bank, set()):
            self.served.append("documents/<id> 404 (derived, hand-written body)")
            return httpx2.Response(404, json={"detail": "Document not found"})
        item = self._derived_documents[bank][document_id]
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

    def _derived_memory_list(self, bank: str, request: httpx2.Request) -> httpx2.Response | None:
        params = dict(request.url.params)
        document_id = params.pop("document_id", None)
        offset = int(params.pop("offset", "0"))
        limit = params.pop("limit", None)
        if document_id not in self._derived_documents.get(bank, {}) or limit is None or params:
            return None
        recording = self.recording(DERIVED_MEMORY_LIST)
        response = copy.deepcopy(recording.response_object())
        first = cast(list[dict[str, JsonValue]], response["items"])[0]
        facts = [
            copy.deepcopy(first) | fact | {"fact_type": "world", "source_memory_ids": []}
            for fact in self._facts(bank).values()
            if fact["document_id"] == document_id
        ]
        page: list[JsonValue] = list[JsonValue](facts[offset : offset + int(limit)])
        response |= {"items": page, "total": len(facts), "limit": int(limit), "offset": offset}
        self.served.append(f"{DERIVED_MEMORY_LIST} (derived)")
        return httpx2.Response(recording.status, json=response)

    # --- derived memories, recall and reflect (see the module docstring) -----------------------

    def _facts(self, bank: str) -> dict[str, dict[str, JsonValue]]:
        """The derived world facts that exist now, by ID, in retain order."""
        facts: dict[str, dict[str, JsonValue]] = {}
        absent = self._absent.get(bank, set())
        for document_id, item in self._derived_documents.get(bank, {}).items():
            fact_id = _fact_id(bank, document_id)
            if self._zero_facts(document_id) or fact_id in self._forgotten or document_id in absent:
                continue
            facts[fact_id] = {
                "id": fact_id,
                "text": self._fact_texts.get(document_id)
                or _collapsed(item["content"])[:FACT_TEXT_CHARS],
                "context": item.get("context"),
                "document_id": document_id,
                "chunk_id": f"{bank}_{document_id}_0",
                "tags": self._fact_tags(bank, document_id, item),
                "metadata": item.get("metadata", {}),
                "mentioned_at": item.get("timestamp"),
            }
        return facts

    def _fact_tags(self, bank: str, document_id: str, item: dict[str, JsonValue]) -> JsonValue:
        """The item's tags, then the fact's scripted labels that are tags in this bank (as
        `entity_labels/04` recorded: a `tag: true` group's labels follow the item's tags)."""
        tags = cast(list[JsonValue], item.get("tags", []))
        tagging = {
            f"{group['key']}:{cast(dict[str, JsonValue], value)['value']}"
            for group in self._entity_labels.get(bank, [])
            if group.get("tag") is True
            for value in cast(list[JsonValue], group.get("values") or [])
        }
        labels = [label for label in self._fact_labels.get(document_id, []) if label in tagging]
        return [*tags, *(label for label in dict.fromkeys(labels) if label not in tags)]

    def _observation(self, observation_id: str, bank: str) -> dict[str, JsonValue]:
        facts = self._facts(bank)
        present = [facts[s] for s in self._observations[observation_id][1] if s in facts]
        tags: list[JsonValue] = []
        if observation_id in self._observation_scopes:
            tags.extend(self._observation_scopes[observation_id])  # the scope's tags alone
        else:
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
        if self._in_bank(memory_id, bank):
            recording = self.recording(DERIVED_OBSERVATION)
            response = copy.deepcopy(recording.response_object())
            embedded = cast(list[dict[str, JsonValue]], response["source_memories"])[0]
            sources = self._observations[memory_id][1]
            response |= self._observation(memory_id, bank)
            response["source_memory_ids"] = list[JsonValue](sources)
            response["source_memories"] = [
                copy.deepcopy(embedded) | {k: facts[s][k] for k in _EMBEDDED_SOURCE_FIELDS}
                for s in sources
                if s in facts
            ]
            self.served.append(f"{DERIVED_OBSERVATION} (derived)")
            return httpx2.Response(recording.status, json=response)
        if memory_id in self._known_memories:
            # A derived memory of another bank, or of a deleted one: not in this bank.
            self.served.append("memories/<id> 404 (derived, hand-written body)")
            return httpx2.Response(404, json={"detail": "Memory not found"})
        return None

    def _in_bank(self, observation_id: str, bank: str) -> bool:
        return (
            observation_id in self._observations and self._observations[observation_id][0] == bank
        )

    def _derived_recall(self, bank: str, body: dict[str, JsonValue]) -> httpx2.Response | None:
        match, tags = body.get("tags_match"), body.get("tags")
        if match not in ("any_strict", "all_strict") or not isinstance(tags, list) or not tags:
            return None
        for failure in self._recall_failures:
            if failure.times != 0 and failure.where(str(body.get("query"))):
                if failure.times is not None:
                    failure.times -= 1
                self.served.append(f"memories/recall {failure.status} (derived, hand-written body)")
                return httpx2.Response(
                    failure.status, json={"detail": "recall failed (scripted by the test)"}
                )
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
            if not self._in_bank(observation_id, bank):
                continue
            fields = self._observation(observation_id, bank)
            if observation_id not in self._forgotten and in_scope(fields["tags"]):
                results.append(copy.deepcopy(observation) | fields)
        results.extend(
            copy.deepcopy(world) | fact
            for fact in self._facts(bank).values()
            if in_scope(fact["tags"])
        )
        response["results"] = results
        include = body.get("include")
        if isinstance(include, dict) and "source_facts" in include:
            self._attach_source_facts(bank, response)
        self.served.append(f"{DERIVED_RECALL} (derived)")
        return httpx2.Response(recording.status, json=response)

    def _attach_source_facts(self, bank: str, response: dict[str, JsonValue]) -> None:
        """`include.source_facts` on a derived recall (see the module docstring): each
        observation lists all its sources; the map holds the ones that exist, in result
        order, up to `truncate_source_facts`'s count."""
        recorded = self.recording(DERIVED_SOURCE_FACTS).response_object()
        entry = next(iter(cast(dict[str, JsonValue], recorded["source_facts"]).values()))
        facts = self._facts(bank)
        listed: dict[str, JsonValue] = {}
        truncated = False
        for result in cast(list[dict[str, JsonValue]], response["results"]):
            if result["type"] != "observation":
                continue
            sources = self._observations[str(result["id"])][1]
            result["source_fact_ids"] = list[JsonValue](sources)
            for source in sources:
                if source not in facts or source in listed:
                    continue
                if self._source_facts_kept is not None and len(listed) >= self._source_facts_kept:
                    truncated = True
                    continue
                listed[source] = copy.deepcopy(cast(dict[str, JsonValue], entry)) | facts[source]
        response["source_facts"] = listed
        response["source_facts_truncated"] = truncated

    def _derived_reflect(self, bank: str) -> httpx2.Response:
        scripted = self._reflects.popleft()
        recording = self.recording(DERIVED_REFLECT)
        response = copy.deepcopy(recording.response_object())
        based_on = cast(dict[str, JsonValue], response["based_on"])
        recorded = cast(list[dict[str, JsonValue]], based_on["memories"])
        entries = {kind: next(m for m in recorded if m["type"] == kind) for kind in _KINDS}
        memories: list[JsonValue] = []
        expanded: list[str | ChunkContent] = []
        for cited in scripted.cited:
            expanded += self.bank_facts(bank) if isinstance(cited, BankFacts) else [cited]
        for cited in expanded:
            fields: dict[str, JsonValue]
            if isinstance(cited, ChunkContent):
                content = self._derived_documents[bank][cited.document_id]["content"]
                text = _collapsed(content)[:CHUNK_TEXT_CHARS]
                fields = _no_identity(text)
            else:
                fields = self._cited_answer_fields(bank, cited)
            entry = entries["observation" if fields["type"] == "observation" else "world"]
            memories.append(copy.deepcopy(entry) | fields)
        based_on["memories"] = memories
        model_entry = cast(
            list[dict[str, JsonValue]],
            cast(
                dict[str, JsonValue],
                self.recording(DERIVED_REFLECT_MENTAL_MODEL).response_object()["based_on"],
            )["mental_models"],
        )[0]
        models: list[JsonValue] = []
        for model_id in scripted.mental_models:
            model = self._mental_model(model_id)
            text = f"{model.definition['name']}: {model.content}"
            models.append(copy.deepcopy(model_entry) | {"id": model_id, "text": text})
        based_on["mental_models"] = models
        response |= {
            "text": scripted.text,
            "structured_output": scripted.structured_output,
            "structured_output_error": scripted.structured_output_error,
        }
        self.served.append(f"{DERIVED_REFLECT} (derived)")
        return httpx2.Response(recording.status, json=response)

    def _cited_fields(self, bank: str, cited: str) -> dict[str, JsonValue]:
        """The identity and content fields of a cited derived memory (see `script_reflect`)."""
        facts = self._facts(bank)
        if self._in_bank(cited, bank):
            text = self._observation(cited, bank)["text"]
            return {"id": cited, "text": text, "type": "observation", "context": None}
        if cited in facts:
            fact = facts[cited]
            return {"id": cited, "text": fact["text"], "type": "world", "context": fact["context"]}
        # cited, then deleted: the answer still carries the text it was given
        return {"id": cited, "text": "(deleted)", "type": "world", "context": None}

    def _cited_answer_fields(self, bank: str, cited: str) -> dict[str, JsonValue]:
        """A cited memory's fields in a 0.10.2 reflect answer: a world fact also carries its
        document, chunk, tags, metadata and mention time; an observation none of them."""
        facts = self._facts(bank)
        if cited in facts:
            fact = facts[cited]
            return {key: fact[key] for key in _CITED_FIELDS if key != "type"} | {"type": "world"}
        fields = _no_identity("") | self._cited_fields(bank, cited)
        if self._in_bank(cited, bank):
            fields["tags"] = self._observation(cited, bank)["tags"]
        return fields

    # --- derived template import and mental models (see the module docstring) -----------------

    def _derived_by_default(
        self, request: httpx2.Request, bank: str, route: list[str], body: JsonValue
    ) -> httpx2.Response | None:
        if request.method == "POST" and route == ["import"] and isinstance(body, dict):
            return self._derived_import(bank, body, request.url.params.get("dry_run") == "true")
        if len(route) >= 2 and route[0] == "mental-models" and route[1] in self._mental_models:
            model_id = route[1]
            if request.method == "GET" and len(route) == 2:
                return self._derived_mental_model(bank, model_id)
            if request.method == "GET" and route[2:] == ["history"]:
                return self._derived_history(bank, model_id)
            if request.method == "POST" and route[2:] == ["refresh"]:
                return self._derived_refresh(model_id)
        if request.method == "GET" and len(route) == 2 and route[0] == "operations":
            if route[1] in self._refresh_operations:
                return self._derived_refresh_operation(bank, route[1])
            if route[1] in self._consolidations:
                return self._derived_consolidation_operation(route[1])
        if request.method == "POST" and route == ["consolidate"] and body == {}:
            return self._derived_consolidation(bank)
        if request.method == "GET" and route in (["observations", "scopes"], ["entities"]):
            if route[0] == "observations" and self._scopes is None and self._derive_memories:
                return self._derived_scopes(bank, request)
            return self._handwritten_listing(request, route)
        return None

    def _derived_scopes(self, bank: str, request: httpx2.Request) -> httpx2.Response | None:
        if self._listing_failure is not None:
            return self._handwritten_listing(request, ["observations", "scopes"])
        params = dict(request.url.params)
        offset = int(params.pop("offset", "0"))
        limit = params.pop("limit", None)
        if limit is None or params:
            return None
        counts: dict[tuple[str, ...], int] = {}
        for observation_id in self._observations:
            if self._in_bank(observation_id, bank) and observation_id not in self._forgotten:
                tags = cast(list[str], self._observation(observation_id, bank)["tags"])
                counts[tuple(tags)] = counts.get(tuple(tags), 0) + 1
        ranked = sorted(counts.items(), key=lambda entry: -entry[1])  # stable: first-derived
        listed: list[JsonValue] = [{"tags": list(tags), "count": n} for tags, n in ranked]
        recording = self.recording(DERIVED_SCOPES)
        response = copy.deepcopy(recording.response_object())
        response |= {
            "scopes": listed[offset : offset + int(limit)],
            "total": len(listed),
            "limit": int(limit),
            "offset": offset,
        }
        self.served.append(f"{DERIVED_SCOPES} (derived)")
        return httpx2.Response(recording.status, json=response)

    # --- hand-written listings (see the module docstring) --------------------------------------

    def _handwritten_listing(
        self, request: httpx2.Request, route: list[str]
    ) -> httpx2.Response | None:
        scopes = route == ["observations", "scopes"]
        if self._listing_failure is not None:
            body = {"detail": "listing failed (scripted by the test)"}
            return httpx2.Response(self._listing_failure, json=body)
        if (self._scopes if scopes else self._entities) is None:
            return None
        params = dict(request.url.params)
        offset = int(params.pop("offset", "0"))
        limit = params.pop("limit", None)
        if limit is None or params:
            return None
        name = "observation-scopes" if scopes else "entities"
        handwritten = json.loads((HANDWRITTEN_DIR / f"{name}.json").read_text(encoding="utf-8"))
        response = cast(dict[str, JsonValue], handwritten["response"]["body"])
        if scopes:
            assert self._scopes is not None
            listed: list[JsonValue] = list[JsonValue](self._scopes)
            key = "scopes"
        else:
            assert self._entities is not None
            example = cast(list[dict[str, JsonValue]], response["items"])[0]
            listed = [
                example
                | {
                    "id": str(uuid.uuid5(_DERIVED_NAMESPACE, f"entity:{entity}")),
                    "canonical_name": entity,
                    "mention_count": mentions,
                }
                for entity, mentions in self._entities
            ]
            key = "items"
        response |= {
            key: listed[offset : offset + int(limit)],
            "total": len(listed),
            "limit": int(limit),
            "offset": offset,
        }
        self.served.append(f"{name} (hand-written)")
        return httpx2.Response(200, json=response)

    # --- derived consolidation and bank deletion (see the module docstring) --------------------

    def _derived_consolidation(self, bank: str) -> httpx2.Response:
        count = len(self._consolidations) + 1
        operation_id = str(uuid.uuid5(_DERIVED_NAMESPACE, f"consolidate:{bank}:{count}"))
        self._consolidations.add(operation_id)
        for hold in self._consolidation_holds:
            self.hold_operation(operation_id, hold.status, hold.polls)
        recording = self.recording(DERIVED_CONSOLIDATE)
        response = copy.deepcopy(recording.response_object()) | {"operation_id": operation_id}
        self.served.append(f"{DERIVED_CONSOLIDATE} (derived)")
        return httpx2.Response(recording.status, json=response)

    def _derived_consolidation_operation(self, operation_id: str) -> httpx2.Response:
        recording = self.recording(DERIVED_CONSOLIDATE_FINAL)
        response = copy.deepcopy(recording.response_object()) | {"operation_id": operation_id}
        self.served.append(f"{DERIVED_CONSOLIDATE_FINAL} (derived)")
        return httpx2.Response(recording.status, json=self._apply_hold(response))

    def _deleted_bank(self, bank: str) -> httpx2.Response:
        absent = self._absent.pop(bank, set())
        documents = [d for d in self._derived_documents.pop(bank, {}) if d not in absent]
        for observation_id in [o for o in self._observations if self._in_bank(o, bank)]:
            del self._observations[observation_id]
        self.deleted_banks.append(bank)
        self.served.append("banks/<id> DELETE (derived, hand-written body)")
        body = {"success": True, "message": None, "deleted_count": len(documents)}
        return httpx2.Response(200, json=body)

    def _derived_import(
        self, bank: str, body: dict[str, JsonValue], dry_run: bool
    ) -> httpx2.Response | None:
        name = DERIVED_TEMPLATE_DRY_RUN if dry_run else DERIVED_TEMPLATE_IMPORT
        recording = self.recording(name)
        if _without_models_and_bank(body) != _without_models_and_bank(recording.request_object()):
            return None
        if not _bank_config_accepted(body):
            return None
        models = cast(list[dict[str, JsonValue]], body.get("mental_models") or [])
        ids: list[JsonValue] = [str(model["id"]) for model in models]
        response = copy.deepcopy(recording.response_object())
        response |= {"bank_id": bank, "mental_models_created": ids}
        if not dry_run:
            config = body.get("bank")
            if isinstance(config, dict) and "entity_labels" in config:
                groups = cast(list[dict[str, JsonValue]] | None, config["entity_labels"])
                self._entity_labels[bank] = list(groups or [])
            response["operation_ids"] = [
                str(uuid.uuid5(_DERIVED_NAMESPACE, f"import-refresh:{bank}:{i}")) for i in ids
            ]
            for model in models:
                existing = self._mental_models.get(str(model["id"]))
                if existing is None:
                    self._mental_models[str(model["id"])] = _MentalModel(model, self._placeholder())
                else:
                    existing.definition = model
        self.served.append(f"{name} (derived)")
        return httpx2.Response(recording.status, json=response)

    def _placeholder(self) -> str:
        """The content Hindsight shows before a model's first refresh (as recorded)."""
        recording = self.recording(DERIVED_MENTAL_MODEL_HISTORY)
        history = cast(list[dict[str, JsonValue]], recording.response_body)
        return str(history[-1]["previous_content"])

    def _mental_model(self, mental_model_id: str) -> _MentalModel:
        if mental_model_id not in self._mental_models:
            raise KeyError(f"{mental_model_id} was not imported through the fake")
        return self._mental_models[mental_model_id]

    def _writes(self) -> int:
        return self._memory_writes

    def _reflect_response(self, bank: str, text: str, cited: Sequence[str]) -> dict[str, JsonValue]:
        recorded = self.recording(DERIVED_MENTAL_MODEL).response_object()
        response = copy.deepcopy(cast(dict[str, JsonValue], recorded["reflect_response"]))
        groups = cast(dict[str, list[JsonValue]], response["based_on"])
        first = {
            kind: cast(dict[str, JsonValue], groups[kind][0]) for kind in ("world", "observation")
        }
        for kind in groups:
            groups[kind] = []
        for memory_id in cited:
            fields = self._cited_fields(bank, memory_id)
            kind = str(fields["type"])
            groups[kind].append(copy.deepcopy(first[kind]) | fields)
        response["text"] = text
        return response

    def _derived_mental_model(self, bank: str, model_id: str) -> httpx2.Response:
        model = self._mental_models[model_id]
        recording = self.recording(DERIVED_MENTAL_MODEL)
        response = copy.deepcopy(recording.response_object())
        definition = model.definition
        trigger = cast(dict[str, JsonValue], response["trigger"])
        template_trigger = cast(dict[str, JsonValue], definition.get("trigger") or {})
        for key in _TEMPLATE_TRIGGER_FIELDS:
            # Unset, the two boolean fields are Hindsight's default, false (as recorded).
            unset = False if key in ("exclude_mental_models", "keep_trace") else None
            trigger[key] = template_trigger.get(key, unset)
        response |= {
            "id": model_id,
            "bank_id": bank,
            "name": definition["name"],
            "source_query": definition["source_query"],
            "max_tokens": definition.get("max_tokens", response["max_tokens"]),
            "tags": definition.get("tags") or [],
            "content": model.content,
            "reflect_response": (
                None
                if model.cited is None
                else self._reflect_response(bank, model.content, model.cited)
            ),
            "last_refreshed_at": model.refreshed_at,
            "is_stale": model.refreshed_at is None or self._writes() > model.seen_writes,
        }
        self.served.append(f"{DERIVED_MENTAL_MODEL} (derived)")
        return httpx2.Response(recording.status, json=response)

    def _derived_history(self, bank: str, model_id: str) -> httpx2.Response:
        model = self._mental_models[model_id]
        recording = self.recording(DERIVED_MENTAL_MODEL_HISTORY)
        entry = cast(list[dict[str, JsonValue]], recording.response_body)[0]
        response = [
            copy.deepcopy(entry)
            | {
                "previous_content": revision.content,
                "previous_reflect_response": (
                    None
                    if revision.cited is None
                    else self._reflect_response(bank, revision.content, revision.cited)
                ),
                "changed_at": revision.changed_at,
            }
            for revision in model.history
        ]
        self.served.append(f"{DERIVED_MENTAL_MODEL_HISTORY} (derived)")
        return httpx2.Response(recording.status, json=response)

    def _derived_refresh(self, model_id: str) -> httpx2.Response | None:
        scripted = self._scripted_refreshes.get(model_id)
        if not scripted:
            return None  # a refresh is LLM output: unrecorded unless the test scripted it
        count = len(self._refresh_operations) + 1
        operation_id = str(uuid.uuid5(_DERIVED_NAMESPACE, f"refresh:{model_id}:{count}"))
        refresh = scripted.popleft()
        self._refresh_operations[operation_id] = _RefreshOperation(model_id, refresh)
        if refresh.hold is not None:
            self.hold_operation(operation_id, refresh.hold, error_message=refresh.error_message)
        recording = self.recording(DERIVED_MENTAL_MODEL_REFRESH)
        response = copy.deepcopy(recording.response_object()) | {"operation_id": operation_id}
        self.served.append(f"{DERIVED_MENTAL_MODEL_REFRESH} (derived)")
        return httpx2.Response(recording.status, json=response)

    def _derived_refresh_operation(self, bank: str, operation_id: str) -> httpx2.Response:
        operation = self._refresh_operations[operation_id]
        refresh = operation.refresh
        recording = self.recording(DERIVED_MENTAL_MODEL_REFRESH_FINAL)
        response = copy.deepcopy(recording.response_object())
        metadata = cast(dict[str, JsonValue], response["result_metadata"])
        counts = cast(dict[str, JsonValue], metadata["based_on_counts"])
        kinds = [str(self._cited_fields(bank, memory_id)["type"]) for memory_id in refresh.cited]
        metadata |= {
            "mental_model_id": operation.mental_model_id,
            "name": self._mental_models[operation.mental_model_id].definition["name"],
            "content_len": len(refresh.content),
            "based_on_counts": {kind: kinds.count(kind) for kind in counts},
        }
        response["operation_id"] = operation_id
        body = self._apply_hold(response)
        if body["status"] == "completed" and not operation.applied:
            operation.applied = True
            refreshed_at = refresh.refreshed_at or str(response["completed_at"])
            self._apply(
                operation.mental_model_id,
                _ScriptedRefresh(refresh.content, refresh.cited, refreshed_at),
            )
        self.served.append(f"{DERIVED_MENTAL_MODEL_REFRESH_FINAL} (derived)")
        return httpx2.Response(recording.status, json=body)

    def _apply(self, model_id: str, refresh: _ScriptedRefresh) -> None:
        model = self._mental_model(model_id)
        recorded = self.recording(DERIVED_MENTAL_MODEL).response_object()
        refreshed_at = refresh.refreshed_at or str(recorded["last_refreshed_at"])
        model.history.insert(0, _Revision(model.content, model.cited, refreshed_at))
        model.content = refresh.content
        model.cited = list(refresh.cited)
        model.refreshed_at = refreshed_at
        model.seen_writes = self._writes()


def _without_models_and_bank(body: dict[str, JsonValue]) -> dict[str, JsonValue]:
    return {key: value for key, value in body.items() if key not in ("mental_models", "bank")}


@functools.cache
def _template_schema_0102() -> dict[str, Any]:
    recording = json.loads(TEMPLATE_SCHEMA_0102.read_text(encoding="utf-8"))
    return cast(dict[str, Any], recording["response"]["body"])


def _bank_config_accepted(body: dict[str, JsonValue]) -> bool:
    """Whether 0.10.2's recorded template schema takes the manifest, and its `bank` sets only
    fields the schema names (the schema allows unknown ones, which Hindsight ignores)."""
    schema = _template_schema_0102()
    if next(validator_for(schema)(schema).iter_errors(body), None) is not None:
        return False
    bank = body.get("bank")
    fields = cast(dict[str, Any], schema["$defs"]["BankTemplateConfig"]["properties"])
    return not isinstance(bank, dict) or set(bank) <= set(fields)


_KINDS = ("world", "observation")


def _no_identity(text: str) -> dict[str, JsonValue]:
    """A cited entry with no memory identity and nothing that leads to a document."""
    return {
        "id": None,
        "text": text,
        "type": None,
        "context": None,
        "document_id": None,
        "chunk_id": None,
        "tags": [],
        "metadata": {},
        "mentioned_at": None,
    }


def _iso(moment: datetime | None) -> str | None:
    return None if moment is None else moment.isoformat()


def _fact_id(bank: str, document_id: str) -> str:
    return str(uuid.uuid5(_DERIVED_NAMESPACE, f"world:{bank}:{document_id}"))


def _collapsed(content: JsonValue) -> str:
    return " ".join(str(content).split())
