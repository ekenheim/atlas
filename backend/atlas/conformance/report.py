"""The conformance report: one per run, as `results.json` and `summary.md`.

Its two halves are the known answers (on the live bank, read-only) and the behaviours (on a
throwaway bank). The run fails (exit 1) when the known answers fail, a behaviour fails, the
run was aborted (a cap reached, the bank not prepared, the bank not deleted), or, with
`--strict`, while any behaviour is pending.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from atlas.conformance.behaviours import CheckResult
from atlas.conformance.known_answers import KnownAnswersReport, Recall

Mode = Literal["live", "rehearse"]


class Usage(BaseModel):
    """What the run spent, as the counting proxies (or the fake) saw it, against the caps."""

    retain_operations: int = 0
    retain_cap: int = 0
    llm_operations: int = 0  # Hindsight requests that make it call its LLM besides extraction
    llm_cap: int = 0
    refused: list[str] = Field(default_factory=list[str])  # requests a cap refused
    bank_llm_requests: dict[str, Any] | None = None  # the bank's own LLM request log, if read


class ConformanceReport(BaseModel):
    mode: Mode
    strict: bool
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    stack: dict[str, str] = Field(default_factory=dict[str, str])
    known_answers: KnownAnswersReport | None = None
    known_answers_error: str | None = None  # the half could not run (e.g. the file is invalid)
    behaviours: list[CheckResult] | None = None
    bank_id: str | None = None
    bank_deleted: bool | None = None
    aborted: str | None = None  # why the behaviours half stopped before its checks finished
    usage: Usage = Field(default_factory=Usage)

    def failures(self) -> list[str]:
        failed: list[str] = []
        if self.known_answers_error:
            failed.append(f"known answers: {self.known_answers_error}")
        elif self.known_answers is not None and self.known_answers.verdict == "failed":
            failed.append(f"known answers: {self.known_answers.reason}")
        if self.aborted:
            failed.append(f"behaviours aborted: {self.aborted}")
        if self.bank_deleted is False:
            failed.append(f"the throwaway bank {self.bank_id} was not deleted")
        failed += [
            f"check {c.number} ({c.id}): {c.reason}"
            for c in self.behaviours or []
            if c.verdict == "failed"
        ]
        return failed

    def pending(self) -> list[CheckResult]:
        return [c for c in self.behaviours or [] if c.verdict == "pending"]

    def exit_code(self, strict: bool | None = None) -> int:
        """0 when nothing failed (and, strict, nothing is pending); else 1."""
        strict = self.strict if strict is None else strict
        return 1 if self.failures() or (strict and self.pending()) else 0

    def write(self, directory: Path) -> None:
        self.finished_at = self.finished_at or datetime.now(UTC)
        directory.mkdir(parents=True, exist_ok=True)
        results = self.model_dump(mode="json") | {"exit_code": self.exit_code()}
        (directory / "results.json").write_text(
            json.dumps(results, indent=2) + "\n", encoding="utf-8"
        )
        (directory / "summary.md").write_text(self.summary(), encoding="utf-8")

    def summary(self) -> str:
        kind = {
            "live": "LIVE (the live bank; a throwaway bank on the real Hindsight)",
            "rehearse": "REHEARSAL (the recorded fakes on localhost; nothing was live)",
        }
        verdict = "FAILED" if self.exit_code() else "passed"
        lines = [
            f"# Memory conformance: {kind[self.mode]}",
            "",
            f"- started {self.started_at.isoformat()}, finished"
            f" {(self.finished_at or datetime.now(UTC)).isoformat()}",
            f"- verdict: **{verdict}**" + (" (strict: pending fails)" if self.strict else ""),
        ]
        for key, value in self.stack.items():
            lines.append(f"- {key}: `{value}`")
        for failure in self.failures():
            lines.append(f"- failure: {failure}")
        lines += self._known_answers_lines() + self._behaviour_lines()
        return "\n".join(lines) + "\n"

    def _known_answers_lines(self) -> list[str]:
        lines = ["", "## Known answers (the live bank, read-only)", ""]
        if self.known_answers_error:
            return [*lines, f"Not run: {self.known_answers_error}"]
        report = self.known_answers
        if report is None:
            return [*lines, "Not run (--only behaviours)."]
        lines += [
            f"Verdict **{report.verdict}**"
            + (f": {report.reason}" if report.reason else "")
            + f". Thresholds: recall at 10 >= {report.thresholds.recall_at_10}, at 50 >="
            f" {report.thresholds.recall_at_50}. {report.answers} answers,"
            f" {len(report.errors)} errors.",
            "",
            "| Group | Answers | Recall@10 | Recall@50 |",
            "|---|---|---|---|",
            _row("**overall**", report.overall),
        ]
        for title, groups in (
            ("question", report.by_question),
            ("hop", report.by_hop),
            ("test part", report.by_test_part),
        ):
            lines += [_row(f"{title}: {name}", recall) for name, recall in groups.items()]
        if report.errors:
            lines += ["", "Errors (not misses):", ""]
            lines += [f"- `{e.id}`: {e.error}" for e in report.errors]
        if report.anchors_found:
            lines += ["", "Anchors found from the sentence (write them into the file):", ""]
            lines += [f"- `{i}`: `{a}`" for i, a in report.anchors_found.items()]
        lines += ["", "| Answer | Question | Hop | Test part | Section | In Memory | Rank |"]
        lines.append("|---|---|---|---|---|---|---|")
        for outcome in report.outcomes:
            a = outcome.answer
            lines.append(
                f"| {a.id} | {a.question} | {a.hop} | {a.test} | {a.section} |"
                f" {a.retain_state or 'no'} | {outcome.rank if outcome.rank else 'absent'} |"
            )
        return lines

    def _behaviour_lines(self) -> list[str]:
        lines = ["", "## Behaviours (a throwaway bank)", ""]
        if self.behaviours is None and not self.aborted:
            return [*lines, "Not run (--only known-answers)."]
        usage = self.usage
        lines += [
            f"Bank `{self.bank_id}`, deleted: {self.bank_deleted}. Retain operations"
            f" {usage.retain_operations}/{usage.retain_cap}; LLM-making requests (reflect,"
            f" refresh, consolidate) {usage.llm_operations}/{usage.llm_cap}."
            + (f" Refused by a cap: {', '.join(usage.refused)}." if usage.refused else ""),
            "",
            "| # | Check | Ticket | Verdict | Reason |",
            "|---|---|---|---|---|",
        ]
        for check in self.behaviours or []:
            reason = (check.reason or "").replace("|", "\\|")
            lines.append(
                f"| {check.number} | {check.id} | {check.ticket or '-'} |"
                f" **{check.verdict}** | {reason[:200]} |"
            )
        for check in self.behaviours or []:
            lines += [
                "",
                f"### {check.number}. {check.id}",
                "",
                f"- Promise: {check.promise}",
                f"- Tested against: {check.source}",
                f"- Verdict: **{check.verdict}**" + (f" ({check.reason})" if check.reason else ""),
            ]
            if check.evidence:
                lines += ["", "```json", json.dumps(check.evidence, indent=2), "```"]
        return lines


def _row(name: str, recall: Recall) -> str:
    def share(value: float | None) -> str:
        return "-" if value is None else f"{value:.2f}"

    return f"| {name} | {recall.answers} | {share(recall.at_10)} | {share(recall.at_50)} |"
