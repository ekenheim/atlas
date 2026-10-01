"""Run the archive-search baseline for each breadth run and summarize (repo root, Windows uv)."""

import json
import pathlib
import subprocess

OUT = pathlib.Path(".scratch/live-runs/breadth-0.2.5")
SEEDS = {
    2: ["axt", "coherent", "lumentum"],
    3: ["fabrinet", "applied-optoelectronics", "coherent"],
    4: ["marvell", "macom"],
    5: ["ciena", "lumentum", "coherent"],
}

for number, seeds in SEEDS.items():
    inv = json.loads((OUT / f"inv-{number}.json").read_text(encoding="utf-8"))
    target = OUT / f"baseline-{number}"
    if not (target / "results.json").exists():
        command = ["uv", "run", "--no-sync", "python", "scripts/pilot_baseline.py"]
        for seed in seeds:
            command += ["--company", seed]
        command += [
            "--question", inv["question"],
            "--investigation", inv["id"],
            "--as-of", inv["created_at"],
            "--out", str(target),
        ]
        done = subprocess.run(command, capture_output=True, text=True)
        print(f"investigation {number}: baseline exit {done.returncode} {done.stderr.strip().splitlines()[-1:]}", flush=True)
    result = json.loads((target / "results.json").read_text(encoding="utf-8"))
    hits = result["hits"]
    covered = [h for h in hits if h["covered_by_claims"]]
    recalled = [h for h in hits if h["in_recalled_sections"]]
    print(
        f"investigation {number}: {result['documents']} documents, {len(hits)} hits, "
        f"{len(covered)} contain an accepted Claim's quote, {len(recalled)} in recalled sections, "
        f"{len(result['claims_in_no_hit'])} accepted Claims in no hit; recall {result['recall']['memories'] if result['recall'] else None} memories",
        flush=True,
    )
    for hit in hits[:5]:
        print(f"    #{hit['rank']} {hit['company']} | {hit['title'][:60]} | cov={len(hit['covered_by_claims'])} | {' '.join(hit['text'].split())[:150]}", flush=True)
