"""The conclusions bank as a known answer (beliefs ticket 12): it exists, and carries the
template version the repository holds.

Read-only through `GET /api/v1/memory/health` (`beliefs.bank` and `beliefs.template_version`,
the version last applied to that bank): no LLM call, no write.
"""

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from atlas.bank_template import BankTemplate, InvalidTemplate
from atlas.conformance.api import AtlasApi, AtlasApiError


class BeliefsBankReport(BaseModel):
    verdict: Literal["passed", "failed"]
    reason: str | None
    bank: str | None
    expected_template_version: str | None
    applied_template_version: str | None


def check_beliefs_bank(api: AtlasApi, template_path: Path) -> BeliefsBankReport:
    """Whether the conclusions bank's template (its file's version) is the one applied."""
    try:
        expected = BankTemplate.load(template_path).template_version
    except InvalidTemplate as error:
        return BeliefsBankReport(
            verdict="failed",
            reason=f"the beliefs template cannot be read: {error}",
            bank=None,
            expected_template_version=None,
            applied_template_version=None,
        )
    try:
        health: dict[str, Any] = api.get("/memory/health")
    except AtlasApiError as error:
        return BeliefsBankReport(
            verdict="failed",
            reason=f"memory health unavailable: {error}",
            bank=None,
            expected_template_version=expected,
            applied_template_version=None,
        )
    beliefs: dict[str, Any] = health.get("beliefs") or {}
    bank: str | None = beliefs.get("bank")
    applied: str | None = beliefs.get("template_version")
    reason = None
    if not bank:
        reason = "memory health names no conclusions bank"
    elif applied is None:
        reason = f"no template was applied to the conclusions bank {bank}"
    elif applied != expected:
        reason = f"the bank {bank} has template {applied}; the repository holds {expected}"
    return BeliefsBankReport(
        verdict="failed" if reason else "passed",
        reason=reason,
        bank=bank,
        expected_template_version=expected,
        applied_template_version=applied,
    )
