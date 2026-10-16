"""The earnings calendar in its confirmed shape (ticket 16d): the period a report is for.

TradingView's answer names no event ID, fiscal year or fiscal period: a row holds the quarter
end the **next** report is for (`fiscal_period_end`) and two dates, and the most recent
report's quarter is derived from it. So an event is now identified by the symbol and the
period's end day (`event_key`, `NASDAQ:LITE:2026-09-30`), and the lead carries:

- `tradingview_calendar_event.period_end`: the day the quarter the report is for ends.
- `tradingview_calendar_observation.period_basis`: how that day was known at the sighting,
  `stated` (the quarter the next report is for, as TradingView gives it) or
  `derived_from_next` (the most recent report's quarter, the month end three months before
  the next one's). A scheduled report that happens is later seen as the recent one: the same
  lead, a `reported` observation, with the basis the sighting had.

`fiscal_period` and `fiscal_year` stay on the event table (insert-only, nothing is dropped)
but nothing writes them any more. Both new columns are nullable: nothing stored before this
migration has them.

Revision ID: 0114
Revises: 0113
"""

from alembic import op

revision = "0114"
down_revision = "0113"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tradingview_calendar_event ADD COLUMN period_end date")
    op.execute(
        "ALTER TABLE tradingview_calendar_observation ADD COLUMN period_basis text"
        " CHECK (period_basis IN ('stated', 'derived_from_next'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE tradingview_calendar_observation DROP COLUMN period_basis")
    op.execute("ALTER TABLE tradingview_calendar_event DROP COLUMN period_end")
