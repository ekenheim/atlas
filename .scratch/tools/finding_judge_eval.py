"""Measure the finding judge on labelled findings or argument statements (bottleneck-argument
ticket 04; pilot 0.5.3 fix T2).

Two label sets, neither in git (some quotes are from licensed call transcripts; never commit
them or what this prints):

- the default: `.scratch/live-runs/pilot-0.4.6/labeled-findings.json`, the 0.4.6 verdict's
  labelled findings (`trust_gate` `pass` or `fail`: 18, 9 failing), each Claim's metadata from
  its investigation's Evidence tray. Target: caught >= 8 of 9, flagged <= 1 of 9.
- `--argument`: `.scratch/live-runs/pilot-0.5.3-arg/labeled-statements.json`, written by
  `.scratch/tools/argument_statement_labels.py`: the 130 statements of 0.5.3's four argument
  cards (17 failing), each with its cited Facts' metadata (status, period, quantity, the
  Reader's statement) and quotes, sent as the argument plan's Editor task sends them. Target:
  caught >= 10 of 17, flagged <= 10 of 113, before the rewrite.

It asks the `finding_judge` role (`atlas.roles.finding_judge`, its committed prompt) about each,
one call per statement (one vote), exactly as the Editor's task asks it: the research question,
the statement and limitations, its cited Claims or Facts by short reference and their exact
quotes as low-trust retrieved data. Each answer's bases are then checked by code as the
Editor's task checks them (`atlas.investigations.meaning.checked`): a `supported` answer with a
clause whose basis isn't in its quote counts as `misstated`.

It prints, per statement, the label and the verdict, and the score: how many `fail`
statements the judge calls `misstated` (caught) and how many `pass` ones (flagged), after the
basis check and as the judge answered, and how many answers the basis check turned.

Live, it calls the configured LiteLLM (`ATLAS_LITELLM_URL`, `ATLAS_LITELLM_API_KEY`,
`ATLAS_LLM_ROLE_MODEL`, from the environment or the repo's `.env`), so it spends the owner's
MiniMax quota: run it only with the lead's go-ahead. It stops at `--max-calls` chat
completions (a repair of an invalid answer counts): by default and at most 40 for the
findings, 300 with `--argument` (130 statements and their repairs). `--dry-run` builds and
prints the requests without calling anything.

    uv run python .scratch/tools/finding_judge_eval.py [--argument] [--dry-run]
        [--max-calls N] [--labels PATH] [--only 1,2,...] [--out DIR]

The report (every request, answer and the score) goes to
`.scratch/live-runs/<stamp>-finding-judge-eval/` (gitignored).
"""

import argparse
import json
import os
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx2

from atlas.investigations.meaning import checked, verify_bases
from atlas.roles.caller import _validate  # pyright: ignore[reportPrivateUsage]
from atlas.roles.contract import DIRECTIVES, REPAIR_DIRECTIVE, QuotedText
from atlas.roles.finding_judge import (
    FINDING_JUDGE,
    FINDING_JUDGE_VERSION,
    FindingJudgement,
    FindingJudgeRequest,
    JudgedClaim,
    JudgedFinding,
)
from atlas.settings import Settings

REPO = Path(__file__).resolve().parents[2]
PILOT = REPO / ".scratch" / "live-runs" / "pilot-0.4.6"
ARGUMENT_LABELS = REPO / ".scratch" / "live-runs" / "pilot-0.5.3-arg" / "labeled-statements.json"
CALL_CEILING = 40
ARGUMENT_CALL_CEILING = 300
ATTEMPTS = 2  # an answer, then one repair (as the role caller does)


def env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip().removeprefix("export ").strip()] = value.strip().strip("'\"")
    return values


def setting(name: str, dotenv: dict[str, str]) -> str | None:
    return os.environ.get(name) or dotenv.get(name) or None


def evidence(
    pilot: Path, investigation: int
) -> tuple[str, dict[str, dict[str, Any]], dict[str, str]]:
    """The investigation's question, its Evidence tray by claim ID and its documents' titles."""
    found = json.loads((pilot / f"inv-{investigation}" / "investigation.json").read_text("utf-8"))
    items = {str(item["claim_id"]): item for item in found.get("evidence") or []}
    titles = {
        str(doc["source_version_id"]): str(doc.get("title") or "")
        for doc in found.get("documents") or []
    }
    return str(found["question"]), items, titles


def build(
    labelled: dict[str, Any],
    question: str,
    items: dict[str, dict[str, Any]],
    titles: dict[str, str],
) -> tuple[FindingJudgeRequest, list[QuotedText]]:
    """A 0.4.6 labelled finding's request, its Claims' metadata from the Evidence tray."""
    refs: list[str] = []
    claims: list[JudgedClaim] = []
    quotes: list[QuotedText] = []
    for index, cited in enumerate(labelled["claims"], start=1):
        ref = f"c{index}"
        item = items.get(str(cited["claim_id"]), {})
        version = str(item.get("source_version_id") or "")
        refs.append(ref)
        claims.append(
            JudgedClaim(
                ref=ref,
                subject=str(item.get("subject_name") or "unknown"),
                predicate=str(item.get("predicate") or "unknown"),
                object=str(item.get("object_name") or item.get("object_text") or ""),
                epistemic_type=str(item.get("epistemic_type") or "company_claim"),
                source_title=titles.get(version, ""),
            )
        )
        quotes.append(
            QuotedText(id=ref, source=version or str(cited["claim_id"]), text=cited["quote"])
        )
    request = FindingJudgeRequest(
        research_question=question,
        finding=JudgedFinding(
            statement=labelled["statement"],
            limitations=list(labelled.get("limitations") or []),
            claim_refs=refs,
        ),
        claims=claims,
    )
    return request, quotes


def build_argument(labelled: dict[str, Any]) -> tuple[FindingJudgeRequest, list[QuotedText]]:
    """An argument statement's request (`argument_statement_labels.py`'s entry), its Facts sent
    as the argument plan's Editor task sends them (`atlas.investigations.tasks._judged_fact`):
    predicate `fact`, no object, the Reader's status, period, quantity and statement. The
    references are the statement's own (`c1`... in its Facts' order, counterevidence last)."""
    refs: list[str] = []
    claims: list[JudgedClaim] = []
    quotes: list[QuotedText] = []
    for index, fact in enumerate(labelled["facts"], start=1):
        ref = f"c{index}"
        refs.append(ref)
        claims.append(
            JudgedClaim(
                ref=ref,
                subject=str(fact.get("company_name") or "unknown"),
                predicate="fact",
                object="",
                epistemic_type=(
                    "third_party_report"
                    if fact.get("status") == "reported_by_third_party"
                    else "company_claim"
                ),
                source_title=str(fact.get("source_title") or ""),
                status=fact.get("status") or None,
                period=fact.get("period") or None,
                quantity=fact.get("quantity") or None,
                reading=fact.get("statement") or None,
            )
        )
        quotes.append(
            QuotedText(
                id=ref,
                source=(
                    f"{fact.get('source_version_id')}#{fact.get('span_start')}"
                    f"-{fact.get('span_end')}"
                ),
                text=str(fact.get("quote") or ""),
            )
        )
    request = FindingJudgeRequest(
        research_question=str(labelled["question"]),
        finding=JudgedFinding(statement=labelled["statement"], limitations=[], claim_refs=refs),
        claims=claims,
    )
    return request, quotes


def labelled_rows(path: Path) -> list[dict[str, Any]]:
    """The labels file's entries labelled `pass` or `fail`, in order."""
    rows: list[dict[str, Any]] = json.loads(path.read_text("utf-8"))
    return [each for each in rows if each.get("trust_gate") in {"pass", "fail"}]


def requests(
    labelled: list[dict[str, Any]], *, argument: bool, pilot: Path
) -> list[tuple[FindingJudgeRequest, list[QuotedText]]]:
    """Each labelled entry's request and quotes."""
    if argument:
        return [build_argument(each) for each in labelled]
    contexts: dict[int, tuple[str, dict[str, dict[str, Any]], dict[str, str]]] = {}
    built: list[tuple[FindingJudgeRequest, list[QuotedText]]] = []
    for each in labelled:
        investigation = int(each["investigation"])
        if investigation not in contexts:
            contexts[investigation] = evidence(pilot, investigation)
        question, items, titles = contexts[investigation]
        built.append(build(each, question, items, titles))
    return built


class Budget:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.used = 0

    def take(self) -> bool:
        if self.used >= self.limit:
            return False
        self.used += 1
        return True


def judge(
    client: httpx2.Client,
    model: str,
    extra_body: dict[str, Any],
    request: FindingJudgeRequest,
    quotes: list[QuotedText],
    budget: Budget,
) -> tuple[FindingJudgement | None, list[dict[str, Any]], str | None]:
    """The role's answer (or None and why), and each attempt's raw content and tokens."""
    user = json.dumps(
        {
            "request": request.model_dump(mode="json"),
            "retrieved_data": [q.model_dump(mode="json") for q in quotes],
        },
        ensure_ascii=False,
    )
    messages: list[dict[str, str]] = [
        {"role": "system", "content": f"{DIRECTIVES}\n\n{FINDING_JUDGE.prompt.text}"},
        {"role": "user", "content": user},
    ]
    attempts: list[dict[str, Any]] = []
    for _ in range(ATTEMPTS):
        if not budget.take():
            return None, attempts, f"call cap reached ({budget.limit})"
        body: dict[str, Any] = {
            **extra_body,
            "model": model,
            "messages": messages,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": FINDING_JUDGE.name,
                    "strict": True,
                    "schema": FINDING_JUDGE.response_schema(),
                },
            },
            "max_tokens": FINDING_JUDGE.max_output_tokens,
            "metadata": {"run_id": str(uuid.uuid4()), "role": FINDING_JUDGE.name},
        }
        started = time.monotonic()
        response = client.post("/chat/completions", json=body)
        if not response.is_success:
            return None, attempts, f"HTTP {response.status_code}: {response.text[:300]}"
        completion = response.json()
        content = completion["choices"][0]["message"].get("content") or ""
        attempts.append(
            {
                "content": content,
                "usage": completion.get("usage"),
                "seconds": round(time.monotonic() - started, 1),
            }
        )
        output, errors, _ = _validate(FindingJudgement, content)
        if output is not None:
            return output, attempts, None
        messages = [
            *messages,
            {"role": "assistant", "content": content},
            {"role": "user", "content": f"{REPAIR_DIRECTIVE}\n\n{json.dumps(errors)}"},
        ]
    return None, attempts, "quarantined: no valid answer after a repair"


def score(rows: list[dict[str, Any]], *, argument: bool, dry_run: bool) -> dict[str, Any]:
    """Caught and flagged, after the basis check (`verdict`) and as answered (`raw_verdict`)."""
    judged = [r for r in rows if r["verdict"] is not None]
    fails = [r for r in rows if r["label"] == "fail"]
    passes = [r for r in rows if r["label"] == "pass"]
    caught = sum(1 for r in fails if r["verdict"] == "misstated")
    flagged = sum(1 for r in passes if r["verdict"] == "misstated")
    if argument:
        target = caught >= 10 and flagged <= 10
    else:
        target = caught >= len(fails) - 1 and flagged <= 1
    return {
        "judged": len(judged),
        "caught": caught,
        "misstated_labelled": len(fails),
        "flagged": flagged,
        "supported_labelled": len(passes),
        "caught_raw": sum(1 for r in fails if r.get("raw_verdict") == "misstated"),
        "flagged_raw": sum(1 for r in passes if r.get("raw_verdict") == "misstated"),
        "basis_unverified": sum(1 for r in rows if r.get("basis_turned")),
        "no_clauses": sum(1 for r in judged if r.get("clauses") == 0),
        "unjudged": len(rows) - len(judged),
        "target_met": not dry_run and len(judged) == len(rows) and target,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--argument", action="store_true", help="the argument statements")
    parser.add_argument("--labels", type=Path, default=None)
    parser.add_argument("--max-calls", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--only", default="", help="comma-separated 1-based labelled indexes")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    ceiling = ARGUMENT_CALL_CEILING if args.argument else CALL_CEILING
    limit = min(args.max_calls or ceiling, ceiling)
    labels: Path = args.labels or (
        ARGUMENT_LABELS if args.argument else PILOT / "labeled-findings.json"
    )
    pilot = labels.resolve().parent
    labelled = labelled_rows(labels)
    if args.only:
        keep = {int(n) for n in args.only.split(",") if n.strip()}
        labelled = [each for n, each in enumerate(labelled, start=1) if n in keep]
    kind = "argument statements" if args.argument else "findings"
    print(f"{len(labelled)} labelled {kind}; judge {FINDING_JUDGE_VERSION}; cap {limit} calls")

    dotenv = env_file(REPO / ".env")
    url = setting("ATLAS_LITELLM_URL", dotenv)
    key = setting("ATLAS_LITELLM_API_KEY", dotenv)
    model = setting("ATLAS_LLM_ROLE_MODEL", dotenv) or str(
        Settings.model_fields["llm_role_model"].default
    )
    extra_body: dict[str, Any] = {"thinking": {"type": "disabled"}}
    if raw := setting("ATLAS_LLM_ROLE_EXTRA_BODY", dotenv):
        extra_body = json.loads(raw)
    if not args.dry_run and (not url or not key):
        print("set ATLAS_LITELLM_URL and ATLAS_LITELLM_API_KEY (environment or .env)")
        return 2

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = args.out or REPO / ".scratch" / "live-runs" / f"{stamp}-finding-judge-eval"
    out.mkdir(parents=True, exist_ok=True)
    budget = Budget(limit)
    built = requests(labelled, argument=args.argument, pilot=pilot)
    rows: list[dict[str, Any]] = []
    client = httpx2.Client(
        base_url=(url or "http://dry-run.invalid").rstrip("/"),
        headers={"Authorization": f"Bearer {key or ''}"},
        timeout=240.0,
    )
    try:
        for number, (each, (request, quotes)) in enumerate(
            zip(labelled, built, strict=True), start=1
        ):
            where = (
                f"inv-{each['investigation']} {each['step']} {each['index']}"
                if args.argument
                else f"inv-{each['investigation']}"
            )
            row: dict[str, Any] = {
                "n": number,
                "investigation": each["investigation"],
                "label": each["trust_gate"],
                "statement": each["statement"],
                "misstatement": each.get("misstatement"),
                "request": request.model_dump(mode="json"),
            }
            if args.argument:
                row |= {"step": each["step"], "index": each["index"]}
            else:
                # A Claim the Evidence tray doesn't hold is sent with subject "unknown".
                row["claims_without_evidence_metadata"] = [
                    cited["claim_id"]
                    for cited, claim in zip(each["claims"], request.claims, strict=True)
                    if claim.subject == "unknown"
                ]
            if args.dry_run:
                row["verdict"] = None
                rows.append(row)
                print(f"#{number:>3} {where} {each['trust_gate']:<4} {len(quotes)} quotes")
                continue
            answer, attempts, failure = judge(client, model, extra_body, request, quotes, budget)
            row["attempts"] = attempts
            row["failure"] = failure
            row["answer"] = answer.model_dump(mode="json") if answer is not None else None
            row["raw_verdict"] = answer.verdict if answer is not None else None
            effective = checked(answer, quotes) if answer is not None else None
            row["verdict"] = effective.verdict if effective is not None else None
            row["basis_turned"] = (
                answer is not None and effective is not None and effective is not answer
            )
            row["unverified"] = verify_bases(answer, quotes) if answer is not None else []
            row["clauses"] = len(answer.clauses) if answer is not None else None
            rows.append(row)
            mark = {
                ("fail", "misstated"): "caught",
                ("fail", "supported"): "MISSED",
                ("pass", "supported"): "ok",
                ("pass", "misstated"): "FLAGGED",
            }.get((each["trust_gate"], row["verdict"]), "failed")
            kinds = ",".join(effective.kinds) if effective is not None else ""
            turned = " (basis unverified)" if row["basis_turned"] else ""
            print(
                f"#{number:>3} {where} {each['trust_gate']:<4} -> "
                f"{row['verdict'] or failure} [{mark}]{turned} {kinds}"
            )
            if failure and failure.startswith("call cap"):
                print("call cap reached: stopping")
                break
    finally:
        client.close()

    summary = {
        "judge": FINDING_JUDGE_VERSION,
        "prompt_sha256": FINDING_JUDGE.prompt.sha256,
        "model": model,
        "labels": str(labels),
        "argument": args.argument,
        "calls": budget.used,
        "requests": len(built),
        **score(rows, argument=args.argument, dry_run=args.dry_run),
    }
    (out / "result.json").write_text(
        json.dumps({"summary": summary, "findings": rows}, indent=1, ensure_ascii=False), "utf-8"
    )
    if args.dry_run:
        print(f"{len(built)} requests built (dry run)")
    else:
        print(
            f"caught {summary['caught']} of {summary['misstated_labelled']} misstated; flagged"
            f" {summary['flagged']} of {summary['supported_labelled']} supported (as answered:"
            f" caught {summary['caught_raw']}, flagged {summary['flagged_raw']}); basis"
            f" unverified {summary['basis_unverified']}; no clauses {summary['no_clauses']};"
            f" {budget.used} calls; unjudged {summary['unjudged']}"
        )
    print(f"report: {out / 'result.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
