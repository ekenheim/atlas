"""Score a saved pilot investigation without a reviewer (bottleneck-argument ticket 06).

    python .scratch/tools/pilot_score.py <folder> <n> [--reference pilot-0.4.6] [--judge]
        [--env FILE] [--runs-dir DIR] [--agreement]

`<folder>` is a run folder as `pilot_runs.py` saves it (a name under the runs directory, or a
path), `<n>` the question (1-5). It compares the run with the reference run (default
`pilot-0.4.6`, whose review of 2026-10-07 is in `inv-<n>/review/workflow-result.json`) of the
same question and prints one table.

Always (no network, no model):
- baseline coverage: for each on-question baseline hit the reviewers judged, whether an accepted
  Claim's or a Fact's quote overlaps the hit's passage: the same Source Version with
  overlapping character spans, or (the hit's `also_in` documents, or spans that moved) a quote
  sharing a run of 8 words with the hit's passage in that Source Version. A hit is the
  reference run's `review/baseline.json` hit, so both runs are scored against the same passages.
- tokens, role calls and wall time.

With `--judge` (spends MiniMax tokens through LiteLLM, only on the owner's go-ahead): each of the
researcher's cited facts (`answer.facts`, the researcher's hour of the same file) is judged against
the run's card and its Claims or Facts, one chat completion per batch of ten, with the prompt in
`pilot_score_judge.md`: on the card, held in a Claim or Fact, or absent. The result is saved to
`<folder>/inv-<n>/score-judge.json` and reused; the key is read from `--env` (default `.env`) and
never printed.

`--agreement` prints, per question, the automatic coverage of the reference run next to the
reviewers' marks (covered; covered or in substance) and the per-hit agreement.

A run's accepted Facts are read from `facts` in its `investigation.json` (or `facts.json`) when
the build has them: each needs `source_version_id`, `quote` and optionally `span_start`, `span_end`.
Run from anywhere; the pilot data is not in git (`--runs-dir`, default the checkout's
`.scratch/live-runs`, else the main checkout's).
"""

import argparse
import json
import pathlib
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime

HERE = pathlib.Path(__file__).resolve().parent
SHINGLE = 8
BATCH = 10
CANDIDATES = 8


def runs_dir(given):
    if given:
        return pathlib.Path(given)
    root = HERE.parents[1]
    local = root / ".scratch" / "live-runs"
    if local.exists():
        return local
    try:
        common = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"], cwd=root, capture_output=True, text=True
        ).stdout.strip()
        main = (root / common).resolve().parent
        if (main / ".scratch" / "live-runs").exists():
            return main / ".scratch" / "live-runs"
    except OSError:
        pass
    return local


def load(path):
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def words(text):
    return re.findall(r"[a-z0-9]+(?:[.,'-][a-z0-9]+)*", (text or "").lower())


def shingles(text, size=SHINGLE):
    w = words(text)
    return {" ".join(w[i : i + size]) for i in range(max(len(w) - size + 1, 0))}


def run_items(run):
    """The run's accepted Claims and Facts as {id, source_version_id, start, end, quote, kind}."""
    investigation = load(run / "investigation.json")
    items = []
    for each in investigation.get("evidence", []):
        if each.get("excluded"):
            continue
        items.append(
            {
                "id": each["claim_id"],
                "source_version_id": each["source_version_id"],
                "start": each.get("span_start"),
                "end": each.get("span_end"),
                "quote": each.get("quote") or "",
                "kind": "claim",
            }
        )
    facts = investigation.get("facts")
    if facts is None and (run / "facts.json").exists():
        facts = load(run / "facts.json")
        facts = facts.get("items", facts) if isinstance(facts, dict) else facts
    for each in facts or []:
        items.append(
            {
                "id": each.get("id") or each.get("fact_id") or "fact",
                "source_version_id": each["source_version_id"],
                "start": each.get("span_start"),
                "end": each.get("span_end"),
                "quote": each.get("quote") or "",
                "kind": "fact",
            }
        )
    return investigation, items


def covers(hit, items):
    """The items that cover a baseline hit: in its own document by overlapping span; in it or an
    `also_in` document by a run of shared words (the same paragraph). A claim restating the
    passage in another document or on another slide is not found (tried: a content-word
    containment rule added false positives in questions 2 and 3 and fixed nothing in question 1;
    the reviewers' extra "covered" marks there are semantic)."""
    own = hit["source_version_id"]
    others = {each["source_version_id"] for each in hit.get("also_in", [])}
    wanted = shingles(hit["text"])
    found = []
    for item in items:
        sv = item["source_version_id"]
        if sv == own:
            start, end = item["start"], item["end"]
            if start is not None and end is not None and start < hit["char_end"] and end > hit["char_start"]:
                found.append(item)
                continue
        if (sv == own or sv in others) and wanted & shingles(item["quote"]):
            found.append(item)
    return found


def reviewer_marks(reference):
    """The on-question hits the reviewers judged, joined to the reference run's baseline hits."""
    review = load(reference / "review" / "workflow-result.json")
    baseline = {hit["rank"]: hit for hit in load(reference / "review" / "baseline.json")["hits"]}
    marks = []
    for judged in review["baseline"]["hits"]:
        if judged["on_question"] and judged["rank"] in baseline:
            marks.append((baseline[judged["rank"]], judged["coverage"]))
    return review, marks


def coverage(items, marks):
    return [(hit, mark, bool(covers(hit, items))) for hit, mark in marks]


def run_facts(run):
    investigation = load(run / "investigation.json")
    start = datetime.fromisoformat(investigation["created_at"].replace("Z", "+00:00"))
    stop = investigation.get("stopped_at")
    wall = (
        round((datetime.fromisoformat(stop.replace("Z", "+00:00")) - start).total_seconds())
        if stop
        else None
    )
    usage = investigation.get("usage", {})
    calls = None
    if (run / "role-calls.json").exists():
        calls = len(load(run / "role-calls.json").get("role_calls", []))
    return {
        "tokens": usage.get("tokens_in", 0) + usage.get("tokens_out", 0),
        "role_calls": calls,
        "wall_seconds": wall,
        "card_findings": len((investigation.get("research_card") or {}).get("findings", [])),
    }


def dotenv(path):
    values = {}
    p = pathlib.Path(path)
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip('"')
    return values


def candidates(fact, items):
    wanted = set(words(fact)) - {"the", "a", "of", "and", "to", "in", "is", "for", "on", "that", "its", "as", "by"}
    scored = []
    for item in items:
        have = set(words(item["quote"]))
        score = len(wanted & have) / (len(wanted) or 1)
        if score > 0:
            scored.append((score, item))
    scored.sort(key=lambda pair: -pair[0])
    return [item for _, item in scored[:CANDIDATES]]


def judge(facts, investigation, items, env_path, out_file):
    env = dotenv(env_path)
    base = (env.get("ATLAS_LITELLM_URL") or env["LITELLM_URL"]).rstrip("/")
    key = env.get("ATLAS_LITELLM_API_KEY") or env["LITELLM_API_KEY"]
    model = env.get("ATLAS_LLM_ROLE_MODEL", "MiniMax-M3")
    prompt = (HERE / "pilot_score_judge.md").read_text(encoding="utf-8")
    card = [f.get("claim_text", "") for f in (investigation.get("research_card") or {}).get("findings", [])]
    saved = load(out_file) if out_file.exists() else {"verdicts": {}, "usage": {"prompt": 0, "completion": 0, "calls": 0}}
    todo = [(i, fact) for i, fact in enumerate(facts) if str(i) not in saved["verdicts"]]
    for at in range(0, len(todo), BATCH):
        batch = todo[at : at + BATCH]
        held = {}
        refs = {}
        for i, fact in batch:
            held[str(i)] = []
            for item in candidates(fact["fact"], items):
                refs[item["id"]] = item
                held[str(i)].append({"ref": item["id"], "quote": item["quote"][:600]})
        payload = {
            "facts": [{"id": str(i), "fact": fact["fact"]} for i, fact in batch],
            "card": card,
            "held": held,
        }
        body = {
            "model": model,
            "thinking": {"type": "disabled"},
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            "max_tokens": 4096,
            "metadata": {"role": "lead-pilot-score"},
        }
        request = urllib.request.Request(
            base + "/chat/completions",
            data=json.dumps(body).encode(),
            headers={"content-type": "application/json", "authorization": f"Bearer {key}"},
        )
        started = time.time()
        with urllib.request.urlopen(request, timeout=600) as response:
            completion = json.load(response)
        content = completion["choices"][0]["message"]["content"] or ""
        match = re.search(r"\{.*\}", content, re.S)
        answer = json.loads(match.group(0)) if match else {"verdicts": []}
        got = {str(v["id"]): v for v in answer.get("verdicts", [])}
        for i, _ in batch:
            v = got.get(str(i))
            if v and v.get("verdict") in ("on_card", "held", "absent"):
                saved["verdicts"][str(i)] = {k: v.get(k) for k in ("verdict", "ref", "reason")}
        usage = completion.get("usage") or {}
        saved["usage"]["prompt"] += usage.get("prompt_tokens", 0)
        saved["usage"]["completion"] += usage.get("completion_tokens", 0)
        saved["usage"]["calls"] += 1
        out_file.write_text(json.dumps(saved, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  judged facts {at + 1}-{at + len(batch)} in {time.time() - started:.0f}s", file=sys.stderr, flush=True)
    return saved


def agreement(reference_dir, numbers):
    print("Automatic baseline coverage of the 0.4.6 runs against the reviewers' marks (on-question hits)")
    print(f"{'q':>2} {'hits':>4} {'auto':>4} {'rev.covered':>11} {'rev.cov+substance':>17} {'hit agreement':>14}  diff(auto-strict) diff(auto-incl)")
    worst = 0
    for n in numbers:
        run = reference_dir / f"inv-{n}"
        _, items = run_items(run)
        _, marks = reviewer_marks(run)
        rows = coverage(items, marks)
        auto = sum(1 for _, _, c in rows if c)
        strict = sum(1 for _, m, _ in rows if m == "covered")
        incl = sum(1 for _, m, _ in rows if m in ("covered", "covered-in-substance"))
        agree = sum(1 for _, m, c in rows if c == (m in ("covered", "covered-in-substance")))
        d1, d2 = auto - strict, auto - incl
        worst = max(worst, min(abs(d1), abs(d2)))
        print(f"{n:>2} {len(rows):>4} {auto:>4} {strict:>11} {incl:>17} {agree:>7}/{len(rows):<6}  {d1:+d} {d2:+d}")
    print(f"largest gap to the nearer of the two reviewer counts: {worst}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", nargs="?")
    ap.add_argument("n", nargs="?", type=int)
    ap.add_argument("--reference", default="pilot-0.4.6")
    ap.add_argument("--judge", action="store_true")
    ap.add_argument("--env", default=".env")
    ap.add_argument("--runs-dir")
    ap.add_argument("--agreement", action="store_true")
    args = ap.parse_args()
    base = runs_dir(args.runs_dir)
    reference_dir = base / args.reference
    if args.agreement:
        agreement(reference_dir, [args.n] if args.n else [1, 2, 3, 4, 5])
        return 0
    if not args.folder or not args.n:
        ap.error("folder and n are required")
    folder = pathlib.Path(args.folder)
    new_dir = (folder if folder.exists() else base / args.folder) / f"inv-{args.n}"
    old_dir = reference_dir / f"inv-{args.n}"
    review, marks = reviewer_marks(old_dir)
    old_inv, old_items = run_items(old_dir)
    new_inv, new_items = run_items(new_dir)
    old_cov, new_cov = coverage(old_items, marks), coverage(new_items, marks)
    old_stats, new_stats = run_facts(old_dir), run_facts(new_dir)
    researcher = review["answer"]["facts"]

    old_judged = {"on_card": sum(1 for f in review["compare"]["facts"] if f.get("on_card")), "held": None}
    new_judged = None
    if args.judge:
        out = new_dir / "score-judge.json"
        saved = judge(researcher, new_inv, new_items, args.env, out)
        counts = {"on_card": 0, "held": 0, "absent": 0}
        for v in saved["verdicts"].values():
            counts[v["verdict"]] += 1
        new_judged = counts

    total = len(old_cov)
    rows = [
        ("on-question baseline hits covered by a Claim or Fact (auto)", f"{sum(c for *_, c in old_cov)}/{total}", f"{sum(c for *_, c in new_cov)}/{total}"),
        ("  reviewers' marks, 0.4.6 (covered / incl. in substance)", f"{sum(1 for _, m, _ in old_cov if m == 'covered')} / {sum(1 for _, m, _ in old_cov if m != 'not-covered')}", "-"),
        (f"researcher's cited facts on the card (of {len(researcher)})", str(old_judged["on_card"]), str(new_judged["on_card"]) if new_judged else "run with --judge"),
        ("researcher's facts held in a Claim or Fact, not on the card", "-", str(new_judged["held"]) if new_judged else "run with --judge"),
        ("researcher's facts absent", "-", str(new_judged["absent"]) if new_judged else "run with --judge"),
        ("accepted Claims / Facts", f"{sum(1 for i in old_items if i['kind'] == 'claim')} / {sum(1 for i in old_items if i['kind'] == 'fact')}", f"{sum(1 for i in new_items if i['kind'] == 'claim')} / {sum(1 for i in new_items if i['kind'] == 'fact')}"),
        ("card findings", str(old_stats["card_findings"]), str(new_stats["card_findings"])),
        ("tokens (in + out)", f"{old_stats['tokens']:,}", f"{new_stats['tokens']:,}"),
        ("role calls", str(old_stats["role_calls"] if old_stats["role_calls"] is not None else review["run"]["role_calls"]), str(new_stats["role_calls"])),
        ("wall time (s)", str(old_stats["wall_seconds"]), str(new_stats["wall_seconds"])),
    ]
    width = max(len(r[0]) for r in rows)
    print(f"Question {args.n}: {new_inv['question'][:100]}")
    print(f"{'':<{width}}  {args.reference:>16}  {new_dir.parent.name:>16}")
    for label, old, new in rows:
        print(f"{label:<{width}}  {old:>16}  {new:>16}")
    missed = [h for h, _, c in new_cov if not c]
    if missed:
        print(f"\nBaseline hits not covered in {new_dir.parent.name} (rank, company, title):")
        for hit in missed:
            print(f"  #{hit['rank']} {hit['company']} | {hit['title'][:70]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
