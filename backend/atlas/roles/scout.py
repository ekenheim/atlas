"""The Theme Scout role (spec §7.1; "Discovery"): a theme's research question and the
Bottlenecks mental model's open gaps in, web search queries out.

The Scout only writes queries. How many are searched is decided by code, not the model: the
discovery keeps the first `max_queries` distinct ones (atlas.discovery).
"""

from pydantic import BaseModel, ConfigDict

from atlas.roles.contract import PROMPTS_DIR, Prompt, Role, RoleOutput

SCOUT_PROMPT_VERSION = 2  # v2: the bottleneck method


class ScoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    theme_id: str
    theme_title: str
    theme_description: str
    research_question: str
    max_queries: int


class ScoutQuery(RoleOutput):
    query: str
    purpose: str | None  # which gap or part of the question it is for


class ScoutQueries(RoleOutput):
    queries: list[ScoutQuery]


SCOUT = Role(
    name="scout",
    prompt=Prompt.load(PROMPTS_DIR, "scout", SCOUT_PROMPT_VERSION),
    request=ScoutRequest,
    response=ScoutQueries,
    max_output_tokens=2048,
)
