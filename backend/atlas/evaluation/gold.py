"""The gold set: labeled research cases in the `docs/evaluation-methodology.md` format.

Layout (methodology §2): `manifest.json` (the case index, the only mutable file),
`cases/<case ID>.json` (immutable, pinned by `case_sha256`) and `sources/<sha256>.<ext>`
(content-addressed source files, shared across cases).

Two keys extend the methodology's case schema (§4), both documented there:

- `pipeline`: which part of Atlas the case runs through (`relationships`: import, the
  Investigator's extraction and relationship review; `families`: import only;
  `financials`: an SEC ingest of recorded responses; `investigation`: import, then an
  investigation) and its parameters;
- `script`: the model answers the fake mode replays, per role, in order (the last one
  repeats). They are *answers*, written against the sources, never the expected outcome: the
  gold says what Atlas must conclude from them.

`validate_gold` is the methodology's validator (§9): ID pattern and file name, unique IDs,
`case_sha256`, every source's hash and licence class, every gold quote occurring exactly in its
source's parse, and every entity and source key a case refers to being defined.
"""

import hashlib
import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, ValidationError

from atlas.parsing import ParsedText, parse

SCHEMA_VERSION = 1
CASE_ID = re.compile(r"^EV-([A-Z]{3})-(\d{3})$")
# Methodology §5 (the § 9.5 categories and ticket 12's two), plus the codes ticket 25 added.
CATEGORIES = frozenset(
    {
        "SUP", "COM", "EXP", "SYN", "ENT", "NOX", "CON", "LAT", "FUT", "RST", "NUS", "INJ",
        "RET", "LAY", "INF", "DIR", "HED",
    }
)  # fmt: skip
COMMITTABLE_LICENCES = frozenset({"synthetic_fixture", "public_regulatory"})
METRICS = frozenset(
    {
        "source_recall_at_k",
        "citation_correctness",
        "relationship_precision",
        "relationship_recall",
        "entity_accuracy",
        "contradiction_discovery",
        "independent_families",
        "extraction_yield",
        "as_of_isolation",
        "coverage_honesty",
        "injection_resistance",
    }
)
ROLES = frozenset({"scout", "investigator", "reviewer", "skeptic_plan", "skeptic", "editor"})

type TemporalConvention = Literal["available_at", "available_and_ingested"]


class GoldError(Exception):
    """The gold set can't be read or fails validation."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --- the manifest --------------------------------------------------------------------------


class Adjudicated(_Strict):
    by: str
    at: date


class ManifestEntry(_Strict):
    case_id: str
    category: str
    case_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["active", "retired", "superseded"]
    superseded_by: str | None = None
    added_at: date
    reason: str | None = None  # why a case was retired
    adjudicated: Adjudicated | None = None  # the researcher confirmed an agent's draft


class Manifest(_Strict):
    schema_version: Literal[1]
    cases: list[ManifestEntry]


# --- a case --------------------------------------------------------------------------------


class Security(_Strict):
    ticker: str
    mic: str
    valid_from: date | None = None
    valid_to: date | None = None


class Entity(_Strict):
    key: str = Field(pattern=r"^[a-z][a-z0-9-]*$")
    legal_name: str
    display_name: str | None = None
    country: str = Field(pattern=r"^[A-Z]{2}$")
    cik: str | None = Field(default=None, pattern=r"^\d{10}$")
    lei: str | None = None
    parent: str | None = None
    layer: str | None = None
    securities: list[Security] = []
    fictional: bool


class Clocks(_Strict):
    event_at: AwareDatetime | None = None
    published_at: AwareDatetime
    available_at: AwareDatetime
    available_at_basis: str
    ingested_at: AwareDatetime | None = None


class Source(_Strict):
    key: str = Field(pattern=r"^[a-z][a-z0-9-]*$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    kind: Literal["document", "edgar_response", "hindsight_recording"]
    media_type: str
    provenance: Literal["synthetic", "redistributable"]
    license_class: str
    licence_basis: str
    source_tier: Literal["A", "B", "C"]
    source_type: str
    form_type: str | None = None
    title: str | None = None
    company: str | None = None  # the entity whose document it is
    origin_url: str
    accession: str | None = None
    clocks: Clocks
    evidence_family: str | None = None
    supersedes_source: str | None = None

    @property
    def extension(self) -> str:
        return _EXTENSIONS.get(self.media_type, "bin")


_EXTENSIONS = {
    "text/html": "html",
    "text/plain": "txt",
    "application/json": "json",
    "application/pdf": "pdf",
}


class Scope(_Strict):
    companies: list[str]
    themes: list[str]


class Pipeline(_Strict):
    kind: Literal["relationships", "families", "financials", "investigation"]
    # relationships: the sources the Investigator reads (default: every document source).
    extract_sources: list[str] | None = None
    # investigation: the seed companies (default: the scope's).
    seeds: list[str] | None = None


class Disagreement(_Strict):
    party: str
    label: str
    resolution: str
    note: str | None = None


class Adjudication(_Strict):
    labeler: str
    adjudicated_at: date
    # `agent_draft`: drafted by an agent, not yet adjudicated by the researcher (the manifest
    # entry's `adjudicated` records the researcher's confirmation).
    method: Literal["manual", "agent_draft_reviewed", "agent_draft"]
    disagreements: list[Disagreement] = []


# --- gold keys (methodology §4.2) ------------------------------------------------------------


class GoldAnswer(_Strict):
    evidence_missing: bool | None = None
    must_not_mention: list[str] = []  # entity keys no accepted Claim or finding may involve


class GoldClaim(_Strict):
    """An accepted Claim with this subject, predicate and object must (`accepted: true`) or must
    not (`false`: rejected or never proposed) exist. `quote` pins the accepted one's quote."""

    subject: str
    predicate: str
    object: str | None = None
    source: str | None = None
    quote: str | None = None
    accepted: bool


class GoldRelationship(_Strict):
    """`present`: the edge exists (in `review_state`, with `reasons_include`, if given);
    `absent`: no such edge in any state; `not_verified`: none machine-reviewed or approved."""

    subject: str
    predicate: str
    object: str | None = None
    object_text: str | None = None
    layer: str | None = None
    expect: Literal["present", "absent", "not_verified"]
    review_state: (
        Literal["machine_reviewed", "needs_human_review", "approved", "rejected"] | None
    ) = None
    reasons_include: list[str] = []


class GoldCitation(_Strict):
    """An Assertion of `source` quotes exactly `quote`, and its span resolves to it."""

    source: str
    quote: str
    state: Literal["resolved", "unverified", "broken"]


class GoldFamilies(_Strict):
    count: int = Field(ge=1)
    sources: list[str] | None = None  # default: every document source


class GoldFinancial(_Strict):
    concept: str
    period_start: date | None
    period_end: date
    unit: str
    as_of: AwareDatetime
    value: Decimal
    from_source: str
    accession: str | None = None
    linkage: Literal["first", "restates", "reaffirms"] | None = None


class GoldInvestigation(_Strict):
    stop_reason: list[str] | None = None  # any of these
    min_contradictions: int | None = None  # independent contradictions on the research card
    min_findings: int | None = None


class Gold(_Strict):
    answer: GoldAnswer | None = None
    claims: list[GoldClaim] = []
    relationships: list[GoldRelationship] = []
    citations: list[GoldCitation] = []
    evidence_families: GoldFamilies | None = None
    forbidden_sources: list[str] = []
    financials: list[GoldFinancial] = []
    investigation: GoldInvestigation | None = None


class Case(_Strict):
    schema_version: Literal[1]
    case_id: str
    category: str
    title: str
    created_at: date
    supersedes: str | None
    question: str
    as_of: AwareDatetime | None = None
    temporal_convention: TemporalConvention | None = None
    scope: Scope
    entities: list[Entity]
    sources: list[Source]
    pipeline: Pipeline
    script: dict[str, list[dict[str, JsonValue]]] = {}
    gold: Gold
    adjudication: Adjudication
    metrics: list[str]
    earliest_phase: Literal["1", "2", "3", "4", "5", "6a"]
    notes: str | None = None

    def source(self, key: str) -> Source:
        return next(source for source in self.sources if source.key == key)

    def entity(self, key: str) -> Entity:
        return next(entity for entity in self.entities if entity.key == key)


# --- loading --------------------------------------------------------------------------------


class LoadedCase(BaseModel):
    """A case as scored: the parsed file, its hash, and where its sources are."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    case: Case
    sha256: str
    root: Path

    def source_path(self, key: str) -> Path:
        source = self.case.source(key)
        return self.root / "sources" / f"{source.sha256}.{source.extension}"


class GoldSet(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    root: Path
    manifest: Manifest
    manifest_sha256: str

    def active_ids(self) -> list[str]:
        return [entry.case_id for entry in self.manifest.cases if entry.status == "active"]

    def load(self, case_id: str) -> LoadedCase:
        entry = next((e for e in self.manifest.cases if e.case_id == case_id), None)
        if entry is None:
            raise GoldError(f"{case_id} is not in {self.root / 'manifest.json'}")
        path = self.root / "cases" / f"{case_id}.json"
        try:
            raw = path.read_bytes()
        except OSError as error:
            raise GoldError(f"cannot read {path}: {error.strerror}") from None
        digest = hashlib.sha256(raw).hexdigest()
        if digest != entry.case_sha256:
            raise GoldError(
                f"{case_id} changed: its sha256 is {digest}, the manifest pins"
                f" {entry.case_sha256} (a committed case is immutable; add a new one)"
            )
        try:
            case = Case.model_validate_json(raw)
        except ValidationError as error:
            raise GoldError(f"{case_id} is not a valid case: {error}") from None
        return LoadedCase(case=case, sha256=digest, root=self.root)


def open_gold(root: Path) -> GoldSet:
    path = root / "manifest.json"
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise GoldError(f"cannot read {path}: {error.strerror}") from None
    try:
        manifest = Manifest.model_validate_json(raw)
    except ValidationError as error:
        raise GoldError(f"{path} is not a valid manifest: {error}") from None
    return GoldSet(root=root, manifest=manifest, manifest_sha256=hashlib.sha256(raw).hexdigest())


def parsed_source(loaded: LoadedCase, key: str) -> str | None:
    """A document source's parse (what Atlas's parser makes of it), or None."""
    source = loaded.case.source(key)
    parsed = parse(loaded.source_path(key).read_bytes(), source.media_type)
    return parsed.text if isinstance(parsed, ParsedText) else None


# --- the validator (methodology §9) ------------------------------------------------------------


def validate_gold(root: Path) -> list[str]:
    """Every problem with the gold set at `root` (empty when it is valid)."""
    try:
        gold = open_gold(root)
    except GoldError as error:
        return [str(error)]
    problems: list[str] = []
    seen: set[str] = set()
    for entry in gold.manifest.cases:
        match = CASE_ID.match(entry.case_id)
        if match is None:
            problems.append(f"{entry.case_id}: the ID doesn't match EV-<CAT>-<NNN>")
            continue
        if entry.case_id in seen:
            problems.append(f"{entry.case_id}: listed twice")
        seen.add(entry.case_id)
        if match.group(1) != entry.category or entry.category not in CATEGORIES:
            problems.append(f"{entry.case_id}: category {entry.category!r} doesn't fit")
        if entry.status == "superseded" and entry.superseded_by is None:
            problems.append(f"{entry.case_id}: superseded, but by nothing")
        try:
            loaded = gold.load(entry.case_id)
        except GoldError as error:
            problems.append(str(error))
            continue
        problems.extend(f"{entry.case_id}: {p}" for p in _case_problems(loaded, entry))
    for path in sorted((root / "cases").glob("*.json")):
        if path.stem not in seen:
            problems.append(f"{path.name}: a case file the manifest doesn't list")
    return problems


def _case_problems(loaded: LoadedCase, entry: ManifestEntry) -> list[str]:
    case = loaded.case
    problems: list[str] = []
    if case.case_id != entry.case_id or case.category != entry.category:
        problems.append("its case_id or category differs from the manifest's")
    if case.as_of is not None and case.temporal_convention is None:
        problems.append("as_of is set without a temporal_convention")
    problems.extend(f"unknown metric {m!r}" for m in case.metrics if m not in METRICS)
    problems.extend(f"unknown script role {r!r}" for r in case.script if r not in ROLES)
    entities = {entity.key for entity in case.entities}
    sources = {source.key for source in case.sources}
    if len(entities) != len(case.entities) or len(sources) != len(case.sources):
        problems.append("an entity or source key is defined twice")
    for source in case.sources:
        path = loaded.source_path(source.key)
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            problems.append(f"source {source.key}: {path.name} is missing")
            continue
        if digest != source.sha256:
            problems.append(f"source {source.key}: {path.name} hashes to {digest}")
        if source.license_class not in COMMITTABLE_LICENCES:
            problems.append(
                f"source {source.key}: licence {source.license_class!r} can't be committed"
            )
        if source.company is not None and source.company not in entities:
            problems.append(f"source {source.key}: unknown company {source.company!r}")
        if source.supersedes_source is not None and source.supersedes_source not in sources:
            problems.append(f"source {source.key}: supersedes unknown {source.supersedes_source!r}")
    referenced = [*case.scope.companies, *(case.pipeline.seeds or [])]
    gold = case.gold
    for claim in gold.claims:
        referenced += [claim.subject, *([claim.object] if claim.object else [])]
    for edge in gold.relationships:
        referenced += [edge.subject, *([edge.object] if edge.object else [])]
    if gold.answer is not None:
        referenced += gold.answer.must_not_mention
    problems.extend(f"unknown entity {key!r}" for key in referenced if key not in entities)
    source_refs = [
        *(case.pipeline.extract_sources or []),
        *gold.forbidden_sources,
        *(gold.evidence_families.sources or [] if gold.evidence_families else []),
        *(f.from_source for f in gold.financials),
        *(c.source for c in gold.citations),
        *(c.source for c in gold.claims if c.source),
    ]
    problems.extend(f"unknown source {key!r}" for key in source_refs if key not in sources)
    if problems:
        return problems
    # Every gold quote occurs exactly in its source's parse (offsets are never stored).
    quotes = [(c.source, c.quote) for c in gold.citations] + [
        (c.source, c.quote) for c in gold.claims if c.source and c.quote
    ]
    for key, quote in quotes:
        assert key is not None and quote is not None
        parsed = parsed_source(loaded, key)
        if parsed is None or quote not in parsed:
            problems.append(f"the gold quote {quote!r} doesn't occur in {key}'s parse")
    problems.extend(_script_problems(case, entities, sources))
    return problems


def _script_problems(case: Case, entities: set[str], sources: set[str]) -> list[str]:
    """The entity and source keys the scripted answers name must be the case's."""
    problems: list[str] = []
    for role, replies in case.script.items():
        for reply in replies:
            for key, value in _walk(reply):
                if key in ("subject", "object") and isinstance(value, str):
                    if value not in entities:
                        problems.append(f"script {role}: unknown entity {value!r}")
                if key == "source" and isinstance(value, str) and value not in sources:
                    problems.append(f"script {role}: unknown source {value!r}")
    return problems


def _walk(value: Any) -> list[tuple[str, Any]]:
    found: list[tuple[str, Any]] = []
    if isinstance(value, dict):
        for key, inner in value.items():  # pyright: ignore[reportUnknownVariableType]
            found.append((str(key), inner))  # pyright: ignore[reportUnknownArgumentType]
            found.extend(_walk(inner))
    elif isinstance(value, list):
        for inner in value:  # pyright: ignore[reportUnknownVariableType]
            found.extend(_walk(inner))
    return found
