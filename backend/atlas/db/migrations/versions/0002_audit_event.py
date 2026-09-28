"""Audit trail: an append-only, hash-chained `audit_event` table enforced by the database.

The database, not the application, assigns each event its place in the chain: a BEFORE
INSERT trigger serializes writers with a transaction-scoped advisory lock, then sets the
gapless `id`, `occurred_at`, `prev_hash` (the previous event's hash, or 64 zeros for the
first event) and `event_hash`. Whatever a caller supplies for those columns is overwritten.

`event_hash` is the SHA-256 (hex) of the UTF-8 concatenation of these fields, in order,
each encoded as `<length in characters>:<value>`, or `~` when NULL:
id, occurred_at (microseconds since the Unix epoch), actor, action, entity_type, entity_id,
old_hash, new_hash, prev_hash. `atlas.audit.verify_chain` recomputes it independently.

Append-only is enforced twice:
- Triggers reject UPDATE, DELETE and TRUNCATE for every role, the owner and superusers
  included. They are ENABLE ALWAYS, so `session_replication_role` does not bypass them;
  only the table owner can disable them, which is why the runtime must not be the owner.
- Privileges: PUBLIC gets nothing. The intended role split is a migration role that owns
  the schema (runs `atlas migrate`) and a runtime role `atlas_app` (API and worker) that
  holds only SELECT and INSERT on `audit_event`. When `atlas_app` exists at migrate time,
  this revision grants it exactly that; the role itself is created by the deployment.

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

HASH = "~ '^[0-9a-f]{64}$'"


def upgrade() -> None:
    op.execute(f"""
        CREATE TABLE audit_event (
            id bigint PRIMARY KEY,
            occurred_at timestamptz NOT NULL,
            actor text NOT NULL CHECK (btrim(actor) <> ''),
            action text NOT NULL CHECK (btrim(action) <> ''),
            entity_type text NOT NULL CHECK (btrim(entity_type) <> ''),
            entity_id text NOT NULL CHECK (btrim(entity_id) <> ''),
            old_hash text CHECK (old_hash {HASH}),
            new_hash text CHECK (new_hash {HASH}),
            prev_hash text NOT NULL CHECK (prev_hash {HASH}),
            event_hash text NOT NULL UNIQUE CHECK (event_hash {HASH})
        )
    """)
    op.execute("CREATE INDEX audit_event_entity ON audit_event (entity_type, entity_id)")

    op.execute("""
        CREATE FUNCTION audit_event_field(value text) RETURNS text
        LANGUAGE sql IMMUTABLE AS $$
            SELECT CASE WHEN value IS NULL THEN '~' ELSE length(value) || ':' || value END
        $$
    """)
    op.execute("""
        CREATE FUNCTION audit_event_chain() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            last_id bigint;
            last_hash text;
        BEGIN
            -- One writer at a time, until its transaction ends: the chain has no forks.
            PERFORM pg_advisory_xact_lock(hashtextextended('atlas.audit_event', 0));
            SELECT id, event_hash INTO last_id, last_hash
                FROM audit_event ORDER BY id DESC LIMIT 1;
            NEW.id := coalesce(last_id, 0) + 1;
            NEW.occurred_at := clock_timestamp();
            NEW.prev_hash := coalesce(last_hash, repeat('0', 64));
            NEW.event_hash := encode(sha256(convert_to(
                audit_event_field(NEW.id::text)
                || audit_event_field(
                    (extract(epoch FROM NEW.occurred_at) * 1000000)::bigint::text)
                || audit_event_field(NEW.actor)
                || audit_event_field(NEW.action)
                || audit_event_field(NEW.entity_type)
                || audit_event_field(NEW.entity_id)
                || audit_event_field(NEW.old_hash)
                || audit_event_field(NEW.new_hash)
                || audit_event_field(NEW.prev_hash),
                'UTF8')), 'hex');
            RETURN NEW;
        END
        $$
    """)
    op.execute("""
        CREATE FUNCTION audit_event_reject_change() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'audit_event is append-only: % is not allowed', TG_OP;
        END
        $$
    """)
    op.execute("""
        CREATE TRIGGER audit_event_chain BEFORE INSERT ON audit_event
        FOR EACH ROW EXECUTE FUNCTION audit_event_chain()
    """)
    op.execute("""
        CREATE TRIGGER audit_event_append_only BEFORE UPDATE OR DELETE ON audit_event
        FOR EACH ROW EXECUTE FUNCTION audit_event_reject_change()
    """)
    op.execute("""
        CREATE TRIGGER audit_event_no_truncate BEFORE TRUNCATE ON audit_event
        FOR EACH STATEMENT EXECUTE FUNCTION audit_event_reject_change()
    """)
    for trigger in ("audit_event_chain", "audit_event_append_only", "audit_event_no_truncate"):
        op.execute(f"ALTER TABLE audit_event ENABLE ALWAYS TRIGGER {trigger}")

    op.execute("REVOKE ALL ON audit_event FROM PUBLIC")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'atlas_app') THEN
                GRANT SELECT, INSERT ON audit_event TO atlas_app;
            END IF;
        END
        $$
    """)


def downgrade() -> None:
    op.execute("DROP TABLE audit_event")
    op.execute("DROP FUNCTION audit_event_reject_change()")
    op.execute("DROP FUNCTION audit_event_chain()")
    op.execute("DROP FUNCTION audit_event_field(text)")
