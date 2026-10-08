"""Score the counter-judge against the lead's labels of the 0.5.3 Skeptic Facts (pilot-review T3).

Reads `.scratch/live-runs/pilot-0.5.3-arg/labeled-counter-facts.json` (written by
`.scratch/tools/counter_relations_labels.py`, its `relation`s filled by the lead; not in git:
some quotes are from licensed call transcripts; never commit it or what this prints), groups
the labelled pairs by Skeptic Fact and asks the `counter_judge` role (`atlas.roles.
counter_judge`, its committed prompt) about each Skeptic Fact, one call each, exactly as the
Skeptic's task asks it: the research question, the Skeptic Fact as `k1`, the Facts it
challenged as `f1`, `f2`, ..., every quote as low-trust retrieved data.

It prints each pair's label and the judge's relation, and the score: exact agreement, and, for
what decides a step's status, the contradicting relations (`contradicts`, `limits`, `dates`)
against the rest: how many labelled contradicting pairs the judge calls contradicting
(caught) and how many labelled non-contradicting pairs it calls contradicting (false alarms;
each one would mark a step disputed that nothing contests).

Live, it calls the configured LiteLLM (`ATLAS_LITELLM_URL`, `ATLAS_LITELLM_API_KEY`,
`ATLAS_LLM_ROLE_MODEL`, from the environment or the repo's `.env`), so it spends the owner's
MiniMax quota: run it only with the lead's go-ahead. It stops at `--max-calls` chat
completions (default and ceiling 60: 50 Skeptic Facts, a repair of an invalid answer counts).
`--dry-run` builds and prints the requests without calling anything.

    uv run python .scratch/tools/counter_judge_eval.py [--dry-run] [--max-calls 60]
        [--labels PATH] [--only 1,2,...] [--out DIR]

The report (every request, answer and the score) goes to
`.scratch/live-runs/<stamp>-counter-judge-eval/` (gitignored).
"""

import argparse
import json
import os
import sys
import time
import uuid
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx2

from atlas.roles.caller import _validate  # pyright: ignore[reportPrivateUsage]
from atlas.roles.contract import DIRECTIVES, REPAIR_DIRECTIVE, QuotedText
from atlas.roles.counter_judge import (
    CONTRADICTING,
    COUNTER_JUDGE,
    COUNTER_JUDGE_VERSION,
    COUNTER_REF,
    RELATIONS,
    CounterJudgement,
    CounterJudgeRequest,
    JudgedFactItem,
)
from atlas.settings import Settings

REPO = Path(__file__).resolve().parents[2]
LABELS = REPO / ".scratch" / "live-runs" / "pilot-0.5.3-arg" / "labeled-counter-facts.json"
CALL_CEILING = 60
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


def quantity_text(quantity: Any) -> str | None:
    if not isinstance(quantity, dict):
        return None
    return f"{quantity.get('value')} {quantity.get('unit')} ({quantity.get('metric')})"


def item(ref: str, fact: dict[str, Any]) -> tuple[JudgedFactItem, QuotedText]:
    return (
        JudgedFactItem(
            ref=ref,
            company=str(fact.get("company") or "unknown"),
            step=str(fact.get("step") or ""),
            statement=str(fact.get("statement") or ""),
            status=str(fact.get("status") or ""),
            quantity=quantity_text(fact.get("quantity")),
            period=fact.get("period"),
            source_title=str(fact.get("source_title") or ""),
        ),
        QuotedText(
            id=ref,
            source=str(fact.get("source_version_id") or fact["fact_id"]),
            text=str(fact.get("quote") or ""),
        ),
    )


def build(
    group: list[dict[str, Any]],
) -> tuple[CounterJudgeRequest, list[QuotedText], dict[str, str]]:
    """One Skeptic Fact's request, its quotes, and each challenged reference's Fact ID."""
    counter, counter_quote = item(COUNTER_REF, group[0]["counter"])
    challenged: list[JudgedFactItem] = []
    quotes = [counter_quote]
    refs: dict[str, str] = {}
    for index, pair in enumerate(group, start=1):
        ref = f"f{index}"
        each, quote = item(ref, pair["challenged"])
        challenged.append(each)
        quotes.append(quote)
        refs[ref] = pair["challenged"]["fact_id"]
    request = CounterJudgeRequest(
        research_question=group[0]["question"], counter=counter, challenged=challenged
    )
    return request, quotes, refs


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
    request: CounterJudgeRequest,
    quotes: list[QuotedText],
    budget: Budget,
) -> tuple[CounterJudgement | None, list[dict[str, Any]], str | None]:
    """The role's answer (or None and why), and each attempt's raw content and tokens."""
    user = json.dumps(
        {
            "request": request.model_dump(mode="json"),
            "retrieved_data": [q.model_dump(mode="json") for q in quotes],
        },
        ensure_ascii=False,
    )
    messages: list[dict[str, str]] = [
        {"role": "system", "content": f"{DIRECTIVES}\n\n{COUNTER_JUDGE.prompt.text}"},
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
                    "name": COUNTER_JUDGE.name,
                    "strict": True,
                    "schema": COUNTER_JUDGE.response_schema(),
                },
            },
            "max_tokens": COUNTER_JUDGE.max_output_tokens,
            "metadata": {"run_id": str(uuid.uuid4()), "role": COUNTER_JUDGE.name},
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
        output, errors, _ = _validate(CounterJudgement, content)
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
    parser.add_argument("--labels", type=Path, default=LABELS)
    parser.add_argument("--max-calls", type=int, default=CALL_CEILING)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--only", default="", help="comma-separated 1-based Skeptic Fact indexes")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    limit = min(args.max_calls, CALL_CEILING)
    pairs = [
        each
        for each in json.loads(args.labels.read_text("utf-8"))
        if each.get("relation") in RELATIONS
    ]
    groups: dict[tuple[int, str], list[dict[str, Any]]] = {}
    for pair in pairs:
        groups.setdefault((pair["investigation"], pair["counter"]["fact_id"]), []).append(pair)
    chosen = list(groups.items())
    if args.only:
        keep = {int(n) for n in args.only.split(",") if n.strip()}
        chosen = [each for n, each in enumerate(chosen, start=1) if n in keep]
    print(
        f"{len(pairs)} labelled pairs, {len(chosen)} Skeptic Facts; judge"
        f" {COUNTER_JUDGE_VERSION}; cap {limit} calls"
    )
    if not chosen:
        print("nothing labelled: fill `relation` in the labels file first")
        return 2

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
    out = args.out or REPO / ".scratch" / "live-runs" / f"{stamp}-counter-judge-eval"
    out.mkdir(parents=True, exist_ok=True)
    budget = Budget(limit)
    rows: list[dict[str, Any]] = []
    client = httpx2.Client(
        base_url=(url or "http://dry-run.invalid").rstrip("/"),
        headers={"Authorization": f"Bearer {key or ''}"},
        timeout=240.0,
    )
    try:
        for number, ((investigation, counter_id), group) in enumerate(chosen, start=1):
            request, quotes, refs = build(group)
            row: dict[str, Any] = {
                "n": number,
                "investigation": investigation,
                "counter_fact_id": counter_id,
                "request": request.model_dump(mode="json"),
                "labels": {p["challenged"]["fact_id"]: p["relation"] for p in group},
            }
            if args.dry_run:
                row["relations"] = None
                rows.append(row)
                print(f"#{number:>2} inv-{investigation} {counter_id[:8]}: {len(group)} pairs")
                continue
            answer, attempts, failure = judge(client, model, extra_body, request, quotes, budget)
            row["attempts"] = attempts
            row["failure"] = failure
            judged: dict[str, str] = {}
            if answer is not None:
                for each in answer.relations:
                    if each.ref in refs and refs[each.ref] not in judged:
                        judged[refs[each.ref]] = each.relation
                row["answer"] = answer.model_dump(mode="json")
            row["relations"] = judged
            rows.append(row)
            shown = ", ".join(
                f"{row['labels'][f]}->{judged.get(f, 'unjudged')}" for f in row["labels"]
            )
            print(f"#{number:>2} inv-{investigation} {counter_id[:8]}: {failure or shown}")
            if failure and failure.startswith("call cap"):
                print("call cap reached: stopping")
                break
    finally:
        client.close()

    scored = [
        (label, (row["relations"] or {}).get(fact_id, "unjudged"))
        for row in rows
        if row.get("relations") is not None
        for fact_id, label in row["labels"].items()
    ]
    agree = sum(1 for label, judged in scored if label == judged)
    labelled_against = [(lab, jud) for lab, jud in scored if lab in CONTRADICTING]
    labelled_other = [(lab, jud) for lab, jud in scored if lab not in CONTRADICTING]
    caught = sum(1 for _, jud in labelled_against if jud in CONTRADICTING)
    false_alarms = sum(1 for _, jud in labelled_other if jud in CONTRADICTING)
    unjudged = sum(1 for _, jud in scored if jud == "unjudged")
    summary = {
        "judge": COUNTER_JUDGE_VERSION,
        "prompt_sha256": COUNTER_JUDGE.prompt.sha256,
        "model": model,
        "calls": budget.used,
        "pairs_scored": len(scored),
        "exact_agreement": agree,
        "contradicting_labelled": len(labelled_against),
        "contradicting_caught": caught,
        "other_labelled": len(labelled_other),
        "false_alarms": false_alarms,
        "unjudged": unjudged,
        "confusion": {
            f"{lab}->{jud}": n for (lab, jud), n in sorted(Counter(scored).items())
        },
    }
    (out / "result.json").write_text(
        json.dumps({"summary": summary, "skeptic_facts": rows}, indent=1, ensure_ascii=False),
        "utf-8",
    )
    if not args.dry_run:
        print(
            f"{agree} of {len(scored)} pairs agree; contradicting caught {caught} of"
            f" {len(labelled_against)}; false alarms {false_alarms} of {len(labelled_other)};"
            f" unjudged {unjudged}; {budget.used} calls"
        )
    print(f"report: {out / 'result.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
