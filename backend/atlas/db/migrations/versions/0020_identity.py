"""Entity resolution: listings in full, company aliases, and identity mappings with provenance.

- `security` gains what the identity research found missing (docs/research/identity-apis.md
  §5): `figi` is the **composite** (country-level) FIGI, now with `share_class_figi` beside it;
  `exchange_mic` stays the ISO 10383 **operating** MIC, with `segment_mic` the segment
  OpenFIGI matched (XNGS for Nasdaq Global Select); an ADR links its underlying line
  (`underlying_security_id`) and ratio (`adr_ratio`); and a `review_state`. Uniqueness per
  (MIC, ticker, validity) is the existing exclusion constraint.
- `company_alias`: legal, former and other names (SEC `formerNames` with their dates, GLEIF
  other/transliterated names), each with its source and when it was observed. Insert-only.
- `identity_mapping`: each identifier the resolver proposed for a company (`cik`, `lei`, or a
  `listing` TICKER@MIC), with its tier, source, source URL, observed_at, reasons, details and
  the evidence chain, and its review state: `committed` (exact or corroborated, applied
  automatically), `pending` (the owner's review queue), `confirmed` or `rejected`. A mapping
  that needs the owner (every CIK↔LEI link) can never be `committed`.

Revision ID: 0020
Revises: 0019 (re-chained at merge)
"""

from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE security
            ADD COLUMN segment_mic text CONSTRAINT security_segment_mic_check
                CHECK (segment_mic ~ '^[A-Z0-9]{4}$'),
            ADD COLUMN share_class_figi text CONSTRAINT security_share_class_figi_check
                CHECK (share_class_figi ~ '^[A-Z0-9]{12}$'),
            ADD COLUMN underlying_security_id uuid REFERENCES security (id)
                CONSTRAINT security_not_its_own_underlying CHECK (underlying_security_id <> id),
            ADD COLUMN adr_ratio numeric CONSTRAINT security_adr_ratio_check
                CHECK (adr_ratio > 0),
            ADD COLUMN review_state text NOT NULL DEFAULT 'unreviewed'
                CONSTRAINT security_review_state_check
                CHECK (review_state IN ('unreviewed', 'needs_review', 'reviewed'))
    """)
    op.execute("COMMENT ON COLUMN security.figi IS 'composite (country-level) FIGI'")
    op.execute("COMMENT ON COLUMN security.exchange_mic IS 'ISO 10383 operating MIC'")

    op.execute("""
        CREATE TABLE company_alias (
            id uuid PRIMARY KEY,
            company_id uuid NOT NULL REFERENCES company (id),
            name text NOT NULL CHECK (btrim(name) <> ''),
            normalized_name text NOT NULL CHECK (normalized_name <> ''),
            kind text NOT NULL CHECK (kind IN ('legal', 'former', 'other')),
            valid_from date,
            valid_to date,
            source text NOT NULL CHECK (source IN ('sec', 'gleif')),
            source_url text NOT NULL CHECK (btrim(source_url) <> ''),
            observed_at timestamptz NOT NULL,
            CHECK (valid_from IS NULL OR valid_to IS NULL OR valid_to > valid_from),
            UNIQUE NULLS NOT DISTINCT (company_id, source, kind, name, valid_from)
        )
    """)
    op.execute("CREATE INDEX company_alias_normalized ON company_alias (normalized_name)")
    op.execute("CREATE INDEX company_alias_company ON company_alias (company_id)")

    op.execute("""
        CREATE TABLE identity_mapping (
            id uuid PRIMARY KEY,
            company_id uuid NOT NULL REFERENCES company (id),
            security_id uuid REFERENCES security (id),
            kind text NOT NULL CHECK (kind IN ('cik', 'lei', 'listing')),
            value text NOT NULL CHECK (btrim(value) <> ''),
            tier text NOT NULL CHECK (tier IN ('exact', 'corroborated', 'candidate')),
            review_state text NOT NULL
                CHECK (review_state IN ('committed', 'pending', 'confirmed', 'rejected')),
            owner_confirmation boolean NOT NULL,
            source text NOT NULL CHECK (source IN ('sec', 'gleif', 'openfigi')),
            source_url text NOT NULL CHECK (btrim(source_url) <> ''),
            observed_at timestamptz NOT NULL,
            reasons text[] NOT NULL DEFAULT '{}',
            details jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(details) = 'object'),
            evidence jsonb NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(evidence) = 'array'),
            reviewed_by text,
            reviewed_at timestamptz,
            review_note text,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (company_id, kind, value),
            CONSTRAINT identity_mapping_owner_never_auto
                CHECK (NOT (owner_confirmation AND review_state = 'committed')),
            CONSTRAINT identity_mapping_commit_tier
                CHECK (review_state <> 'committed' OR tier IN ('exact', 'corroborated')),
            CONSTRAINT identity_mapping_reviewed
                CHECK ((review_state IN ('confirmed', 'rejected'))
                       = (reviewed_at IS NOT NULL AND reviewed_by IS NOT NULL)),
            CONSTRAINT identity_mapping_rejection_reason
                CHECK (review_state <> 'rejected' OR btrim(coalesce(review_note, '')) <> '')
        )
    """)
    op.execute(
        "CREATE INDEX identity_mapping_review ON identity_mapping (review_state, created_at, id)"
    )
    op.execute("CREATE INDEX identity_mapping_company ON identity_mapping (company_id)")

    op.execute("REVOKE ALL ON company_alias, identity_mapping FROM PUBLIC")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'atlas_app') THEN
                GRANT SELECT, INSERT ON company_alias TO atlas_app;
                GRANT SELECT, INSERT, UPDATE ON identity_mapping TO atlas_app;
            END IF;
        END
        $$
    """)


def downgrade() -> None:
    op.execute("DROP TABLE identity_mapping")
    op.execute("DROP TABLE company_alias")
    op.execute("""
        ALTER TABLE security
            DROP COLUMN review_state,
            DROP COLUMN adr_ratio,
            DROP COLUMN underlying_security_id,
            DROP COLUMN share_class_figi,
            DROP COLUMN segment_mic
    """)
    op.execute("COMMENT ON COLUMN security.figi IS NULL")
    op.execute("COMMENT ON COLUMN security.exchange_mic IS NULL")
