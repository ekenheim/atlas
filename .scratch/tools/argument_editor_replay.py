"""Replay a saved argument-plan Editor call against another model (pilot-review ticket 25, step 2).

    uv run python .scratch/tools/argument_editor_replay.py <inv folder> --model <alias> --out <dir>
        [--dry-run] [--max-calls 2] [--env-file .env]

`<inv folder>` is one `inv-N` folder saved by `.scratch/tools/pilot_runs.py` (it needs
`role-calls.json`; `facts.json` gives the Facts' IDs when present). The tool takes the first
accepted argument-Editor call (`editor-argument`, the highest prompt version present),
validates its request with `EditorArgumentRequest`, and rebuilds the chat completion exactly as
`atlas.roles.caller.RoleCaller` posts it (the system message is `DIRECTIVES`, the role's prompt
and its answer format; the user message is the request and the quoted retrieved data;
`response_format` is the role's strict JSON schema; the role's output cap; the extra body of
`ATLAS_LLM_ROLE_EXTRA_BODY`, thinking off by default), with `--model` in place of the
configured one. It posts it to LiteLLM (`ATLAS_LITELLM_URL` / `ATLAS_LITELLM_API_KEY`, or
`LITELLM_URL` / `LITELLM_API_KEY`, from the environment or the env file; the key is never
printed or written), validates the answer with the caller's own `_validate`, asks one repair
as the caller does, and asks once more with the cap doubled (up to
`ATLAS_EDITOR_MAX_OUTPUT_TOKENS`, 16,384) when the answer was cut off at the cap. `--max-calls`
bounds the chat completions (default 2).

Writes to `--out`:

- `request.json`: the model, the messages and the whole body, minus the key.
- `answer.json`: each attempt's raw content, finish reason, tokens and validation errors, and the
  validated answer.
- `statements.json`: one entry per step statement, in card order, in the shape of
  `argument_statement_labels.py`'s (`investigation`, `question`, `step`, `index`, `statement`,
  `facts`, each cited Fact and then each counterevidence Fact resolved from the request by the
  Editor's short references), `trust_gate` null for the lead's review.
- `summary.json`: model, the routed model ID (`x-litellm-model-id`), tokens, time, statements
  per step, statements citing a reference that resolved to no Fact.
- `review.md`: each statement with the quotes it cites, for judging by eye.

`--dry-run` builds and writes `request.json` and stops. The output holds quotes from licensed
call transcripts: keep it under `.scratch/live-runs/` (gitignored); never commit it.
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import httpx2

sys.path.insert(0, str(Path(__file__).resolve().parent))

from argument_statement_labels import cited

from atlas.roles.caller import _validate  # pyright: ignore[reportPrivateUsage]
from atlas.roles.contract import (
    DIRECTIVES,
    REPAIR_DIRECTIVE,
    QuotedText,
    answer_format,
)
from atlas.roles.editor import EDITOR_ARGUMENT, EditorArgumentRequest

DEFAULT_THINKING_OFF: dict[str, Any] = {"thinking": {"type": "disabled"}}
DEFAULT_EDITOR_CAP = 16_384


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


def pick_call(calls: list[dict[str, Any]]) -> dict[str, Any]:
    """The first accepted argument-Editor call of the highest prompt version present."""
    mine = [
        c
        for c in calls
        if c.get("role") == "editor"
        and c.get("prompt_name") == "editor-argument"
        and c.get("status") == "accepted"
    ]
    if not mine:
        raise SystemExit("no accepted editor-argument call in role-calls.json")
    top = max(int(c["prompt_version"]) for c in mine)
    return next(c for c in mine if int(c["prompt_version"]) == top)


def build_messages(
    request: dict[str, Any], retrieved: list[dict[str, Any]]
) -> tuple[list[dict[str, str]], dict[str, Any], list[dict[str, Any]]]:
    """The messages the role caller would send for this request (its own code, not a copy)."""
    request_json = EditorArgumentRequest.model_validate(request).model_dump(mode="json")
    quoted = [QuotedText.model_validate(r).model_dump(mode="json") for r in retrieved]
    user = json.dumps({"request": request_json, "retrieved_data": quoted}, ensure_ascii=False)
    system = (
        f"{DIRECTIVES}\n\n{EDITOR_ARGUMENT.prompt.text}\n\n"
        f"{answer_format(EDITOR_ARGUMENT.response_schema())}"
    )
    return (
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        request_json,
        quoted,
    )


def request_body(
    messages: list[dict[str, str]], model: str, extra: dict[str, Any], cap: int
) -> dict[str, Any]:
    return {
        **extra,
        "model": model,
        "messages": messages,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": EDITOR_ARGUMENT.name,
                "strict": True,
                "schema": EDITOR_ARGUMENT.response_schema(),
            },
        },
        "max_tokens": cap,
        "metadata": {"role": EDITOR_ARGUMENT.name, "purpose": "argument editor replay"},
    }


def fact_ids(inv: Path) -> tuple[dict[tuple[str, int, int], str], dict[str, str]]:
    """Fact IDs from `facts.json` by quote span, and by statement as a fallback."""
    path = inv / "facts.json"
    by_span: dict[tuple[str, int, int], str] = {}
    by_text: dict[str, str] = {}
    if not path.is_file():
        return by_span, by_text
    items = json.loads(path.read_text("utf-8")).get("items") or []
    for item in items:
        a = item.get("assertion") or {}
        by_text.setdefault(str(item.get("statement")), str(item["id"]))
        if a.get("source_version_id") is not None and a.get("span_start") is not None:
            by_span[(str(a["source_version_id"]), int(a["span_start"]), int(a["span_end"]))] = str(
                item["id"]
            )
    return by_span, by_text


_SOURCE = re.compile(r"^(?P<version>[^#]+)#(?P<start>\d+)-(?P<end>\d+)$")


def resolve(
    item: dict[str, Any],
    kind: str,
    quotes: dict[str, dict[str, Any]],
    ids: tuple[dict[tuple[str, int, int], str], dict[str, str]],
) -> dict[str, Any]:
    """One request Fact in `argument_statement_labels.cited`'s shape."""
    quote = quotes.get(item["ref"]) or {}
    match = _SOURCE.match(str(quote.get("source") or ""))
    span: dict[str, Any] = {"quote": quote.get("text")}
    fact_id = None
    if match:
        version, start, end = match["version"], int(match["start"]), int(match["end"])
        span.update(source_version_id=version, span_start=start, span_end=end)
        fact_id = ids[0].get((version, start, end))
    fact_id = fact_id or ids[1].get(str(item.get("statement")))
    return cited(
        {
            "fact_id": fact_id or item["ref"],
            "company_name": item.get("company"),
            "status": item.get("status"),
            "statement": item.get("statement"),
            "quantity": item.get("quantity"),
            "period": item.get("period"),
            "source_title": item.get("source_title"),
            "source_span": span,
        },
        kind,
    ) | {"ref": item["ref"], "quantity": item.get("quantity")}


def statements_of(
    answer: dict[str, Any],
    request: dict[str, Any],
    quotes: dict[str, dict[str, Any]],
    ids: tuple[dict[tuple[str, int, int], str], dict[str, str]],
    number: int,
) -> tuple[list[dict[str, Any]], int]:
    """Every step statement of the answer, in card order, and how many cite an unknown ref."""
    facts = {f["ref"]: f for f in request["facts"]}
    counters = {f["ref"]: f for f in request["counterevidence"]}
    entries: list[dict[str, Any]] = []
    unresolved = 0
    for step in answer["steps"]:
        for index, said in enumerate(step["statements"], start=1):
            sent: list[dict[str, Any]] = []
            missing = False
            for ref in said["fact_refs"]:
                if ref in facts:
                    sent.append(resolve(facts[ref], "fact", quotes, ids))
                else:
                    missing = True
            for ref in said["counter_refs"]:
                if ref in counters:
                    sent.append(resolve(counters[ref], "counter", quotes, ids))
                else:
                    missing = True
            unresolved += missing
            entries.append(
                {
                    "investigation": number,
                    "question": request["research_question"],
                    "step": step["step"],
                    "index": index,
                    "statement": said["statement"],
                    "trust_gate": None,
                    "unresolved_refs": missing,
                    "facts": sent,
                }
            )
    return entries, unresolved


def review_md(entries: list[dict[str, Any]], answer: dict[str, Any], model: str) -> str:
    lines = [f"# Argument Editor replay: {model}", ""]
    if entries:
        lines += [f"Question: {entries[0]['question']}", ""]
    status = {s["step"]: s["status"] for s in answer["steps"]}
    current = None
    for e in entries:
        if e["step"] != current:
            current = e["step"]
            lines += [f"## {current} ({status.get(current)})", ""]
        lines += [f"### {current} {e['index']}", "", e["statement"], ""]
        if e["unresolved_refs"]:
            lines += ["**A cited reference resolved to no Fact.**", ""]
        for f in e["facts"]:
            lines += [
                f"- [{f['kind']}] {f['company_name']}, {f['status']}, period: {f['period']},"
                f" quantity: {f['quantity']} ({f['source_title']})",
                f"  - Reader: {f['statement']}",
                f'  - Quote: "{f["quote"]}"',
            ]
        lines.append("")
    lines += ["## Unchecked and open", ""]
    for s in answer["steps"]:
        for u in s["unchecked"]:
            lines.append(f"- {s['step']}: {u}")
    lines += [f"- open: {q}" for q in answer["open_questions"]]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("inv", type=Path)
    parser.add_argument("--model", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-calls", type=int, default=2)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    args = parser.parse_args(argv)

    env = env_file(args.env_file)

    def setting(*names: str) -> str | None:
        for name in names:
            if os.environ.get(name) or env.get(name):
                return os.environ.get(name) or env.get(name)
        return None

    calls = json.loads((args.inv / "role-calls.json").read_text("utf-8"))["role_calls"]
    saved = pick_call(calls)
    messages, request, quoted = build_messages(saved["request"], saved["retrieved"])
    quotes = {q["id"]: q for q in quoted}
    extra_text = setting("ATLAS_LLM_ROLE_EXTRA_BODY")
    extra: dict[str, Any] = json.loads(extra_text) if extra_text else DEFAULT_THINKING_OFF
    editor_cap = int(setting("ATLAS_EDITOR_MAX_OUTPUT_TOKENS") or DEFAULT_EDITOR_CAP)
    cap = EDITOR_ARGUMENT.max_output_tokens
    number = int(args.inv.name.split("-")[-1]) if args.inv.name.split("-")[-1].isdigit() else 0

    args.out.mkdir(parents=True, exist_ok=True)
    first = request_body(messages, args.model, extra, cap)
    (args.out / "request.json").write_text(json.dumps(first, ensure_ascii=False, indent=1), "utf-8")
    counts = {
        "prompt": f"{EDITOR_ARGUMENT.prompt.name}.v{EDITOR_ARGUMENT.prompt.version}",
        "saved_prompt_version": saved["prompt_version"],
        "facts": len(request["facts"]),
        "counterevidence": len(request["counterevidence"]),
        "steps": len(request["steps"]),
        "question_parts": len(request["question_parts"]),
        "leads": len(request["leads"]),
        "quotes": len(quoted),
        "refs_without_quote": sorted(
            f["ref"]
            for f in request["facts"] + request["counterevidence"]
            if f["ref"] not in quotes
        ),
        "cap": cap,
        "request_chars": len(messages[0]["content"]) + len(messages[1]["content"]),
    }
    if args.dry_run:
        print(json.dumps(counts, indent=1))
        return 0

    base = setting("ATLAS_LITELLM_URL", "LITELLM_URL")
    key = setting("ATLAS_LITELLM_API_KEY", "LITELLM_API_KEY")
    if not base or not key:
        raise SystemExit("LiteLLM URL and key are not set (environment or --env-file)")

    attempts: list[dict[str, Any]] = []
    output = None
    model_id = None
    doubled = repaired = False
    convo = messages
    started = time.time()
    with httpx2.Client(
        base_url=base.rstrip("/"), headers={"Authorization": f"Bearer {key}"}, timeout=900
    ) as client:
        for _ in range(args.max_calls):
            response = client.post(
                "/chat/completions", json=request_body(convo, args.model, extra, cap)
            )
            if not response.is_success:
                attempts.append({"http_status": response.status_code, "error": response.text[:500]})
                break
            body = response.json()
            model_id = response.headers.get("x-litellm-model-id") or model_id
            choice = body["choices"][0]
            content = choice["message"].get("content") or ""
            usage = body.get("usage") or {}
            output, errors, ignored = _validate(EDITOR_ARGUMENT.response, content)
            attempts.append(
                {
                    "max_tokens": cap,
                    "finish_reason": choice.get("finish_reason"),
                    "tokens_in": usage.get("prompt_tokens"),
                    "tokens_out": usage.get("completion_tokens"),
                    "model": body.get("model"),
                    "content": content,
                    "validation_errors": errors,
                    "ignored_fields": ignored,
                }
            )
            if output is not None:
                break
            cut = (
                choice.get("finish_reason") == "length" or usage.get("completion_tokens", 0) >= cap
            )
            if cut and not doubled and cap < editor_cap:
                doubled, cap, convo = True, min(cap * 2, editor_cap), messages
            elif not cut and not repaired:
                repaired = True
                convo = [
                    *convo,
                    {"role": "assistant", "content": content},
                    {
                        "role": "user",
                        "content": (
                            f"{REPAIR_DIRECTIVE}\n\n{json.dumps(errors)}"
                            f"\n\n{answer_format(EDITOR_ARGUMENT.response_schema())}"
                        ),
                    },
                ]
            else:
                break
    seconds = round(time.time() - started, 1)
    validated = output.model_dump(mode="json") if output is not None else None
    (args.out / "answer.json").write_text(
        json.dumps({"attempts": attempts, "validated": validated}, ensure_ascii=False, indent=1),
        "utf-8",
    )
    summary: dict[str, Any] = {
        "model": args.model,
        "model_id": model_id,
        "tokens_in": sum(a.get("tokens_in") or 0 for a in attempts),
        "tokens_out": sum(a.get("tokens_out") or 0 for a in attempts),
        "seconds": seconds,
        "calls": len(attempts),
        "repaired": repaired,
        "cap_doubled": doubled,
        "valid": validated is not None,
        **counts,
    }
    if validated is not None:
        entries, unresolved = statements_of(validated, request, quotes, fact_ids(args.inv), number)
        (args.out / "statements.json").write_text(
            json.dumps(entries, ensure_ascii=False, indent=1), "utf-8"
        )
        (args.out / "review.md").write_text(review_md(entries, validated, args.model), "utf-8")
        summary["verdict"] = validated["verdict"]
        summary["statements_per_step"] = {
            s["step"]: len(s["statements"]) for s in validated["steps"]
        }
        summary["statements"] = len(entries)
        summary["statements_with_unresolved_refs"] = unresolved
    (args.out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), "utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0 if validated is not None else 1


if __name__ == "__main__":
    sys.exit(main())
