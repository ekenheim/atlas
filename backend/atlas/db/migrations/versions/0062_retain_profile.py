"""What a retained section said: its retain profile, context and entities (memory-quality
ticket 04; `docs/decisions.md`, "What a retained section says").

Each memory document records, when it is submitted, what its retain item said:

- `retain_profile`: the version of what a retain item says (`atlas.retention.context`,
  `RETAIN_PROFILE`). Every section retained before this revision is `retain-v1` (the context
  `<title>: <heading or anchor>`, no entities, no display metadata), so a backfill can find
  the sections below the current profile. Null: never submitted (linked, or awaiting its
  first batch).
- `retain_context`: the context sent; null for `retain-v1`, whose context was not recorded.
- `retain_entities`: the names sent as entities (a JSON array); null for `retain-v1`.

The new columns are not identity columns, so the `memory_document` guard lets them change.
The downgrade drops them.

Revision ID: 0062
Revises: 0068 (re-chained at merge)
"""

from alembic import op

revision = "0062"
down_revision = "0068"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE memory_document
            ADD COLUMN retain_profile text CHECK (btrim(retain_profile) <> ''),
            ADD COLUMN retain_context text,
            ADD COLUMN retain_entities jsonb
                CHECK (retain_entities IS NULL OR jsonb_typeof(retain_entities) = 'array')
    """)
    op.execute(
        "UPDATE memory_document SET retain_profile = 'retain-v1' WHERE retain_state <> 'linked'"
    )


def downgrade() -> None:
    op.execute("""
        ALTER TABLE memory_document
            DROP COLUMN retain_entities,
            DROP COLUMN retain_context,
            DROP COLUMN retain_profile
    """)
