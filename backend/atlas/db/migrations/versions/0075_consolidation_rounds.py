"""A consolidation is followed to its end and counted by rounds (memory-quality ticket 20).

Hindsight consolidates in rounds: one consolidation operation processes at most a round's
memories, and when it ends with memories still pending Hindsight submits the next round by
itself. Atlas follows a run's whole chain and counts each round.

- `memory_consolidation_round`: one row per consolidation operation of a run Atlas followed
  (the operation it requested, and each round Hindsight chained after it), keyed by
  Hindsight's operation ID, with the status Atlas last saw, Hindsight's `created_at` and
  when Atlas first saw it. Each row is one unit of the `hindsight_consolidation` budget
  (`atlas.jobs.budget`; source the operation ID). Rows are never deleted.
- `memory_consolidation` gains `rounds` (the rounds counted for the run), `last_operation_id`
  (the newest round followed) and `pending_consolidation` (the bank's `pending_consolidation`
  when the run ended: completed or stopped). The status `stopped_at_budget`: the rounds counted
  in the window reached the limit, so Atlas cancelled the run's running round. The skip reason
  `other_consolidation_running`: a consolidation of the bank Atlas did not request was pending
  or running, so Atlas asked for nothing (it neither counts nor cancels such a chain).
- `provider_usage` accepts the provider `hindsight_consolidation`.

Existing rows keep their values (`rounds` 0; their requests stay counted in `codex`). The
downgrade records a stopped run as `failed` (`permanent`) and the new skip as
`retains_pending`, and forgets the rounds' usage.

Revision ID: 0075
Revises: 0074
"""

from alembic import op

revision = "0075"
down_revision = "0074"
branch_labels = None
depends_on = None

_PROVIDERS_BEFORE = "'codex', 'hindsight_minimax', 'minimax', 'tradingview'"
_PROVIDERS = f"{_PROVIDERS_BEFORE}, 'hindsight_consolidation'"
_REASONS_BEFORE = "'nothing_retained', 'retains_pending', 'consolidation_off'"
_REASONS = f"{_REASONS_BEFORE}, 'other_consolidation_running'"
_STATUSES_BEFORE = "'skipped', 'submitted', 'completed', 'failed'"
_STATUSES = f"{_STATUSES_BEFORE}, 'stopped_at_budget'"
_ENDED_BEFORE = "'skipped', 'completed', 'failed'"
_ENDED = f"{_ENDED_BEFORE}, 'stopped_at_budget'"

# The checks 0069 created inline, under the names Postgres gave them (and 0074 kept).
_STATUS = "memory_consolidation_status_check"
_REASON = "memory_consolidation_skip_reason_check"
_ENDED_CHECK = "memory_consolidation_check2"  # 0069's third table check: completed_at


def _checks(statuses: str, reasons: str, ended: str, providers: str) -> None:
    for name, check in (
        (_STATUS, f"status IN ({statuses})"),
        (_REASON, f"skip_reason IN ({reasons})"),
        (_ENDED_CHECK, f"(status IN ({ended})) = (completed_at IS NOT NULL)"),
    ):
        op.execute(f"ALTER TABLE memory_consolidation DROP CONSTRAINT {name}")
        op.execute(f"ALTER TABLE memory_consolidation ADD CONSTRAINT {name} CHECK ({check})")
    op.execute("ALTER TABLE provider_usage DROP CONSTRAINT provider_usage_provider_check")
    op.execute(
        "ALTER TABLE provider_usage ADD CONSTRAINT provider_usage_provider_check"
        f" CHECK (provider IN ({providers}))"
    )


def upgrade() -> None:
    op.execute("""
        ALTER TABLE memory_consolidation
            ADD COLUMN rounds integer NOT NULL DEFAULT 0 CHECK (rounds >= 0),
            ADD COLUMN last_operation_id text CHECK (btrim(last_operation_id) <> ''),
            ADD COLUMN pending_consolidation integer CHECK (pending_consolidation >= 0)
    """)
    _checks(_STATUSES, _REASONS, _ENDED, _PROVIDERS)
    op.execute("""
        CREATE TABLE memory_consolidation_round (
            operation_id text PRIMARY KEY CHECK (btrim(operation_id) <> ''),
            consolidation_id uuid NOT NULL REFERENCES memory_consolidation (id),
            status text NOT NULL CHECK (btrim(status) <> ''),
            created_at timestamptz,
            first_seen_at timestamptz NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX memory_consolidation_round_run"
        " ON memory_consolidation_round (consolidation_id, created_at)"
    )
    # 0069's function refuses any removal; the rounds are kept the same way.
    triggers = {
        "memory_consolidation_round_no_delete": "BEFORE DELETE ON memory_consolidation_round"
        " FOR EACH ROW EXECUTE FUNCTION memory_consolidation_no_delete()",
        "memory_consolidation_round_no_truncate": "BEFORE TRUNCATE ON memory_consolidation_round"
        " FOR EACH STATEMENT EXECUTE FUNCTION memory_consolidation_no_delete()",
    }
    for name, definition in triggers.items():
        op.execute(f"CREATE TRIGGER {name} {definition}")
        op.execute(f"ALTER TABLE memory_consolidation_round ENABLE ALWAYS TRIGGER {name}")
    op.execute("REVOKE ALL ON memory_consolidation_round FROM PUBLIC")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'atlas_app') THEN
                GRANT SELECT, INSERT, UPDATE ON memory_consolidation_round TO atlas_app;
            END IF;
        END
        $$
    """)


def downgrade() -> None:
    op.execute("DELETE FROM provider_usage WHERE provider = 'hindsight_consolidation'")
    op.execute("DROP TABLE memory_consolidation_round")
    op.execute(
        "UPDATE memory_consolidation SET status = 'failed', error_class = 'permanent',"
        " error = coalesce(error, 'stopped at the consolidation budget')"
        " WHERE status = 'stopped_at_budget'"
    )
    op.execute(
        "UPDATE memory_consolidation SET skip_reason = 'retains_pending'"
        " WHERE skip_reason = 'other_consolidation_running'"
    )
    _checks(_STATUSES_BEFORE, _REASONS_BEFORE, _ENDED_BEFORE, _PROVIDERS_BEFORE)
    op.execute(
        "ALTER TABLE memory_consolidation DROP COLUMN pending_consolidation,"
        " DROP COLUMN last_operation_id, DROP COLUMN rounds"
    )
