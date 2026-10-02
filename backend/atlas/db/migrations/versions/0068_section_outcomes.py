"""A section's outcome comes from its own document (memory-quality ticket 03;
`docs/decisions.md`, "A section's outcome comes from its own document").

- `memory_document.retain_state` gains `cancelled`: the section's operation was cancelled
  (by the owner) before Hindsight stored its document. It is not a failure, keeps the
  operation's error text, and `atlas retention retry-failed` enqueues it again.
- `memory_document.error_class`: why a `failed` or `cancelled` section is not in memory:
  `cancelled`, `permanent` (an operation error of no other class), `transient` (a timeout or
  relayed server error, retried up to `ATLAS_RETAIN_TRANSIENT_RETRIES` times) or `missing`
  (its document is absent after its operation completed). Null for every other state.
- `memory_document.transient_retries`: how many times the section's operation ended with a
  transient error (reset by `retry-failed`).
- `memory_document.extraction_errors`: the `extraction_errors_count` Hindsight reported on the
  operation that last stored the section with facts (null: none read). A completed section
  whose count is above zero after its one retry is **partial**.
- `hindsight_operation.error_class` gains `transient` and `cancelled`.

Data: the sections recorded `failed` with exactly the error "Hindsight reported the operation
cancelled with no error message" (the owner's cancellations early in the rollout) move to
`cancelled`; the other failed sections take the class their error shows (`missing` for a
document not found after its operation completed, else `permanent`), and every cancelled
operation is classed `cancelled`. The move is a migration, so it is not in the audit chain;
each row keeps its error text, which says what it was.

Revision ID: 0068
Revises: 0061
"""

import sqlalchemy as sa
from alembic import op

revision = "0068"
down_revision = "0061"
branch_labels = None
depends_on = None

CANCELLED_ERROR = "Hindsight reported the operation cancelled with no error message"
_MISSING_ERROR = "document % not found in Hindsight after its operation completed"

_STATES = "'pending', 'completed', 'failed', 'zero_fact', 'linked'"
_OPERATION_CLASSES = "'quota', 'unavailable', 'permanent'{extra}"


def upgrade() -> None:
    op.execute("ALTER TABLE memory_document DROP CONSTRAINT memory_document_retain_state_check")
    op.execute(f"""
        ALTER TABLE memory_document ADD CONSTRAINT memory_document_retain_state_check
            CHECK (retain_state IN ({_STATES}, 'cancelled'))
    """)
    op.execute("""
        ALTER TABLE memory_document
            ADD COLUMN error_class text CONSTRAINT ck_memory_document_error_class
                CHECK (error_class IN ('cancelled', 'permanent', 'transient', 'missing')),
            ADD COLUMN transient_retries integer NOT NULL DEFAULT 0
                CONSTRAINT ck_memory_document_transient_retries CHECK (transient_retries >= 0),
            ADD COLUMN extraction_errors integer
                CONSTRAINT ck_memory_document_extraction_errors CHECK (extraction_errors >= 0)
    """)
    op.execute("ALTER TABLE hindsight_operation DROP CONSTRAINT ck_hindsight_operation_error_class")
    op.execute(f"""
        ALTER TABLE hindsight_operation ADD CONSTRAINT ck_hindsight_operation_error_class
            CHECK (error_class IN ({_OPERATION_CLASSES.format(extra=", 'transient', 'cancelled'")}))
    """)

    op.execute(
        sa.text(
            "UPDATE memory_document SET retain_state = 'cancelled', error_class = 'cancelled'"
            " WHERE retain_state = 'failed' AND error = :error"
        ).bindparams(error=CANCELLED_ERROR)
    )
    op.execute(
        sa.text(
            "UPDATE memory_document SET error_class = 'missing'"
            " WHERE retain_state = 'failed' AND error LIKE :pattern"
        ).bindparams(pattern=_MISSING_ERROR)
    )
    op.execute(
        "UPDATE memory_document SET error_class = 'permanent'"
        " WHERE retain_state = 'failed' AND error_class IS NULL"
    )
    op.execute(
        "UPDATE hindsight_operation SET error_class = 'cancelled' WHERE status = 'cancelled'"
    )

    # Only a section that is not in memory has a class; a cancelled one keeps its error.
    op.execute("""
        ALTER TABLE memory_document
            ADD CONSTRAINT ck_memory_document_class_of_state
                CHECK ((retain_state IN ('failed', 'cancelled')) = (error_class IS NOT NULL)),
            ADD CONSTRAINT ck_memory_document_cancelled_class
                CHECK ((retain_state = 'cancelled')
                    = (error_class IS NOT DISTINCT FROM 'cancelled')),
            ADD CONSTRAINT ck_memory_document_cancelled_error
                CHECK (retain_state <> 'cancelled' OR error IS NOT NULL)
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE memory_document
            DROP CONSTRAINT ck_memory_document_class_of_state,
            DROP CONSTRAINT ck_memory_document_cancelled_class,
            DROP CONSTRAINT ck_memory_document_cancelled_error
    """)
    op.execute(
        "UPDATE memory_document SET retain_state = 'failed' WHERE retain_state = 'cancelled'"
    )
    op.execute(
        "UPDATE hindsight_operation SET error_class = 'permanent'"
        " WHERE error_class IN ('transient', 'cancelled')"
    )
    op.execute("ALTER TABLE hindsight_operation DROP CONSTRAINT ck_hindsight_operation_error_class")
    op.execute(f"""
        ALTER TABLE hindsight_operation ADD CONSTRAINT ck_hindsight_operation_error_class
            CHECK (error_class IN ({_OPERATION_CLASSES.format(extra="")}))
    """)
    op.execute("""
        ALTER TABLE memory_document
            DROP COLUMN error_class,
            DROP COLUMN transient_retries,
            DROP COLUMN extraction_errors
    """)
    op.execute("ALTER TABLE memory_document DROP CONSTRAINT memory_document_retain_state_check")
    op.execute(f"""
        ALTER TABLE memory_document ADD CONSTRAINT memory_document_retain_state_check
            CHECK (retain_state IN ({_STATES}))
    """)
