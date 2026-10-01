"""The counterevidence kind: a contradiction of a named Claim, or bear context
(memory-directed reading, ticket 03; pilot-fix ticket 16).

`counterevidence` gains:

- `kind`: `contradiction` (the quote denies, limits or dates a named supporting Claim, about
  the same company and object) or `bear_context` (a bear-checklist item about a company,
  attached to no Claim). A rejected item keeps the kind the Skeptic proposed.
- `how`: how a contradiction contradicts its Claims (`denies`, `limits`, `dates`); None for
  bear context, and for rows recorded before this revision.
- `kind_reason`: why code stored as bear context an item the Skeptic proposed as a
  contradiction (its quote names neither the Claim's subject nor its object, it names no
  Claim, it is a table row, ...); None otherwise.
- `figure_name`, `figure_period`: the figure a quoted table row states and its period (a table
  row with no words is accepted only with both).

**Backfill of the rows recorded before this revision:** `kind` is `contradiction` when the
row names a Claim (`contradicts_claim_ids` is not empty), else `bear_context`. Nothing else
about them changes: `how` and `kind_reason` stay NULL, and a row backfilled as bear context
keeps the `independent` and `independence_detail` recorded for it then. The table is
insert-only (its triggers are ENABLE ALWAYS), so the no-update trigger is off for the backfill
and back on after it.

Independence is a property of contradictions from here on: an accepted contradiction records
`independent`, new bear context records none (the old rule, accepted = `independent` set, is
replaced). An accepted row is a contradiction exactly when it names a Claim.

The downgrade refuses while an accepted row has no `independent` (bear context recorded
after this revision): counterevidence is never deleted, and the old rule couldn't hold it.

Revision ID: 0053
Revises: 0050 (re-chained at merge)
"""

from alembic import op
from sqlalchemy import text

revision = "0053"
down_revision = "0050"
branch_labels = None
depends_on = None

# The old rule's constraint is unnamed in 0031, so it is found by its definition.
_DROP_OLD_INDEPENDENCE_RULE = """
    DO $$
    DECLARE
        found text;
    BEGIN
        SELECT conname INTO STRICT found FROM pg_constraint
        WHERE conrelid = 'counterevidence'::regclass AND contype = 'c'
          AND pg_get_constraintdef(oid) LIKE '%independent IS NOT NULL%';
        EXECUTE format('ALTER TABLE counterevidence DROP CONSTRAINT %I', found);
    END
    $$
"""


def upgrade() -> None:
    op.execute("""
        ALTER TABLE counterevidence
            ADD COLUMN kind text,
            ADD COLUMN how text CHECK (how IN ('denies', 'limits', 'dates')),
            ADD COLUMN kind_reason text,
            ADD COLUMN figure_name text,
            ADD COLUMN figure_period text
    """)
    op.execute("ALTER TABLE counterevidence DISABLE TRIGGER counterevidence_no_update")
    op.execute("""
        UPDATE counterevidence SET kind = CASE
            WHEN cardinality(contradicts_claim_ids) > 0 THEN 'contradiction'
            ELSE 'bear_context' END
    """)
    op.execute("ALTER TABLE counterevidence ENABLE ALWAYS TRIGGER counterevidence_no_update")
    op.execute("ALTER TABLE counterevidence ALTER COLUMN kind SET NOT NULL")
    op.execute(_DROP_OLD_INDEPENDENCE_RULE)
    op.execute("""
        ALTER TABLE counterevidence
            ADD CONSTRAINT counterevidence_kind_check
                CHECK (kind IN ('contradiction', 'bear_context')),
            ADD CONSTRAINT counterevidence_kind_names_claim CHECK (
                outcome = 'rejected'
                OR (kind = 'contradiction') = (cardinality(contradicts_claim_ids) > 0)
            ),
            ADD CONSTRAINT counterevidence_how_of_contradiction
                CHECK (how IS NULL OR kind = 'contradiction'),
            ADD CONSTRAINT counterevidence_kind_reason_of_bear_context
                CHECK (kind_reason IS NULL OR (kind = 'bear_context' AND outcome = 'accepted')),
            ADD CONSTRAINT counterevidence_independence CHECK (
                CASE
                    WHEN outcome = 'rejected' THEN independent IS NULL
                    WHEN kind = 'contradiction' THEN independent IS NOT NULL
                    ELSE true  -- bear context: none (rows backfilled keep what was recorded)
                END
            )
    """)


def downgrade() -> None:
    connection = op.get_bind()
    held = connection.execute(
        text(
            "SELECT count(*) FROM counterevidence"
            " WHERE outcome = 'accepted' AND independent IS NULL"
        )
    ).scalar_one()
    if held:
        raise RuntimeError(
            f"refusing to downgrade: {held} accepted bear-context items record no independence,"
            " and counterevidence is never deleted"
        )
    op.execute("""
        ALTER TABLE counterevidence
            DROP CONSTRAINT counterevidence_independence,
            DROP CONSTRAINT counterevidence_kind_reason_of_bear_context,
            DROP CONSTRAINT counterevidence_how_of_contradiction,
            DROP CONSTRAINT counterevidence_kind_names_claim,
            DROP CONSTRAINT counterevidence_kind_check
    """)
    op.execute("""
        ALTER TABLE counterevidence
            ADD CHECK ((outcome = 'accepted') = (independent IS NOT NULL))
    """)
    op.execute("""
        ALTER TABLE counterevidence
            DROP COLUMN figure_period,
            DROP COLUMN figure_name,
            DROP COLUMN kind_reason,
            DROP COLUMN how,
            DROP COLUMN kind
    """)
