"""The mention extractor role (spec "Discovery"; ticket 09): the companies a lead names.

A small role call over leads' titles and snippets (quoted low-trust data, one item per
lead): for each lead, the companies it names as written, with a ticker and exchange only
when the text gives them. It never resolves or judges a company: entity resolution
(atlas.identity) decides deterministically who each mention is, and only the owner commits
a Candidate (atlas.candidates).
"""

from pydantic import BaseModel, ConfigDict

from atlas.roles.contract import PROMPTS_DIR, Prompt, Role, RoleOutput


class MentionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    theme_id: str
    theme_title: str
    lead_ids: list[str]  # the retrieved_data ids to answer for, one per lead


class CompanyMention(RoleOutput):
    name: str  # as the lead writes it
    ticker: str | None  # only when the lead gives it
    exchange: str | None  # the exchange the lead names with the ticker


class LeadMentions(RoleOutput):
    lead: str  # a retrieved_data id
    companies: list[CompanyMention]


class MentionAnswer(RoleOutput):
    leads: list[LeadMentions]


MENTION_EXTRACTOR = Role(
    name="mention_extractor",
    prompt=Prompt.load(PROMPTS_DIR, "mention_extractor", 1),
    request=MentionRequest,
    response=MentionAnswer,
    max_output_tokens=2048,
)
