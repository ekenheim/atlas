"""Creating, linking, closing and reading Issues, and choosing the next action."""

import uuid
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Self, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Connection, Engine, text

from atlas.audit import Actor, content_hash, record
from atlas.calls.record import signal_call

type IssueKind = Literal["question", "step", "read"]
type IssueStatus = Literal["active", "complete", "abandoned", "invalid"]
type EdgeKind = Literal["narrows", "requires"]
type NextReason = Literal["step_without_belief", "flagged_or_disputed", "priority"]

# Step statuses of a card that close their step Issue: the argument holds there, or the
# invalidation search found nothing.
SETTLED_STEP_STATUSES = frozenset({"supported", "nothing_found"})
# Words of an Issue's body that put it ahead of plain priority.
ATTENTION_WORDS = ("flagged", "disputed")


class IssueNotFound(Exception):
    pass


class IssueNotOpen(Exception):
    pass


class IssueCycle(Exception):
    pass


class UnknownProduct(Exception):
    pass


class UnknownCompany(Exception):
    pass


class UnknownLead(Exception):
    pass


class IssueCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    body: str = ""
    theme: str = Field(min_length=1)
    kind: IssueKind = "read"
    priority: int = 0
    company_ids: list[uuid.UUID] = Field(default_factory=list[uuid.UUID])
    produced_by: uuid.UUID | None = Field(default=None, description="the session that opened it")
    narrows: uuid.UUID | None = Field(default=None, description="the Issue it narrows (parent)")
    requires: list[uuid.UUID] = Field(
        default_factory=list[uuid.UUID], description="Issues to finish before this one"
    )
    lead_id: uuid.UUID | None = Field(
        default=None,
        description="the archive-signal lead a `question` escalates; it makes a call"
        " (atlas-beliefs ticket 19), dated now",
    )

    @model_validator(mode="after")
    def _lead_on_a_question(self) -> Self:
        if self.lead_id is not None and self.kind != "question":
            raise ValueError("only a question Issue escalates a lead")
        return self


class IssueEdgeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: EdgeKind
    parent_id: uuid.UUID


class IssueProductCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    belief_id: uuid.UUID | None = None
    fact_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _one(self) -> Self:
        if (self.belief_id is None) == (self.fact_id is None):
            raise ValueError("give exactly one of belief_id and fact_id")
        return self


class IssueProduct(BaseModel):
    belief_id: uuid.UUID | None
    fact_id: uuid.UUID | None
    actor: str
    created_at: datetime


class Issue(BaseModel):
    id: uuid.UUID
    title: str
    body: str
    theme: str
    kind: IssueKind
    priority: int
    status: IssueStatus
    produced_by: uuid.UUID | None
    company_ids: list[uuid.UUID]
    created_by: str
    created_at: datetime
    closed_at: datetime | None
    parent_id: uuid.UUID | None = Field(description="the Issue it narrows")
    parent_title: str | None
    requires: list[uuid.UUID] = Field(description="the Issues it requires")
    blocked: bool = Field(description="a required Issue is still active")
    open_children: int = Field(description="active Issues narrowing it")
    products: list[IssueProduct]


class NextIssue(BaseModel):
    issue: Issue | None = Field(description="None: nothing is active and unblocked")
    reason: NextReason | None


_COLUMNS = """
    i.id, i.title, i.body, i.theme, i.kind, i.priority, i.status, i.produced_by, i.company_ids,
    i.created_by, i.created_at, i.closed_at
"""


def _load(
    connection: Connection, where: str, params: Mapping[str, Any], *, tail: str = ""
) -> list[Issue]:
    rows = connection.execute(
        text(f"SELECT {_COLUMNS} FROM issue i WHERE {where} {tail}"),  # noqa: S608 (constants)
        params,
    ).all()
    ids = [row.id for row in rows]
    edges = connection.execute(
        text(
            "SELECT e.child_id, e.parent_id, e.kind, p.title, p.status FROM issue_edge e"
            " JOIN issue p ON p.id = e.parent_id WHERE e.child_id = ANY(:ids)"
            " ORDER BY e.created_at, e.parent_id"
        ),
        {"ids": ids},
    ).all()
    children = {
        row[0]: row[1]
        for row in connection.execute(
            text(
                "SELECT e.parent_id, count(*) FROM issue_edge e JOIN issue c ON c.id = e.child_id"
                " WHERE e.kind = 'narrows' AND c.status = 'active' AND e.parent_id = ANY(:ids)"
                " GROUP BY e.parent_id"
            ),
            {"ids": ids},
        )
    }
    products = connection.execute(
        text(
            "SELECT issue_id, belief_id, fact_id, actor, created_at FROM issue_product"
            " WHERE issue_id = ANY(:ids) ORDER BY created_at, id"
        ),
        {"ids": ids},
    ).all()
    issues: list[Issue] = []
    for row in rows:
        mine = [edge for edge in edges if edge.child_id == row.id]
        narrows = next((edge for edge in mine if edge.kind == "narrows"), None)
        requires = [edge for edge in mine if edge.kind == "requires"]
        issues.append(
            Issue(
                id=row.id,
                title=row.title,
                body=row.body,
                theme=row.theme,
                kind=row.kind,
                priority=row.priority,
                status=row.status,
                produced_by=row.produced_by,
                company_ids=list(row.company_ids),
                created_by=row.created_by,
                created_at=row.created_at,
                closed_at=row.closed_at,
                parent_id=None if narrows is None else narrows.parent_id,
                parent_title=None if narrows is None else narrows.title,
                requires=[edge.parent_id for edge in requires],
                blocked=any(edge.status == "active" for edge in requires),
                open_children=int(children.get(row.id, 0)),
                products=[
                    IssueProduct(
                        belief_id=product.belief_id,
                        fact_id=product.fact_id,
                        actor=product.actor,
                        created_at=product.created_at,
                    )
                    for product in products
                    if product.issue_id == row.id
                ],
            )
        )
    return issues


def get_issue(connection: Connection, issue_id: uuid.UUID) -> Issue | None:
    found = _load(connection, "i.id = :id", {"id": issue_id})
    return found[0] if found else None


def list_issues(
    connection: Connection,
    *,
    theme: str | None = None,
    status: IssueStatus | None = None,
    limit: int,
    offset: int,
) -> tuple[list[Issue], int]:
    """Oldest first within a theme."""
    params: dict[str, Any] = {"theme": theme, "status": status, "limit": limit, "offset": offset}
    where = (
        "(CAST(:theme AS text) IS NULL OR i.theme = :theme)"
        " AND (CAST(:status AS text) IS NULL OR i.status = :status)"
    )
    total = connection.execute(
        text(f"SELECT count(*) FROM issue i WHERE {where}"),  # noqa: S608 (constants)
        params,
    ).scalar_one()
    return (
        _load(
            connection,
            where,
            params,
            tail="ORDER BY i.created_at, i.id LIMIT :limit OFFSET :offset",
        ),
        total,
    )


def next_issue(connection: Connection, theme: str) -> NextIssue:
    """The next action: among the theme's active Issues that are not blocked by an active
    `requires` and have no active Issue narrowing them (their work is in those), a `step`
    Issue no Belief was produced for first, then one whose body says it is flagged or
    disputed, then by priority (high first), then oldest."""
    candidates = [
        issue
        for issue in _load(connection, "i.theme = :theme AND i.status = 'active'", {"theme": theme})
        if not issue.blocked and issue.open_children == 0
    ]

    def tier(issue: Issue) -> int:
        if issue.kind == "step" and not any(p.belief_id for p in issue.products):
            return 0
        if any(word in issue.body.lower() for word in ATTENTION_WORDS):
            return 1
        return 2

    if not candidates:
        return NextIssue(issue=None, reason=None)
    best = min(candidates, key=lambda i: (tier(i), -i.priority, i.created_at, str(i.id)))
    reason: tuple[NextReason, NextReason, NextReason] = (
        "step_without_belief",
        "flagged_or_disputed",
        "priority",
    )
    return NextIssue(issue=best, reason=reason[tier(best)])


def _has_ancestor(connection: Connection, start: uuid.UUID, target: uuid.UUID) -> bool:
    """True when `target` is `start` or reachable from it going child to parent."""
    return bool(
        connection.execute(
            text(
                "WITH RECURSIVE up(id) AS (SELECT CAST(:start AS uuid)"
                " UNION SELECT e.parent_id FROM issue_edge e JOIN up ON e.child_id = up.id)"
                " SELECT EXISTS (SELECT 1 FROM up WHERE id = :target)"
            ),
            {"start": start, "target": target},
        ).scalar_one()
    )


def _insert_edge(
    connection: Connection, actor: Actor, child: uuid.UUID, parent: uuid.UUID, kind: EdgeKind
) -> None:
    exists = connection.execute(
        text("SELECT count(*) FROM issue WHERE id = ANY(:ids)"), {"ids": [child, parent]}
    ).scalar_one()
    if exists != len({child, parent}):
        raise IssueNotFound(str(parent))
    if _has_ancestor(connection, parent, child):
        raise IssueCycle(f"{kind}: {parent} already depends on {child}")
    connection.execute(
        text(
            "INSERT INTO issue_edge (child_id, parent_id, kind, actor)"
            " VALUES (:child, :parent, :kind, :actor) ON CONFLICT DO NOTHING"
        ),
        {"child": child, "parent": parent, "kind": kind, "actor": actor.name},
    )
    record(
        connection,
        actor,
        "issue.edge_added",
        entity_type="issue",
        entity_id=str(child),
        new_hash=content_hash({"kind": kind, "parent_id": str(parent)}),
    )


def _insert_issue(
    connection: Connection,
    actor: Actor,
    request: IssueCreate,
    themes_config: Path | None = None,
) -> uuid.UUID:
    issue_id = uuid.uuid4()
    if request.lead_id is not None and (
        connection.execute(
            text("SELECT 1 FROM archive_signal WHERE lead_id = :lead"), {"lead": request.lead_id}
        ).one_or_none()
        is None
    ):
        raise UnknownLead("the lead is not an archive-signal lead")
    if request.company_ids:
        known = connection.execute(
            text("SELECT count(*) FROM company WHERE id = ANY(:ids)"),
            {"ids": list(set(request.company_ids))},
        ).scalar_one()
        if known != len(set(request.company_ids)):
            raise UnknownCompany("a company is not in the universe")
    created_at: datetime = connection.execute(
        text(
            "INSERT INTO issue (id, title, body, theme, kind, priority, produced_by, company_ids,"
            " created_by, lead_id) VALUES (:id, :title, :body, :theme, :kind, :priority,"
            " :produced_by, :companies, :actor, :lead) RETURNING created_at"
        ),
        {
            "id": issue_id,
            "title": request.title,
            "body": request.body,
            "theme": request.theme,
            "kind": request.kind,
            "priority": request.priority,
            "produced_by": request.produced_by,
            "companies": list(request.company_ids),
            "actor": actor.name,
            "lead": request.lead_id,
        },
    ).scalar_one()
    if request.lead_id is not None:
        # The prospective record (ticket 19): escalating a signal is a call, dated now (the
        # session's as-of time is not used: a call is never back-dated).
        signal_call(
            connection,
            actor,
            issue_id=issue_id,
            lead_id=request.lead_id,
            theme=request.theme,
            made_at=created_at,
            themes_config=themes_config,
        )
    record(
        connection,
        actor,
        "issue.created",
        entity_type="issue",
        entity_id=str(issue_id),
        new_hash=content_hash(request.model_dump(mode="json")),
    )
    if request.narrows is not None:
        _insert_edge(connection, actor, issue_id, request.narrows, "narrows")
    for required in request.requires:
        _insert_edge(connection, actor, issue_id, required, "requires")
    return issue_id


class Issues:
    def __init__(self, engine: Engine, actor: Actor, themes_config: Path | None = None) -> None:
        self._engine = engine
        self._actor = actor
        self._themes_config = themes_config

    def create(self, request: IssueCreate) -> Issue:
        with self._engine.begin() as connection:
            issue_id = _insert_issue(connection, self._actor, request, self._themes_config)
            issue = get_issue(connection, issue_id)
        assert issue is not None
        return issue

    def add_edge(self, issue_id: uuid.UUID, request: IssueEdgeCreate) -> Issue:
        with self._engine.begin() as connection:
            _insert_edge(connection, self._actor, issue_id, request.parent_id, request.kind)
            issue = get_issue(connection, issue_id)
        assert issue is not None
        return issue

    def _close(self, issue_id: uuid.UUID, status: Literal["complete", "abandoned"]) -> Issue:
        with self._engine.begin() as connection:
            row = connection.execute(
                text("SELECT status FROM issue WHERE id = :id FOR UPDATE"), {"id": issue_id}
            ).one_or_none()
            if row is None:
                raise IssueNotFound(str(issue_id))
            if row.status != "active":
                raise IssueNotOpen(f"the Issue is {row.status}")
            connection.execute(
                text("UPDATE issue SET status = :status, closed_at = now() WHERE id = :id"),
                {"id": issue_id, "status": status},
            )
            record(
                connection,
                self._actor,
                "issue.completed" if status == "complete" else "issue.abandoned",
                entity_type="issue",
                entity_id=str(issue_id),
                old_hash=content_hash({"status": "active"}),
                new_hash=content_hash({"status": status}),
            )
            issue = get_issue(connection, issue_id)
        assert issue is not None
        return issue

    def complete(self, issue_id: uuid.UUID) -> Issue:
        return self._close(issue_id, "complete")

    def abandon(self, issue_id: uuid.UUID) -> Issue:
        return self._close(issue_id, "abandoned")

    def produced(self, issue_id: uuid.UUID, request: IssueProductCreate) -> Issue:
        with self._engine.begin() as connection:
            if (
                connection.execute(
                    text("SELECT 1 FROM issue WHERE id = :id"), {"id": issue_id}
                ).one_or_none()
                is None
            ):
                raise IssueNotFound(str(issue_id))
            if request.fact_id is not None and (
                connection.execute(
                    text("SELECT 1 FROM fact WHERE assertion_id = :id"), {"id": request.fact_id}
                ).one_or_none()
                is None
            ):
                raise UnknownProduct("no such Fact")
            connection.execute(
                text(
                    "INSERT INTO issue_product (id, issue_id, belief_id, fact_id, actor)"
                    " VALUES (:id, :issue, :belief, :fact, :actor)"
                ),
                {
                    "id": uuid.uuid4(),
                    "issue": issue_id,
                    "belief": request.belief_id,
                    "fact": request.fact_id,
                    "actor": self._actor.name,
                },
            )
            record(
                connection,
                self._actor,
                "issue.product_recorded",
                entity_type="issue",
                entity_id=str(issue_id),
                new_hash=content_hash(request.model_dump(mode="json")),
            )
            issue = get_issue(connection, issue_id)
        assert issue is not None
        return issue


def _strings(value: object) -> list[str]:
    found: list[str] = []
    if isinstance(value, list):
        for item in cast("list[object]", value):
            if isinstance(item, str) and item.strip():
                found.append(item.strip())
    return found


def create_session_issues(
    connection: Connection,
    actor: Actor,
    *,
    session_id: uuid.UUID,
    question: str,
    theme: str,
    seed_company_ids: list[uuid.UUID],
    card: Mapping[str, Any] | None,
) -> list[uuid.UUID]:
    """In the transaction that closes a session: the root `question` Issue narrowed into one
    `step` Issue per argument step of its card (settled ones, `supported` or `nothing_found`,
    already complete), and a `question` Issue for each open question and a `read` Issue for each
    company the card lists as not read, under the root. Returns the root's ID and the others."""

    def make(title: str, kind: IssueKind, **fields: Any) -> uuid.UUID:
        return _insert_issue(
            connection,
            actor,
            IssueCreate(title=title, kind=kind, theme=theme, produced_by=session_id, **fields),
        )

    root = make(question, "question", company_ids=seed_company_ids)
    created = [root]
    if card is None:
        return created
    steps: list[Any] = card["steps"] if isinstance(card.get("steps"), list) else []
    for step in steps:
        if not isinstance(step, dict):
            continue
        key = str(step.get("step") or "").strip()  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
        if not key:
            continue
        status = str(step.get("status") or "unknown")  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
        title = str(step.get("title") or key.replace("_", " "))  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
        issue = make(
            f"{title}: {question}",
            "step",
            body=f"{key}: {status}",
            priority=2 if status == "disputed" else 1 if status in ("unknown", "found") else 0,
            company_ids=seed_company_ids,
            narrows=root,
        )
        if status in SETTLED_STEP_STATUSES:
            connection.execute(
                text("UPDATE issue SET status = 'complete', closed_at = now() WHERE id = :id"),
                {"id": issue},
            )
        created.append(issue)
    for open_question in _strings(card.get("open_questions")):
        created.append(make(open_question, "question", narrows=root))
    unread: list[Any] = card["not_read"] if isinstance(card.get("not_read"), list) else []
    for entry in unread:
        company_id: uuid.UUID | None = None
        name = ""
        if isinstance(entry, dict):
            name = str(entry.get("company_name") or "").strip()  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
            try:
                company_id = uuid.UUID(str(entry.get("company_id")))  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
            except ValueError:
                company_id = None
            if company_id is not None and (
                connection.execute(
                    text("SELECT 1 FROM company WHERE id = :id"), {"id": company_id}
                ).one_or_none()
                is None
            ):
                company_id = None
        elif isinstance(entry, str):
            name = entry.strip()
        if not name:
            continue
        created.append(
            make(
                f"Read {name}",
                "read",
                narrows=root,
                company_ids=[company_id] if company_id else [],
            )
        )
    return created
