"""`agent/run.sh`, the scheduled agents' runner (atlas-beliefs ticket 17).

Run as a subprocess under bash with a stand-in `claude` first on the PATH: nothing calls the
network, the model or the real Claude Code. What is checked is what the runner does around
`claude`: the command it builds, the MCP config it writes, the prompt it fills in, the summary
line it prints, its exit status, and that the owner's token never appears in anything it prints
or writes.

Needs bash and node (the runner parses claude's JSON result with node, as the image has it). On
Windows only Git's bash runs these paths (WSL's cannot); the Linux runners have both.
"""

import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUN_SH = ROOT / "agent" / "run.sh"
TOKEN = "sk-ant-oat01-THE-OWNERS-TOKEN-0123456789"
AS_OF = "2026-10-20T05:00:00+00:00"
DEFAULT_URL = "http://atlas.development.svc.cluster.local:8000/mcp"


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
pytestmark = pytest.mark.skipif(
    BASH is None or shutil.which("node") is None,
    reason="agent/run.sh needs bash (Git's, on Windows) and node",
)

# Stands in for `claude`: records what it was called with, answers like `--output-format json`.
STUB = """#!/usr/bin/env bash
printf '%s\\n' "$@" >"$STUB_DIR/args.txt"
pwd >"$STUB_DIR/cwd.txt"
printf '%s' "${CLAUDE_CODE_OAUTH_TOKEN:-}" >"$STUB_DIR/token-seen.txt"
printf '%s' "${ANTHROPIC_API_KEY:-unset}" >"$STUB_DIR/api-key-seen.txt"
printf '%s' "${ENABLE_TOOL_SEARCH:-unset}" >"$STUB_DIR/tool-search-seen.txt"
echo "stderr: the stand-in saw $CLAUDE_CODE_OAUTH_TOKEN" >&2
case "${STUB_MODE:-success}" in
  success)
    printf '{"type":"result","subtype":"success","is_error":false,"duration_ms":1234,"num_turns":7,'
    printf '"result":"%s",' "${STUB_RESULT:-all done}"
    printf '"session_id":"3f1c0d2e","total_cost_usd":0.5}\\n'
    ;;
  max_turns)
    printf '{"type":"result","subtype":"error_max_turns","is_error":false,'
    printf '"duration_ms":99,"num_turns":100,'
    printf '"session_id":"3f1c0d2e","total_cost_usd":1.25}\\n'
    ;;
  is_error)
    printf '{"type":"result","subtype":"success","is_error":true,"duration_ms":99,"num_turns":1,'
    printf '"result":"Invalid API key","session_id":"3f1c0d2e","total_cost_usd":0}\\n'
    ;;
  crash)
    echo "boom $CLAUDE_CODE_OAUTH_TOKEN" >&2
    exit 3
    ;;
esac
"""


def posix(path: Path) -> str:
    return path.as_posix()


class Run:
    """One call of run.sh in a scratch directory, with the stand-in `claude` on the PATH."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp = tmp_path / "tmp"
        self.stub_dir = tmp_path / "stub"
        self.tmp.mkdir()
        self.stub_dir.mkdir()
        stub = self.stub_dir / "claude"
        stub.write_text(STUB, encoding="utf-8", newline="\n")
        stub.chmod(0o755)

    def call(
        self, *args: str, token: str | None = TOKEN, **env: str
    ) -> subprocess.CompletedProcess[str]:
        assert BASH is not None
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("ATLAS_", "ANTHROPIC_", "CLAUDE_"))
        }
        environment["PATH"] = os.pathsep.join([str(self.stub_dir), environment.get("PATH", "")])
        environment["STUB_DIR"] = posix(self.stub_dir)
        environment["ATLAS_AGENT_TMP"] = posix(self.tmp)
        environment["ATLAS_AGENT_AS_OF"] = AS_OF
        if token is not None:
            environment["CLAUDE_CODE_OAUTH_TOKEN"] = token
        environment.update(env)
        return subprocess.run(
            [BASH, posix(RUN_SH), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=environment,
            timeout=60,
            check=False,
        )

    def stub_was_called(self) -> bool:
        return (self.stub_dir / "args.txt").exists()

    def stub_args(self) -> list[str]:
        return (self.stub_dir / "args.txt").read_text(encoding="utf-8").splitlines()


@pytest.fixture
def run(tmp_path: Path) -> Run:
    return Run(tmp_path)


COMPANIES = [{"slug": "sandisk", "id": "id-sandisk"}, {"slug": "iren", "id": "id-iren"}]


class FakeAtlas:
    """`tests/fakes/atlas_http.py` as a subprocess (the test process opens no socket): the
    companies, sessions and session POST run.sh talks to when it opens an isolated session."""

    def __init__(self, tmp_path: Path, **config: Any) -> None:
        config = {"companies": COMPANIES, "post_id": "opened-by-run-sh"} | config
        self.posts = tmp_path / "posts.jsonl"
        self.requests = tmp_path / "posts.jsonl.requests"
        (tmp_path / "atlas-config.json").write_text(json.dumps(config), encoding="utf-8")
        self.process = subprocess.Popen(
            [
                sys.executable,
                "-u",
                str(ROOT / "tests" / "fakes" / "atlas_http.py"),
                str(tmp_path / "atlas-config.json"),
                str(self.posts),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        assert self.process.stdout is not None
        port = re.search(r"port (\d+)", self.process.stdout.readline())
        assert port is not None
        self.mcp_url = f"http://127.0.0.1:{port.group(1)}/mcp"

    def posted(self) -> list[dict[str, Any]]:
        if not self.posts.exists():
            return []
        return [json.loads(line) for line in self.posts.read_text(encoding="utf-8").splitlines()]

    def asked(self) -> list[str]:
        if not self.requests.exists():
            return []
        return self.requests.read_text(encoding="utf-8").splitlines()

    def stop(self) -> None:
        self.process.terminate()
        self.process.wait(timeout=10)


@pytest.fixture
def atlas(tmp_path: Path) -> Iterator[Callable[..., FakeAtlas]]:
    started: list[FakeAtlas] = []

    def start(**config: Any) -> FakeAtlas:
        started.append(FakeAtlas(tmp_path, **config))
        return started[-1]

    yield start
    for each in started:
        each.stop()


def everything_printed_or_written(result: subprocess.CompletedProcess[str], run: Run) -> str:
    text = result.stdout + result.stderr
    for path in run.tmp.rglob("*"):
        if path.is_file():
            text += path.read_text(encoding="utf-8", errors="replace")
    return text


@pytest.mark.parametrize("agent", ["scout", "researcher", "skeptic"])
def test_dry_run_prints_the_command_and_calls_nothing(run: Run, agent: str):
    result = run.call(agent, "--dry-run")

    assert result.returncode == 0, result.stderr
    assert not run.stub_was_called()
    assert list(run.tmp.iterdir()) == [], "a dry run writes nothing"
    command = next(
        line for line in result.stdout.splitlines() if line.startswith("command: claude -p ")
    )
    assert " --strict-mcp-config" in command
    assert f" --mcp-config {posix(run.tmp)}/atlas-mcp.json" in command
    assert " --allowedTools mcp__atlas 'mcp__atlas__*' Read Write Edit Glob" in command
    assert " --tools Read,Write,Edit,Glob" in command
    assert f" --add-dir {posix(run.tmp)}/out" in command
    assert " --model opus" in command
    assert " --output-format json" in command
    assert re.search(r" --max-turns [1-9][0-9]*( |$)", command)
    assert DEFAULT_URL in result.stdout
    assert '"atlas":{"type":"http"' in result.stdout


@pytest.mark.parametrize("agent", ["scout", "researcher", "skeptic"])
def test_dry_run_prompt_is_filled_in_and_says_nothing_is_judged_or_published(run: Run, agent: str):
    result = run.call(agent, "--dry-run")

    prompt = result.stdout.split("prompt:\n", 1)[1]
    assert "{{" not in prompt
    assert "photonics" in prompt
    assert AS_OF in prompt
    assert f"{posix(run.tmp)}/out" in prompt
    assert re.search(r"Call bound: [1-9][0-9]* ", prompt)
    assert "You set no judgement" in prompt
    assert "You publish nothing" in prompt
    assert (
        f".claude/skills/atlas-research/{'SKILL' if agent == 'researcher' else agent}.md" in prompt
    )


def test_the_researcher_starts_from_the_frontier_and_uses_both_banks(run: Run):
    prompt = run.call("researcher", "--dry-run").stdout.split("prompt:\n", 1)[1]

    assert "Start from `next_issue`" in prompt
    assert "- Actor: pass `actor: atlas-researcher` to `open_session`" in prompt
    assert "`bank: research`" in prompt
    assert "`bank: beliefs`" in prompt
    assert "born `unproven`" in prompt


ISOLATED_TOOLS = [
    "close_session",
    "companies",
    "search",
    "read",
    "locate",
    "record_fact",
    "get_fact",
    "judge_statement",
    "relate_facts",
    "propose_belief",
    "cite_belief",
    "recall",
]
BUILT_IN = ["Read", "Write", "Edit", "Glob"]

SCORECARD_QUESTION = (
    "As of 2025-02-28, does anything constrain supply in SanDisk's market, who holds it, and"
    " what would relieve it? {{not a placeholder}} & more"
)


def scorecard_run(run: Run, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
    settings = {
        "ATLAS_AGENT_THEME": "scorecard",
        "ATLAS_AGENT_AS_OF": "2025-02-28T00:00:00+00:00",
        "ATLAS_AGENT_MODEL": "claude-opus-5-5",
        "ATLAS_AGENT_QUESTION": SCORECARD_QUESTION,
        "ATLAS_AGENT_SEEDS": "sandisk",
        "ATLAS_AGENT_ISOLATED": "true",
    }
    return run.call("researcher", *args, **(settings | env))


def test_a_given_question_and_seeds_replace_next_issue_in_the_dry_run(run: Run):
    result = scorecard_run(run, "--dry-run")

    assert result.returncode == 0, result.stderr
    assert f"question: {SCORECARD_QUESTION}" in result.stdout
    assert "seeds: sandisk" in result.stdout
    assert "isolated: true" in result.stdout
    assert " --model claude-opus-5-5" in result.stdout  # the exact ID, not an alias
    prompt = result.stdout.split("prompt:\n", 1)[1]
    # The question verbatim (braces and an ampersand intact), the seeds as slugs, no frontier.
    assert f"do not call `next_issue`): {SCORECARD_QUESTION}" in prompt
    assert "Seed companies: sandisk (slugs; already the session's seeds)." in prompt
    assert "Start from `next_issue`" not in prompt
    assert "Theme: scorecard" in prompt
    assert "2025-02-28T00:00:00+00:00" in prompt


def test_several_seeds_are_listed_in_the_prompt(run: Run):
    prompt = scorecard_run(run, "--dry-run", ATLAS_AGENT_SEEDS="iren,etoro").stdout.split(
        "prompt:\n", 1
    )[1]

    assert "Seed companies: iren, etoro (slugs;" in prompt


def test_an_isolated_run_tells_the_researcher_its_session_is_open_and_to_use_only_its_tools(
    run: Run,
):
    prompt = scorecard_run(run, "--dry-run").stdout.split("prompt:\n", 1)[1]

    assert "its Atlas session is already open" in prompt
    assert "Pass that `session_id` to every tool call" in prompt
    assert "Do not call `open_session`" in prompt
    assert "call `close_session` with your card" in prompt
    assert "pass `isolated: true` to `open_session`" not in prompt
    assert "pass it to `open_session`" not in prompt  # the wrapper's as-of line, rewritten
    assert "pass them to `open_session`" not in prompt
    # The actor the wrapper tells a routine to pass is the session's already (run.sh sets it).
    assert "to `open_session`" not in prompt
    assert "the session already has `actor: atlas-researcher`" in prompt
    assert "Your tools are exactly the ones on the Tools line below" in prompt
    assert "facts, never observations" in prompt
    assert "use only what the tools return" in prompt
    assert "Atlas will never judge it" in prompt
    assert "Cite only Facts you recorded in this session" in prompt
    # The standing rules stay: nothing judged, nothing published.
    assert "You set no judgement" in prompt
    assert "You publish nothing" in prompt
    assert "{{" not in prompt.replace("{{not a placeholder}}", "")
    # The Tools line is the allow-list, not the researcher's whole set.
    assert f"\nTools: {', '.join(ISOLATED_TOOLS)}\n" in prompt
    for refused in (
        "open_session",
        "prior_work",
        "examine_belief",
        "list_beliefs",
        "next_issue",
        "open_issue",
    ):
        assert refused not in prompt.split("\nTools: ", 1)[1].split("\n", 1)[0]


def test_the_isolated_prompt_names_every_tool_that_is_off_the_list(run: Run):
    # The Tools line and the named list together are the server's tools, none twice: a tool the
    # server gains is on neither, and this test fails until someone decides where it goes.
    from atlas.mcp.server import McpServer

    prompt = scorecard_run(run, "--dry-run").stdout.split("prompt:\n", 1)[1]
    recall = next(line for line in prompt.splitlines() if line.startswith("- Recall:"))
    named = re.findall(r"`([a-z_]+)`", recall.split("are not available to you", 1)[1])
    on_list = prompt.split("\nTools: ", 1)[1].split("\n", 1)[0].split(", ")
    server = {each["name"] for each in McpServer.tool_list()}

    assert on_list == ISOLATED_TOOLS
    assert len(named) == len(set(named))
    assert not set(named) & set(on_list)
    assert set(named) | set(on_list) == server, sorted(server ^ (set(named) | set(on_list)))
    # The sixteen the lead named, whatever else the server lists.
    assert {
        "open_session",
        "supersede_belief",
        "examine_belief",
        "list_beliefs",
        "get_belief",
        "prior_work",
        "open_issue",
        "narrow_issue",
        "complete_issue",
        "next_issue",
        "list_issues",
        "draft_hypothesis",
        "get_hypothesis",
        "signal_leads",
        "upcoming_reports",
        "newest_documents",
    } <= set(named)


def test_a_question_without_isolation_still_uses_prior_work_and_both_banks(run: Run):
    result = scorecard_run(run, "--dry-run", ATLAS_AGENT_ISOLATED="false")

    prompt = result.stdout.split("prompt:\n", 1)[1]
    assert "isolated: false" in result.stdout
    assert "do not call `next_issue`" in prompt
    assert "call `prior_work`" in prompt
    assert "`bank: beliefs` is in use" in prompt
    assert "isolated: true" not in prompt


def test_the_default_dry_run_shows_no_question_seeds_or_isolation(run: Run):
    result = run.call("researcher", "--dry-run")

    assert "question: none (next_issue)" in result.stdout
    assert "seeds: none" in result.stdout
    assert "isolated: false" in result.stdout


def test_an_isolated_run_opens_its_session_before_claude_and_gives_claude_its_id(
    run: Run, atlas: Callable[..., FakeAtlas]
):
    fake = atlas()

    result = scorecard_run(run, ATLAS_MCP_URL=fake.mcp_url)

    assert result.returncode == 0, result.stderr
    # One POST, from run.sh, before claude: isolated, the run's theme, question, seeds (slugs
    # looked up to ids), as-of time and model, and an actor naming the agent.
    assert fake.posted() == [
        {
            "question": SCORECARD_QUESTION,
            "theme": "scorecard",
            "seed_company_ids": ["id-sandisk"],
            "as_of": "2025-02-28T00:00:00+00:00",
            "model": "claude-opus-5-5",
            "actor": "atlas-researcher",
            "isolated": True,
        }
    ]
    args = run.stub_args()
    assert args[args.index("--model") + 1] == "claude-opus-5-5"
    prompt = "\n".join(args)
    assert SCORECARD_QUESTION in prompt
    assert "its `session_id` is opened-by-run-sh." in prompt
    assert "<the Atlas session id" not in prompt
    assert "pass `isolated: true` to `open_session`" not in prompt
    # The log line names that session directly, and says when the run started and finished.
    summary = json.loads(result.stdout.splitlines()[0])
    assert summary["atlas_session_id"] == "opened-by-run-sh"
    assert summary["ok"] is True
    assert summary["started_at"] <= summary["finished_at"]
    assert len(result.stdout.splitlines()) == 1


def test_an_isolated_run_names_its_session_without_matching_by_question_or_date(
    run: Run, atlas: Callable[..., FakeAtlas]
):
    # Another session shares the run's as-of time, question and seeds: no matching is done.
    lookalike = {
        "id": "lookalike",
        "as_of": "2025-02-28T00:00:00Z",
        "question": SCORECARD_QUESTION,
        "seed_company_ids": ["id-sandisk"],
        "actor": "atlas-researcher",
    }
    fake = atlas(sessions=[lookalike])

    result = scorecard_run(run, ATLAS_MCP_URL=fake.mcp_url)

    assert json.loads(result.stdout.splitlines()[0])["atlas_session_id"] == "opened-by-run-sh"
    assert "GET /api/v1/sessions?limit=50" not in fake.asked()


def test_an_isolated_run_whose_session_cannot_be_opened_fails_without_calling_claude(
    run: Run, atlas: Callable[..., FakeAtlas]
):
    fake = atlas(post_status=500)

    result = scorecard_run(run, ATLAS_MCP_URL=fake.mcp_url)

    assert result.returncode == 1
    assert not run.stub_was_called()
    lines = result.stdout.splitlines()
    assert len(lines) == 1
    summary = json.loads(lines[0])
    assert summary["ok"] is False and summary["agent"] == "researcher"
    assert summary["atlas_session_id"] is None
    assert "answered 500" in summary["reason"]
    assert summary["started_at"] <= summary["finished_at"]
    assert "could not open the isolated Atlas session" in result.stderr
    assert TOKEN not in result.stdout + result.stderr


def test_an_isolated_run_with_no_atlas_to_ask_fails_without_calling_claude(run: Run):
    # Nothing listens on the discard port.
    result = scorecard_run(run, ATLAS_MCP_URL="http://127.0.0.1:9/mcp")

    assert result.returncode == 1
    assert not run.stub_was_called()
    summary = json.loads(result.stdout)
    assert summary["ok"] is False
    assert "Atlas is unreachable" in summary["reason"]


def test_an_isolated_run_with_an_unknown_seed_fails_before_it_posts_anything(
    run: Run, atlas: Callable[..., FakeAtlas]
):
    fake = atlas()

    result = scorecard_run(run, ATLAS_MCP_URL=fake.mcp_url, ATLAS_AGENT_SEEDS="sandisk,nobody")

    assert result.returncode == 1
    assert not run.stub_was_called()
    assert "unknown seed company: nobody" in json.loads(result.stdout)["reason"]
    assert fake.posted() == []


def test_an_isolated_run_refuses_a_session_atlas_did_not_open_isolated(
    run: Run, atlas: Callable[..., FakeAtlas]
):
    fake = atlas(post_isolated=False)

    result = scorecard_run(run, ATLAS_MCP_URL=fake.mcp_url)

    assert result.returncode == 1
    assert not run.stub_was_called()
    assert "not isolated" in json.loads(result.stdout)["reason"]


def test_an_isolated_run_needs_the_question(run: Run):
    result = run.call("researcher", "--dry-run", ATLAS_AGENT_ISOLATED="true")

    assert result.returncode == 2
    assert "ATLAS_AGENT_ISOLATED needs ATLAS_AGENT_QUESTION" in result.stderr


def test_an_isolated_dry_run_makes_no_network_call_and_shows_a_placeholder(
    run: Run, atlas: Callable[..., FakeAtlas]
):
    fake = atlas()

    result = scorecard_run(run, "--dry-run", ATLAS_MCP_URL=fake.mcp_url)

    assert result.returncode == 0, result.stderr
    assert fake.asked() == [] and fake.posted() == []
    assert not run.stub_was_called()
    assert "session: run.sh would open it before claude starts" in result.stdout
    assert "isolated, theme scorecard, actor atlas-researcher" in result.stdout
    prompt = result.stdout.split("prompt:\n", 1)[1]
    assert "its `session_id` is <the Atlas session id: run.sh opens it before you start>." in prompt
    assert list(run.tmp.iterdir()) == []


@pytest.mark.parametrize(
    "setting",
    [
        {"ATLAS_AGENT_ISOLATED": "yes"},
        {"ATLAS_AGENT_SEEDS": "SanDisk"},
        {"ATLAS_AGENT_SEEDS": "sandisk,"},
        {"ATLAS_AGENT_SEEDS": "sandisk; rm -rf /"},
        {"ATLAS_AGENT_QUESTION": "two\nlines"},
        {"ATLAS_AGENT_QUESTION": "x" * 1001},
    ],
)
def test_a_scorecard_setting_that_does_not_fit_is_refused(run: Run, setting: dict[str, str]):
    result = scorecard_run(run, "--dry-run", **setting)

    assert result.returncode == 2
    assert "run.sh:" in result.stderr
    assert not run.stub_was_called()


def test_seeds_without_a_question_are_refused(run: Run):
    result = run.call("researcher", "--dry-run", ATLAS_AGENT_SEEDS="sandisk")

    assert result.returncode == 2
    assert "ATLAS_AGENT_SEEDS needs ATLAS_AGENT_QUESTION" in result.stderr


@pytest.mark.parametrize("agent", ["scout", "skeptic"])
def test_the_question_seeds_and_isolation_are_the_researcher_s_alone(run: Run, agent: str):
    result = run.call(agent, "--dry-run", ATLAS_AGENT_QUESTION="Is anything short?")

    assert result.returncode == 2
    assert "are the researcher's" in result.stderr
    isolated = run.call(agent, "--dry-run", ATLAS_AGENT_ISOLATED="true")
    assert isolated.returncode == 2


def test_the_skeptic_is_given_no_belief(run: Run):
    prompt = run.call("skeptic", "--dry-run").stdout.split("prompt:\n", 1)[1]

    assert "Belief id: none is given" in prompt
    assert "stalest proven Belief" in prompt
    assert "examined_through" in prompt


def test_dry_run_takes_the_environments_settings(run: Run):
    result = run.call(
        "scout",
        "--dry-run",
        ATLAS_MCP_URL="http://127.0.0.1:9/mcp",
        ATLAS_AGENT_THEME="robotics",
        ATLAS_AGENT_MODEL="sonnet",
        ATLAS_AGENT_MAX_TURNS="12",
        ATLAS_AGENT_CALL_BOUND="33",
    )

    assert " --model sonnet" in result.stdout
    assert " --max-turns 12" in result.stdout
    assert "http://127.0.0.1:9/mcp" in result.stdout
    prompt = result.stdout.split("prompt:\n", 1)[1]
    assert "Theme: robotics" in prompt
    assert "Call bound: 33 " in prompt


def test_dry_run_never_prints_the_token(run: Run):
    result = run.call("researcher", "--dry-run")

    assert TOKEN not in everything_printed_or_written(result, run)
    assert "CLAUDE_CODE_OAUTH_TOKEN: set" in result.stdout


@pytest.mark.parametrize(
    "arguments",
    [(), ("nobody",), ("scout", "researcher"), ("scout", "--bogus")],
)
def test_a_wrong_call_is_a_usage_error(run: Run, arguments: tuple[str, ...]):
    result = run.call(*arguments)

    assert result.returncode == 2
    assert "usage: run.sh" in result.stderr
    assert not run.stub_was_called()


@pytest.mark.parametrize(
    "setting",
    [
        {"ATLAS_AGENT_THEME": "Photonics; rm -rf /"},
        {"ATLAS_MCP_URL": 'http://a/mcp"}, "x":{'},
        {"ATLAS_MCP_URL": "file:///etc/passwd"},
        {"ATLAS_AGENT_MAX_TURNS": "many"},
        {"ATLAS_AGENT_AS_OF": "tomorrow"},
        {"ATLAS_AGENT_MODEL": "opus --dangerously-skip-permissions"},
        {"ATLAS_AGENT_TMP": "/tmp/x&y"},
        {"ATLAS_AGENT_TMP": "relative/dir"},
    ],
)
def test_a_setting_that_does_not_fit_is_refused(run: Run, setting: dict[str, str]):
    result = run.call("scout", "--dry-run", **setting)

    assert result.returncode == 2
    assert "run.sh:" in result.stderr


def test_a_real_run_without_the_token_fails_before_calling_claude(run: Run):
    result = run.call("scout", token=None)

    assert result.returncode == 2
    assert "CLAUDE_CODE_OAUTH_TOKEN is not set" in result.stderr
    assert not run.stub_was_called()


def test_a_run_calls_claude_once_and_prints_one_summary_line(run: Run):
    # Nothing listens on the discard port, so no Atlas session is found (never the cluster's).
    result = run.call(
        "scout", ANTHROPIC_API_KEY="sk-a-metered-key", ATLAS_MCP_URL="http://127.0.0.1:9/mcp"
    )

    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert len(lines) == 1
    summary = json.loads(lines[0])
    assert summary == {
        "agent": "scout",
        "ok": True,
        "exit_status": 0,
        "session_id": "3f1c0d2e",
        "atlas_session_id": None,  # no Atlas answers on the test's MCP URL
        "turns": 7,
        "cost_usd": 0.5,
        "duration_ms": 1234,
        "wall_s": summary["wall_s"],
        "started_at": summary["started_at"],
        "finished_at": summary["finished_at"],
        "subtype": "success",
        "is_error": False,
        "result": "all done",
    }
    assert isinstance(summary["wall_s"], int)
    utc = r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ"
    assert re.fullmatch(utc, summary["started_at"])
    assert re.fullmatch(utc, summary["finished_at"])
    assert summary["started_at"] <= summary["finished_at"]

    args = run.stub_args()
    assert args[0] == "-p"
    assert args[1].startswith("# Routine: the Atlas Scout")
    assert AS_OF in "\n".join(args)  # the prompt is one argument; the stand-in prints it by line
    assert "--strict-mcp-config" in args
    assert args[args.index("--mcp-config") + 1] == f"{posix(run.tmp)}/atlas-mcp.json"
    assert args[args.index("--output-format") + 1] == "json"
    assert args[args.index("--model") + 1] == "opus"
    # The working directory is the image's layout root, where the skill is the project's.
    assert (run.stub_dir / "cwd.txt").read_text(encoding="utf-8").strip().endswith(ROOT.name)
    # The subscription token pays; a metered key in the environment is dropped.
    assert (run.stub_dir / "token-seen.txt").read_text(encoding="utf-8") == TOKEN
    assert (run.stub_dir / "api-key-seen.txt").read_text(encoding="utf-8") == "unset"
    # --tools leaves ToolSearch out, so the MCP tools must never be deferred behind it.
    assert (run.stub_dir / "tool-search-seen.txt").read_text(encoding="utf-8") == "false"


def test_a_run_writes_the_mcp_config_and_keeps_claudes_answer(run: Run):
    run.call("skeptic")

    config = json.loads((run.tmp / "atlas-mcp.json").read_text(encoding="utf-8"))
    assert config == {"mcpServers": {"atlas": {"type": "http", "url": DEFAULT_URL}}}
    kept = json.loads((run.tmp / "out" / "claude-result.json").read_text(encoding="utf-8"))
    assert kept["session_id"] == "3f1c0d2e"


def test_a_run_never_prints_or_writes_the_token(run: Run):
    result = run.call("researcher", STUB_RESULT=f"the token is {TOKEN}")

    assert result.returncode == 0
    assert json.loads(result.stdout)["result"] == "the token is [redacted]"
    assert "[redacted]" in result.stderr  # the stand-in's stderr line, relayed with the token cut
    # Not on stdout, not on stderr, not in the MCP config, and not in the files kept for review.
    assert TOKEN not in everything_printed_or_written(result, run)
    assert (run.tmp / "out" / "claude-result.json").exists()
    assert (run.tmp / "out" / "claude-stderr.txt").exists()


def test_the_result_is_cut_to_two_thousand_characters(run: Run):
    result = run.call("scout", STUB_RESULT="é" * 5000)

    assert json.loads(result.stdout)["result"] == "é" * 2000


@pytest.mark.parametrize(
    ("mode", "subtype"),
    [("max_turns", "error_max_turns"), ("is_error", "success")],
)
def test_a_run_that_did_not_succeed_exits_non_zero(run: Run, mode: str, subtype: str):
    result = run.call("scout", STUB_MODE=mode)

    assert result.returncode == 1
    summary = json.loads(result.stdout)
    assert summary["ok"] is False
    assert summary["subtype"] == subtype
    assert summary["session_id"] == "3f1c0d2e"


def test_a_crashed_claude_exits_non_zero_with_the_token_cut_from_its_stderr(run: Run):
    result = run.call("scout", STUB_MODE="crash")

    assert result.returncode == 1
    summary = json.loads(result.stdout)
    assert summary["ok"] is False
    assert summary["exit_status"] == 3
    assert summary["result"].startswith("unparseable output")
    assert "boom [redacted]" in result.stderr
    assert TOKEN not in result.stdout + result.stderr


def test_an_isolated_run_allows_only_the_listed_atlas_tools(run: Run):
    result = scorecard_run(run, "--dry-run")

    command = next(
        line for line in result.stdout.splitlines() if line.startswith("command: claude -p ")
    )
    allowed = " ".join(f"mcp__atlas__{name}" for name in ISOLATED_TOOLS)
    assert f" --allowedTools {allowed} Read Write Edit Glob " in command + " "
    # Not the whole server, and none of the Belief, Issue or prior-work tools by name.
    assert " mcp__atlas " not in command and "mcp__atlas__*" not in command
    for refused in (
        "open_session",
        "prior_work",
        "list_beliefs",
        "get_belief",
        "next_issue",
        "open_issue",
    ):
        assert f"mcp__atlas__{refused}" not in command
    assert " --tools Read,Write,Edit,Glob" in command


def test_a_real_isolated_run_hands_claude_the_same_allow_list(
    run: Run, atlas: Callable[..., FakeAtlas]
):
    result = scorecard_run(run, ATLAS_MCP_URL=atlas().mcp_url)

    assert result.returncode == 0, result.stderr
    args = run.stub_args()
    start = args.index("--allowedTools") + 1
    end = next(i for i in range(start, len(args)) if args[i].startswith("--"))
    assert args[start:end] == [f"mcp__atlas__{name}" for name in ISOLATED_TOOLS] + BUILT_IN


def test_a_run_that_is_not_isolated_keeps_the_whole_server_allowed(run: Run):
    result = scorecard_run(run, "--dry-run", ATLAS_AGENT_ISOLATED="false")

    assert " --allowedTools mcp__atlas 'mcp__atlas__*' Read Write Edit Glob" in result.stdout
    prompt = result.stdout.split("prompt:\n", 1)[1]
    assert "\nTools: open_session, close_session, companies, search," in prompt
    assert "prior_work" in prompt.split("\nTools: ", 1)[1].split("\n", 1)[0]


def serve(tmp_path: Path, files: dict[str, Any]) -> subprocess.Popen[str]:
    """A stand-in Atlas: a static file server (a subprocess, so the test process opens no
    socket) whose `/api/v1/<name>` answers with the file's JSON."""
    site = tmp_path / "site" / "api" / "v1"
    site.mkdir(parents=True, exist_ok=True)
    for name, body in files.items():
        (site / name).write_text(json.dumps(body), encoding="utf-8")
    return subprocess.Popen(
        [sys.executable, "-u", "-m", "http.server", "0", "--bind", "127.0.0.1"],
        cwd=tmp_path / "site",
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )


def test_a_scorecard_run_finds_its_session_by_question_and_seeds_not_by_date_alone(
    run: Run, tmp_path: Path
):
    # Three sessions share the as-of time (scorecard cases do: 2025-05-31 is SanDisk's and IREN's).
    as_of = "2025-05-31T00:00:00Z"
    question = "As of 2025-05-31, does anything constrain supply in IREN's market?"
    server = serve(
        tmp_path,
        {
            "sessions": {
                "items": [
                    {
                        "id": "sandisk-run",
                        "as_of": as_of,
                        "question": "As of 2025-05-31, does anything constrain SanDisk's supply?",
                        "seed_company_ids": ["id-sandisk"],
                    },
                    {
                        "id": "iren-other-seed",
                        "as_of": as_of,
                        "question": question,
                        "seed_company_ids": ["id-sandisk"],
                    },
                    {
                        "id": "iren-run",
                        "as_of": as_of,
                        "question": question,
                        "seed_company_ids": ["id-iren"],
                    },
                ]
            },
            "companies": {
                "items": [
                    {"slug": "sandisk", "id": "id-sandisk"},
                    {"slug": "iren", "id": "id-iren"},
                ]
            },
        },
    )
    try:
        assert server.stdout is not None
        port = re.search(r"port (\d+)", server.stdout.readline())
        assert port is not None
        result = scorecard_run(
            run,
            ATLAS_MCP_URL=f"http://127.0.0.1:{port.group(1)}/mcp",
            ATLAS_AGENT_AS_OF=as_of.replace("Z", "+00:00"),
            ATLAS_AGENT_QUESTION=question,
            ATLAS_AGENT_SEEDS="iren",
            ATLAS_AGENT_ISOLATED="false",  # an isolated run names its own session, no matching
        )
        no_seeds = scorecard_run(
            run,
            ATLAS_MCP_URL=f"http://127.0.0.1:{port.group(1)}/mcp",
            ATLAS_AGENT_AS_OF=as_of.replace("Z", "+00:00"),
            ATLAS_AGENT_QUESTION="a question no session asked",
            ATLAS_AGENT_SEEDS="iren",
            ATLAS_AGENT_ISOLATED="false",
        )
    finally:
        server.terminate()
        server.wait(timeout=10)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.splitlines()[0])["atlas_session_id"] == "iren-run"
    # A question no session asked is no session: not the first one with the date.
    assert json.loads(no_seeds.stdout.splitlines()[0])["atlas_session_id"] is None


def test_the_summary_names_the_atlas_session_the_run_opened(run: Run, tmp_path: Path):
    # A stand-in Atlas: a static file server whose /api/v1/sessions lists two sessions, one at
    # the run's as-of time. The server is a subprocess, so the test process opens no socket.
    site = tmp_path / "site" / "api" / "v1"
    site.mkdir(parents=True)
    (site / "sessions").write_text(
        json.dumps(
            {
                "items": [
                    {"id": "older", "as_of": "2026-10-13T05:00:00Z", "actor": "atlas-scout"},
                    {"id": "this-run", "as_of": "2026-10-20T05:00:00Z", "actor": "atlas-scout"},
                ]
            }
        ),
        encoding="utf-8",
    )
    server = subprocess.Popen(
        [sys.executable, "-u", "-m", "http.server", "0", "--bind", "127.0.0.1"],
        cwd=tmp_path / "site",
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        assert server.stdout is not None
        port = re.search(r"port (\d+)", server.stdout.readline())
        assert port is not None
        result = run.call("scout", ATLAS_MCP_URL=f"http://127.0.0.1:{port.group(1)}/mcp")
    finally:
        server.terminate()
        server.wait(timeout=10)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.splitlines()[0])["atlas_session_id"] == "this-run"
