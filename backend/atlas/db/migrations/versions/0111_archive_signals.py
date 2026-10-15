"""Archive bottleneck signals as Tier C leads (atlas-beliefs ticket 18).

- `lead.origin` gains `archive_signal`: a sentence of an archived document that reads like a
  bottleneck (`atlas.discovery.signals`), found by the nightly `scan_signals` job. Like a
  `tradingview_calendar` lead it has no query. It is where to look, never Evidence.
- `archive_signal`: the lead's facts, one row per span of a Source Version's parse: the
  sentence verbatim (`quote`) and its code-point span, the section it is in, the company and
  its themes, the cue families and phrases that matched, the factors that made the score, the
  speaker of a call transcript's sentence, and the scorer and config versions. A hash of the
  normalized sentence (`sentence_sha256`) lets the scan skip a sentence a company has already
  repeated in an earlier document. Insert-only.
- `signal_scan`: one row per run of the job (`since`, `until`, counts, versions), so "since
  the last scan" has a record even when a scan finds nothing. Insert-only.

Both tables are guarded by triggers (update, delete and truncate refused, enabled always), as
the repo's other insert-only tables are.

Revision ID: 0111
Revises: 0110
"""

from alembic import op

revision = "0111"
down_revision = "0110"
branch_labels = None
depends_on = None

_TABLES = ("archive_signal", "signal_scan")


def upgrade() -> None:
    op.execute("ALTER TABLE lead DROP CONSTRAINT lead_origin_query")
    op.execute("ALTER TABLE lead DROP CONSTRAINT lead_origin_check")
    op.execute("""
        ALTER TABLE lead ADD CONSTRAINT lead_origin_check
            CHECK (origin IN ('searxng', 'tradingview_news', 'edgar_fts', 'tradingview_calendar',
                              'archive_signal'))
    """)
    op.execute("""
        ALTER TABLE lead ADD CONSTRAINT lead_origin_query
            CHECK ((origin IN ('searxng', 'edgar_fts')) = (first_query_id IS NOT NULL))
    """)
    op.execute("""
        CREATE TABLE signal_scan (
            id uuid PRIMARY KEY,
            job_id uuid REFERENCES job (id),
            mode text NOT NULL CHECK (mode IN ('since_last', 'since', 'versions')),
            since timestamptz,
            until timestamptz NOT NULL,
            versions_scanned integer NOT NULL CHECK (versions_scanned >= 0),
            hits integer NOT NULL CHECK (hits >= 0),
            stored integer NOT NULL CHECK (stored >= 0),
            repeats integer NOT NULL CHECK (repeats >= 0),
            scorer_version text NOT NULL,
            config_version integer NOT NULL,
            scanned_at timestamptz NOT NULL
        )
    """)
    op.execute("CREATE INDEX ix_signal_scan_until ON signal_scan (until DESC)")
    op.execute("""
        CREATE TABLE archive_signal (
            lead_id uuid PRIMARY KEY REFERENCES lead (id),
            source_version_id uuid NOT NULL REFERENCES source_version (id),
            company_id uuid NOT NULL REFERENCES company (id),
            themes text[] NOT NULL,
            parser_version text NOT NULL CHECK (btrim(parser_version) <> ''),
            section_anchor text,
            char_start integer NOT NULL CHECK (char_start >= 0),
            char_end integer NOT NULL,
            quote text NOT NULL CHECK (btrim(quote) <> ''),
            sentence_sha256 text NOT NULL CHECK (sentence_sha256 ~ '^[0-9a-f]{64}$'),
            families text[] NOT NULL CHECK (cardinality(families) >= 1),
            matches jsonb NOT NULL,
            factors jsonb NOT NULL,
            score numeric NOT NULL CHECK (score > 0),
            speaker text,
            speaker_kind text CHECK (speaker_kind IN ('management', 'analyst', 'unknown')),
            scorer_version text NOT NULL,
            config_version integer NOT NULL,
            job_id uuid REFERENCES job (id),
            scanned_at timestamptz NOT NULL,
            CHECK (char_end > char_start),
            UNIQUE (source_version_id, parser_version, char_start, char_end)
        )
    """)
    op.execute("CREATE INDEX ix_archive_signal_company ON archive_signal (company_id)")
    op.execute(
        "CREATE INDEX ix_archive_signal_sentence ON archive_signal (company_id, sentence_sha256)"
    )
    op.execute("CREATE INDEX ix_archive_signal_score ON archive_signal (score DESC)")
    op.execute("""
        CREATE FUNCTION archive_signal_insert_only_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '% is insert-only: % is not allowed', TG_TABLE_NAME, TG_OP;
        END
        $$
    """)
    for table in _TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_guard BEFORE UPDATE OR DELETE ON {table}"
            " FOR EACH ROW EXECUTE FUNCTION archive_signal_insert_only_guard()"
        )
        op.execute(
            f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table}"
            " FOR EACH STATEMENT EXECUTE FUNCTION archive_signal_insert_only_guard()"
        )
        for trigger in (f"{table}_guard", f"{table}_no_truncate"):
            op.execute(f"ALTER TABLE {table} ENABLE ALWAYS TRIGGER {trigger}")
    op.execute("REVOKE ALL ON archive_signal, signal_scan FROM PUBLIC")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'atlas_app') THEN
                GRANT SELECT, INSERT ON archive_signal, signal_scan TO atlas_app;
            END IF;
        END
        $$
    """)


def downgrade() -> None:
    op.execute("DROP TABLE archive_signal")
    op.execute("DROP TABLE signal_scan")
    op.execute("DROP FUNCTION archive_signal_insert_only_guard()")
    op.execute("DELETE FROM lead WHERE origin = 'archive_signal'")
    op.execute("ALTER TABLE lead DROP CONSTRAINT lead_origin_query")
    op.execute("ALTER TABLE lead DROP CONSTRAINT lead_origin_check")
    op.execute("""
        ALTER TABLE lead ADD CONSTRAINT lead_origin_check
            CHECK (origin IN ('searxng', 'tradingview_news', 'edgar_fts', 'tradingview_calendar'))
    """)
    op.execute("""
        ALTER TABLE lead ADD CONSTRAINT lead_origin_query
            CHECK ((origin IN ('searxng', 'edgar_fts')) = (first_query_id IS NOT NULL))
    """)
