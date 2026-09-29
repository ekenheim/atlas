"""As-of financial observations from XBRL companyfacts (build plan §5.7; ticket 18).

Tables:
- `financial_observation`: one XBRL fact of one filing (accession) as companyfacts lists it,
  read from an archived companyfacts Source Version. Its `available_at` is the *filing's*
  availability (EDGAR dissemination), never the companyfacts fetch time. A later value for
  the same (taxonomy, concept, unit, period) is a new row linked to its predecessor
  (`previous_observation_id`, `linkage` restates/reaffirms); nothing is ever overwritten.
  Values stay in the reported unit: `currency` is the unit's currency and `fx_basis` is NULL
  (as filed). A converted value would need a stated FX basis (rate source, date, from).
- `financial_normalization`: which companyfacts Source Version was normalized, by which
  normalizer version, and what it produced; at most once per (version, normalizer).

Both are insert-only (ENABLE ALWAYS triggers, like the ledger's).

Revision ID: 0017
Revises: 0012
"""

from alembic import op

revision = "0017"
down_revision = "0012"
branch_labels = None
depends_on = None

_TABLES = ("financial_observation", "financial_normalization")


def upgrade() -> None:
    op.execute("""
        CREATE TABLE financial_observation (
            id uuid PRIMARY KEY,
            company_id uuid NOT NULL REFERENCES company (id),
            cik text NOT NULL CHECK (cik ~ '^[0-9]{10}$'),
            source_version_id uuid NOT NULL REFERENCES source_version (id),
            accession text NOT NULL CHECK (accession ~ '^[0-9]{10}-[0-9]{2}-[0-9]{6}$'),
            form text NOT NULL CHECK (btrim(form) <> ''),
            filed date NOT NULL,
            fiscal_year integer,
            fiscal_period text,
            frame text,
            taxonomy text NOT NULL CHECK (btrim(taxonomy) <> ''),
            concept text NOT NULL CHECK (btrim(concept) <> ''),
            unit text NOT NULL CHECK (btrim(unit) <> ''),
            currency text CHECK (currency ~ '^[A-Z]{3}$'),
            fx_basis jsonb CHECK (
                fx_basis IS NULL OR (
                    jsonb_typeof(fx_basis) = 'object'
                    AND fx_basis ? 'rate_source' AND fx_basis ? 'rate_date'
                    AND fx_basis ? 'from_currency' AND currency IS NOT NULL
                )
            ),
            period_start date,
            period_end date NOT NULL,
            value numeric NOT NULL,
            available_at timestamptz NOT NULL,
            available_at_basis text NOT NULL CHECK (
                available_at_basis IN ('sec_acceptance', 'sec_dissemination',
                                       'sec_filing_date_eod', 'observed_revision')
            ),
            accepted_at timestamptz,
            previous_observation_id uuid REFERENCES financial_observation (id),
            linkage text NOT NULL CHECK (linkage IN ('first', 'restates', 'reaffirms')),
            suspect_reasons text[] NOT NULL DEFAULT '{}',
            created_at timestamptz NOT NULL DEFAULT now(),
            CHECK (period_start IS NULL OR period_start <= period_end),
            CHECK ((linkage = 'first') = (previous_observation_id IS NULL)),
            CHECK (linkage = 'restates' OR cardinality(suspect_reasons) = 0),
            UNIQUE NULLS NOT DISTINCT
                (cik, taxonomy, concept, unit, period_start, period_end, accession, value)
        )
    """)
    op.execute(
        "CREATE INDEX financial_observation_company ON financial_observation"
        " (company_id, taxonomy, concept, unit, period_end)"
    )
    op.execute("CREATE INDEX financial_observation_accession ON financial_observation (accession)")

    op.execute("""
        CREATE TABLE financial_normalization (
            id uuid PRIMARY KEY,
            source_version_id uuid NOT NULL REFERENCES source_version (id),
            company_id uuid NOT NULL REFERENCES company (id),
            normalizer_version text NOT NULL CHECK (btrim(normalizer_version) <> ''),
            facts_read integer NOT NULL CHECK (facts_read >= 0),
            observations_created integer NOT NULL CHECK (observations_created >= 0),
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (source_version_id, normalizer_version)
        )
    """)

    triggers: list[tuple[str, str]] = []
    for table in _TABLES:
        op.execute(f"""
            CREATE TRIGGER {table}_no_change BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION ledger_reject_change()
        """)
        op.execute(f"""
            CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table}
            FOR EACH STATEMENT EXECUTE FUNCTION ledger_reject_change()
        """)
        triggers += [(table, f"{table}_no_change"), (table, f"{table}_no_truncate")]
    for table, trigger in triggers:
        op.execute(f"ALTER TABLE {table} ENABLE ALWAYS TRIGGER {trigger}")

    for table in _TABLES:
        op.execute(f"REVOKE ALL ON {table} FROM PUBLIC")
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
    op.execute("DROP TABLE financial_normalization, financial_observation")
