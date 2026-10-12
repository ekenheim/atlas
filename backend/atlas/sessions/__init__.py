"""Research sessions (beliefs ticket 08): one run of a researcher on a question as of a time.

A `claude` session is opened and closed through the API (`POST /sessions`, `.../close`); the
Facts it records name it (`session_id`). A `pipeline` session is the argument plan's
investigation, recorded in the transaction that stores its research card when the Editor task
ends (and updated by a follow-up round's card). Both list together. The card is the argument
plan's card shape as JSON, with its markdown; usage is JSON (calls, tokens, records, refusals).
Opening, closing and recording are audited (`research_session.opened|closed|recorded|updated`).
"""

from atlas.sessions.service import (
    ResearchSession,
    SessionAlreadyClosed,
    SessionClose,
    SessionNotFound,
    SessionOpen,
    Sessions,
    SessionSummary,
    UnknownCompany,
    get_session,
    list_sessions,
    record_pipeline_session,
)

__all__ = [
    "ResearchSession",
    "SessionAlreadyClosed",
    "SessionClose",
    "SessionNotFound",
    "SessionOpen",
    "SessionSummary",
    "Sessions",
    "UnknownCompany",
    "get_session",
    "list_sessions",
    "record_pipeline_session",
]
