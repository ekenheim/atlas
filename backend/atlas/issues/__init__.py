"""Issues (beliefs ticket 04): the research frontier.

An Issue is a research question still to answer: a `question` narrows into `step` Issues (one
per argument step), a step into what it needs (`read`); `requires` orders them. Edges run from
the child to the parent and may not form a cycle. `GET /issues/next` chooses the next action by
rule (`atlas.issues.service.next_issue`). A Claude session's close creates the Issues of its
card. Every write is audited (`issue.created|edge_added|completed|abandoned|product_recorded`).
"""

from atlas.issues.service import (
    Issue,
    IssueCreate,
    IssueCycle,
    IssueEdgeCreate,
    IssueNotFound,
    IssueNotOpen,
    IssueProduct,
    IssueProductCreate,
    Issues,
    NextIssue,
    UnknownCompany,
    UnknownProduct,
    create_session_issues,
    get_issue,
    list_issues,
    next_issue,
)

__all__ = [
    "Issue",
    "IssueCreate",
    "IssueCycle",
    "IssueEdgeCreate",
    "IssueNotFound",
    "IssueNotOpen",
    "IssueProduct",
    "IssueProductCreate",
    "Issues",
    "NextIssue",
    "UnknownCompany",
    "UnknownProduct",
    "create_session_issues",
    "get_issue",
    "list_issues",
    "next_issue",
]
