"""Retention: Source Versions into the research bank, section by section (spec Part B).

`service` runs the `retain`, `poll_operation` and `reprocess` jobs, `sections` splits a
parse into anchored sections, `triage` decides which sections are worth retaining (the
`triage` job, retain on demand) and `decisions` records and reads those decisions, and
`reads` serves a version's memory documents to the API.
"""

from atlas.retention.decisions import TriageDecision, list_decisions
from atlas.retention.handlers import register_retention_handlers
from atlas.retention.reads import (
    RETAIN_STATES,
    MemoryDocument,
    MemoryOperation,
    RetainState,
    SourceVersionMemory,
    source_version_memory,
)
from atlas.retention.sections import (
    MAX_CHUNK_CHARS,
    SECTIONER_VERSION,
    Section,
    split_sections,
)
from atlas.retention.service import (
    POLL_KIND,
    REPROCESS_KIND,
    RETAIN_KIND,
    TRIAGE_KIND,
    NoTemplateApplied,
    enqueue_retains,
    retain_payload,
    retry_failed,
)
from atlas.retention.triage import (
    RULES_VERSION,
    RetainOnDemand,
    RetainRefused,
    RetainRequested,
    request_retain,
)

__all__ = [
    "MAX_CHUNK_CHARS",
    "POLL_KIND",
    "REPROCESS_KIND",
    "RETAIN_KIND",
    "RETAIN_STATES",
    "RULES_VERSION",
    "SECTIONER_VERSION",
    "TRIAGE_KIND",
    "MemoryDocument",
    "MemoryOperation",
    "NoTemplateApplied",
    "RetainOnDemand",
    "RetainRefused",
    "RetainRequested",
    "RetainState",
    "Section",
    "SourceVersionMemory",
    "TriageDecision",
    "enqueue_retains",
    "list_decisions",
    "register_retention_handlers",
    "request_retain",
    "retain_payload",
    "retry_failed",
    "source_version_memory",
    "split_sections",
]
