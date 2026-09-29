"""The photonics universe: each company's supply-chain layer, source path and SEC forms.

- `company.layer`: its primary layer in the photonics supply chain (substrate, epi,
  chip-laser, dsp, module, contract-manufacturing, system). NULL for a company that has no
  layer yet (e.g. a later committed Candidate).
- `company.source_path`: where its primary disclosures come from: `sec` (SEC EDGAR) or
  `exchange:<hkex|lse-rns|euronext>`. Only `sec` companies are fetched by the SEC ingest.
- `company.sec_forms`: the SEC forms ingested for it (e.g. 20-F/6-K for a foreign private
  issuer); NULL means the adapter's default (10-K, 10-Q, 8-K). Only for `sec` companies.

All three are set by `atlas companies seed` from the theme config.

Revision ID: 0015
Revises: 0014
"""

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

_LAYERS = "'substrate', 'epi', 'chip-laser', 'dsp', 'module', 'contract-manufacturing', 'system'"


def upgrade() -> None:
    op.execute(f"""
        ALTER TABLE company
            ADD COLUMN layer text CONSTRAINT company_layer_check CHECK (layer IN ({_LAYERS})),
            ADD COLUMN source_path text CONSTRAINT company_source_path_check
                CHECK (source_path ~ '^(sec|exchange:(hkex|lse-rns|euronext))$'),
            ADD COLUMN sec_forms text[] CONSTRAINT company_sec_forms_check
                CHECK (sec_forms IS NULL OR (source_path = 'sec' AND cardinality(sec_forms) > 0))
    """)
    op.execute("""
        ALTER TABLE company ADD CONSTRAINT company_sec_path_has_cik
            CHECK (source_path IS DISTINCT FROM 'sec' OR cik IS NOT NULL)
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE company DROP CONSTRAINT company_sec_path_has_cik")
    op.execute(
        "ALTER TABLE company DROP COLUMN sec_forms, DROP COLUMN source_path, DROP COLUMN layer"
    )
