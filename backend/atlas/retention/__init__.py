"""Retention: Source Versions into the research bank, section by section (spec Part B).

`service` runs the `retain`, `poll_operation` and `reprocess` jobs, `sections` splits a
parse into anchored sections, and `reads` serves a version's memory documents to the API.
"""

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
    NoTemplateApplied,
    enqueue_retains,
    retain_payload,
)

__all__ = [
    "MAX_CHUNK_CHARS",
    "POLL_KIND",
    "REPROCESS_KIND",
    "RETAIN_KIND",
    "RETAIN_STATES",
    "SECTIONER_VERSION",
    "MemoryDocument",
    "MemoryOperation",
    "NoTemplateApplied",
    "RetainState",
    "Section",
    "SourceVersionMemory",
    "enqueue_retains",
    "register_retention_handlers",
    "retain_payload",
    "source_version_memory",
    "split_sections",
]
