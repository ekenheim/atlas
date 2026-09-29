"""PDF parsing and language: `unsupported` parses, page anchors and a version's language.

- `source_version.parse_status` gains `unsupported`: a parsed media type that yields no
  usable text (an image-only or scanned PDF; Atlas does no OCR). Like `failed`, it records
  why in `parse_error`, which is now set iff the status is `failed` or `unsupported`.
- `source_version.page_anchors`: for a PDF parse, one `{page, label, start, end}` per page
  (code-point offsets into the parsed text); NULL for formats without pages. Set only with
  a parse (`parsed` or `incomplete`).
- `source_version.language`: a lowercase ISO 639 primary subtag, or `und` (undetermined).
  The adapter's declaration, else the parse's (docs/decisions.md, "PDF parsing and
  language"). Every Source Version before this revision came from SEC EDGAR, whose
  filings are in English (Regulation S-T Rule 306), so they are `en`: set by the column's
  default while it is added (no UPDATE, so the immutability trigger is not involved),
  then the default is dropped.

Like the other parse columns, `page_anchors` and `language` can be written again only while
the parse is `pending` or `failed` (`source_version_guard_update`).

Revision ID: 0014
Revises: 0012
"""

from alembic import op

revision = "0014"
down_revision = "0012"
branch_labels = None
depends_on = None

_STATUSES = "'pending', 'parsed', 'incomplete', 'failed', 'not_applicable'"


def upgrade() -> None:
    op.execute("ALTER TABLE source_version DROP CONSTRAINT source_version_parse_status_check")
    op.execute(f"""
        ALTER TABLE source_version ADD CONSTRAINT source_version_parse_status_check
            CHECK (parse_status IN ({_STATUSES}, 'unsupported'))
    """)
    # Was `(parse_status = 'failed') = (parse_error IS NOT NULL)` (migration 0004).
    op.execute("ALTER TABLE source_version DROP CONSTRAINT source_version_check3")
    op.execute("""
        ALTER TABLE source_version ADD CONSTRAINT source_version_parse_error_check
            CHECK ((parse_status IN ('failed', 'unsupported')) = (parse_error IS NOT NULL))
    """)
    op.execute("""
        ALTER TABLE source_version
            ADD COLUMN language text DEFAULT 'en'
                CONSTRAINT source_version_language_check CHECK (language ~ '^[a-z]{2,3}$'),
            ADD COLUMN page_anchors jsonb
                CONSTRAINT source_version_page_anchors_check CHECK (
                    page_anchors IS NULL
                    OR (jsonb_typeof(page_anchors) = 'array'
                        AND parse_status IN ('parsed', 'incomplete'))
                )
    """)
    op.execute("ALTER TABLE source_version ALTER COLUMN language DROP DEFAULT")


def downgrade() -> None:
    op.execute("ALTER TABLE source_version DROP COLUMN language, DROP COLUMN page_anchors")
    op.execute("ALTER TABLE source_version DROP CONSTRAINT source_version_parse_error_check")
    op.execute("""
        ALTER TABLE source_version ADD CONSTRAINT source_version_check3
            CHECK ((parse_status = 'failed') = (parse_error IS NOT NULL))
    """)
    op.execute("ALTER TABLE source_version DROP CONSTRAINT source_version_parse_status_check")
    op.execute(f"""
        ALTER TABLE source_version ADD CONSTRAINT source_version_parse_status_check
            CHECK (parse_status IN ({_STATUSES}))
    """)
