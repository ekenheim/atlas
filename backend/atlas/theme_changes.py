"""What changed on a theme (atlas-beliefs ticket 21): a feed, newest first, of what the owner
would want to see again: a Belief judged (not its proposal, which is no judgement), a flag or a
notice raised on one, and a Fact recorded.

Read-only and derived from the records themselves: every item names the record it comes from
(`belief_id`, or `fact_id` with the Source Version it quotes) so a page can link to it. A Fact
belongs to the theme of the research session or investigation that recorded it, or of a Belief
that cites it.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import Connection, text

type ChangeKind = Literal["judged", "flagged", "notice", "fact"]


class ThemeChange(BaseModel):
    kind: ChangeKind
    at: datetime
    text: str = Field(description="one line: the statement and what happened to it")
    belief_id: uuid.UUID | None = Field(description="the Belief it is about (not for a Fact)")
    fact_id: uuid.UUID | None = Field(description="the Fact recorded (only for a Fact)")
    source_version_id: uuid.UUID | None = Field(description="the Source Version the Fact quotes")


_CHANGES = """
    SELECT * FROM (
        SELECT 'judged' AS kind, j.at AS at,
               j.judgement || ' ' || round(j.confidence * 100)::int::text || '%: '
                   || b.statement AS line,
               b.id AS belief_id, NULL::uuid AS fact_id, NULL::uuid AS source_version_id
        FROM belief_judgement j JOIN belief b ON b.id = j.belief_id
        WHERE b.theme = :theme AND NOT (j.judgement = 'unproven' AND j.reason = 'proposed')
        UNION ALL
        SELECT 'flagged', f.raised_at, f.detail || ' (' || b.statement || ')',
               b.id, NULL::uuid, NULL::uuid
        FROM belief_flag f JOIN belief b ON b.id = f.belief_id
        WHERE b.theme = :theme
        UNION ALL
        SELECT 'notice', n.raised_at, n.detail || ' (' || b.statement || ')',
               b.id, NULL::uuid, NULL::uuid
        FROM belief_notice n JOIN belief b ON b.id = n.belief_id
        WHERE b.theme = :theme
        UNION ALL
        SELECT 'fact', f.created_at,
               coalesce(c.display_name || ': ', '') || (a.value_json ->> 'statement'),
               NULL::uuid, f.assertion_id, a.source_version_id
        FROM fact f
        JOIN assertion a ON a.id = f.assertion_id
        LEFT JOIN company c ON c.id = a.subject_company_id
        LEFT JOIN research_session s ON s.id = f.session_id
        LEFT JOIN investigation i ON i.id = f.investigation_id
        WHERE coalesce(s.theme, i.theme) = :theme
           OR EXISTS (
               SELECT 1 FROM belief_citation bc JOIN belief bf ON bf.id = bc.belief_id
               WHERE bc.ref_id = f.assertion_id AND bf.theme = :theme)
    ) changes
    ORDER BY at DESC, kind, line
    LIMIT :limit
"""


def theme_changes(connection: Connection, theme_id: str, limit: int) -> list[ThemeChange]:
    rows = connection.execute(text(_CHANGES), {"theme": theme_id, "limit": limit}).all()
    return [
        ThemeChange(
            kind=row.kind,
            at=row.at,
            text=row.line,
            belief_id=row.belief_id,
            fact_id=row.fact_id,
            source_version_id=row.source_version_id,
        )
        for row in rows
    ]
