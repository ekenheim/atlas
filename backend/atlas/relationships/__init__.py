"""Relationships: typed, directed, layer-tagged edges backed by Assertions, and their review.

`checks` holds the deterministic checks (verbatim span, Tier A, directional language) and
how they combine with the Reviewer's answer; `review` runs the `review_relationships` job
(eligibility, checks, Reviewer calls, outcomes); `service` links reviewed Assertions to their
edges and records the owner's approvals and rejections, audited; `reads` is the edge table,
one edge with its Evidence, and the exceptions queue.
"""

from atlas.relationships.checks import (
    DeterministicChecks,
    DirectionalLanguage,
    ReviewerAnswer,
    deterministic_checks,
    directional_language,
    review_outcome,
)
from atlas.relationships.handlers import register_relationship_handlers
from atlas.relationships.reads import (
    MachineReview,
    Relationship,
    RelationshipDetail,
    RelationshipEvidence,
    RelationshipState,
    SortKey,
    SortOrder,
    get_relationship,
    get_relationship_detail,
    list_relationships,
)
from atlas.relationships.review import (
    REVIEW_RELATIONSHIPS_KIND,
    REVIEWER_ACTOR,
    RelationshipReviewer,
    ReviewRelationshipsPayload,
)
from atlas.relationships.service import (
    InvalidTransition,
    OwnerReview,
    RelationshipNotFound,
    RelationshipRecorded,
    RelationshipRefused,
    Relationships,
)

__all__ = [
    "REVIEWER_ACTOR",
    "REVIEW_RELATIONSHIPS_KIND",
    "DeterministicChecks",
    "DirectionalLanguage",
    "InvalidTransition",
    "MachineReview",
    "OwnerReview",
    "Relationship",
    "RelationshipDetail",
    "RelationshipEvidence",
    "RelationshipNotFound",
    "RelationshipRecorded",
    "RelationshipRefused",
    "RelationshipReviewer",
    "RelationshipState",
    "Relationships",
    "ReviewRelationshipsPayload",
    "ReviewerAnswer",
    "SortKey",
    "SortOrder",
    "deterministic_checks",
    "directional_language",
    "get_relationship",
    "get_relationship_detail",
    "list_relationships",
    "register_relationship_handlers",
    "review_outcome",
]
