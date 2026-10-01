"""A layer only when the quote supports one; an edge is (subject, predicate, object)
(memory-directed reading ticket 08; `docs/decisions.md`, "A layer only when the quote supports
one").

- `claim.layer` may be null. `claim.layer_term` is the taxonomy term in the quote or the
  object text that supports an accepted Claim's layer; `claim.layer_reason` is
  `layer_unsupported` when an accepted Claim's proposed layer was dropped because nothing in
  the quote or the object names it (the proposal stays in `claim.proposed`). Both are null for
  rejected Claims and for Claims recorded before 0055.
- `relationship.layer` may be null, and the layer leaves the edge's identity: the unique
  constraint on (subject, predicate, object key, layer) is replaced by the unique index
  `uq_relationship_identity` on (subject, predicate, object key). **Existing edges keep their
  layer and are never merged or deleted.** Edges that already share an identity and differ only
  by layer stay as they are; all but the oldest of each such group are marked
  `legacy_layer_duplicate` (the only thing this migration writes to an existing row), which
  leaves them out of the index. No new duplicate can be made.
- The identity trigger now guards (subject, predicate, object, `legacy_layer_duplicate`); the
  layer may be set once, from null to a layer (an edge with no layer takes the layer later
  Evidence supports), and never changed or cleared after.
- `relationship_review`: `reviewer_hedge` (`none`, `hedged`) is the Reviewer's hedge check and
  `supported_layer` the layer the Assertion's quote supports (null: none). From `reviewer.v4`
  on the Reviewer answers each check on its own, so a new review has no `reviewer_verdict`;
  reviews recorded before keep theirs. `reviewer_layer` gains `not_proposed` (the Assertion had
  no layer). "Answered" now means a direction was answered.

`claim` and `relationship_review` stay insert-only; adding columns touches no row. The
downgrade refuses while anything of the new shape exists: Claims, Relationships and reviews
are never rewritten or deleted.

Revision ID: 0055
Revises: 0052 (re-chained at merge)
"""

from alembic import op
from sqlalchemy import text

revision = "0055"
down_revision = "0052"
branch_labels = None
depends_on = None

_GUARD = """
    CREATE OR REPLACE FUNCTION relationship_guard_update() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        IF ({new}) IS DISTINCT FROM ({old}) THEN
            RAISE EXCEPTION 'a relationship''s identity is immutable; only its review changes';
        END IF;
        {layer}
        RETURN NEW;
    END
    $$
"""
_IDENTITY = (
    "id, subject_company_id, predicate, object_company_id, object_text, object_key, created_at"
)


def _columns(prefix: str, columns: str) -> str:
    return ", ".join(f"{prefix}.{name.strip()}" for name in columns.split(","))


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
    op.execute("ALTER TABLE claim ALTER COLUMN layer DROP NOT NULL")
    op.execute("ALTER TABLE claim ADD COLUMN layer_term text CHECK (btrim(layer_term) <> '')")
    op.execute(
        "ALTER TABLE claim ADD COLUMN layer_reason text"
        " CHECK (layer_reason IN ('layer_unsupported'))"
    )
    op.execute(
        "ALTER TABLE claim ADD CONSTRAINT claim_layer_support_check CHECK ("
        " (layer_term IS NULL OR layer IS NOT NULL)"
        " AND (layer_reason IS NULL OR layer IS NULL))"
    )

    # --- Relationships: the layer optional and out of the identity -------------------------
    op.execute("ALTER TABLE relationship ALTER COLUMN layer DROP NOT NULL")
    unique = (
        op.get_bind()
        .execute(
            text(
                "SELECT conname FROM pg_constraint"
                " WHERE conrelid = CAST('relationship' AS regclass) AND contype = 'u'"
            )
        )
        .scalars()
        .all()
    )
    for name in unique:
        op.execute(f'ALTER TABLE relationship DROP CONSTRAINT "{name}"')
    op.execute(
        "ALTER TABLE relationship ADD COLUMN legacy_layer_duplicate boolean NOT NULL DEFAULT false"
    )
    # The old guard (0021) doesn't watch the new column, so this passes it.
    op.execute("""
        UPDATE relationship r SET legacy_layer_duplicate = true
        WHERE EXISTS (
            SELECT FROM relationship older
            WHERE older.subject_company_id = r.subject_company_id
              AND older.predicate = r.predicate
              AND older.object_key = r.object_key
              AND (older.created_at, older.id) < (r.created_at, r.id)
        )
    """)
    op.execute(
        "CREATE UNIQUE INDEX uq_relationship_identity ON relationship"
        " (subject_company_id, predicate, object_key) WHERE NOT legacy_layer_duplicate"
    )
    op.execute(
        "CREATE INDEX ix_relationship_identity ON relationship"
        " (subject_company_id, predicate, object_key)"
    )
    identity = f"{_IDENTITY}, legacy_layer_duplicate"
    op.execute(
        _GUARD.format(
            new=_columns("NEW", identity),
            old=_columns("OLD", identity),
            layer=(
                "IF NEW.layer IS DISTINCT FROM OLD.layer AND OLD.layer IS NOT NULL THEN"
                " RAISE EXCEPTION 'a relationship''s layer is set once: it can''t change';"
                " END IF;"
            ),
        )
    )

    # --- machine reviews: one answer per check ----------------------------------------------
    op.execute(
        "ALTER TABLE relationship_review ADD COLUMN reviewer_hedge text"
        " CHECK (reviewer_hedge IN ('none', 'hedged'))"
    )
    op.execute("ALTER TABLE relationship_review ADD COLUMN supported_layer text")
    for name in _checks("relationship_review", "reviewer_verdict IS"):
        op.execute(f'ALTER TABLE relationship_review DROP CONSTRAINT "{name}"')
    for name in _checks("relationship_review", "reviewer_layer = ANY"):
        op.execute(f'ALTER TABLE relationship_review DROP CONSTRAINT "{name}"')
    op.execute("""
        ALTER TABLE relationship_review
            ADD CONSTRAINT relationship_review_reviewer_layer_check CHECK (
                reviewer_layer IN ('correct', 'wrong', 'unclear', 'not_proposed')),
            ADD CONSTRAINT relationship_review_answered_check CHECK (
                (reviewer_status = 'answered') = (reviewer_direction IS NOT NULL)),
            ADD CONSTRAINT relationship_review_answer_parts_check CHECK (
                (reviewer_direction IS NULL) = (reviewer_layer IS NULL)
                AND (reviewer_verdict IS NULL OR reviewer_direction IS NOT NULL)
                AND (reviewer_hedge IS NULL OR reviewer_direction IS NOT NULL))
    """)


def downgrade() -> None:
    blockers = {
        "Claims without a layer": "SELECT count(*) FROM claim WHERE layer IS NULL",
        "Relationships without a layer": "SELECT count(*) FROM relationship WHERE layer IS NULL",
        "machine reviews answered per check": (
            "SELECT count(*) FROM relationship_review WHERE reviewer_hedge IS NOT NULL"
            " OR reviewer_layer = 'not_proposed'"
            " OR (reviewer_status = 'answered' AND reviewer_verdict IS NULL)"
        ),
    }
    found = {what: _count(query) for what, query in blockers.items()}
    if any(found.values()):
        listed = ", ".join(f"{count} {what}" for what, count in found.items() if count)
        raise RuntimeError(
            f"refusing to downgrade: {listed}; Claims, Relationships and reviews are never"
            " rewritten or deleted"
        )
    op.execute("""
        ALTER TABLE relationship_review
            DROP CONSTRAINT relationship_review_answer_parts_check,
            DROP CONSTRAINT relationship_review_answered_check,
            DROP CONSTRAINT relationship_review_reviewer_layer_check
    """)
    op.execute("""
        ALTER TABLE relationship_review
            ADD CONSTRAINT relationship_review_reviewer_layer_check CHECK (
                reviewer_layer IN ('correct', 'wrong', 'unclear')),
            ADD CHECK ((reviewer_status = 'answered') = (reviewer_verdict IS NOT NULL)),
            ADD CHECK ((reviewer_verdict IS NULL) = (reviewer_direction IS NULL)),
            ADD CHECK ((reviewer_verdict IS NULL) = (reviewer_layer IS NULL))
    """)
    op.execute("ALTER TABLE relationship_review DROP COLUMN supported_layer")
    op.execute("ALTER TABLE relationship_review DROP COLUMN reviewer_hedge")

    identity = f"{_IDENTITY}, layer"
    op.execute(
        _GUARD.format(new=_columns("NEW", identity), old=_columns("OLD", identity), layer="")
    )
    op.execute("DROP INDEX ix_relationship_identity")
    op.execute("DROP INDEX uq_relationship_identity")
    op.execute("ALTER TABLE relationship DROP COLUMN legacy_layer_duplicate")
    op.execute(
        "ALTER TABLE relationship ADD UNIQUE (subject_company_id, predicate, object_key, layer)"
    )
    op.execute("ALTER TABLE relationship ALTER COLUMN layer SET NOT NULL")

    op.execute("ALTER TABLE claim DROP CONSTRAINT claim_layer_support_check")
    op.execute("ALTER TABLE claim DROP COLUMN layer_reason")
    op.execute("ALTER TABLE claim DROP COLUMN layer_term")
    op.execute("ALTER TABLE claim ALTER COLUMN layer SET NOT NULL")
