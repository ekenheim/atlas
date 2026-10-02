"""Replay a production Editor request against the model with the code of a worktree (the lead's
check of memory-quality ticket 16 before its release).

    python editor_replay.py <worktree> <role-calls.json> <env file> <out dir> [max_tokens]

It takes the first Editor call of a saved run (`GET /runs/{id}/role-calls`), rebuilds the
request the worktree's code would send (Claims by short reference), posts the same chat
completion body the role caller builds, and reports whether the answer validates, where the
model stopped, the tokens and the time. A cut-off answer is asked once more with the cap
doubled, as the investigation does. At most two chat completions. The key is read from the env
file and never printed.
"""

import json
import pathlib
import sys
import time
import urllib.request


def dotenv(path):
    values = {}
    for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"')
    return values


def main():
    worktree, calls_path, env_path, out_dir = sys.argv[1:5]
    cap = int(sys.argv[5]) if len(sys.argv) > 5 else None
    sys.path.insert(0, str(pathlib.Path(worktree) / "backend"))
    from pydantic import ValidationError

    from atlas.roles.contract import DIRECTIVES
    from atlas.roles.editor import EDITOR, EditorRequest, ResearchCardDraft

    calls = json.loads(pathlib.Path(calls_path).read_text(encoding="utf-8"))["role_calls"]
    saved = next(c for c in calls if c["role"] == "editor")
    old = saved["request"]
    refs = {claim["claim_id"]: f"c{index}" for index, claim in enumerate(old["claims"], start=1)}
    request = dict(old)
    request["claims"] = [
        {"ref": refs[c["claim_id"]], **{k: v for k, v in c.items() if k != "claim_id"}} for c in old["claims"]
    ]
    request["contradictions"] = [
        {
            **{k: v for k, v in c.items() if k != "contradicts_claim_ids"},
            "contradicts_refs": [refs[i] for i in c.get("contradicts_claim_ids", []) if i in refs],
        }
        for c in old["contradictions"]
    ]
    request = EditorRequest.model_validate(request).model_dump(mode="json")
    retrieved = [{**each, "id": refs.get(each["id"], each["id"])} for each in saved["retrieved"]]

    env = dotenv(env_path)
    base = (env.get("ATLAS_LITELLM_URL") or env["LITELLM_URL"]).rstrip("/")
    key = env.get("ATLAS_LITELLM_API_KEY") or env["LITELLM_API_KEY"]
    messages = [
        {"role": "system", "content": f"{DIRECTIVES}\n\n{EDITOR.prompt.text}"},
        {"role": "user", "content": json.dumps({"request": request, "retrieved_data": retrieved}, ensure_ascii=False)},
    ]
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = {"claims": len(request["claims"]), "prompt_version": getattr(EDITOR.prompt, "version", None), "attempts": []}
    cap = cap or EDITOR.max_output_tokens
    for attempt in (1, 2):
        body = {
            "thinking": {"type": "disabled"},
            "model": "MiniMax-M3",
            "messages": messages,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": EDITOR.name, "strict": True, "schema": EDITOR.response_schema()},
            },
            "max_tokens": cap,
            "metadata": {"role": "editor", "purpose": "lead replay of ticket 16"},
        }
        post = urllib.request.Request(
            base + "/chat/completions",
            data=json.dumps(body).encode(),
            headers={"content-type": "application/json", "authorization": f"Bearer {key}"},
        )
        started = time.time()
        with urllib.request.urlopen(post, timeout=900) as response:
            completion = json.load(response)
        seconds = round(time.time() - started, 1)
        choice = completion["choices"][0]
        content = choice["message"]["content"] or ""
        (out / f"attempt-{attempt}.json").write_text(json.dumps(completion, ensure_ascii=False, indent=1), encoding="utf-8")
        row = {
            "attempt": attempt, "max_tokens": cap, "seconds": seconds,
            "finish_reason": choice.get("finish_reason"), "usage": completion.get("usage"),
            "content_chars": len(content),
        }
        try:
            draft = ResearchCardDraft.model_validate_json(content)
        except ValidationError as error:
            row["valid"] = False
            row["error"] = str(error).splitlines()[1][:200] if len(str(error).splitlines()) > 1 else str(error)[:200]
        else:
            cited = [ref for finding in draft.findings for ref in finding.claim_refs]
            known = set(refs.values())
            row.update(
                valid=True, verdict=draft.verdict, findings=len(draft.findings),
                open_questions=len(draft.open_questions), refs_cited=len(cited),
                distinct_refs_cited=len(set(cited)), unknown_refs=sorted(set(cited) - known),
                findings_without_refs=sum(1 for f in draft.findings if not f.claim_refs),
                statements=[f.statement[:160] for f in draft.findings],
            )
        report["attempts"].append(row)
        print(json.dumps({k: v for k, v in row.items() if k != "statements"}, ensure_ascii=False), flush=True)
        cut = choice.get("finish_reason") == "length" or (completion.get("usage") or {}).get("completion_tokens", 0) >= cap
        if row.get("valid") or not cut:
            break
        cap *= 2
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    for statement in report["attempts"][-1].get("statements", []):
        print(" -", statement)


if __name__ == "__main__":
    main()
