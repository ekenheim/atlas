"""The Theme Scout role (spec §7.1; "Discovery"): a theme's research question and the
Bottlenecks mental model's open gaps in, web search queries out.

The Scout only writes queries. How many are searched is decided by code, not the model: the
discovery keeps the first `max_queries` distinct ones (atlas.discovery). Each query may name
a `filing_phrase` (v3, pilot fix 12): the exact phrase to search in SEC filings through EDGAR
full-text search, the discovery's second channel. v4 asks for a specific phrase (at least two
words, or a theme product term; a bare term paired with a second phrase): only such a phrase is
searched, and only a kept hit proposes its filer (memory-directed reading, ticket 04).
"""

from typing import Any

from pydantic import BaseModel, ConfigDict

from atlas.roles.contract import PROMPTS_DIR, Prompt, Role, RoleOutput

# v2: the bottleneck method; v3: a filing phrase per query; v4: a specific filing phrase
SCOUT_PROMPT_VERSION = 4


def filing_phrase_required(schema: dict[str, Any]) -> None:
    """Send `filing_phrase` as a required (nullable) property, as strict mode wants every
    property, while an answer without it (one recorded before v3) still parses as null."""
    schema.setdefault("required", [])
    if "filing_phrase" not in schema["required"]:
        schema["required"].append("filing_phrase")
    schema["properties"]["filing_phrase"].pop("default", None)


class ScoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    theme_id: str
    theme_title: str
    theme_description: str
    research_question: str
    max_queries: int


class ScoutQuery(RoleOutput):
    model_config = ConfigDict(json_schema_extra=filing_phrase_required)

    query: str
    purpose: str | None  # which gap or part of the question it is for
    # The exact phrase to search in SEC filings (EDGAR full-text search), or None.
    filing_phrase: str | None = None


class ScoutQueries(RoleOutput):
    queries: list[ScoutQuery]


SCOUT = Role(
    name="scout",
    prompt=Prompt.load(PROMPTS_DIR, "scout", SCOUT_PROMPT_VERSION),
    request=ScoutRequest,
    response=ScoutQueries,
    max_output_tokens=2048,
)
