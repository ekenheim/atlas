"""Entity pointers: a reading pointer the entity hop made.

Memory-quality ticket 09 (docs/decisions.md, "The entity hop"). After an investigation's
Scout has recalled, Atlas lists, for each company the round reads (its seeds, then the
companies the recall pointers name), the theme's facts that carry the company's entity in
Memory; a fact from **another** company's document that resolves to a section is stored in
`reading_pointer` like a recall's, with:

- `query_kind` `entity` (the third kind beside `scout` and `bear_checklist`);
- `query_company_id`: the company the hop was made for (the company the document names), and
  `company_id` as ever the company whose document it is; `query` the entity's canonical name,
  `query_index` the company's place in the round's hop (from 1), `rank` the fact's place
  among the company's entity pointers, newest first (from 1);
- `entity_id`: the Hindsight entity the facts were listed by (only an entity pointer has one).

The unique key gains `query_kind`, so an entity pointer never collides with a recall pointer
of the same task, index, rank and section. The table stays insert-only; the constraints
change no row (no row is an entity pointer yet). The downgrade refuses while an entity pointer
exists: pointers are never deleted.

Revision ID: 0064
Revises: 0066 (re-chained at merge)
"""

from alembic import op
from sqlalchemy import text

revision = "0064"
down_revision = "0066"
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
    for name in _unique_constraints():
        op.execute(f'ALTER TABLE reading_pointer DROP CONSTRAINT "{name}"')
    op.execute(f"""
        ALTER TABLE reading_pointer
            ADD COLUMN entity_id text CHECK (btrim(entity_id) <> ''),
            DROP CONSTRAINT reading_pointer_query_kind_check,
            ADD CONSTRAINT reading_pointer_query_kind_check
                CHECK (query_kind IN ('scout', 'bear_checklist', 'entity')),
            DROP CONSTRAINT reading_pointer_bear_checklist_query,
            ADD CONSTRAINT reading_pointer_bear_checklist_query CHECK (
                (query_kind = 'bear_checklist') = (checklist_item IS NOT NULL)
                AND (query_kind IN ('bear_checklist', 'entity')) = (query_company_id IS NOT NULL)
                AND (query_kind = 'scout' OR query_index >= 1)
                AND (query_kind = 'entity') = (entity_id IS NOT NULL)
            ),
            ADD CONSTRAINT {_UNIQUE}
                UNIQUE (task_id, query_kind, query_index, rank, source_version_id, section_anchor)
    """)


def downgrade() -> None:
    recorded = (
        op.get_bind()
        .execute(text("SELECT count(*) FROM reading_pointer WHERE query_kind = 'entity'"))
        .scalar_one()
    )
    if recorded:
        raise RuntimeError(
            f"{recorded} entity pointers exist: reading pointers are insert-only and would"
            " lose what made them; the downgrade is refused"
        )
    op.execute(f"""
        ALTER TABLE reading_pointer
            DROP CONSTRAINT {_UNIQUE},
            DROP CONSTRAINT reading_pointer_bear_checklist_query,
            ADD CONSTRAINT reading_pointer_bear_checklist_query CHECK (
                (query_kind = 'bear_checklist') = (checklist_item IS NOT NULL)
                AND (query_kind = 'bear_checklist') = (query_company_id IS NOT NULL)
                AND (query_kind <> 'bear_checklist' OR query_index >= 1)
            ),
            DROP CONSTRAINT reading_pointer_query_kind_check,
            ADD CONSTRAINT reading_pointer_query_kind_check
                CHECK (query_kind IN ('scout', 'bear_checklist')),
            DROP COLUMN entity_id,
            ADD UNIQUE (task_id, query_index, rank, source_version_id, section_anchor)
    """)
