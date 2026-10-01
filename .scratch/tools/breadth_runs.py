"""Breadth runs of pilot investigations 2-5 on production (pilot-review ticket 16).

One at a time: start, poll until it stops, save the investigation JSON, its claims and role
calls. No review. Run from the repo root; output under .scratch/live-runs/breadth-0.2.5/.
"""

import json
import pathlib
import sys
import time
import urllib.request

BASE = "https://atlas.ekenhome.se/api/v1"
OUT = pathlib.Path(".scratch/live-runs/breadth-0.2.5")
RUNS = [
    (
        2,
        "Is indium phosphide substrate supply a chokepoint for optical laser chips: who makes it, how concentrated is it, and do export controls (gallium, germanium, indium) bind?",
        ["axt", "coherent", "lumentum"],
    ),
    (
        3,
        "Where is transceiver module assembly constrained: contract manufacturing and module capacity, customer concentration, and qualification cycles?",
        ["fabrinet", "applied-optoelectronics", "coherent"],
    ),
    (
        4,
        "Is the DSP/driver layer a chokepoint for 1.6T modules: who supplies, how many qualified sources, and what are the technology transitions (LPO, CPO)?",
        ["marvell", "macom"],
    ),
    (
        5,
        "How does coherent-optics and systems demand (DCI, 800ZR) pull on component supply, and where does it bind?",
        ["ciena", "lumentum", "coherent"],
    ),
]


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=90) as response:
        return json.load(response)


def post(path, body):
    request = urllib.request.Request(
        BASE + path, data=json.dumps(body).encode(), headers={"content-type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.load(response)


def items(answer):
    return answer["items"] if isinstance(answer, dict) and "items" in answer else answer


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    companies = {c["slug"]: c["id"] for c in items(get("/companies"))}
    only = {int(a) for a in sys.argv[1:]} or {n for n, _, _ in RUNS}
    for number, question, seeds in RUNS:
        if number not in only:
            continue
        target = OUT / f"inv-{number}.json"
        if target.exists():
            print(f"investigation {number}: already saved, skipping", flush=True)
            continue
        started = post(
            "/investigations",
            {"theme": "photonics", "question": question, "seed_company_ids": [companies[s] for s in seeds]},
        )
        investigation_id = started["id"]
        print(f"investigation {number}: {investigation_id} started", flush=True)
        deadline = time.time() + 45 * 60
        while True:
            time.sleep(20)
            try:
                current = get(f"/investigations/{investigation_id}")
            except Exception as error:  # a transient read error: keep polling
                print(f"  poll error: {error}", flush=True)
                continue
            if current["status"] != "running" or time.time() > deadline:
                break
        target.write_text(json.dumps(current), encoding="utf-8")
        run_id = current["run_id"]
        for name, path in (
            ("role-calls", f"/runs/{run_id}/role-calls"),
            ("claims", f"/claims?run_id={run_id}&limit=200"),
        ):
            try:
                (OUT / f"inv-{number}-{name}.json").write_text(json.dumps(get(path)), encoding="utf-8")
            except Exception as error:
                print(f"  could not save {name}: {error}", flush=True)
        print(
            f"investigation {number}: {current['status']} {current.get('stop_reason')} "
            f"usage {current['usage']} paused={current.get('paused')}",
            flush=True,
        )


if __name__ == "__main__":
    main()
