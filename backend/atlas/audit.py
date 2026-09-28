"""The audit trail: who changed what, append-only and hash-chained.

Every mutating service calls `record` on the connection that carries its change, so the
event commits or rolls back with it. The database assigns each event its id, timestamp
and chain hashes, and rejects any UPDATE, DELETE or TRUNCATE (migration 0002 holds the
canonical hash format). `verify_chain` recomputes the chain independently.
"""

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import Connection, text

from atlas.settings import Settings

GENESIS_HASH = "0" * 64
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class Actor:
    """Who is making a change. From configuration today; an authenticated principal later."""

    name: str

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("an actor must have a non-blank name")

    @classmethod
    def from_settings(cls, settings: Settings) -> "Actor":
        return cls(settings.actor)


@dataclass(frozen=True)
class AuditEvent:
    id: int
    occurred_at: datetime
    actor: str
    action: str
    entity_type: str
    entity_id: str
    old_hash: str | None
    new_hash: str | None
    prev_hash: str
    event_hash: str


def record(
    connection: Connection,
    actor: Actor,
    action: str,
    *,
    entity_type: str,
    entity_id: str,
    old_hash: str | None = None,
    new_hash: str | None = None,
) -> AuditEvent:
    """Append an event within the caller's transaction; it commits or rolls back with it.

    `old_hash` and `new_hash` are the SHA-256 (hex) of the entity's content before and
    after the change (None for a creation or a removal). Appending takes the chain's lock
    until the transaction ends, so keep audited transactions short.
    """
    row = connection.execute(
        text(
            "INSERT INTO audit_event (actor, action, entity_type, entity_id, old_hash, new_hash)"
            " VALUES (:actor, :action, :entity_type, :entity_id, :old_hash, :new_hash)"
            " RETURNING id, occurred_at, actor, action, entity_type, entity_id,"
            " old_hash, new_hash, prev_hash, event_hash"
        ),
        {
            "actor": actor.name,
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "old_hash": old_hash,
            "new_hash": new_hash,
        },
    ).one()
    return AuditEvent(*row)


@dataclass(frozen=True)
class ChainBreak:
    event_id: int
    reason: str


@dataclass(frozen=True)
class ChainReport:
    events: int
    head_hash: str | None
    breaks: list[ChainBreak]

    @property
    def ok(self) -> bool:
        return not self.breaks


def verify_chain(connection: Connection) -> ChainReport:
    """Walk the whole trail in order, checking every event's hash and link.

    Detects altered events, events removed from the middle, and forged links. Removing
    the newest events leaves a valid shorter chain: compare `head_hash` with a copy kept
    outside the database to detect that.
    """
    rows = connection.execute(
        text(
            "SELECT id, occurred_at, actor, action, entity_type, entity_id,"
            " old_hash, new_hash, prev_hash, event_hash FROM audit_event ORDER BY id"
        )
    )
    return _walk(AuditEvent(*row) for row in rows)


def _walk(events: Iterable[AuditEvent]) -> ChainReport:
    breaks: list[ChainBreak] = []
    expected_id, expected_prev = 1, GENESIS_HASH
    count = 0
    for event in events:
        count += 1
        if event.id != expected_id:
            breaks.append(ChainBreak(event.id, "missing event(s) before it"))
        elif event.prev_hash != expected_prev:
            breaks.append(ChainBreak(event.id, "broken link (prev_hash does not match)"))
        if _event_hash(event) != event.event_hash:
            breaks.append(ChainBreak(event.id, "tampered (content does not match its hash)"))
        expected_id, expected_prev = event.id + 1, event.event_hash
    return ChainReport(count, expected_prev if count else None, breaks)


def _event_hash(event: AuditEvent) -> str:
    micros = (event.occurred_at - _EPOCH) // timedelta(microseconds=1)
    fields = (
        str(event.id),
        str(micros),
        event.actor,
        event.action,
        event.entity_type,
        event.entity_id,
        event.old_hash,
        event.new_hash,
        event.prev_hash,
    )
    payload = "".join("~" if value is None else f"{len(value)}:{value}" for value in fields)
    return hashlib.sha256(payload.encode()).hexdigest()
