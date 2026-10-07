"""Measure the finding judge on the pilot verdict's labelled findings (bottleneck-argument
ticket 04).

Reads `.scratch/live-runs/pilot-0.4.6/labeled-findings.json` (not in git: some quotes are
from licensed call transcripts; never commit it or what this prints), takes the findings the
reviewers labelled (`trust_gate` `pass` or `fail`: 18 in the 0.4.6 verdict, 9 failing), and
asks the `finding_judge` role (`atlas.roles.finding_judge`, its committed prompt) about each,
one call per finding, exactly as the Editor's task asks it: the research question, the
finding's statement and limitations, its cited Claims (metadata from the investigation's
Evidence tray) and their exact quotes as low-trust retrieved data.

It prints, per finding, the label and the verdict, and the score: how many `fail` findings the
judge calls `misstated` (caught) and how many `pass` findings it calls `misstated` (flagged).
Target (the ticket): caught >= 8 of 9, flagged <= 1 of 9.

Live, it calls the configured LiteLLM (`ATLAS_LITELLM_URL`, `ATLAS_LITELLM_API_KEY`,
`ATLAS_LLM_ROLE_MODEL`, from the environment or the repo's `.env`), so it spends the owner's
MiniMax quota: run it only with the lead's go-ahead. It stops at `--max-calls` chat
completions (default and ceiling 40; a repair of an invalid answer counts). `--dry-run` builds
and prints the requests without calling anything.

    uv run python .scratch/tools/finding_judge_eval.py [--dry-run] [--max-calls 40]
        [--labels PATH] [--only 1,2,...] [--out DIR]

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
CALL_CEILING = 40
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--labels", type=Path, default=PILOT / "labeled-findings.json")
    parser.add_argument("--max-calls", type=int, default=CALL_CEILING)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--only", default="", help="comma-separated 1-based labelled indexes")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    limit = min(args.max_calls, CALL_CEILING)
    pilot = args.labels.resolve().parent
    labelled = [
        each
        for each in json.loads(args.labels.read_text("utf-8"))
        if each.get("trust_gate") in {"pass", "fail"}
    ]
    if args.only:
        keep = {int(n) for n in args.only.split(",") if n.strip()}
        labelled = [each for n, each in enumerate(labelled, start=1) if n in keep]
    print(f"{len(labelled)} labelled findings; judge {FINDING_JUDGE_VERSION}; cap {limit} calls")

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
    rows: list[dict[str, Any]] = []
    contexts: dict[int, tuple[str, dict[str, dict[str, Any]], dict[str, str]]] = {}
    client = httpx2.Client(
        base_url=(url or "http://dry-run.invalid").rstrip("/"),
        headers={"Authorization": f"Bearer {key or ''}"},
        timeout=240.0,
    )
    try:
        for number, each in enumerate(labelled, start=1):
            investigation = int(each["investigation"])
            if investigation not in contexts:
                contexts[investigation] = evidence(pilot, investigation)
            question, items, titles = contexts[investigation]
            request, quotes = build(each, question, items, titles)
            missing = [c["claim_id"] for c in each["claims"] if str(c["claim_id"]) not in items]
            row: dict[str, Any] = {
                "n": number,
                "investigation": investigation,
                "label": each["trust_gate"],
                "statement": each["statement"],
                "claims_without_evidence_metadata": missing,
                "request": request.model_dump(mode="json"),
            }
            if args.dry_run:
                row["verdict"] = None
                rows.append(row)
                print(
                    f"#{number:>2} inv-{investigation} {each['trust_gate']:<4} {len(quotes)} quotes"
                    f"{' (metadata missing: ' + str(len(missing)) + ')' if missing else ''}"
                )
                continue
            answer, attempts, failure = judge(client, model, extra_body, request, quotes, budget)
            row["attempts"] = attempts
            row["failure"] = failure
            row["verdict"] = answer.verdict if answer is not None else None
            row["answer"] = answer.model_dump(mode="json") if answer is not None else None
            rows.append(row)
            mark = {
                ("fail", "misstated"): "caught",
                ("fail", "supported"): "MISSED",
                ("pass", "supported"): "ok",
                ("pass", "misstated"): "FLAGGED",
            }.get((each["trust_gate"], row["verdict"]), "failed")
            kinds = ",".join(answer.kinds) if answer is not None else ""
            print(
                f"#{number:>2} inv-{investigation} {each['trust_gate']:<4} -> "
                f"{row['verdict'] or failure} [{mark}] {kinds}"
            )
            if failure and failure.startswith("call cap"):
                print("call cap reached: stopping")
                break
    finally:
        client.close()

    judged = [r for r in rows if r["verdict"] is not None]
    fails = [r for r in rows if r["label"] == "fail"]
    passes = [r for r in rows if r["label"] == "pass"]
    caught = sum(1 for r in fails if r["verdict"] == "misstated")
    flagged = sum(1 for r in passes if r["verdict"] == "misstated")
    summary = {
        "judge": FINDING_JUDGE_VERSION,
        "prompt_sha256": FINDING_JUDGE.prompt.sha256,
        "model": model,
        "calls": budget.used,
        "judged": len(judged),
        "caught": caught,
        "misstated_labelled": len(fails),
        "flagged": flagged,
        "supported_labelled": len(passes),
        "unjudged": len(rows) - len(judged),
        "target_met": (
            not args.dry_run
            and len(judged) == len(rows)
            and caught >= len(fails) - 1
            and flagged <= 1
        ),
    }
    (out / "result.json").write_text(
        json.dumps({"summary": summary, "findings": rows}, indent=1, ensure_ascii=False), "utf-8"
    )
    if not args.dry_run:
        print(
            f"caught {caught} of {len(fails)} misstated; flagged {flagged} of {len(passes)}"
            f" supported; {budget.used} calls; unjudged {summary['unjudged']}"
        )
    print(f"report: {out / 'result.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
