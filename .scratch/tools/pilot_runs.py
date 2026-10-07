"""The reviewed pilot runs on production 0.3.0 (pilot-review tickets 15 and 05 to 08).

One investigation per call: `python .scratch/tools/pilot_runs.py <number>`. It starts the
investigation (the plan's question verbatim, a 2,000,000 token budget in the request, which is
what home-ops PR #7194 makes the default), polls until it stops (a pause for a budget is waited
out), saves everything the review reads and runs the archive-search baseline. Resumable: the
started ID is kept in `inv-<n>/state.json`, so a second call polls the same investigation.
Run from the repo root; output under .scratch/live-runs/pilot-0.3.0/ (not in git).
"""

import json
import pathlib
import subprocess
import sys
import time
import urllib.request

BASE = "https://atlas.ekenhome.se/api/v1"
OUT = pathlib.Path(".scratch/live-runs/pilot-0.3.0")
TOKEN_BUDGET = 2_000_000
POLL_SECONDS = 20
DEADLINE_SECONDS = 110 * 60
RUNS = {
    1: (
        "For 800G/1.6T AI transceivers, who supplies the laser chips (EML, CW/DFB, VCSEL), who is capacity- or allocation-constrained, and what feedstock or equipment (InP substrates, MOCVD) limits them?",
        ["lumentum", "coherent"],
    ),
    2: (
        "Is indium phosphide substrate supply a chokepoint for optical laser chips: who makes it, how concentrated is it, and do export controls (gallium, germanium, indium) bind?",
        ["axt", "coherent", "lumentum"],
    ),
    3: (
        "Where is transceiver module assembly constrained: contract manufacturing and module capacity, customer concentration, and qualification cycles?",
        ["fabrinet", "applied-optoelectronics", "coherent"],
    ),
    4: (
        "Is the DSP/driver layer a chokepoint for 1.6T modules: who supplies, how many qualified sources, and what are the technology transitions (LPO, CPO)?",
        ["marvell", "macom"],
    ),
    5: (
        "How does coherent-optics and systems demand (DCI, 800ZR) pull on component supply, and where does it bind?",
        ["ciena", "lumentum", "coherent"],
    ),
}


def get(path, base=BASE):
    with urllib.request.urlopen(base + path, timeout=90) as response:
        return json.load(response)


def get_text(url):
    with urllib.request.urlopen(url, timeout=90) as response:
        return response.read().decode()


def post(path, body):
    request = urllib.request.Request(
        BASE + path, data=json.dumps(body).encode(), headers={"content-type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.load(response)


def items(answer):
    return answer["items"] if isinstance(answer, dict) and "items" in answer else answer


def save(target, name, value):
    (target / name).write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding="utf-8")


def ids_under(value, suffixes, found):
    """Every string stored under a key ending in one of `suffixes`, anywhere in `value`."""
    if isinstance(value, dict):
        for key, inner in value.items():
            if isinstance(inner, str) and key.endswith(suffixes):
                found.setdefault(key, set()).add(inner)
            else:
                ids_under(inner, suffixes, found)
    elif isinstance(value, list):
        for inner in value:
            ids_under(inner, suffixes, found)
    return found


def main():
    # `--plan=argument` starts the argument plan (bottleneck-argument ticket 05); the default
    # plan otherwise.
    args = [a for a in sys.argv[1:] if not a.startswith("--plan")]
    plan = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--plan=")), None)
    sys.argv = [sys.argv[0], *args]
    number = int(sys.argv[1])
    question, seeds = RUNS[number]
    # An optional second argument names the output folder (default pilot-0.3.0), so a run on a
    # later version is kept apart: `pilot_runs.py 1 pilot-0.3.1`.
    out = pathlib.Path(".scratch/live-runs") / sys.argv[2] if len(sys.argv) > 2 else OUT
    target = out / f"inv-{number}"
    target.mkdir(parents=True, exist_ok=True)
    state_file = target / "state.json"
    if (target / "investigation.json").exists():
        print(f"investigation {number}: already saved", flush=True)
        return 0
    if state_file.exists():
        state = json.loads(state_file.read_text(encoding="utf-8"))
        print(f"investigation {number}: resuming the poll of {state['id']}", flush=True)
    else:
        version = [
            line for line in get_text("https://atlas.ekenhome.se/metrics").splitlines()
            if line.startswith("atlas_build_info")
        ]
        save(target, "queue-before.json", get("/queue"))
        companies = {c["slug"]: c["id"] for c in items(get("/companies"))}
        started = post(
            "/investigations",
            {
                "theme": "photonics",
                "question": question,
                "seed_company_ids": [companies[s] for s in seeds],
                "budgets": {"token_budget": TOKEN_BUDGET},
                **({"plan": plan} if plan else {}),
            },
        )
        state = {"id": started["id"], "version": version, "seeds": seeds, "started_at": started["created_at"]}
        save(target, "state.json", state)
        print(f"investigation {number}: {state['id']} started on {version}", flush=True)

    investigation_id = state["id"]
    deadline = time.time() + DEADLINE_SECONDS
    paused_polls = 0
    while True:
        time.sleep(POLL_SECONDS)
        try:
            current = get(f"/investigations/{investigation_id}")
        except Exception as error:  # a transient read error: keep polling
            print(f"  poll error: {error}", flush=True)
            continue
        if current["status"] != "running":
            break
        if current.get("paused"):
            paused_polls += 1
            if paused_polls % 15 == 1:
                print(f"  paused for a budget ({paused_polls} polls so far)", flush=True)
        if time.time() > deadline:
            print(f"investigation {number}: still running at the deadline; call again to keep polling", flush=True)
            return 2

    save(target, "investigation.json", current)
    save(target, "queue-after.json", get("/queue"))
    run_id = current["run_id"]
    reads = {
        "role-calls.json": f"/runs/{run_id}/role-calls",
        "claims.json": f"/claims?run_id={run_id}&limit=200",
        "facts.json": f"/facts?investigation_id={investigation_id}&limit=200",
        "events.json": f"/investigations/{investigation_id}/events",
        "relationships.json": "/relationships?sort=created_at&order=desc&limit=200",
        "counterparties.json": "/companies?role=counterparty",
    }
    found = ids_under(current.get("tasks", []), ("discovery_id", "extraction_id"), {})
    for key, values in found.items():
        resource = "discoveries" if key.endswith("discovery_id") else "claim-extractions"
        for value in sorted(values):
            reads[f"{resource}-{value}.json"] = f"/{resource}/{value}"
    for name, path in reads.items():
        try:
            save(target, name, get(path))
        except Exception as error:
            print(f"  could not save {name}: {error}", flush=True)

    command = ["uv", "run", "--no-sync", "python", "scripts/pilot_baseline.py"]
    for seed in seeds:
        command += ["--company", seed]
    command += [
        "--question", question,
        "--investigation", investigation_id,
        "--as-of", current["created_at"],
        "--out", str(target / "baseline"),
    ]
    done = subprocess.run(command, capture_output=True, text=True)
    print(f"  baseline exit {done.returncode} {done.stderr.strip().splitlines()[-1:]}", flush=True)
    print(
        f"investigation {number}: {current['status']} {current.get('stop_reason')} "
        f"usage {current['usage']} paused polls {paused_polls}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
