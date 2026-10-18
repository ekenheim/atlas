"""The Watch's board for the e2e (UI round 3, spec §10.8), seeded through the public routes of
the first served API, after it starts and before Playwright runs.

Photonics gets six chokepoints, one per state the pages must read: A thesis-ready, B below the
bar (its falsifiers cleared), F needing a new open question (its only question answered), C a
candidate with a contradicted step and a step resting on an Issue alone, D ruled out, E spotted
with no holder; and a weekly run whose memo carries everything the renderer must neutralise.
Robotics, which the e2e universe does not list, gets a first survey and one chokepoint.
Memory-packaging gets nothing: the empty-state control.

Only A's creation and one event carry a session (it must be of now, so it is opened here and
closed with no card); every other write omits the session. The five Issues are new, so the
Issues the other specs read are left as they are.
"""

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx2

SESSION_QUESTION = "Is laser capacity the constraint on AI optics?"
WATCH_QUESTION = "What does the Watch see in photonics this week?"

A = "Indium phosphide laser capacity"
B = "EML supply for 800G transceivers"
F = "Indium phosphide substrate export permits"
C = "CW lasers for silicon photonics"
D = "Pump laser capacity"
E = "MOCVD reactor lead times"
ROBOTICS = "Precision strain-wave reducer capacity"
KILL_REASON = "Supply added faster than demand."
FALSIFIERS = ["A second indium phosphide laser source qualifies at a hyperscaler"]

CLEAN = """Two makers hold most precision reducer capacity, and the humanoid programmes would need
more of it than both plan to add.

## Discoveries

- Precision strain-wave reducer capacity: lead times stretched, two makers at scale.

## Rejections

- Robot controllers: many suppliers, nothing scarce.

## Changes

This is the first survey: everything on the board is new.

## Next questions

- How much reducer capacity do the humanoid programmes assume for 2027?
"""

# Everything the memo renderer must neutralise (§10.8, item 11). `{link}` is A's board link; the
# bare UUID is not one of the board's.
DIRTY = """# Photonics this week

[A]({link}) is `thesis_ready` now, and step d holds:
Fact 3f2b8c1e-9d4a-4b6e-8f10-2a3b4c5d6e7f shows it.

- **Bold** progress on the board
- [ok](https://example.com) and [bad](javascript:window.__pwned=1)

<script>window.__pwned=1</script>

```
uv run atlas ingest --company x
```

## Next questions

- Who else could qualify a laser line?
"""


def _ok(response: httpx2.Response) -> Any:
    if response.status_code >= 400:
        raise SystemExit(
            f"e2e: seeding the board failed: {response.request.method} {response.request.url}"
            f" answered {response.status_code}: {response.text}"
        )
    return response.json()


def seed_board(base_url: str) -> None:
    """Seed the board through the API at `base_url`."""
    with httpx2.Client(base_url=f"{base_url}/api/v1", timeout=60.0) as client:

        def get(path: str, **params: Any) -> Any:
            return _ok(client.get(path, params=params))

        def post(path: str, body: dict[str, Any] | None = None) -> Any:
            return _ok(client.post(path, json=body or {}))

        def event(cp: str, kind: str, payload: dict[str, Any], **more: Any) -> Any:
            return post(f"/chokepoints/{cp}/events", {"kind": kind, "payload": payload, **more})

        companies = get("/companies", limit=500)["items"]
        lumentum = next(each["id"] for each in companies if each["slug"] == "lumentum")
        sessions = get("/sessions", limit=500)["items"]
        seeded = next(each["id"] for each in sessions if each["question"] == SESSION_QUESTION)
        facts = [each["id"] for each in get("/facts", session_id=seeded, limit=10)["items"]]
        if len(facts) < 2:
            raise SystemExit(f"e2e: the seeded session has {len(facts)} Facts, not 2")
        issues = [
            post(
                "/issues",
                {
                    "title": f"Watch question {n}: who else could supply it?",
                    "theme": "photonics",
                    "kind": "question",
                    "priority": 0,
                },
            )["id"]
            for n in range(1, 6)
        ]
        i1, i2, i3, i4, _i5 = issues

        session = post(
            "/sessions",
            {
                "question": WATCH_QUESTION,
                "theme": "photonics",
                "as_of": datetime.now(UTC).isoformat(),
                "seed_company_ids": [lumentum],
                "actor": "e2e-watch",
            },
        )["id"]
        holders = [{"name": "Lumentum", "slug": "lumentum"}, {"name": "Outside Holder Co"}]

        def thesis_ready(constraint: str, issue: str, session_id: str | None = None) -> str:
            created = post(
                "/chokepoints",
                {
                    "theme": "photonics",
                    "constraint": constraint,
                    "layer": "laser",
                    "holders": holders,
                    **({"session_id": session_id} if session_id else {}),
                },
            )["id"]
            first = {
                "step": "constraint",
                "status": "primary",
                "evidence": {"fact_ids": [facts[0]]},
            }
            if session_id:
                event(created, "step_set", first, session_id=session_id)
                post(f"/sessions/{session_id}/close", {"usage": {}})
            else:
                event(created, "step_set", first)
            event(
                created,
                "step_set",
                {
                    "step": "demand_vs_supply",
                    "status": "primary",
                    "evidence": {"fact_ids": [facts[1]]},
                },
            )
            event(
                created,
                "step_set",
                {
                    "step": "control",
                    "status": "primary",
                    "evidence": {"fact_ids": [facts[0], facts[1]]},
                },
            )
            event(
                created,
                "step_set",
                {"step": "capture", "status": "lead", "evidence": {"issue_ids": [issue]}},
            )
            event(
                created,
                "field_set",
                {
                    "kill_criteria": FALSIFIERS,
                    "add_issue_ids": [issue],
                    "crowding": "early",
                    "relief_horizon": {
                        "horizon": "2028, once a second laser line is qualified",
                        "basis": "No second source has named a qualification date.",
                    },
                },
            )
            event(created, "status_set", {"status": "candidate"})
            event(created, "status_set", {"status": "thesis_ready"})
            return created

        a = thesis_ready(A, i1, session)
        b = thesis_ready(B, i2)
        event(b, "field_set", {"kill_criteria": []})
        f = thesis_ready(F, i3)
        post(f"/issues/{i3}/complete")

        c = post(
            "/chokepoints",
            {
                "theme": "photonics",
                "constraint": C,
                "layer": "laser",
                "holders": [{"name": "Coherent", "slug": "coherent"}],
            },
        )["id"]
        event(
            c,
            "step_set",
            {
                "step": "invalidation",
                "status": "contradicted",
                "evidence": {"fact_ids": [facts[0]]},
            },
        )
        event(c, "step_set", {"step": "relief", "status": "lead", "evidence": {"issue_ids": [i4]}})
        event(c, "status_set", {"status": "candidate"})

        d = post("/chokepoints", {"theme": "photonics", "constraint": D, "layer": "laser"})["id"]
        event(d, "status_set", {"status": "killed"}, reason=KILL_REASON)

        post("/chokepoints", {"theme": "photonics", "constraint": E, "layer": "equipment"})

        today = datetime.now(UTC).date().isoformat()
        post(
            "/chokepoints",
            {
                "theme": "robotics",
                "constraint": ROBOTICS,
                "layer": "reducer",
                "holders": [{"name": "Harmonic Drive Systems"}, {"name": "Nabtesco"}],
            },
        )
        post(
            "/watch-runs",
            {
                "theme": "robotics",
                "mode": "architect",
                "run_date": today,
                "memo": CLEAN,
                "tool_calls": 212,
                "cost_usd": 3.1,
            },
        )
        post(
            "/watch-runs",
            {
                "theme": "photonics",
                "mode": "delta",
                "run_date": today,
                "memo": DIRTY.format(link=f"atlas:chokepoint/{a}"),
                "tool_calls": 96,
            },
        )
        board = get("/chokepoints", limit=500)
        print(
            f"e2e: the board: {board['total']} chokepoints (A {a}, B {b}, F {f}, C {c}, D {d})",
            flush=True,
        )
        # `ATLAS_E2E_BOARD_FIXTURE=<path>` writes the board as answered (the unit tests' real
        # board answer, `frontend/unit/fixtures/board.json`).
        fixture = os.environ.get("ATLAS_E2E_BOARD_FIXTURE")
        if fixture:
            Path(fixture).write_text(json.dumps(board, indent=1) + "\n", encoding="utf-8")
