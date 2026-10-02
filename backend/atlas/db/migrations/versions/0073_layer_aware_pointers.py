"""A Scout query may carry a layer; a reading pointer says which scope's recall made it.

Memory-quality ticket 13 (docs/decisions.md, "Layer-aware pointer recall").

- `discovery_query.layer`: the supply-chain layer the Scout says the query concerns (one of the
  Claim layer taxonomy's names; the Scout role's answer is checked against them), or null.
- `reading_pointer.scope`: `theme` (the recall across the theme, as every pointer was made
  before) or `theme_layer` (the second recall of a query that carries a layer, scoped by the
  theme and by the layer's label tag `layer:<value>`); `reading_pointer.layer` is the layer of
  a `theme_layer` pointer and null otherwise. A memory both recalls return makes one pointer
  per recall, so the unique key gains `scope`.

The table stays insert-only; the columns change no row (the default fills `scope`). The
downgrade refuses while a layer-scoped pointer exists: pointers are never deleted.

Revision ID: 0073
Revises: 0067 (re-chained at merge)
"""

from alembic import op
from sqlalchemy import text

revision = "0073"
down_revision = "0067"
branch_labels = None
depends_on = None

_UNIQUE = "reading_pointer_task_query_rank_section_key"


def _unique_constraints() -> list[str]:
    return list(
        op.get_bind()
        .execute(
            text(
                "SELECT conname FROM pg_constraint"
                " WHERE conrelid = 'reading_pointer'::regclass AND contype = 'u'"
            )
        )
        .scalars()
    )


def upgrade() -> None:
    op.execute("ALTER TABLE discovery_query ADD COLUMN layer text CHECK (btrim(layer) <> '')")
    for name in _unique_constraints():
        op.execute(f'ALTER TABLE reading_pointer DROP CONSTRAINT "{name}"')
    op.execute(f"""
        ALTER TABLE reading_pointer
            ADD COLUMN scope text NOT NULL DEFAULT 'theme'
                CONSTRAINT reading_pointer_scope_check CHECK (scope IN ('theme', 'theme_layer')),
            ADD COLUMN layer text CHECK (btrim(layer) <> ''),
            ADD CONSTRAINT reading_pointer_scope_layer_check
                CHECK ((scope = 'theme_layer') = (layer IS NOT NULL)),
            ADD CONSTRAINT {_UNIQUE} UNIQUE (
                task_id, query_kind, scope, query_index, rank, source_version_id, section_anchor
            )
    """)


def downgrade() -> None:
    recorded = (
        op.get_bind()
        .execute(text("SELECT count(*) FROM reading_pointer WHERE scope = 'theme_layer'"))
        .scalar_one()
    )
    if recorded:
        raise RuntimeError(
            f"{recorded} layer-scoped pointers exist: reading pointers are insert-only and"
            " would lose what made them; the downgrade is refused"
        )
    op.execute(f"""
        ALTER TABLE reading_pointer
            DROP CONSTRAINT {_UNIQUE},
            DROP CONSTRAINT reading_pointer_scope_layer_check,
            DROP COLUMN layer,
            DROP COLUMN scope,
            ADD CONSTRAINT {_UNIQUE}
                UNIQUE (task_id, query_kind, query_index, rank, source_version_id, section_anchor)
    """)
    op.execute("ALTER TABLE discovery_query DROP COLUMN layer")
