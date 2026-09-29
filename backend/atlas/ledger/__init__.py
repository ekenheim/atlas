"""The source ledger: Source Documents, immutable Source Versions and fetch observations
(spec Part A, Source ledger). `service` writes, `reads` reads, `ingest` is the job,
`families` groups parsed versions into Evidence Families."""

from atlas.ledger.availability import CorrectionSummary, correct_availability
from atlas.ledger.families import FamilyBackfill, assign_missing
from atlas.ledger.reads import (
    Content,
    ContentKind,
    EvidenceFamily,
    EvidenceFamilyMember,
    EvidenceFamilyMembership,
    FetchObservation,
    SourceDocument,
    SourceVersionDetail,
    SourceVersionSummary,
    get_content,
    get_evidence_family,
    get_source_document,
    get_version,
    list_source_documents,
    list_versions,
)
from atlas.ledger.service import (
    IDENTITY_RULE,
    SEC_EDGE_SCRIPT_RULE,
    LedgerError,
    RecordedFetch,
    SourceLedger,
    canonical_url,
    comparison_bytes,
)

__all__ = [
    "IDENTITY_RULE",
    "SEC_EDGE_SCRIPT_RULE",
    "Content",
    "ContentKind",
    "CorrectionSummary",
    "EvidenceFamily",
    "EvidenceFamilyMember",
    "EvidenceFamilyMembership",
    "FamilyBackfill",
    "FetchObservation",
    "LedgerError",
    "RecordedFetch",
    "SourceDocument",
    "SourceLedger",
    "SourceVersionDetail",
    "SourceVersionSummary",
    "assign_missing",
    "canonical_url",
    "comparison_bytes",
    "correct_availability",
    "get_content",
    "get_evidence_family",
    "get_source_document",
    "get_version",
    "list_source_documents",
    "list_versions",
]
