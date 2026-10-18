"""`agent/scorecard-run.sh` and `agent/scorecard/runs.json`, the early-call scorecard's runner
(atlas-beliefs ticket 29b).

Run as a subprocess under bash with a stand-in `claude` first on the PATH and a stand-in Atlas
over HTTP (`tests/fakes/atlas_http.py`, a subprocess too, so the test process opens no socket):
what is checked is which run list entry the script picks from what Atlas says is done, what it
hands `run.sh`, and that it refuses what it should. Needs bash and node (Git's bash on Windows).
"""

import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from tests.harness import REPO

SCORECARD_RUN = REPO / "agent" / "scorecard-run.sh"
RUNS_FILE = REPO / "agent" / "scorecard" / "runs.json"
ENTRIES: list[dict[str, str]] = json.loads(RUNS_FILE.read_text(encoding="utf-8"))
TOKEN = "sk-ant-oat01-THE-OWNERS-TOKEN-0123456789"

COMPANIES = [
    {"slug": slug, "id": f"id-{slug}"}
    for slug in ("iren", "sandisk", "etoro", "snap", "poet-technologies", "axt")
]


def find_bash() -> str | None:
    if sys.platform == "win32":
        for candidate in (
            r"C:\Program Files\Git\bin\bash.exe",
            r"C:\Program Files (x86)\Git\bin\bash.exe",
        ):
            if Path(candidate).exists():
                return candidate
        return None
    return shutil.which("bash")


BASH = find_bash()
needs_bash = pytest.mark.skipif(
    BASH is None or shutil.which("node") is None,
    reason="agent/scorecard-run.sh needs bash (Git's, on Windows) and node",
)

STUB = """#!/usr/bin/env bash
printf '%s\\n' "$@" >"$STUB_DIR/args.txt"
printf '{"type":"result","subtype":"success","is_error":false,"duration_ms":1,"num_turns":1,'
printf '"result":"ok","session_id":"c1","total_cost_usd":0}\\n'
"""


class Scorecard:
    """One call of scorecard-run.sh with the stand-in `claude` and a stand-in Atlas."""

    def __init__(self, tmp_path: Path) -> None:
        self.root = tmp_path
        self.tmp = tmp_path / "tmp"
        self.stub_dir = tmp_path / "stub"
        self.tmp.mkdir()
        self.stub_dir.mkdir()
        stub = self.stub_dir / "claude"
        stub.write_text(STUB, encoding="utf-8", newline="\n")
        stub.chmod(0o755)
        self.processes: list[subprocess.Popen[str]] = []
        self.posts = tmp_path / "posts.jsonl"
        self.requests = tmp_path / "posts.jsonl.requests"

    def atlas(self, **config: Any) -> str:
        config = {"companies": COMPANIES, "post_id": "opened"} | config
        path = self.root / "atlas-config.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        process = subprocess.Popen(
            [
                sys.executable,
                "-u",
                str(REPO / "tests" / "fakes" / "atlas_http.py"),
                str(path),
                str(self.posts),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        self.processes.append(process)
        assert process.stdout is not None
        port = re.search(r"port (\d+)", process.stdout.readline())
        assert port is not None
        return f"http://127.0.0.1:{port.group(1)}/mcp"

    def call(self, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
        assert BASH is not None
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("ATLAS_", "ANTHROPIC_", "CLAUDE_"))
        }
        environment["PATH"] = os.pathsep.join([str(self.stub_dir), environment.get("PATH", "")])
        environment["STUB_DIR"] = self.stub_dir.as_posix()
        environment["ATLAS_AGENT_TMP"] = self.tmp.as_posix()
        environment["CLAUDE_CODE_OAUTH_TOKEN"] = TOKEN
        environment.update(env)
        return subprocess.run(
            [BASH, SCORECARD_RUN.as_posix(), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=environment,
            timeout=90,
            check=False,
        )

    def stub_was_called(self) -> bool:
        return (self.stub_dir / "args.txt").exists()

    def stub_args(self) -> list[str]:
        return (self.stub_dir / "args.txt").read_text(encoding="utf-8").splitlines()

    def posted(self) -> list[dict[str, Any]]:
        if not self.posts.exists():
            return []
        return [json.loads(line) for line in self.posts.read_text(encoding="utf-8").splitlines()]

    def asked(self) -> list[str]:
        if not self.requests.exists():
            return []
        return self.requests.read_text(encoding="utf-8").splitlines()


@pytest.fixture
def card(tmp_path: Path) -> Iterator[Scorecard]:
    scorecard = Scorecard(tmp_path)
    yield scorecard
    for process in scorecard.processes:
        process.terminate()
        process.wait(timeout=10)


def session_for(entry: dict[str, str], *, isolated: bool = True, **change: Any) -> dict[str, Any]:
    """The Atlas session a run of `entry` leaves (its as-of time written the other way: 'Z')."""
    session: dict[str, Any] = {
        "id": f"session-{entry['case']}-{entry['as_of'][:10]}",
        "question": entry["question"],
        "as_of": entry["as_of"].replace("+00:00", "Z"),
        "seed_company_ids": [f"id-{entry['company']}"],
        "isolated": isolated,
        "theme": "scorecard",
        "started_at": "2026-10-01T05:00:00Z",  # long ago, and closed: never a run in flight
        "finished_at": "2026-10-01T05:30:00Z",
        "tool_calls": 5,
    }
    return session | change


def hours_ago(hours: float) -> str:
    moment = datetime.now(UTC) - timedelta(hours=hours)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


# --- the run list ------------------------------------------------------------------------------


def test_the_run_list_is_the_nine_runs_in_order_with_the_protocols_question() -> None:
    assert [(e["case"], e["company"], e["as_of"][:10]) for e in ENTRIES] == [
        ("iren", "iren", "2025-03-31"),
        ("sandisk", "sandisk", "2025-02-28"),
        ("etoro", "etoro", "2025-09-30"),
        ("iren", "iren", "2025-05-31"),
        ("sandisk", "sandisk", "2025-05-31"),
        ("snap", "snap", "2025-08-31"),
        ("sandisk", "sandisk", "2025-08-31"),
        ("poet", "poet-technologies", "2025-11-30"),
        ("axt", "axt", "2025-08-31"),
    ]
    names = {
        "iren": "IREN",
        "sandisk": "SanDisk",
        "etoro": "eToro",
        "snap": "Snap",
        "poet-technologies": "POET",
        "axt": "AXT",
    }
    for entry in ENTRIES:
        date = entry["as_of"][:10]
        assert entry["as_of"] == f"{date}T23:59:59+00:00"
        assert entry["question"] == (
            f"As of {date}, does anything constrain supply in {names[entry['company']]}'s"
            " market, who holds it, and what would relieve it?"
        )
        # No key, no outcome, no price: these four fields and nothing else.
        assert set(entry) == {"case", "company", "as_of", "question"}


def test_the_run_list_agrees_with_the_scorecards_key() -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "scorecard_key", REPO / "scripts" / "scorecard.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["scorecard_key"] = module
    spec.loader.exec_module(module)
    for entry in ENTRIES:
        case = module.KEY[entry["case"]]
        assert case.slug == entry["company"]
        assert entry["as_of"][:10] in case.as_of_dates
        company = case.name.split(" (")[0]
        assert entry["question"] == module.QUESTION.format(
            date=entry["as_of"][:10], company=company
        )


# --- which entry is next -----------------------------------------------------------------------


@needs_bash
def test_it_picks_the_first_entry_that_has_not_been_run(card: Scorecard) -> None:
    url = card.atlas()

    result = card.call(ATLAS_MCP_URL=url)

    assert result.returncode == 0, result.stderr
    first = ENTRIES[0]
    posted = card.posted()
    assert len(posted) == 1
    assert posted[0]["question"] == first["question"]
    assert posted[0]["as_of"] == first["as_of"]
    assert posted[0]["theme"] == "scorecard"
    assert posted[0]["seed_company_ids"] == ["id-iren"]
    assert posted[0]["isolated"] is True
    # The exact model ID by default, handed to claude and to the session.
    assert posted[0]["model"] == "claude-opus-5-5"
    args = card.stub_args()
    assert args[args.index("--model") + 1] == "claude-opus-5-5"
    assert json.loads(result.stdout.splitlines()[-1])["atlas_session_id"] == "opened"


@needs_bash
def test_it_skips_an_entry_that_has_an_isolated_session_and_compares_the_time_as_an_instant(
    card: Scorecard,
) -> None:
    # The session writes the as-of time with a Z and the list with +00:00: the same instant.
    url = card.atlas(sessions=[session_for(ENTRIES[0])])

    result = card.call(ATLAS_MCP_URL=url)

    assert result.returncode == 0, result.stderr
    assert [p["question"] for p in card.posted()] == [ENTRIES[1]["question"]]
    assert card.posted()[0]["seed_company_ids"] == ["id-sandisk"]


@needs_bash
def test_it_does_not_skip_an_entry_for_a_session_that_is_not_isolated(card: Scorecard) -> None:
    url = card.atlas(sessions=[session_for(ENTRIES[0], isolated=False)])

    card.call(ATLAS_MCP_URL=url)

    assert [p["question"] for p in card.posted()] == [ENTRIES[0]["question"]]


@needs_bash
@pytest.mark.parametrize(
    "change",
    [
        {"question": "As of 2025-03-31, a different question?"},
        {"as_of": "2025-03-31T00:00:00Z"},
        {"seed_company_ids": ["id-sandisk"]},
        {"seed_company_ids": ["id-iren", "id-sandisk"]},
    ],
)
def test_a_session_of_another_question_time_or_seed_is_not_this_entrys(
    card: Scorecard, change: dict[str, Any]
) -> None:
    url = card.atlas(sessions=[session_for(ENTRIES[0], **change)])

    card.call(ATLAS_MCP_URL=url)

    assert [p["question"] for p in card.posted()] == [ENTRIES[0]["question"]]


@needs_bash
def test_it_reports_done_when_every_entry_has_been_run(card: Scorecard) -> None:
    url = card.atlas(sessions=[session_for(entry) for entry in ENTRIES])

    result = card.call(ATLAS_MCP_URL=url)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"scorecard": "done"}
    assert not card.stub_was_called()
    assert card.posted() == []


@needs_bash
def test_a_run_that_failed_after_its_session_opened_still_counts_as_run(card: Scorecard) -> None:
    # Its session exists, closed or not, with or without Beliefs: the entry is not retried.
    url = card.atlas(sessions=[session_for(ENTRIES[0], finished_at=None, facts=0, tool_calls=2)])

    card.call(ATLAS_MCP_URL=url)

    assert [p["question"] for p in card.posted()] == [ENTRIES[1]["question"]]


@needs_bash
def test_it_reads_every_page_of_the_session_list(card: Scorecard) -> None:
    # 600 other sessions come before the one that matters: the list is paged at 500.
    filler = [session_for(ENTRIES[0], isolated=False, id=f"filler-{index}") for index in range(600)]
    url = card.atlas(sessions=[*filler, session_for(ENTRIES[0])])

    card.call(ATLAS_MCP_URL=url)

    assert [p["question"] for p in card.posted()] == [ENTRIES[1]["question"]]
    assert sum(1 for each in card.asked() if each.startswith("GET /api/v1/sessions")) == 2


@needs_bash
def test_an_entry_is_run_only_once_its_session_has_recorded_a_tool_call(card: Scorecard) -> None:
    # A POST that timed out after Atlas created the session, and a run that died before its first
    # call, left a session with no call: that does not spend the entry.
    url = card.atlas(sessions=[session_for(ENTRIES[0], tool_calls=0)])

    card.call(ATLAS_MCP_URL=url)

    assert [p["question"] for p in card.posted()] == [ENTRIES[0]["question"]]


@needs_bash
def test_it_waits_while_a_scorecard_session_is_open_and_recent(card: Scorecard) -> None:
    open_now = session_for(
        ENTRIES[0], started_at=hours_ago(1), finished_at=None, id="in-flight", tool_calls=3
    )
    url = card.atlas(sessions=[open_now])

    result = card.call(ATLAS_MCP_URL=url)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "scorecard": "busy",
        "session": "in-flight",
        "started_at": open_now["started_at"],
    }
    assert not card.stub_was_called()
    assert card.posted() == []


@needs_bash
def test_it_waits_for_an_open_session_with_no_call_too(card: Scorecard) -> None:
    url = card.atlas(
        sessions=[
            session_for(ENTRIES[0], started_at=hours_ago(5.5), finished_at=None, tool_calls=0)
        ]
    )

    result = card.call(ATLAS_MCP_URL=url)

    assert json.loads(result.stdout)["scorecard"] == "busy"
    assert not card.stub_was_called()


@needs_bash
@pytest.mark.parametrize(
    "change",
    [
        {"started_at": hours_ago(7), "finished_at": None},  # open, but older than six hours
        {"started_at": hours_ago(1), "finished_at": hours_ago(0.5)},  # closed
        {"started_at": hours_ago(1), "finished_at": None, "isolated": False},
        {"started_at": hours_ago(1), "finished_at": None, "theme": "photonics"},
    ],
)
def test_it_does_not_wait_for_a_session_that_is_old_closed_not_isolated_or_not_the_scorecards(
    card: Scorecard, change: dict[str, Any]
) -> None:
    url = card.atlas(sessions=[session_for(ENTRIES[0]) | change])

    result = card.call(ATLAS_MCP_URL=url)

    assert result.returncode == 0, result.stderr
    assert len(card.posted()) == 1  # it ran an entry: busy only for an open, recent, isolated one


# --- what it refuses ---------------------------------------------------------------------------


@needs_bash
@pytest.mark.parametrize("alias", ["opus", "sonnet", "claude-opus", "claude-opus-5-5[1m]", "5-5"])
def test_it_refuses_a_model_alias_before_asking_atlas_anything(card: Scorecard, alias: str) -> None:
    url = card.atlas()

    result = card.call(ATLAS_MCP_URL=url, ATLAS_AGENT_MODEL=alias)

    assert result.returncode == 2
    assert "exact model ID" in result.stderr
    assert not card.stub_was_called()
    assert card.asked() == []


@needs_bash
def test_it_takes_another_exact_model_id(card: Scorecard) -> None:
    url = card.atlas()

    result = card.call(ATLAS_MCP_URL=url, ATLAS_AGENT_MODEL="claude-opus-5-6")

    assert result.returncode == 0, result.stderr
    assert card.posted()[0]["model"] == "claude-opus-5-6"


@needs_bash
def test_it_runs_nothing_when_atlas_cannot_be_asked(card: Scorecard) -> None:
    # Nothing listens on the discard port.
    result = card.call(ATLAS_MCP_URL="http://127.0.0.1:9/mcp")

    assert result.returncode != 0
    assert "could not be asked which runs are done" in result.stderr
    assert not card.stub_was_called()


@needs_bash
def test_it_runs_nothing_when_atlas_does_not_know_the_company(card: Scorecard) -> None:
    url = card.atlas(companies=[each for each in COMPANIES if each["slug"] != "iren"])

    result = card.call(ATLAS_MCP_URL=url)

    assert result.returncode != 0
    assert "company Atlas does not have: iren" in result.stderr
    assert not card.stub_was_called()
    assert card.posted() == []


@needs_bash
def test_a_wrong_call_is_a_usage_error(card: Scorecard) -> None:
    result = card.call("--bogus")

    assert result.returncode == 2
    assert "usage: scorecard-run.sh" in result.stderr


@needs_bash
def test_dry_run_is_passed_to_run_sh_which_calls_nothing(card: Scorecard) -> None:
    url = card.atlas(sessions=[session_for(ENTRIES[0])])

    result = card.call("--dry-run", ATLAS_MCP_URL=url)

    assert result.returncode == 0, result.stderr
    assert not card.stub_was_called()
    assert card.posted() == []
    assert "isolated: true" in result.stdout
    assert "seeds: sandisk" in result.stdout
    assert f"question: {ENTRIES[1]['question']}" in result.stdout
    assert " --model claude-opus-5-5" in result.stdout
    assert "Theme: scorecard" in result.stdout
    assert TOKEN not in result.stdout + result.stderr
