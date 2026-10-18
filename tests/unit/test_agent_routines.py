"""The scheduled agents' prompts name only tools the MCP server has (atlas-beliefs ticket 17).

The routine wrappers in `agent/prompts/` and the skill's prompts (`SKILL.md`, `scout.md`,
`skeptic.md`, `editor.md`) each list the tools they use. A tool renamed or removed on the server
would otherwise fail only in a live run, at five in the morning, so every name listed is checked
against `tools/list`. The image's pins are checked here too: the Dockerfile is the only place
that says which Node and which Claude Code the routines run on.
"""

import re
from collections.abc import Callable
from pathlib import Path

import pytest

from atlas.mcp.server import McpServer

ROOT = Path(__file__).resolve().parents[2]
SKILL_DIR = ROOT / ".claude" / "skills" / "atlas-research"
PROMPTS_DIR = ROOT / "agent" / "prompts"
ROUTINES = ("scout", "researcher", "skeptic")

BACKTICKED_NAME = re.compile(r"`([a-z][a-z_]*)`")


def registry() -> set[str]:
    return {each["name"] for each in McpServer.tool_list()}


def names_in(segment: str) -> list[str]:
    return BACKTICKED_NAME.findall(segment)


def listed_after(text: str, marker: str) -> list[str]:
    """The backticked names of the list that follows `marker`, up to the first parenthesis or
    sentence end: the arguments and notes in a parenthesis, and the sentences after the list,
    name arguments (`session_id`, `window_days`), not tools."""
    start = text.index(marker) + len(marker)
    rest = text[start:]
    end = min(position for position in (rest.find("("), rest.find(". ")) if position >= 0)
    return names_in(rest[:end])


def skill_prompt_tools(name: str) -> list[str]:
    """The tools a skill agent prompt lists in its Tools section."""
    text = (SKILL_DIR / f"{name}.md").read_text(encoding="utf-8")
    section = text[text.index("\n## Tools") :]
    return listed_after(section, "and no others:")


def researcher_tools() -> list[str]:
    """The Researcher's: SKILL.md's list after the MCP server's own description."""
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    return listed_after(text, "claude mcp add --transport http atlas <url>/mcp`):")


def skill_added_tools() -> list[str]:
    """The tools SKILL.md says the other three agents add."""
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    return listed_after(text, "They add these tools:")


def wrapper_tools(routine: str) -> list[str]:
    """A routine wrapper's machine-readable `Tools:` line."""
    text = (PROMPTS_DIR / f"{routine}.md").read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if line.startswith("Tools: ")]
    assert len(lines) == 1, f"{routine}.md needs exactly one `Tools: a, b, c` line"
    return [word.strip() for word in lines[0].removeprefix("Tools: ").split(",")]


@pytest.mark.parametrize("routine", ROUTINES)
def test_a_routine_wrapper_names_the_actor_to_open_its_session_with(routine: str):
    # Ticket 31 reads a session's agent from its actor, so each routine opens its session as
    # `atlas-<routine>`, beside the as-of line.
    lines = (PROMPTS_DIR / f"{routine}.md").read_text(encoding="utf-8").splitlines()
    as_of = next(index for index, line in enumerate(lines) if line.startswith("- As-of time:"))
    assert lines[as_of + 1] == f"- Actor: pass `actor: atlas-{routine}` to `open_session`"


def test_the_server_lists_tools():
    # Guards the registry the other tests lean on: a refactor that empties it must not make
    # every check below pass for want of anything to check.
    assert {"open_session", "close_session", "search", "record_fact", "next_issue"} <= registry()


@pytest.mark.parametrize("routine", ROUTINES)
def test_a_routine_wrapper_names_only_tools_the_server_has(routine: str):
    listed = wrapper_tools(routine)
    assert len(listed) >= 5
    assert len(listed) == len(set(listed)), "a tool listed twice"
    assert set(listed) <= registry(), sorted(set(listed) - registry())


@pytest.mark.parametrize("agent", ["scout", "skeptic", "editor"])
def test_a_skill_agent_prompt_names_only_tools_the_server_has(agent: str):
    listed = skill_prompt_tools(agent)
    assert len(listed) >= 5, listed
    assert set(listed) <= registry(), sorted(set(listed) - registry())


def test_the_skill_names_only_tools_the_server_has():
    for listed in (researcher_tools(), skill_added_tools()):
        assert len(listed) >= 5, listed
        assert set(listed) <= registry(), sorted(set(listed) - registry())


def test_the_parser_does_not_take_arguments_for_tools():
    # The Scout's Tools section also backticks the arguments of `upcoming_reports`.
    section = (SKILL_DIR / "scout.md").read_text(encoding="utf-8")
    assert "`window_days`" in section
    assert "window_days" not in skill_prompt_tools("scout")
    assert "session_id" not in skill_prompt_tools("scout")
    assert "upcoming_reports" in skill_prompt_tools("scout")


@pytest.mark.parametrize(
    ("routine", "from_skill"),
    [
        ("scout", lambda: skill_prompt_tools("scout")),
        ("skeptic", lambda: skill_prompt_tools("skeptic")),
        ("researcher", researcher_tools),
    ],
)
def test_a_wrapper_lists_the_tools_of_the_prompt_it_wraps(
    routine: str, from_skill: Callable[[], list[str]]
):
    # The wrapper does not rewrite the skill's prompt: a tool the prompt gains or loses must be
    # a decision here too.
    assert set(wrapper_tools(routine)) == set(from_skill())


def test_every_mcp_prefixed_name_in_the_prompts_exists():
    registry_names = registry()
    texts = [path.read_text(encoding="utf-8") for path in PROMPTS_DIR.glob("*.md")]
    texts += [path.read_text(encoding="utf-8") for path in SKILL_DIR.glob("*.md")]
    for text in texts:
        for name in re.findall(r"mcp__atlas__([a-z_]+)", text):
            assert name in registry_names, name


@pytest.mark.parametrize("routine", ROUTINES)
def test_a_routine_sets_no_judgement_and_publishes_nothing(routine: str):
    text = (PROMPTS_DIR / f"{routine}.md").read_text(encoding="utf-8")
    assert "You set no judgement" in text
    assert "You publish nothing" in text
    for placeholder in ("{{THEME}}", "{{AS_OF}}", "{{OUT_DIR}}", "{{CALL_BOUND}}"):
        assert placeholder in text, placeholder


def test_the_agent_image_pins_node_and_claude_code_exactly():
    dockerfile = (ROOT / "agent" / "Dockerfile").read_text(encoding="utf-8")
    from_lines = [line for line in dockerfile.splitlines() if line.startswith("FROM ")]
    assert len(from_lines) == 1
    assert re.fullmatch(r"FROM node:\d+\.\d+\.\d+-[a-z]+-slim@sha256:[0-9a-f]{64}", from_lines[0])
    version = re.search(r"^ARG CLAUDE_CODE_VERSION=(\S+)$", dockerfile, re.MULTILINE)
    assert version is not None
    assert re.fullmatch(r"\d+\.\d+\.\d+", version.group(1)), "an exact version, not a range"
    assert "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" in dockerfile
    code = re.sub(r"(?m)^#.*$", "", dockerfile)
    assert "--omit=optional" not in code  # the native binary is an optional dependency


def test_the_agent_image_is_non_root_and_holds_no_secret():
    dockerfile = (ROOT / "agent" / "Dockerfile").read_text(encoding="utf-8")
    users = re.findall(r"^USER (\S+)$", dockerfile, re.MULTILINE)
    assert users and users[-1] not in {"root", "0"}
    assert "HOME=/tmp" in dockerfile
    assert "OAUTH_TOKEN" not in re.sub(r"(?m)^#.*$", "", dockerfile)
    assert 'ENTRYPOINT ["/opt/atlas-agent/agent/run.sh"]' in dockerfile


@pytest.mark.parametrize("routine", ROUTINES)
def test_a_routine_never_tells_a_shell_less_agent_to_pause(routine: str):
    text = (PROMPTS_DIR / f"{routine}.md").read_text(encoding="utf-8")
    assert "retry once after a pause" not in text


def test_the_researcher_supersedes_only_its_own_beliefs():
    text = (PROMPTS_DIR / "researcher.md").read_text(encoding="utf-8")
    assert "`supersede_belief` only for a Belief you proposed in this same session" in text
    assert "Supersede Belief <id> by <new id>?" in text


def test_the_agent_image_never_defers_tool_schemas():
    dockerfile = (ROOT / "agent" / "Dockerfile").read_text(encoding="utf-8")
    assert "ENABLE_TOOL_SEARCH=false" in dockerfile


def test_the_scout_reads_the_ranked_signal_leads_before_the_newest_documents():
    # Atlas's nightly scan of the archive (ticket 18) is the Scout's first source: every list
    # that names its tools carries `signal_leads`, and step 2 of its prompt calls it.
    assert "signal_leads" in skill_prompt_tools("scout")
    assert "signal_leads" in wrapper_tools("scout")
    assert "signal_leads" in skill_added_tools()
    scout = (SKILL_DIR / "scout.md").read_text(encoding="utf-8")
    assert scout.index("2. `signal_leads` once") < scout.index(
        "3. `newest_documents` for the theme"
    )
    assert "never a Fact" in scout
