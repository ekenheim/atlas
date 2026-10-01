"""The extractor Atlas's retains ask Hindsight for (memory-directed reading ticket 11;
`docs/decisions.md`, "Atlas's retains on MiniMax by metadata routing").

With `ATLAS_RETAIN_EXTRACTOR` set, every retain item carries `extractor: <value>` in its
metadata, which the shared Hindsight's `metadata` routing strategy sends to another chain
member (MiniMax). Hindsight stores nothing about the route, so Atlas records what it asked
for:

- `memory_document.extractor`: the extractor asked for when the section was last submitted
  (a reprocess or a resubmission records its own). Null: none, so Hindsight's primary LLM
  extracted it; also for a section never submitted (linked, or awaiting its first batch) and
  for every row recorded before this revision.
- `hindsight_operation.extractor`: the extractor the operation's items asked for; it decides
  which rolling-window budget the operation counts against (`atlas.jobs.budget`). Null (and
  every row recorded before this revision): the `codex` budget, as before.
- `provider_usage` accepts the provider `hindsight_minimax`: the routed retain and reprocess
  operations, one unit each.

Adding the columns touches no existing row (the `memory_document` guard watches identity
columns only, and the new column is not one of them). The downgrade counts the routed
operations against `codex` at their submission time and drops the columns.

Revision ID: 0060
Revises: 0055 (re-chained at merge)
"""

from alembic import op

revision = "0060"
down_revision = "0055"
branch_labels = None
depends_on = None

_PROVIDER_CHECK = """
    ALTER TABLE provider_usage ADD CONSTRAINT provider_usage_provider_check
        CHECK (provider IN ({providers}))
"""


def upgrade() -> None:
    for table in ("memory_document", "hindsight_operation"):
        op.execute(f"ALTER TABLE {table} ADD COLUMN extractor text CHECK (btrim(extractor) <> '')")
    op.execute("ALTER TABLE provider_usage DROP CONSTRAINT provider_usage_provider_check")
    op.execute(
        _PROVIDER_CHECK.format(providers="'codex', 'hindsight_minimax', 'minimax', 'tradingview'")
    )


def downgrade() -> None:
    # Without the column every operation is a `codex` operation again: count the routed ones
    # there at their own submission time, so the downgrade doesn't count them as spent now.
    op.execute("""
        INSERT INTO provider_usage (provider, source_id, units, recorded_at)
        SELECT 'codex', id, 1, submitted_at FROM hindsight_operation
        WHERE extractor IS NOT NULL
        ON CONFLICT DO NOTHING
    """)
    op.execute("DELETE FROM provider_usage WHERE provider = 'hindsight_minimax'")
    op.execute("ALTER TABLE provider_usage DROP CONSTRAINT provider_usage_provider_check")
    op.execute(_PROVIDER_CHECK.format(providers="'codex', 'minimax', 'tradingview'"))
    for table in ("hindsight_operation", "memory_document"):
        op.execute(f"ALTER TABLE {table} DROP COLUMN extractor")
