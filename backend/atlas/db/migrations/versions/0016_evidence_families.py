"""Evidence Families: copies of one announcement grouped as one witness (ticket 11).

- `evidence_family`: one per group, recording the SimHash rule and the Hamming threshold it
  was founded with (`atlas.ledger.families`).
- `evidence_family_member`: a parsed Source Version's family, at most one per version, with
  how it matched (`founder`, `content_hash`, `simhash`), the member it matched and their
  Hamming distance. `seq` orders members by assignment.

Both are append-only, like the source ledger: a version's family never changes.

Revision ID: 0016
Revises: 0012
"""

from alembic import op

revision = "0016"
down_revision = "0012"
branch_labels = None
depends_on = None

_TABLES = ("evidence_family", "evidence_family_member")


def upgrade() -> None:
    op.execute("""
        CREATE TABLE evidence_family (
            id uuid PRIMARY KEY,
            simhash_rule text NOT NULL,
            max_hamming_distance integer NOT NULL
                CHECK (max_hamming_distance BETWEEN 0 AND 64),
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE evidence_family_member (
            source_version_id uuid PRIMARY KEY REFERENCES source_version (id),
            evidence_family_id uuid NOT NULL REFERENCES evidence_family (id),
            seq bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
            content_sha256 text NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
            simhash bigint NOT NULL,
            match text NOT NULL CHECK (match IN ('founder', 'content_hash', 'simhash')),
            matched_source_version_id uuid
                REFERENCES evidence_family_member (source_version_id),
            hamming_distance integer CHECK (hamming_distance BETWEEN 0 AND 64),
            assigned_at timestamptz NOT NULL DEFAULT now(),
            CHECK ((match = 'founder') = (matched_source_version_id IS NULL)),
            CHECK ((match = 'founder') = (hamming_distance IS NULL))
        )
    """)
    op.execute(
        "CREATE INDEX evidence_family_member_family ON evidence_family_member"
        " (evidence_family_id, seq)"
    )
    op.execute(
        "CREATE INDEX evidence_family_member_content ON evidence_family_member"
        " (content_sha256, seq)"
    )
    for table in _TABLES:
        op.execute(f"""
            CREATE TRIGGER {table}_no_change BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION ledger_reject_change()
        """)
        op.execute(f"""
            CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table}
            FOR EACH STATEMENT EXECUTE FUNCTION ledger_reject_change()
        """)
        for trigger in ("no_change", "no_truncate"):
            op.execute(f"ALTER TABLE {table} ENABLE ALWAYS TRIGGER {table}_{trigger}")
    op.execute(f"REVOKE ALL ON {', '.join(_TABLES)} FROM PUBLIC")
    op.execute(f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'atlas_app') THEN
                GRANT SELECT, INSERT ON {", ".join(_TABLES)} TO atlas_app;
            END IF;
        END
        $$
    """)


def downgrade() -> None:
    op.execute("DROP TABLE evidence_family_member")
    op.execute("DROP TABLE evidence_family")
