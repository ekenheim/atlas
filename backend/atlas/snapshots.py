"""Research Snapshots (spec §5.7 "research_snapshot"; ticket 20): what a published Hypothesis
version was built from, frozen in the transaction that publishes it.

**Contents** (`FORMAT`), all read from the database as it stands at publication:

- `hypothesis`: the Hypothesis, the version (its ID, number, content hash) and who published
  it when; `cutoff`: the investigation's question and as-of time.
- `source_versions`: every Source Version considered: each one a role was sent a passage or
  quote of (a `role_call.retrieved` source `<id>#<start>-<end>`), an extraction named, a
  finding or Assertion cites, or a financial observation came from; with its raw and parsed
  hashes, archive URIs and `available_at`.
- `memory`: Hindsight Memory **exactly as it was returned to the run**: every retrieved item
  a role was sent whose source is a mental model or memory (e.g. the Scout's open gaps).
  The investigation's **reading pointers** (`reading_pointers`; snapshots written before
  memory-directed reading have none) are what Memory returned to the Scout's recalls, each
  memory's text as returned with the section it resolved to: an index of where to read,
  sent to no role. Memory only chose which windows of Source Versions the Investigators
  read, so those choices are listed and the text the model saw is in the Source Versions:
  `pointer_selections`, the passages a reading pointer chose (their `selected_by` names the
  queries; memory-directed reading ticket 05), and `recall_selections`, the passages of
  extractions made before that ticket, whose own recall chose sections. `used` says whether
  any Memory reached the run at all.
- `assertions`: the Assertions the findings, the counterevidence and the scenarios cite, with
  their exact quote spans and review state; `relationships`: those the version depends on,
  with the owner's approval.
- `scenarios` attached to the version (inputs, assumption and output hashes, outputs) and the
  `financial_dataset`: the XBRL observations their inputs cite, and the SHA-256 of that list's
  canonical JSON.
- `runs` (code, Hindsight and template versions, the LiteLLM deployments behind each alias)
  and `role_calls` (prompt name, version and hash, the model alias asked for and each
  attempt's routed model); `hindsight`: the bank and the Hindsight versions of those runs.
- `outputs`: the version's content, as published.

**Storage.** The canonical JSON (keys sorted, fixed separators, UTF-8) is put in the archive
under `archive://snapshots/sha256/<hex>` and an insert-only `research_snapshot` row records
the hash; the audit event `research_snapshot.created` carries it. **Every read verifies it**:
the archived bytes must hash to the row's SHA-256 and name the row's version, or the read is
a `SnapshotIntegrityError`. On the filesystem archive the object is protected by the app and
the database, not the storage (until MinIO object lock).
"""

import hashlib
import json
import re
import uuid
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any, cast

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Connection, RowMapping, text

from atlas.archive import Archive, ArchiveIntegrityError, Namespace, ObjectNotFound
from atlas.audit import Actor, record
from atlas.hypotheses.model import HypothesisVersion
from atlas.hypotheses.service import PublishHook, dependent_assertion_ids
from atlas.scenarios.model import AssertionSource, AssumptionTable, SourcedInput, XbrlSource

FORMAT = "atlas.research_snapshot.v1"
# A role's retrieved item quoting a Source Version: `<source_version_id>#<start>-<end>`.
_QUOTED_SOURCE = re.compile(
    r"^(?P<id>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})#"
)
# A role's retrieved item that is Hindsight Memory (a mental model's content, a memory).
_MEMORY_SOURCES = ("mental-model:", "memory:")


class SnapshotError(Exception):
    code = "snapshot_error"
    status = 500

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class SnapshotIntegrityError(SnapshotError):
    """The archived snapshot is missing, or no longer hashes to its row."""

    code = "snapshot_integrity_failed"


class ResearchSnapshotRecord(BaseModel):
    """A snapshot's row: what was frozen, where, and its hash."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    hypothesis_id: uuid.UUID
    hypothesis_version: int
    hypothesis_version_id: uuid.UUID
    sha256: str
    object_uri: str
    byte_size: int
    as_of: datetime
    created_by: str
    created_at: datetime


class ResearchSnapshot(ResearchSnapshotRecord):
    """A snapshot read back and verified: `content` hashes to `sha256`."""

    verified: bool
    content: dict[str, Any]


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def snapshot_hook(archive: Archive) -> PublishHook:
    """The publish hook writing the version's Research Snapshot (atlas.hypotheses)."""

    def write(
        connection: Connection, hypothesis: RowMapping, version: HypothesisVersion, actor: Actor
    ) -> None:
        write_snapshot(connection, archive, hypothesis, version, actor)

    return write


def write_snapshot(
    connection: Connection,
    archive: Archive,
    hypothesis: RowMapping,
    version: HypothesisVersion,
    actor: Actor,
) -> uuid.UUID:
    """Freeze the published `version`: archive its snapshot, record the row and audit it."""
    content = build_snapshot(connection, hypothesis, version)
    data = canonical_json(content)
    sha256 = hashlib.sha256(data).hexdigest()
    uri = archive.put(Namespace.SNAPSHOTS, data)
    snapshot_id = uuid.uuid4()
    connection.execute(
        text(
            "INSERT INTO research_snapshot (id, hypothesis_id, hypothesis_version_id, sha256,"
            " object_uri, byte_size, as_of, created_by) VALUES (:id, :hypothesis, :version,"
            " :sha, :uri, :size, :as_of, :by)"
        ),
        {
            "id": snapshot_id,
            "hypothesis": hypothesis["id"],
            "version": version.id,
            "sha": sha256,
            "uri": uri,
            "size": len(data),
            "as_of": datetime.fromisoformat(content["cutoff"]["as_of"]),
            "by": actor.name,
        },
    )
    record(
        connection,
        actor,
        "research_snapshot.created",
        entity_type="research_snapshot",
        entity_id=str(snapshot_id),
        new_hash=sha256,
    )
    return snapshot_id


# --- building ------------------------------------------------------------------------------------


def build_snapshot(
    connection: Connection, hypothesis: RowMapping, version: HypothesisVersion
) -> dict[str, Any]:
    investigation = (
        connection.execute(
            text("SELECT * FROM investigation WHERE id = :id"),
            {"id": hypothesis["investigation_id"]},
        )
        .mappings()
        .one()
    )
    scenarios = _scenarios(connection, version.id)
    sources = [source for scenario in scenarios for source in _scenario_sources(scenario)]
    observation_ids = [s.observation_id for s in sources if isinstance(s, XbrlSource)]
    observations = _rows(
        connection,
        "SELECT id, company_id, source_version_id, accession, form, filed, fiscal_year,"
        " fiscal_period, frame, taxonomy, concept, unit, currency, fx_basis, period_start,"
        " period_end, value, available_at, available_at_basis FROM financial_observation"
        " WHERE id = ANY(CAST(:ids AS uuid[])) ORDER BY id",
        observation_ids,
    )
    finding_assertions = dependent_assertion_ids(version)
    assertion_ids = list(
        dict.fromkeys(
            [
                *finding_assertions,
                *(c.source_span.assertion_id for c in version.content.contradictions),
                *(s.assertion_id for s in sources if isinstance(s, AssertionSource)),
            ]
        )
    )
    assertions = _rows(
        connection,
        "SELECT a.id, a.subject_company_id, a.predicate, a.object_company_id, a.value_json,"
        " a.source_version_id, a.quote, a.span_start, a.span_end, a.page_or_anchor,"
        " a.event_start, a.event_end, a.epistemic_type, a.verification_status,"
        " a.independence_family_id, a.extracted_at, a.extractor_version, a.parser_version,"
        " a.reviewer_id, a.reviewed_at, a.superseded_by, ra.relationship_id FROM assertion a"
        " LEFT JOIN relationship_assertion ra ON ra.assertion_id = a.id"
        " WHERE a.id = ANY(CAST(:ids AS uuid[])) ORDER BY a.id",
        assertion_ids,
    )
    relationships = _rows(
        connection,
        "SELECT r.id, r.subject_company_id, r.predicate, r.object_company_id, r.object_text,"
        " r.layer, r.review_state, r.reviewed_by, r.reviewed_at, r.review_note,"
        " array_agg(ra.assertion_id ORDER BY ra.assertion_id) AS supporting_assertion_ids"
        " FROM relationship r JOIN relationship_assertion ra ON ra.relationship_id = r.id"
        " WHERE r.id IN (SELECT relationship_id FROM relationship_assertion"
        "  WHERE assertion_id = ANY(CAST(:ids AS uuid[])))"
        " GROUP BY r.id ORDER BY r.id",
        finding_assertions,
    )

    # The runs behind the version: the investigation's, every Editor draft up to this
    # version, and those of the machine reviews and scenario proposals it relies on.
    core_runs = _ids(
        [
            investigation["run_id"],
            *connection.execute(
                text(
                    "SELECT (provenance ->> 'draft_run_id')::uuid FROM hypothesis_version"
                    " WHERE hypothesis_id = :id AND version <= :version"
                ),
                {"id": hypothesis["id"], "version": version.version},
            ).scalars(),
        ]
    )
    extra_calls = _ids(
        [
            *connection.execute(
                text(
                    "SELECT role_call_id FROM relationship_review"
                    " WHERE assertion_id = ANY(CAST(:ids AS uuid[]))"
                ),
                {"ids": finding_assertions},
            ).scalars(),
            *(scenario["role_call_id"] for scenario in scenarios),
        ]
    )
    role_calls = _rows(
        connection,
        "SELECT id, run_id, role, prompt_name, prompt_version, prompt_sha256, model, status,"
        " retrieved, started_at, finished_at FROM role_call"
        " WHERE run_id = ANY(CAST(:ids AS uuid[])) OR id = ANY(CAST(:calls AS uuid[]))"
        " ORDER BY started_at, id",
        core_runs,
        calls=extra_calls,
    )
    attempts = _rows(
        connection,
        "SELECT role_call_id, attempt, response_model, model_id FROM llm_call"
        " WHERE role_call_id = ANY(CAST(:ids AS uuid[])) ORDER BY role_call_id, attempt",
        _ids(call["id"] for call in role_calls),
    )
    runs = _rows(
        connection,
        "SELECT id, kind, code_version, hindsight_version, template_version, routed_models,"
        " started_at, finished_at FROM run WHERE id = ANY(CAST(:ids AS uuid[]))"
        " ORDER BY started_at, id",
        _ids([*core_runs, *(call["run_id"] for call in role_calls)]),
    )
    extractions = _rows(
        connection,
        "SELECT id, run_id, source_version_ids, question, passages FROM claim_extraction"
        " WHERE run_id = ANY(CAST(:ids AS uuid[])) ORDER BY started_at, id",
        core_runs,
    )

    memory_items = [
        {
            "role_call_id": call["id"],
            "role": call["role"],
            "id": item["id"],
            "source": item["source"],
            "text": item["text"],
        }
        for call in role_calls
        for item in call["retrieved"]
        if str(item.get("source", "")).startswith(_MEMORY_SOURCES)
    ]
    selected = [
        {"claim_extraction_id": extraction["id"], "question": extraction["question"]} | passage
        for extraction in extractions
        for passage in extraction["passages"]
    ]
    recall_selections = [each for each in selected if "recall" in each.get("selected_by", [])]
    pointer_selections = [
        each
        for each in selected
        if any(str(tag).startswith("pointer:") for tag in each.get("selected_by", []))
    ]
    reading_pointers = _rows(
        connection,
        "SELECT p.id, p.round, p.task_id, p.query_index, p.query, p.discovery_query_id, p.rank,"
        " p.memory_id, p.memory_type, p.memory_text, p.source_version_id, p.section_anchor,"
        " p.section_heading, p.section_char_start, p.section_char_end, p.company_id,"
        " p.available_at, p.citation_state, p.created_at FROM reading_pointer p"
        " JOIN investigation_task t ON t.id = p.task_id"
        " WHERE p.investigation_id = ANY(CAST(:ids AS uuid[]))"
        " ORDER BY p.round, t.position, p.query_index, p.rank, p.source_version_id,"
        " p.section_char_start, p.section_anchor",
        [investigation["id"]],
    )

    considered = _ids(
        [
            *(
                uuid.UUID(match["id"])
                for call in role_calls
                for item in call["retrieved"]
                if (match := _QUOTED_SOURCE.match(str(item.get("source", "")))) is not None
            ),
            *(uuid.UUID(each) for e in extractions for each in e["source_version_ids"]),
            *(
                each
                for finding in version.content.findings
                for each in finding.original_source_version_ids
            ),
            *(uuid.UUID(a["source_version_id"]) for a in assertions),
            *(uuid.UUID(o["source_version_id"]) for o in observations),
        ]
    )
    source_versions = _rows(
        connection,
        # `available_at` is the effective one (a recorded correction's, else the version's
        # own; docs/decisions.md), with what the immutable version recorded beside it.
        "SELECT v.id, v.source_document_id, v.version_number, v.raw_sha256, v.content_sha256,"
        " v.object_uri, v.parsed_object_uri, v.parser_version, v.parse_status,"
        " a.available_at, a.available_at_basis, v.available_at AS recorded_available_at,"
        " v.available_at_basis AS recorded_available_at_basis, v.published_at, v.fetched_at"
        " FROM source_version v"
        " JOIN source_version_availability a ON a.source_version_id = v.id"
        " WHERE v.id = ANY(CAST(:ids AS uuid[])) ORDER BY v.id",
        considered,
    )

    published = _plain(
        connection.execute(
            text("SELECT published_at, published_by FROM hypothesis_version WHERE id = :id"),
            {"id": version.id},
        )
        .mappings()
        .one()
    )
    return {
        "format": FORMAT,
        "hypothesis": {
            "id": str(hypothesis["id"]),
            "theme_id": hypothesis["theme_id"],
            "investigation_id": str(hypothesis["investigation_id"]),
            "version": version.version,
            "version_id": str(version.id),
            "content_sha256": version.content_sha256,
            "published_at": published["published_at"],
            "published_by": published["published_by"],
        },
        "cutoff": {
            "as_of": _plain(investigation["as_of"]),
            "question": investigation["question"],
        },
        "source_versions": source_versions,
        "memory": {
            "used": bool(
                memory_items or recall_selections or pointer_selections or reading_pointers
            ),
            "items": memory_items,
            "recall_selections": recall_selections,
            "pointer_selections": pointer_selections,
            "reading_pointers": reading_pointers,
        },
        "assertions": assertions,
        "relationships": relationships,
        "scenarios": [_plain(scenario) for scenario in scenarios],
        "financial_dataset": {
            "sha256": hashlib.sha256(canonical_json(observations)).hexdigest(),
            "observations": observations,
        },
        "runs": runs,
        "role_calls": [
            {key: value for key, value in call.items() if key != "retrieved"}
            | {"attempts": [a for a in attempts if a["role_call_id"] == call["id"]]}
            for call in role_calls
        ],
        "hindsight": {
            "bank_id": investigation["bank_id"],
            "versions": sorted({run["hindsight_version"] for run in runs}),
            "template_versions": sorted({run["template_version"] for run in runs}),
        },
        "outputs": {
            "content": version.content.model_dump(mode="json"),
            "content_sha256": version.content_sha256,
        },
    }


def _scenarios(connection: Connection, version_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = connection.execute(
        text(
            "SELECT id, company_id, as_of, model_version, origin, investigation_task_id,"
            " role_call_id, assumptions, assumptions_sha256, outputs, outputs_sha256, note,"
            " created_by, created_at FROM scenario WHERE hypothesis_version_id = :id"
            " ORDER BY created_at, id"
        ),
        {"id": version_id},
    ).mappings()
    # The outputs are stored as their canonical JSON text: kept as that text, which is what
    # `outputs_sha256` hashes.
    return [dict(row) for row in rows]


def _scenario_sources(scenario: Mapping[str, Any]) -> Iterable[XbrlSource | AssertionSource]:
    table = AssumptionTable.model_validate(scenario["assumptions"])
    for each in table.inputs.values():
        if isinstance(each, SourcedInput):
            yield each.source


def _rows(
    connection: Connection, sql: str, ids: Sequence[uuid.UUID], **params: Any
) -> list[dict[str, Any]]:
    """The rows as plain JSON values (IDs and times as strings, numbers exact)."""
    rows = connection.execute(text(sql), {"ids": list(ids), **params}).mappings()
    return [_plain(row) for row in rows]


def _ids(values: Iterable[uuid.UUID | str | None]) -> list[uuid.UUID]:
    """Distinct IDs in first-seen order (a row's plain values are strings)."""
    return list(dict.fromkeys(uuid.UUID(str(value)) for value in values if value is not None))


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        mapping = cast(Mapping[Any, Any], value)
        return {str(key): _plain(each) for key, each in mapping.items()}
    if isinstance(value, list | tuple):
        items = cast(Sequence[Any], value)
        return [_plain(each) for each in items]
    if isinstance(value, uuid.UUID | Decimal):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value


# --- reading -------------------------------------------------------------------------------------

_SELECT = (
    "SELECT s.*, v.version AS hypothesis_version FROM research_snapshot s"
    " JOIN hypothesis_version v ON v.id = s.hypothesis_version_id"
)


def list_snapshots(
    connection: Connection, *, hypothesis_id: uuid.UUID | None, limit: int, offset: int
) -> tuple[list[ResearchSnapshotRecord], int]:
    params = {"hypothesis": hypothesis_id, "limit": limit, "offset": offset}
    where = " WHERE (CAST(:hypothesis AS uuid) IS NULL OR s.hypothesis_id = :hypothesis)"
    total = connection.execute(
        text(f"SELECT count(*) FROM research_snapshot s{where}"),  # noqa: S608 (constant)
        params,
    ).scalar_one()
    rows = connection.execute(
        text(f"{_SELECT}{where} ORDER BY s.created_at, s.id LIMIT :limit OFFSET :offset"),
        params,
    ).mappings()
    return [ResearchSnapshotRecord.model_validate(dict(row)) for row in rows], int(total)


def read_snapshot(
    connection: Connection, archive: Archive, snapshot_id: uuid.UUID
) -> ResearchSnapshot | None:
    """The snapshot, verified against its row; None if there is no such snapshot."""
    row = (
        connection.execute(text(f"{_SELECT} WHERE s.id = :id"), {"id": snapshot_id})
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    snapshot = ResearchSnapshotRecord.model_validate(dict(row))
    try:
        data = archive.get(snapshot.object_uri)
    except ObjectNotFound:
        raise SnapshotIntegrityError(
            f"snapshot {snapshot.id}'s archived object {snapshot.object_uri} is missing"
        ) from None
    except ArchiveIntegrityError:
        raise SnapshotIntegrityError(
            f"snapshot {snapshot.id} was altered: its archived bytes no longer hash to"
            f" {snapshot.sha256}"
        ) from None
    if hashlib.sha256(data).hexdigest() != snapshot.sha256:
        raise SnapshotIntegrityError(
            f"snapshot {snapshot.id} was altered: its archived bytes no longer hash to"
            f" {snapshot.sha256}"
        )
    content: dict[str, Any] = json.loads(data)
    if content.get("hypothesis", {}).get("version_id") != str(snapshot.hypothesis_version_id):
        raise SnapshotIntegrityError(
            f"snapshot {snapshot.id}'s archived object is not of its Hypothesis version"
        )
    return ResearchSnapshot.model_validate(
        snapshot.model_dump() | {"verified": True, "content": content}
    )
