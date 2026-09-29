"""Evidence Families: Source Versions that are copies of one announcement, one witness.

A syndicated press release reaches Atlas many times, at many URLs. Each copy is its own
Source Version, but they are not independent of each other, so they share one Evidence
Family and count once (CONTEXT.md; spec Phase 3, "Evidence Families").

A parsed Source Version joins a family when it is recorded (`assign`, called by the ledger
in the version's transaction; `assign_missing` backfills versions recorded before this
rule). The rule, in order:

1. **Exact:** a member with the same `content_sha256` (the hash of the parse) → its family
   (`match = content_hash`).
2. **Near:** else a member whose SimHash is within its family's recorded
   `max_hamming_distance` (default 3) and was computed by the same `simhash_rule` → the
   family of the nearest such member, ties to the earliest-assigned member
   (`match = simhash`).
3. Else a new family, recording the rule and threshold it was founded with
   (`match = founder`).

Membership is append-only (migration 0016): a version's family never changes, and families
are never merged. A version near two families joins the nearest one only. A later change of
threshold applies to new assignments; each family keeps the threshold it was founded with.

SimHash rule `simhash64-w3-blake2b-v1` (fixed, so a SimHash is the same in every process
and on every machine; any change to its output is a new rule):
- Input: the archived parse (`html-text-v1`), already NFC with whitespace collapsed.
- Normalization: NFKC, then `str.casefold()`.
- Tokens: maximal runs of Unicode letters and digits (`[^\\W_]+`); everything else
  (punctuation, underscores, whitespace, markup residue) separates tokens.
- Features: every run of 3 consecutive tokens (word 3-shingles), joined by one space; a text
  with fewer than 3 tokens has the single feature of all its tokens. Each occurrence counts
  (term-frequency weights).
- Feature hash: BLAKE2b with an 8-byte digest of the feature's UTF-8 bytes, read as a
  big-endian unsigned 64-bit integer (no key, no salt; Python's `hash()` is never used).
- Fingerprint bit i is 1 when the weighted sum of +1 (feature bit i set) / -1 (unset) over
  all features is positive. A text with no tokens has fingerprint 0.
Stored as a signed bigint (the same 64 bits); shown as 16 lowercase hex digits.
"""

import hashlib
import re
import unicodedata
import uuid
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy import Connection, Engine, text

from atlas.archive import Archive
from atlas.audit import Actor, content_hash, record

SIMHASH_RULE = "simhash64-w3-blake2b-v1"
DEFAULT_MAX_HAMMING_DISTANCE = 3
SHINGLE_SIZE = 3

Match = Literal["founder", "content_hash", "simhash"]

_TOKEN = re.compile(r"[^\W_]+")
_BITS = 64
_MASK = (1 << _BITS) - 1
# One lock serializes family assignment, so concurrent copies of one announcement can't
# found two families.
_ASSIGN_LOCK = "atlas.evidence_family"


def tokens(parsed_text: str) -> list[str]:
    """The SimHash tokens of a parse: NFKC, casefolded, runs of letters and digits."""
    return _TOKEN.findall(unicodedata.normalize("NFKC", parsed_text).casefold())


def simhash(parsed_text: str) -> int:
    """The 64-bit SimHash of a parse under `SIMHASH_RULE`, as an unsigned integer."""
    words = tokens(parsed_text)
    if not words:
        return 0
    if len(words) < SHINGLE_SIZE:
        features = Counter([" ".join(words)])
    else:
        features = Counter(
            " ".join(words[i : i + SHINGLE_SIZE]) for i in range(len(words) - SHINGLE_SIZE + 1)
        )
    sums = [0] * _BITS
    for feature, weight in features.items():
        value = int.from_bytes(
            hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest(), "big"
        )
        for bit in range(_BITS):
            sums[bit] += weight if value >> bit & 1 else -weight
    return sum(1 << bit for bit in range(_BITS) if sums[bit] > 0)


def hamming_distance(a: int, b: int) -> int:
    return ((a ^ b) & _MASK).bit_count()


def simhash_hex(value: int) -> str:
    return f"{value & _MASK:016x}"


def _signed(value: int) -> int:
    """The same 64 bits as a Postgres bigint."""
    value &= _MASK
    return value - (1 << _BITS) if value >> (_BITS - 1) else value


@dataclass(frozen=True)
class Assignment:
    source_version_id: uuid.UUID
    evidence_family_id: uuid.UUID
    match: Match
    matched_source_version_id: uuid.UUID | None
    hamming_distance: int | None
    created_family: dict[str, Any] | None = None  # the rows written, for the audit
    created_member: dict[str, Any] | None = None  # None: the version already had a family


def assign(
    connection: Connection,
    *,
    source_version_id: uuid.UUID,
    content_sha256: str,
    parsed_text: str,
    max_hamming_distance: int = DEFAULT_MAX_HAMMING_DISTANCE,
) -> Assignment:
    """Put a parsed Source Version in its Evidence Family, in `connection`'s transaction
    (then `audit` it). A version that already has a family keeps it (idempotent).

    Takes the family lock until commit; take it before the audit chain's lock (that is,
    before recording any audit event in the transaction), or two writers can deadlock."""
    connection.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": _ASSIGN_LOCK}
    )
    existing = (
        connection.execute(
            text(
                "SELECT evidence_family_id, match, matched_source_version_id, hamming_distance"
                " FROM evidence_family_member WHERE source_version_id = :id"
            ),
            {"id": source_version_id},
        )
        .mappings()
        .one_or_none()
    )
    if existing is not None:
        return Assignment(
            source_version_id,
            existing["evidence_family_id"],
            existing["match"],
            existing["matched_source_version_id"],
            existing["hamming_distance"],
        )

    fingerprint = simhash(parsed_text)
    match: Match
    matched = (
        connection.execute(
            text(
                "SELECT m.evidence_family_id, m.source_version_id, m.simhash"
                " FROM evidence_family_member m WHERE m.content_sha256 = :sha"
                " ORDER BY m.seq LIMIT 1"
            ),
            {"sha": content_sha256},
        )
        .mappings()
        .one_or_none()
    )
    if matched is not None:
        match = "content_hash"
    else:
        matched = (
            connection.execute(
                text(
                    "SELECT m.evidence_family_id, m.source_version_id, m.simhash,"
                    " bit_count(CAST(m.simhash # :simhash AS bit(64))) AS distance"
                    " FROM evidence_family_member m"
                    " JOIN evidence_family f ON f.id = m.evidence_family_id"
                    " WHERE f.simhash_rule = :rule"
                    " AND bit_count(CAST(m.simhash # :simhash AS bit(64)))"
                    " <= f.max_hamming_distance"
                    " ORDER BY distance, m.seq LIMIT 1"
                ),
                {"simhash": _signed(fingerprint), "rule": SIMHASH_RULE},
            )
            .mappings()
            .one_or_none()
        )
        match = "simhash" if matched is not None else "founder"

    family: dict[str, Any] | None = None
    if matched is None:
        family_id = uuid.uuid4()
        family = {
            "id": family_id,
            "simhash_rule": SIMHASH_RULE,
            "max_hamming_distance": max_hamming_distance,
        }
        connection.execute(
            text(
                "INSERT INTO evidence_family (id, simhash_rule, max_hamming_distance)"
                " VALUES (:id, :simhash_rule, :max_hamming_distance)"
            ),
            family,
        )
        matched_version, distance = None, None
    else:
        family_id = matched["evidence_family_id"]
        matched_version = matched["source_version_id"]
        distance = hamming_distance(matched["simhash"], fingerprint)

    member: dict[str, Any] = {
        "source_version_id": source_version_id,
        "evidence_family_id": family_id,
        "content_sha256": content_sha256,
        "simhash": _signed(fingerprint),
        "match": match,
        "matched_source_version_id": matched_version,
        "hamming_distance": distance,
    }
    connection.execute(
        text(
            "INSERT INTO evidence_family_member (source_version_id, evidence_family_id,"
            " content_sha256, simhash, match, matched_source_version_id, hamming_distance)"
            " VALUES (:source_version_id, :evidence_family_id, :content_sha256, :simhash,"
            " :match, :matched_source_version_id, :hamming_distance)"
        ),
        member,
    )
    return Assignment(
        source_version_id,
        family_id,
        match,
        matched_version,
        distance,
        created_family=family,
        created_member=member | {"simhash_rule": SIMHASH_RULE},
    )


def audit(connection: Connection, actor: Actor, assignment: Assignment) -> None:
    """The audit events of a new assignment (none if the version already had a family).
    Separate from `assign` so the ledger can keep its audit order; call it in the same
    transaction, after `assign`."""
    if assignment.created_family is not None:
        record(
            connection,
            actor,
            "evidence_family.created",
            entity_type="evidence_family",
            entity_id=str(assignment.evidence_family_id),
            new_hash=content_hash(assignment.created_family),
        )
    if assignment.created_member is not None:
        record(
            connection,
            actor,
            "evidence_family.member_added",
            entity_type="source_version",
            entity_id=str(assignment.source_version_id),
            new_hash=content_hash(assignment.created_member),
        )


@dataclass
class FamilyBackfill:
    assigned: list[str] = field(default_factory=list[str])  # Source Version IDs, in order
    families_created: int = 0


def assign_missing(
    engine: Engine,
    archive: Archive,
    actor: Actor,
    *,
    max_hamming_distance: int = DEFAULT_MAX_HAMMING_DISTANCE,
) -> FamilyBackfill:
    """Assign every parsed Source Version without a family, oldest ingested first, each in
    its own transaction. Idempotent: a version with a family is never considered again."""
    summary = FamilyBackfill()
    with engine.connect() as connection:
        pending = connection.execute(
            text(
                "SELECT v.id, v.content_sha256, v.parsed_object_uri FROM source_version v"
                " WHERE v.parse_status IN ('parsed', 'incomplete') AND NOT EXISTS"
                " (SELECT FROM evidence_family_member m WHERE m.source_version_id = v.id)"
                " ORDER BY v.ingested_at, v.id"
            )
        ).all()
    for row in pending:
        parsed_text = archive.get(row.parsed_object_uri).decode("utf-8")
        with engine.begin() as connection:
            assignment = assign(
                connection,
                source_version_id=row.id,
                content_sha256=row.content_sha256,
                parsed_text=parsed_text,
                max_hamming_distance=max_hamming_distance,
            )
            audit(connection, actor, assignment)
        if assignment.created_member is not None:  # else assigned meanwhile, elsewhere
            summary.assigned.append(str(row.id))
            summary.families_created += assignment.created_family is not None
    return summary
