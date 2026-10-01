"""A company-level constraint needs no named product (memory-directed reading ticket 09;
`docs/decisions.md`, "A company-level constraint needs no named product").

- `claim.company_level` (boolean, false by default): true on an accepted `capacity_constrained`
  Claim that has **no object and no layer**, because the constraint is the company's own
  supply ("This demand is outpacing our current supply ..."). Its `object_text` and `layer` are
  null; what the model proposed for them ("our products", the question's layer) stays in
  `claim.proposed`. False on every other Claim, the rejected ones and those recorded before
  0057 included.
- `relationship`: an edge may have **no object** (neither `object_company_id` nor
  `object_text`): the company-level edge. Its `object_key` is the reserved empty string, which
  no product's key can be (an object text is never blank), so the identity index
  `uq_relationship_identity` (subject, predicate, object key) holds **one company-level edge
  per company and predicate**. Three named checks replace the two of 0021 ("exactly one of
  company and text", "the key is not empty"):
  `relationship_object_check` (at most one of the two), `relationship_object_key_check` (the
  key is empty exactly when there is no object) and `relationship_company_level_check` (an
  edge with no object is `capacity_constrained` and has no layer, so it can never take one).

`claim` stays insert-only: adding a column with a constant default touches no row. No existing
Relationship is changed. The downgrade refuses while a company-level Claim or Relationship
exists: Claims and Relationships are never rewritten or deleted.

Revision ID: 0057
Revises: 0055 (re-chained at merge)
"""

from alembic import op
from sqlalchemy import text

revision = "0057"
down_revision = "0055"
branch_labels = None
depends_on = None


def _checks(table: str, containing: str) -> list[str]:
    """The names of `table`'s check constraints whose definition contains `containing`."""
    rows = op.get_bind().execute(
        text(
            "SELECT conname FROM pg_constraint WHERE conrelid = CAST(:table AS regclass)"
            " AND contype = 'c' AND pg_get_constraintdef(oid) LIKE :pattern ORDER BY conname"
        ),
        {"table": table, "pattern": f"%{containing}%"},
    )
    return [row.conname for row in rows]


def _count(statement: str) -> int:
    return op.get_bind().execute(text(statement)).scalar_one()


def upgrade() -> None:
    # --- Claims ---------------------------------------------------------------------------
    op.execute("ALTER TABLE claim ADD COLUMN company_level boolean NOT NULL DEFAULT false")
    op.execute(
        "ALTER TABLE claim ADD CONSTRAINT claim_company_level_check CHECK ("
        " NOT company_level OR (outcome = 'accepted' AND predicate = 'capacity_constrained'"
        " AND object_company_id IS NULL AND object_text IS NULL AND layer IS NULL))"
    )

    # --- Relationships: an edge with no object ------------------------------------------------
    # 0021's unnamed checks: exactly one of the object company and the object text; the key
    # not empty.
    for containing in ("(object_text IS NULL)", "object_key <> ''"):
        for name in _checks("relationship", containing):
            op.execute(f'ALTER TABLE relationship DROP CONSTRAINT "{name}"')
    op.execute("""
        ALTER TABLE relationship
            ADD CONSTRAINT relationship_object_check CHECK (
                num_nonnulls(object_company_id, object_text) <= 1),
            ADD CONSTRAINT relationship_object_key_check CHECK (
                (object_key = '') = (object_company_id IS NULL AND object_text IS NULL)),
            ADD CONSTRAINT relationship_company_level_check CHECK (
                object_key <> '' OR (predicate = 'capacity_constrained' AND layer IS NULL))
    """)


def downgrade() -> None:
    blockers = {
        "company-level Claims": "SELECT count(*) FROM claim WHERE company_level",
        "Relationships with no object": "SELECT count(*) FROM relationship WHERE object_key = ''",
    }
    found = {what: _count(query) for what, query in blockers.items()}
    if any(found.values()):
        listed = ", ".join(f"{count} {what}" for what, count in found.items() if count)
        raise RuntimeError(
            f"refusing to downgrade: {listed}; Claims and Relationships are never rewritten or"
            " deleted"
        )
    op.execute("""
        ALTER TABLE relationship
            DROP CONSTRAINT relationship_company_level_check,
            DROP CONSTRAINT relationship_object_key_check,
            DROP CONSTRAINT relationship_object_check
    """)
    op.execute("""
        ALTER TABLE relationship
            ADD CHECK (object_key <> ''),
            ADD CHECK ((object_company_id IS NULL) <> (object_text IS NULL))
    """)
    op.execute("ALTER TABLE claim DROP CONSTRAINT claim_company_level_check")
    op.execute("ALTER TABLE claim DROP COLUMN company_level")
